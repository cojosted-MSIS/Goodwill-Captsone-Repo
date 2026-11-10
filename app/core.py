"""The channel-neutral intake core (add-web-application, Stage 2).

Every use case lives here, with one public method per worker action, so the email channel
(app/email_channel.py) and the web channel call the same logic:

  new_client, update, ask          a worker's note or question
  confirm_search                   the worker states they searched HMIS (held new-client note)
  pick_client                      the worker picks a lookup candidate (held update note)
  confirm, retry, correct          a draft in review, a failed entry, plain-language corrections
  same_client, different_person    a same-name verification

Flow: note -> parse -> searched HMIS? -> staged draft (in review) -> corrections -> new
version ... -> confirmation from the author on the current version -> entry in order ->
receipt, audit, note copies deleted. Unconfirmed drafts expire after the configured hours
and go to the supervisor queue. Before review, a new-client draft is checked against HMIS
by name and date of birth (the read-only lookup) and against other open drafts (a keyed
hash); while that verification is open, confirmation is refused.

Input: every note, question, and set of corrections arrives as a channel-neutral Note
(app/note.py). The core never sees an email.

Writes: entry only, after confirmation. When the author confirms a version, the core makes an
HMIS idempotency key and saves it with the draft before the first HMIS call; each step sends
"<key>:<step>", and every retry reuses it, so an entry HMIS saved but whose answer was lost is
returned again instead of made twice. The mock HMIS honors the key [TBC with CHIP for the real HMIS]. Reads: only the four fixed read-only queries
(app/queries.py) [TBC with CHIP]. Audit entries hold field names, versions, times, and
identifiers, never note text.

Messages: the core never writes wording. It names what happened with a neutral key and its
parameters (`_say`), and the draft's channel supplies the words (app/messages.py: the email
wording in app/email_wording.py, the web wording in app/web_wording.py). The core records each
message in the store and calls two hooks a channel may override: `_deliver_review` and
`_deliver_verification`. Audit event names are neutral too (for example "ready_for_review").
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from parser.interface import EmailParser, ParsedField, ParseResult, QueryRequest
from parser.shared import clean_case_note, clean_source, first_sentence_matching, split_sentences, update_fields

from .config_loader import AppConfig, Worker
from .dates import resolve_contact_phrase
from .drafts import Candidate, Correction, Draft, DraftField, Flag, PendingIntake, Verification
from .hmis_gateway import EntryResult, HmisGateway
from .hmis_reader import HmisReader, Neighbor, ReadRefused
from .match_key import match_key
from .messages import phrase, render
from .note import Note
from .queries import answer, audit_details, check, needs_more, structured
from .review import display, entry_ids, failure_meaning, staged_view
from .storage import Store
from .validation import validate

# Entry order and which draft section goes to each HMIS operation.
ENTRY_STEPS = [
    ("client", "client_id", "the client record"),
    ("enrollment", "enrollment_id", "the program enrollment"),
    ("ce_enrollment", "ce_enrollment_id", "the Coordinated Entry enrollment"),
]
# An update to a client already in HMIS: the case note, then the service entry.
UPDATE_STEPS = [
    ("case_note", "case_note_id", "the case note"),
    ("service", "service_id", "the service entry"),
]
ENTRY_ID_IN_TEXT = re.compile(r"\bHMIS-[A-Z]+-\d+\b", re.IGNORECASE)
IDENTITY_FIELDS = ("first_name", "last_name", "date_of_birth")

PARSER_FLAG_FIELDS = {"ssn_known_invalid_pattern": "ssn_quality", "case_note_check": "case_note",
                      "length_of_stay_unstated": "length_of_stay"}

# Called once the author check passes, before anything else happens (a channel keeps its copy then).
Accepted = Callable[[], None] | None


@dataclass(frozen=True)
class Outcome:
    action: str
    ref: str | None = None


class IntakeCore:
    def __init__(self, config: AppConfig, store: Store, parser: EmailParser, gateway: HmisGateway,
                 clock: Callable[[], datetime] | None = None, reader: HmisReader | None = None,
                 match_key: bytes | None = None) -> None:
        self.config = config
        self.store = store
        self.parser = parser
        self.gateway = gateway
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.reader = reader  # read-only HMIS queries; None means queries are not available
        # The open-draft hash key (app/match_key.py). Never printed, logged, or stored.
        self._match_key = match_key or secrets.token_bytes(32)

    # ------------------------------------------------------------------ actions: notes and questions

    def new_client(self, note: Note, worker: Worker) -> Outcome:
        """A note about someone new. Held until the worker states they searched HMIS."""
        now = self.clock()
        started = time.perf_counter()
        result = self.parser.parse(note)
        result = result.model_copy(update={"elapsed_seconds": round(time.perf_counter() - started, 2)})
        if not result.ok:
            draft = self._base_draft(result, note, worker, now)
            draft.parser_flags = [Flag(code="parser_failed", message=result.failure.message, blocking=True)]
            self._keep_note(draft.id, "intake", note)
            self.store.save_draft(draft)
            self.store.audit(draft.id, "parse_failed", now, worker.worker_id, code=result.failure.code,
                             parser=result.parser, model=result.model, prompt_version=result.prompt_version,
                             attempts=result.attempts)
            self._say(draft.id, "notice", draft.author, note.channel, "parse_failed", title=note.title,
                      failure=result.failure.message, failure_code=result.failure.code)
            return Outcome("parse_failed", draft.id)

        if result.hmis_search_stated is None:
            pending = PendingIntake(id=self.store.next_id("INT"), author=note.author, subject=note.title,
                                    email_sent_at=note.written_at, created_at=now, parse=result.model_dump(mode="json"),
                                    channel=note.channel)
            self.store.save_pending(pending)
            self._keep_note(pending.id, "intake", note)
            self.store.audit(pending.id, "hmis_search_not_stated", now, worker.worker_id)
            self._say(pending.id, "search_request", note.author, note.channel, "search_request", title=note.title)
            return Outcome("search_requested", pending.id)

        draft = self._create_draft(result, note, worker, now)
        self._keep_note(draft.id, "intake", note)
        self._enter_review(draft, now)
        return Outcome("drafted", draft.id)

    def update(self, note: Note, worker: Worker) -> Outcome:
        """One visit's note for a client already in HMIS (add-existing-client-updates)."""
        now = self.clock()
        ref = self.store.next_id("UPD")
        self._keep_note(ref, "intake", note)
        started = time.perf_counter()
        result = self.parser.parse(note)
        result = result.model_copy(update={"elapsed_seconds": round(time.perf_counter() - started, 2)})
        if not result.ok:
            return self._notice(ref, note.author, note.channel, ("parse_failed", {"title": note.title,
                                "failure": result.failure.message, "failure_code": result.failure.code}),
                                "parse_failed", worker, "parse_failed", code=result.failure.code)
        pattern = re.compile(self.config.settings.updates.client_id_in_text, re.IGNORECASE)
        ids = sorted({m.group("id").upper() for m in pattern.finditer(f"{note.title}\n{note.text}")})
        if len(ids) > 1:
            return self._notice(ref, note.author, note.channel, ("client_ids_disagree", {"ids": ", ".join(ids)}),
                                "client_ids_disagree", worker, "update_client_ids_disagree", count=len(ids))
        if ids:
            client_id = ids[0]
            if not re.fullmatch(self.config.settings.hmis_queries.client_id_pattern, client_id):
                return self._notice(ref, note.author, note.channel, ("client_id_invalid", {"client_id": client_id}),
                                    "client_id_invalid", worker, "update_client_id_invalid")
            found = self._lookup(ref, worker, client_id=client_id)
            if found is None:
                return self._notice(ref, note.author, note.channel, ("client_check_failed_id", {}),
                                    "client_check_failed", worker, "update_client_check_failed")
            if not found:
                return self._notice(ref, note.author, note.channel, ("client_not_found_id", {"client_id": client_id}),
                                    "client_not_found", worker, "update_client_not_found", client_id=client_id)
            draft = self._create_update_draft(result, note, worker, now, found[0], ref)
            self._enter_review(draft, now)
            return Outcome("drafted", draft.id)

        first, last = result.fields.get("first_name"), result.fields.get("last_name")
        dob = result.fields.get("date_of_birth")
        if not (first and last and dob):
            return self._notice(ref, note.author, note.channel, ("client_id_needed", {}),
                                "client_id_needed", worker, "update_client_id_needed")
        found = self._lookup(ref, worker, first=first.value, last=last.value, dob=date.fromisoformat(dob.value))
        if found is None:
            return self._notice(ref, note.author, note.channel, ("client_check_failed_name", {}),
                                "client_check_failed", worker, "update_client_check_failed")
        if not found:
            return self._notice(ref, note.author, note.channel, ("client_not_found_name", {}),
                                "client_not_found", worker, "update_client_not_found", client_id=None)
        pending = PendingIntake(id=ref, author=note.author, subject=note.title, email_sent_at=note.written_at,
                                created_at=now, parse=result.model_dump(mode="json"), kind="pick_client",
                                candidates=[n.client_id for n in found], channel=note.channel,
                                candidate_details=[{"client_id": n.client_id, "label": f"{n.first_name} {n.last_initial}.",
                                                    "last_contact": n.last_contact, "quadrant": n.quadrant}
                                                   for n in found])
        self.store.save_pending(pending)
        self.store.audit(ref, "update_client_candidates", now, worker.worker_id, candidates=len(found))
        self._say(ref, "pick_client", note.author, note.channel, "pick_client", title=note.title,
                  **self._candidates(found))
        return Outcome("pick_client", ref)

    def ask(self, note: Note, worker: Worker) -> Outcome:
        """A read-only query (add-hmis-readonly-queries): never a draft, never a write."""
        now = self.clock()
        ref = self.store.next_id("QRY")
        self._keep_note(ref, "query", note)
        request = self.parser.parse_query(note)
        if request.failure is not None:
            self.store.audit(ref, "query_refused", now, worker.worker_id, query_type=None, refused=request.failure.code)
            body, action = request.failure.message, "query_failed"
        else:
            q = check(request, self.config, now.astimezone().date())
            if not q.ok:
                self.store.audit(ref, "query_refused", now, worker.worker_id, **audit_details(q, None))
                body, action = needs_more(q, self.config), "query_needs_more"
            elif self.reader is None:
                self.store.audit(ref, "query_refused", now, worker.worker_id, **{**audit_details(q, None), "refused": "unavailable"})
                body, action = "HMIS queries are not available in this setup. No query was run.", "query_unavailable"
            else:
                try:
                    body, rows = answer(q, self.reader, self.config, worker.project, now.astimezone().date(),
                                        question=f"{note.title}\n{note.text}")
                except ReadRefused:
                    self.store.audit(ref, "query_refused", now, worker.worker_id, **{**audit_details(q, None), "refused": "read_failed"})
                    body, action = "HMIS could not be read right now. No query was run. Please try again later.", "query_failed"
                else:
                    self.store.audit(ref, "query", now, worker.worker_id, **audit_details(q, rows))
                    body = body + f"\n\nFrom HMIS as of {now.astimezone():%m/%d/%Y %I:%M %p}. Only records your project can see are included. Nothing in HMIS was changed by this question."
                    action = "query_answered"
        self._say(ref, "query_reply", note.author, note.channel, "query_answer", title=note.title, answer=body)
        hours = self.config.settings.hmis_queries.email_retention_hours
        self.store.schedule_email_deletion(ref, now + timedelta(hours=hours))
        return Outcome(action, ref)

    def ask_fixed(self, request: QueryRequest, worker: Worker) -> dict:
        """A read-only query from a fixed form (add-web-application, Stage 3c). No parser and no free text:
        the form's fields are the request. The same checks, reads, limits, and audit as `ask`. Nothing is
        kept except the audit: no copy of the request and no copy of the answer."""
        now = self.clock()
        ref = self.store.next_id("QRY")
        q = check(request, self.config, now.astimezone().date())
        if not q.ok:
            self.store.audit(ref, "query_refused", now, worker.worker_id, **audit_details(q, None))
            return {"action": "query_needs_more", "ref": ref, "result": None, "missing": list(q.missing)}
        if self.reader is None:
            self.store.audit(ref, "query_refused", now, worker.worker_id, **{**audit_details(q, None), "refused": "unavailable"})
            return {"action": "query_unavailable", "ref": ref, "result": None, "missing": []}
        try:
            result, rows = structured(q, self.reader, self.config, worker.project, now.astimezone().date())
        except ReadRefused:
            self.store.audit(ref, "query_refused", now, worker.worker_id, **{**audit_details(q, None), "refused": "read_failed"})
            return {"action": "query_failed", "ref": ref, "result": None, "missing": []}
        self.store.audit(ref, "query", now, worker.worker_id, **audit_details(q, rows))
        result["as_of"] = f"{now.astimezone():%m/%d/%Y %I:%M %p}"
        return {"action": "query_answered", "ref": ref, "result": result, "missing": []}

    # ------------------------------------------------------------------ actions: held notes

    def confirm_search(self, ref: str, actor: str, worker: Worker, statement: str, *, explicit: bool = False,
                       on_accepted: Accepted = None) -> Outcome:
        """The worker states they searched HMIS and found no match, so the held note becomes a draft.

        `statement` is the worker's own words; `explicit` is a plain yes (a button, or CONFIRM)."""
        now = self.clock()
        pending = self.store.get_pending(ref)
        if pending is None or actor != pending.author:
            self.store.audit(ref, "action_ignored", now, worker.worker_id)
            return Outcome("ignored", ref)
        if on_accepted:
            on_accepted()
        stated = explicit or any(first_sentence_matching(split_sentences(statement, self.config) or [statement], p)
                                 for p in self.config.mappings.shared.hmis_search)
        if not stated:
            self._say(ref, "search_request", actor, pending.channel, "search_request_again", title=pending.subject)
            return Outcome("search_requested", ref)

        original = self._held_note(ref, pending)
        result = ParseResult.model_validate(pending.parse)
        sentence = (split_sentences(statement, self.config) or [statement])[0]
        result = result.model_copy(update={"hmis_search_stated": ParsedField(value=True, source=sentence, confidence="high")})
        draft = self._create_draft(result, original, worker, now)
        self.store.move_emails(ref, draft.id)
        self.store.delete_pending(ref)
        self.store.audit(draft.id, "hmis_search_confirmed_by_worker", now, worker.worker_id, pending_id=ref)
        self._enter_review(draft, now)
        return Outcome("drafted", draft.id)

    def pick_client(self, ref: str, actor: str, worker: Worker, client_id: str | None, *,
                    on_accepted: Accepted = None) -> Outcome:
        """The worker picks which lookup candidate a held update note is for. The system never picks."""
        now = self.clock()
        pending = self.store.get_pending(ref)
        if pending is None or pending.kind != "pick_client" or actor != pending.author:
            self.store.audit(ref, "action_ignored", now, worker.worker_id)
            return Outcome("ignored", ref)
        if on_accepted:
            on_accepted()
        chosen = client_id.upper() if client_id else None
        if chosen not in pending.candidates:
            self._say(ref, "pick_client", actor, pending.channel, "pick_client_again", title=pending.subject,
                      ids=", ".join(pending.candidates))
            return Outcome("pick_client", ref)
        found = self._lookup(ref, worker, client_id=chosen) or []
        if not found:
            return self._notice(ref, actor, pending.channel, ("client_not_found_picked", {"client_id": chosen}),
                                "client_not_found", worker, "update_client_not_found", client_id=chosen)
        original = self._held_note(ref, pending)
        result = ParseResult.model_validate(pending.parse)
        draft = self._create_update_draft(result, original, worker, now, found[0], ref)
        self.store.move_emails(ref, draft.id)
        self.store.delete_pending(ref)
        self.store.audit(draft.id, "update_client_chosen", now, worker.worker_id, client_id=chosen, from_ref=ref)
        self._enter_review(draft, now)
        return Outcome("drafted", draft.id)

    # ------------------------------------------------------------------ actions: drafts

    def confirm(self, ref: str, actor: str, worker: Worker, version: int | None, *, on_accepted: Accepted = None) -> Outcome:
        """The author confirms a version. Entry starts only for the current version, with nothing missing and
        no same-name verification open. Confirming a failed draft retries its entry."""
        draft, refused = self._open_draft(ref, actor, worker, on_accepted)
        if refused:
            return refused
        now = self.clock()
        if draft.state == "expired":
            return self._expired(draft, worker, now, "CONFIRM")
        if draft.state == "submitted":
            return Outcome("already_submitted", ref)
        if draft.state == "failed":
            self.store.audit(ref, "retry_requested", now, worker.worker_id)
            return self._enter(draft)
        if draft.state != "in_review":
            return self._not_in_review(draft)
        if self._verification_open(draft):
            self.store.audit(ref, "confirm_blocked_verification", now, worker.worker_id, version=draft.version)
            self._send_verification(draft, now, "verify_confirm_blocked")
            return Outcome("verification", ref)
        if version != draft.version:
            self.store.audit(ref, "confirm_of_old_version", now, worker.worker_id, confirmed=version, current=draft.version)
            self._say(ref, "notice", draft.author, draft.channel, "old_version", v=draft.version, confirmed=version)
            return Outcome("old_version", ref)
        if draft.blocking_flags:
            self.store.audit(ref, "confirm_blocked", now, worker.worker_id, version=draft.version,
                             blocking=[f.field or f.code for f in draft.blocking_flags])
            listed = "\n".join(f"  - {f.message}" for f in draft.blocking_flags)
            self._say(ref, "missing_info", draft.author, draft.channel, "missing_info", v=draft.version, listed=listed)
            return Outcome("still_missing", ref)
        draft.state, draft.confirmed_at, draft.confirmed_by = "confirmed", now, actor
        # A new key for each confirmed version, saved here, before any call to HMIS: a crash or a retry
        # after this point reuses it. Never taken from a request.
        draft.entry_key = secrets.token_urlsafe(24)
        self.store.save_draft(draft)
        self.store.audit(ref, "confirmed", now, worker.worker_id, version=draft.version)
        return self._enter(draft)

    def retry(self, ref: str, actor: str, worker: Worker, *, on_accepted: Accepted = None) -> Outcome:
        """Retry a failed entry from the step that failed; steps HMIS already accepted are not repeated."""
        draft, refused = self._open_draft(ref, actor, worker, on_accepted)
        if refused:
            return refused
        now = self.clock()
        if draft.state == "expired":
            return self._expired(draft, worker, now, "RETRY")
        if draft.state == "submitted":
            return Outcome("already_submitted", ref)
        if draft.state == "failed":
            self.store.audit(ref, "retry_requested", now, worker.worker_id)
            return self._enter(draft)
        if draft.state == "in_review":
            return Outcome("not_failed", ref)  # nothing to retry; the draft is waiting for review
        return self._not_in_review(draft)

    def correct(self, ref: str, actor: str, worker: Worker, note: Note, *, on_accepted: Accepted = None,
                audit_command: str = "changes") -> Outcome:
        """Plain-language corrections (the note's body). On an update already entered, a correction of its entries."""
        draft, refused = self._open_draft(ref, actor, worker, on_accepted)
        if refused:
            return refused
        now = self.clock()
        if draft.state == "expired":
            return self._expired(draft, worker, now, audit_command)
        if draft.state == "submitted":
            if draft.kind == "update":
                return self._correct_after_entry(draft, note, worker, now)
            return Outcome("already_submitted", ref)
        if draft.state != "in_review":
            return self._not_in_review(draft)
        return self._corrections(draft, note, worker, now)

    def same_client(self, ref: str, actor: str, worker: Worker, client_id: str, *, on_accepted: Accepted = None) -> Outcome:
        """Same-name verification: this neighbor is the HMIS client `client_id`, so the note becomes an update."""
        draft, refused = self._open_draft(ref, actor, worker, on_accepted)
        if refused:
            return refused
        now = self.clock()
        if not self._verification_open(draft) or draft.state != "in_review":
            return Outcome("not_waiting", ref)
        ids = [c.client_id for c in draft.verification.candidates]
        chosen = (client_id or "").upper()
        if chosen not in ids:
            self.store.audit(ref, "verification_answer_refused", now, worker.worker_id, refused="not_a_candidate")
            self._send_verification(draft, now, "verify_not_candidate", ids=", ".join(ids))
            return Outcome("verification", ref)
        return self._same_client(draft, chosen, worker, now)

    def different_person(self, ref: str, actor: str, worker: Worker, reason: str, *, on_accepted: Accepted = None) -> Outcome:
        """Same-name verification: someone else, with a reason; entered later with the confirmed-distinct override."""
        draft, refused = self._open_draft(ref, actor, worker, on_accepted)
        if refused:
            return refused
        now = self.clock()
        if not self._verification_open(draft) or draft.state != "in_review":
            return Outcome("not_waiting", ref)
        v = draft.verification
        ids = [c.client_id for c in v.candidates]
        reason = " ".join((reason or "").split())
        likely = any(c.grade == "likely_same" for c in v.candidates)
        minimum = self.config.settings.verification.min_reason_length_matching_digits if likely else 1
        if len(reason) < minimum:
            self.store.audit(ref, "verification_answer_refused", now, worker.worker_id,
                             refused="reason_missing" if not reason else "reason_too_short", length=len(reason))
            if reason:
                self._send_verification(draft, now, "verify_reason_short", minimum=minimum)
            else:
                self._send_verification(draft, now, "verify_reason_missing")
            return Outcome("verification", ref)
        v.decision, v.reason, v.supervisor_review = "different_person", clean_case_note(reason, self.config)[0], likely
        self.store.audit(ref, "verification_decided", now, worker.worker_id, decision="different_person",
                         candidates=len(ids), grades=[c.grade for c in v.candidates], reason=v.reason,
                         supervisor_review=likely)
        self._enter_review(draft, now)
        return Outcome("verified_different", ref)

    # ------------------------------------------------------------------ guards

    def _open_draft(self, ref: str, actor: str, worker: Worker, on_accepted: Accepted) -> tuple[Draft | None, Outcome | None]:
        """The draft, if `actor` wrote it. An action from anyone else is ignored and changes nothing."""
        draft = self.store.get_draft(ref)
        if draft is None or actor != draft.author:
            self.store.audit(ref, "action_ignored_not_author", self.clock(), worker.worker_id)
            return None, Outcome("ignored", ref)
        if on_accepted:
            on_accepted()
        return draft, None

    def _expired(self, draft: Draft, worker: Worker, now: datetime, command: str) -> Outcome:
        self.store.audit(draft.id, "action_after_expiry", now, worker.worker_id, command=command)
        self._say(draft.id, "notice", draft.author, draft.channel, "expired_action")
        return Outcome("expired", draft.id)

    def _not_in_review(self, draft: Draft) -> Outcome:
        self._say(draft.id, "notice", draft.author, draft.channel, "not_in_review")
        return Outcome("ignored", draft.id)

    @staticmethod
    def _verification_open(draft: Draft) -> bool:
        v = draft.verification
        return draft.kind == "new_client" and v is not None and v.open

    # ------------------------------------------------------------------ updates to a client already in HMIS

    def _notice(self, ref: str, to: str, channel: str, message: tuple[str, dict], action: str, worker: Worker,
                event: str, **details) -> Outcome:
        self.store.audit(ref, event, self.clock(), worker.worker_id, **details)
        key, params = message
        self._say(ref, "notice", to, channel, key, **params)
        return Outcome(action, ref)

    def _lookup(self, ref: str, worker: Worker, **params) -> list[Neighbor] | None:
        """A read-only lookup for an update, audited like a query. None when HMIS cannot be read."""
        if self.reader is None:
            return None
        try:
            if params.get("client_id"):
                found = self.reader.lookup_by_id(params["client_id"], worker.project)
            else:
                found = self.reader.lookup_by_name(params["first"], params["last"], params["dob"], worker.project)
        except ReadRefused:
            return None
        self.store.audit(ref, "lookup", self.clock(), worker.worker_id, query_type="lookup",
                         client_id=params.get("client_id"), name="given" if params.get("first") else None,
                         date_of_birth="given" if params.get("dob") else None, rows=len(found))
        return found

    @staticmethod
    def _candidates(found: list[Neighbor]) -> dict:
        """The pick-client message's parameters: minimal data, as in query replies."""
        lines = []
        for n in found:
            where = f" in the {n.quadrant.upper()} quadrant" if n.quadrant else ""
            last = (f"last contact {date.fromisoformat(n.last_contact):%m/%d/%Y}" if n.last_contact
                    else "no contact recorded")
            lines.append(f"  - {n.client_id}  {n.first_name} {n.last_initial}.  {last}{where}")
        return {"count": len(found), "plural": "s" if len(found) != 1 else "", "lines": "\n".join(lines)}

    def _held_note(self, ref: str, pending: PendingIntake) -> Note:
        intake = next(e for e in self.store.emails(ref=ref, kind="intake"))
        return Note(author=pending.author, title=pending.subject, written_at=pending.email_sent_at, text=intake.body,
                    channel=pending.channel)

    def _create_update_draft(self, result: ParseResult, note: Note, worker: Worker, now: datetime,
                             client: Neighbor, ref: str) -> Draft:
        draft = self._base_draft(result, note, worker, now)
        draft.kind, draft.client_id = "update", client.client_id
        draft.client_label = f"{client.first_name} {client.last_initial}."
        parsed = update_fields(result, note, self.config)
        draft.fields = {n: DraftField(value=f.value, origin="email", source=f.source, confidence=f.confidence)
                        for n, f in parsed.items()}
        if result.case_note:
            draft.fields["case_note"] = DraftField(value=result.case_note, origin="generated")
        draft.notices = list(result.notices)
        draft.parse_output = {  # only the update's own fields: no names or dates of birth
            "fields": {n: {"value": f.value, "source": f.source, "confidence": f.confidence} for n, f in parsed.items()},
            "case_note": result.case_note, "flags": [], "notices": list(result.notices),
            "attempts": result.attempts, "retry_reasons": list(result.retry_reasons),
            "elapsed_seconds": result.elapsed_seconds,
        }
        keep = set(self.config.fields.update_draft.fields)
        draft.parser_flags = [f for f in (self._parser_flag(t) for t in result.flags) if f.field is None or f.field in keep]
        self._set_contact_date(draft, result.contact_date_phrase, origin_if_stated="email")
        self._apply_defaults(draft)
        self.store.move_emails(ref, draft.id)
        self.store.audit(draft.id, "draft_created", now, worker.worker_id, version=1, kind="update",
                         client_id=draft.client_id, parser=draft.parser, model=draft.model,
                         prompt_version=draft.prompt_version, parsed_at=draft.parsed_at, attempts=result.attempts)
        return draft

    # ------------------------------------------------------------------ drafts

    def _base_draft(self, result: ParseResult, note: Note, worker: Worker, now: datetime) -> Draft:
        return Draft(
            id=self.store.next_id("ENC", note.written_at.date()), author=note.author, worker_id=worker.worker_id,
            subject=note.title, state="draft", channel=note.channel, email_sent_at=note.written_at,
            encounter_date=note.written_at.date(),
            created_at=now, parser=result.parser, model=result.model, prompt_version=result.prompt_version,
            parsed_at=result.parsed_at,
        )

    def _create_draft(self, result: ParseResult, note: Note, worker: Worker, now: datetime) -> Draft:
        draft = self._base_draft(result, note, worker, now)
        draft.fields = {
            name: DraftField(value=f.value, origin="email", source=f.source, confidence=f.confidence)
            for name, f in result.fields.items()
        }
        if result.case_note:
            draft.fields["case_note"] = DraftField(value=result.case_note, origin="generated")
        draft.notices = list(result.notices)
        draft.parse_output = {
            "fields": {n: {"value": f.value, "source": f.source, "confidence": f.confidence} for n, f in result.fields.items()},
            "case_note": result.case_note,
            "flags": list(result.flags),
            "notices": list(result.notices),
            "attempts": result.attempts,
            "retry_reasons": list(result.retry_reasons),  # field names only, never note text
            "elapsed_seconds": result.elapsed_seconds,
        }
        # The case note is marked as generated by its origin and its heading in the review.
        draft.parser_flags = [self._parser_flag(f) for f in result.flags]
        self._set_contact_date(draft, result.contact_date_phrase, origin_if_stated="email")
        self._apply_defaults(draft)
        self.store.audit(draft.id, "draft_created", now, worker.worker_id, version=1, parser=draft.parser,
                         model=draft.model, prompt_version=draft.prompt_version, parsed_at=draft.parsed_at,
                         attempts=result.attempts)
        return draft

    @staticmethod
    def _parser_flag(text: str) -> Flag:
        code, _, message = text.partition(": ")
        return Flag(code=code, message=message or text, field=PARSER_FLAG_FIELDS.get(code))

    def _set_contact_date(self, draft: Draft, phrase_text: ParsedField | None, *, origin_if_stated: str) -> None:
        """Enrollment and information dates from the contact date phrase, else the date of the note."""
        sent = draft.email_sent_at.date()
        resolved = resolve_contact_phrase(phrase_text.value, sent) if phrase_text else None
        draft.parser_flags = [f for f in draft.parser_flags if f.code != "contact_date"]
        if resolved:
            stated = resolved.kind == "stated"
            origin = origin_if_stated if stated else "email_date"
            source = phrase_text.source if stated else phrase_text.value
            value, draft.encounter_date = resolved.value.isoformat(), resolved.value
        else:
            if phrase_text:
                field = "service_date" if draft.kind == "update" else "enrollment_date"
                draft.parser_flags.append(Flag(
                    code="contact_date", field=field,
                    message=phrase(draft.channel, "contact_date_unclear", phrase=phrase_text.value,
                                   what="service" if draft.kind == "update" else "enrollment")))
            origin, source, value = "email_date", None, sent.isoformat()
            draft.encounter_date = sent
        names = ("service_date",) if draft.kind == "update" else ("enrollment_date", "information_date")
        for name in names:
            current = draft.fields.get(name)
            if current is None or current.origin in ("email_date", "email") or origin_if_stated == "worker":
                draft.fields[name] = DraftField(value=value, origin=origin, source=source, confidence="high")

    def _apply_defaults(self, draft: Draft) -> None:
        programs = self.config.programs
        region = programs.ce_regions.get(str(draft.value("ce_region") or ""))
        for name, f in self.config.fields.fields_for(draft.kind).items():
            if f.fixed_value is not None:
                draft.fields[name] = DraftField(value=f.fixed_value, origin="fixed")
            elif f.fallback == "program_default":
                value = programs.program_defaults.get(name)
                if value is None and region is not None:
                    value = getattr(region, name, None)
                if value is None:
                    draft.fields.pop(name, None)
                else:
                    draft.fields[name] = DraftField(value=value, origin="program_default")

    def _validate(self, draft: Draft) -> None:
        flags = validate(draft, self.config)
        region = draft.value("ce_region")
        if region and str(region) not in self.config.programs.ce_regions:
            flags.append(Flag(code="unknown_region", field="ce_region", blocking=True,
                              message=f"CE region {region} is not set up in the demo. Check the region number."))
        draft.flags = flags

    def _enter_review(self, draft: Draft, now: datetime) -> None:
        if draft.kind == "new_client":
            self._check_same_name(draft, now)
        self._validate(draft)
        draft.state = "in_review"
        draft.review_since = draft.review_since or now
        self.store.save_draft(draft)
        if draft.verification is not None and draft.verification.open:
            self._send_verification(draft, now)
            return
        self._deliver_review(draft)
        self.store.audit(draft.id, "ready_for_review", now, version=draft.version,
                         flags=[f.code for f in draft.all_flags], blocking=len(draft.blocking_flags))

    # ------------------------------------------------------------------ same name and date of birth verification

    def _check_same_name(self, draft: Draft, now: datetime) -> None:
        """The open-draft hash check and the HMIS lookup by name and date of birth."""
        draft.parser_flags = [f for f in draft.parser_flags if f.code != "open_draft_same_name"]
        first, last, dob = (draft.value(n) for n in IDENTITY_FIELDS)
        if not (first and last and dob):
            self.store.delete_match_key(draft.id)
            draft.verification = Verification(
                checked=False, not_checked_reason="it runs once your note gives the full name and date of birth.")
            return
        key = match_key(self._match_key, first, last, dob)
        others = self.store.drafts_with_match_key(key, draft.id)
        self.store.save_match_key(draft.id, key)
        if others:
            draft.parser_flags.append(Flag(code="open_draft_same_name", message=(
                f"Another open draft ({', '.join(others)}) has the same name and date of birth. Check with your team "
                "that it is not the same neighbor before you confirm.")))
            self.store.audit(draft.id, "open_draft_same_name", now, drafts=others)  # draft IDs only
        v = draft.verification
        if v is not None and v.decision is not None and v.checked_key == key:
            return  # already decided for this name and date of birth
        worker = self.config.workers.worker_for(draft.author)
        found = self._lookup(draft.id, worker, first=str(first), last=str(last), dob=date.fromisoformat(str(dob)))
        if found is None:
            draft.verification = Verification(checked=False, not_checked_reason=(
                "HMIS could not be read, so the check did not run. Search HMIS for this name and date of birth "
                "yourself before you confirm."))
            return
        digits = draft.value("ssn_last4")
        candidates = [
            Candidate(client_id=n.client_id, label=f"{n.first_name} {n.last_initial}.", quadrant=n.quadrant,
                      last_contact=n.last_contact, entered=n.entered, enrollment=n.enrollment,
                      last_service=display(self.config, "service_type", n.last_service_type) if n.last_service_type else None,
                      grade=("hard_stop" if not (digits and n.ssn_last4) else
                             "likely_same" if str(digits) == n.ssn_last4 else "warning"))
            for n in found]
        strong = [c.client_id for c in candidates if c.grade == "likely_same"]
        before = v.possible_duplicates if v is not None else []
        draft.verification = Verification(checked=True, checked_key=key, candidates=candidates,
                                          possible_duplicates=strong if len(strong) > 1 else [])
        if found:
            self.store.audit(draft.id, "same_name_found", now, worker.worker_id, candidates=len(found),
                             grades=[c.grade for c in candidates])
        if len(strong) > 1 and strong != before:
            # For follow-up in HMIS: these records may be one neighbor entered twice. Client IDs only.
            self.store.audit(draft.id, "possible_duplicate_pair_in_hmis", now, worker.worker_id, client_ids=strong)

    def _send_verification(self, draft: Draft, now: datetime, lead: str | None = None, **params) -> None:
        """Ask the worker to settle the same-name check. `lead` names a phrase to show first (why it is asked again)."""
        self._deliver_verification(draft, phrase(draft.channel, lead, **params) if lead else None)
        self.store.audit(draft.id, "verification_requested", now, version=draft.version,
                         candidates=len(draft.verification.candidates),
                         grades=[c.grade for c in draft.verification.candidates])

    def _same_client(self, draft: Draft, client_id: str, worker: Worker, now: datetime) -> Outcome:
        """SAME CLIENT: the new-client draft becomes an update draft for that client."""
        found = self._lookup(draft.id, worker, client_id=client_id) or []
        if not found:
            return self._notice(draft.id, draft.author, draft.channel, ("client_not_found_now", {"client_id": client_id}),
                                "client_not_found", worker, "update_client_not_found", client_id=client_id)
        client, v = found[0], draft.verification
        names = self.config.settings.verification.update_in_hmis_yourself
        draft.update_in_hmis_yourself = [
            {"label": self.config.fields.fields[n].label, "value": display(self.config, n, draft.value(n))}
            for n in names if n in draft.fields and draft.fields[n].origin in ("email", "worker")
            and draft.value(n) not in ("data_not_collected", ["data_not_collected"])]
        stated = {n: ParsedField(value=f.value, source=f.source or "", confidence=f.confidence or "high")
                  for n, f in draft.fields.items() if f.origin in ("email", "worker") and n != "case_note"}
        intake = self.store.emails(ref=draft.id, kind="intake")
        note = Note(author=draft.author, title=draft.subject, written_at=draft.email_sent_at,
                    text=intake[0].body if intake else "")
        result = ParseResult(parser=draft.parser, model=draft.model, prompt_version=draft.prompt_version,
                             parsed_at=draft.parsed_at, fields=stated)
        old = draft.fields
        draft.kind, draft.client_id = "update", client.client_id
        draft.client_label = f"{client.first_name} {client.last_initial}."
        draft.fields = {n: DraftField(value=f.value, origin=old[n].origin if n in old else "email", source=f.source,
                                      confidence=f.confidence) for n, f in update_fields(result, note, self.config).items()}
        if "enrollment_date" in old:
            draft.fields["service_date"] = old["enrollment_date"]
        keep = set(self.config.fields.update_draft.fields)
        draft.parser_flags = [f for f in draft.parser_flags if f.field in keep or (f.field is None and f.code != "open_draft_same_name")]
        draft.visit_note = self._visit_sentences(note.text, old, keep | {"contact_service"})  # services given: this visit
        self._regenerate_case_note(draft, extra={n: stated[n] for n in ("contact_service",) if n in stated})
        draft.changed_by_worker = [n for n in draft.changed_by_worker if n in keep]
        v.decision, v.chosen = "same_client", client.client_id
        self._apply_defaults(draft)
        self.store.delete_match_key(draft.id)  # no longer a new-client draft
        self.store.audit(draft.id, "verification_decided", now, worker.worker_id, decision="same_client",
                         chosen=client.client_id, candidates=len(v.candidates), grades=[c.grade for c in v.candidates])
        draft.version += 1
        self._enter_review(draft, now)
        return Outcome("verified_same", draft.id)

    # ------------------------------------------------------------------ corrections

    def _corrections(self, draft: Draft, note: Note, worker: Worker, now: datetime) -> Outcome:
        text = note.text
        self._keep_note(draft.id, "correction", note)  # the worker's words, for case note rewrites
        result = self.parser.parse(note) if text else None
        if result is not None and not result.ok:
            self._say(draft.id, "notice", draft.author, draft.channel, "corrections_parse_failed", v=draft.version,
                      failure=result.failure.message, failure_code=result.failure.code)
            return Outcome("parse_failed", draft.id)

        parsable = self.config.parsable_fields(draft.kind)
        found = (update_fields(result, note, self.config) if draft.kind == "update" else result.fields) if result else {}
        changes = {n: f for n, f in found.items() if n in parsable
                   and (draft.fields.get(n) is None or draft.fields[n].value != f.value)}
        if not changes and not (result and result.contact_date_phrase):
            self.store.audit(draft.id, "rephrase_requested", now, worker.worker_id, version=draft.version)
            not_asked = re.search(r"\b(?:didn't|did not|never|not) ask", text, re.IGNORECASE)
            self._say(draft.id, "notice", draft.author, draft.channel, "rephrase_not_asked" if not_asked else "rephrase",
                      v=draft.version)
            return Outcome("rephrase", draft.id)

        for name, f in changes.items():
            draft.fields[name] = DraftField(value=f.value, origin="worker", source=f.source, confidence="high")
            draft.parser_flags = [flag for flag in draft.parser_flags if flag.field != name]
        if result.contact_date_phrase and resolve_contact_phrase(result.contact_date_phrase.value, draft.email_sent_at.date()):
            self._set_contact_date(draft, result.contact_date_phrase, origin_if_stated="worker")
            changes.setdefault("service_date" if draft.kind == "update" else "enrollment_date", None)
        if "date_of_birth" in draft.fields and draft.value("dob_quality") != "full_dob_reported":
            draft.fields.pop("date_of_birth")
            changes.setdefault("date_of_birth", None)
        for name in changes:
            if name not in draft.changed_by_worker:
                draft.changed_by_worker.append(name)
        self._apply_defaults(draft)
        self._regenerate_case_note(draft)

        old = draft.version
        draft.version += 1
        self.store.audit(draft.id, "corrections_applied", now, worker.worker_id, from_version=old,
                         to_version=draft.version, changed_fields=sorted(changes))
        self._enter_review(draft, now)
        return Outcome("revised", draft.id)

    def _correct_after_entry(self, draft: Draft, note: Note, worker: Worker, now: datetime) -> Outcome:
        """A correction of an update's entries already in HMIS: a new version that corrects them."""
        if draft.stubbed:
            return self._notice(draft.id, draft.author, draft.channel, ("correction_refused_stubbed", {}),
                                "correction_refused", worker, "correction_refused_stubbed")
        own = {i for i in (draft.entry.case_note_id, draft.entry.service_id, draft.client_id) if i}
        named = {m.group(0).upper() for m in ENTRY_ID_IN_TEXT.finditer(note.text)}
        if named - own:
            return self._notice(draft.id, draft.author, draft.channel, ("correction_refused_not_ours", {}),
                                "correction_refused", worker, "correction_refused_not_our_entry")
        before = {n: f.value for n, f in draft.fields.items()}
        draft.correction = Correction(case_note_id=draft.entry.case_note_id, service_id=draft.entry.service_id)
        outcome = self._corrections(draft, note, worker, now)
        if outcome.action != "revised":
            return outcome  # nothing understood: the entries and the draft are unchanged
        draft.correction.changed_fields = sorted(n for n, f in draft.fields.items()
                                                 if f.origin == "worker" and before.get(n) != f.value)
        self.store.save_draft(draft)
        self.store.audit(draft.id, "correction_drafted", now, worker.worker_id, version=draft.version,
                         entries=sorted(i for i in (draft.correction.case_note_id, draft.correction.service_id) if i),
                         changed_fields=draft.correction.changed_fields)
        return outcome

    def _visit_sentences(self, body: str, old: dict[str, DraftField], keep: set[str]) -> str:
        """SAME CLIENT: the note's sentences about this visit. A sentence goes when it is only the source of
        new-client answers (history, demographics, enrollment) or says HMIS was searched."""
        def sources(sentence: str, names) -> bool:
            cleaned = clean_source(sentence, self.config)
            return any(old[n].source and old[n].source.strip() in cleaned for n in names if n in old)

        history = [n for n, f in old.items() if n not in keep and n != "case_note" and f.origin in ("email", "worker")]
        searched = [re.compile(p, re.IGNORECASE) for p in self.config.mappings.shared.hmis_search]
        kept = [s for s in split_sentences(body, self.config)
                if not any(p.search(s) for p in searched) and (sources(s, keep) or not sources(s, history))]
        return " ".join(kept)

    def _regenerate_case_note(self, draft: Draft, extra: dict[str, ParsedField] | None = None) -> None:
        intake = self.store.emails(ref=draft.id, kind="intake")
        corrections = "\n".join(e.body for e in self.store.emails(ref=draft.id, kind="correction"))
        fields = {n: ParsedField(value=f.value, source=f.source or "", confidence=f.confidence or "high")
                  for n, f in draft.fields.items() if n != "case_note"}
        note_text = intake[0].body if intake else ""
        if draft.visit_note is not None:  # SAME CLIENT: this visit only, named by first name and last initial
            note_text = draft.visit_note
            first, _, initial = (draft.client_label or "").partition(" ")
            if first:
                fields = {"first_name": ParsedField(value=first, source="", confidence="high"),
                          "last_name": ParsedField(value=initial.rstrip(".") or first, source="", confidence="high"),
                          **fields, **(extra or {})}
        note = self.parser.regenerate_case_note(note_text, corrections, fields)
        draft.parser_flags = [f for f in draft.parser_flags if f.code != "case_note_stale"]
        draft.parser_flags = [f for f in draft.parser_flags if f.code != "case_note_check"]
        if note:
            note, note_flags = clean_case_note(note, self.config)
            draft.fields["case_note"] = DraftField(value=note, origin="generated")
            draft.parser_flags += [self._parser_flag(f) for f in note_flags]
        else:
            draft.parser_flags.append(Flag(code="case_note_stale", field="case_note",
                                           message="The case note could not be rewritten to match your changes. Check it."))

    # ------------------------------------------------------------------ writes to HMIS (entry operations only)

    def _payload(self, draft: Draft, section: str) -> dict:
        if draft.kind == "update":
            if section == "case_note":
                return {"note_date": draft.value("service_date"), "case_note": draft.value("case_note")}
            names = [n for n in self.config.fields.update_draft.fields if n != "case_note"]
        else:
            names = list(self.config.fields.fields_in_section(section))
        return {name: draft.value(name) for name in names if draft.value(name) not in (None, "", [])}

    def _ensure_entry_key(self, draft: Draft) -> None:
        """A draft confirmed before keys existed gets one now, saved before its first HMIS call."""
        if not draft.entry_key:
            draft.entry_key = secrets.token_urlsafe(24)
            self.store.save_draft(draft)

    @staticmethod
    def _key(draft: Draft, step: str) -> str:
        return f"{draft.entry_key}:{step}"

    def _replayed(self, draft: Draft, step: str, result: EntryResult) -> None:
        """HMIS returned the result it gave this key before: audited with the step and draft ID only."""
        if result.ok and result.code == "idempotent_replay":
            self.store.audit(draft.id, "hmis_idempotent_replay", self.clock(), type=step)

    def _steps(self, draft: Draft) -> tuple[list[tuple[str, str, str]], dict[str, Callable[[], EntryResult]]]:
        k = lambda step: self._key(draft, step)  # noqa: E731
        if draft.kind == "update":
            return UPDATE_STEPS, {
                "case_note": lambda: self.gateway.add_case_note(draft.client_id, self._payload(draft, "case_note"),
                                                                idempotency_key=k("case_note")),
                "service": lambda: self.gateway.add_service(draft.client_id, self._payload(draft, "service"),
                                                            idempotency_key=k("service")),
            }
        return ENTRY_STEPS, {
            "client": lambda: self._create_client(draft),
            "enrollment": lambda: self.gateway.enroll_in_program(draft.entry.client_id, self._payload(draft, "enrollment"),
                                                                 idempotency_key=k("enrollment")),
            "ce_enrollment": lambda: self.gateway.create_ce_enrollment(
                draft.entry.client_id, self._payload(draft, "ce_enrollment"), idempotency_key=k("ce_enrollment")),
        }

    def _create_client(self, draft: Draft) -> EntryResult:
        v = draft.verification
        payload = self._payload(draft, "client")
        key = self._key(draft, "client")
        if v is None or v.decision != "different_person":
            return self.gateway.create_client(payload, idempotency_key=key)
        # The worker chose DIFFERENT PERSON: entered with the confirmed-distinct override and the reason.
        self.store.audit(draft.id, "confirmed_distinct_override", self.clock(), candidates=len(v.candidates),
                         supervisor_review=v.supervisor_review)
        return self.gateway.create_client(payload, confirmed_distinct_reason=v.reason, idempotency_key=key)

    def _finish_submission(self, draft: Draft) -> None:
        """After submission: the match key goes, and production retention keeps only a stub."""
        self.store.delete_match_key(draft.id)
        if self.config.settings.retention.mode == "production":
            self.store.save_draft(draft.as_stub())

    def _entry_failed(self, draft: Draft, label: str, result: EntryResult, steps: list[tuple[str, str, str]],
                      recorded_ids: dict[str, str | None]) -> Outcome:
        draft.state, draft.last_failure = "failed", result.code
        self.store.save_draft(draft)
        self.store.delete_match_key(draft.id)
        recorded = [f"  - {lbl}: {recorded_ids[attr]}" for _, attr, lbl in steps if recorded_ids.get(attr)]
        missing = [f"  - {lbl}" for _, attr, lbl in steps if not recorded_ids.get(attr)]
        self._say(draft.id, "notice", draft.author, draft.channel, "entry_failed", label=label,
                  reason=result.reason or result.code,
                  meaning=failure_meaning(result.code, draft.channel),
                  recorded="\n".join(recorded) or "  (nothing)", missing="\n".join(missing))
        return Outcome("entry_failed", draft.id)

    def _enter_correction(self, draft: Draft) -> Outcome:
        """Enter a correction to entries already made: an update, or a new correcting entry if HMIS forbids edits."""
        now = self.clock()
        c = draft.correction
        draft.state = "confirmed"
        self.store.save_draft(draft)
        self._ensure_entry_key(draft)
        service_fields = set(self.config.fields.update_draft.fields) - {"case_note"}
        todo = [("case_note_id", "the case note", c.case_note_id, "case_note")]
        if set(c.changed_fields) & service_fields:
            todo.append(("service_id", "the service entry", c.service_id, "service"))
        for attr, label, entry_id, section in todo:
            if attr in c.done or not entry_id:
                continue
            payload = self._payload(draft, section)
            update = self.gateway.update_case_note if section == "case_note" else self.gateway.update_service
            result = update(entry_id, payload, idempotency_key=self._key(draft, f"correct-{section}"))
            self._replayed(draft, f"correct_{section}", result)
            if not result.ok and result.code == "edit_not_allowed":
                if section == "case_note":
                    payload = {**payload, "case_note": f"Corrects case note {entry_id}: {payload['case_note']}"}
                add = self.gateway.add_case_note if section == "case_note" else self.gateway.add_service
                result = add(draft.client_id, {**payload, "corrects": entry_id},
                             idempotency_key=self._key(draft, f"correct-{section}-new"))
                self._replayed(draft, f"correct_{section}_new", result)
                if result.ok:
                    c.as_new_entries.append(attr)
            self.store.audit(draft.id, "correction_step", now, step=section, ok=result.ok, code=result.code,
                             identifier=result.identifier, corrects=entry_id)
            if not result.ok:
                return self._entry_failed(draft, label, result, UPDATE_STEPS, dict(c.done))
            c.done[attr] = result.identifier
            self.store.save_draft(draft)
        lines = []
        for attr, label, entry_id, _ in todo:
            if attr not in c.done:
                continue
            if attr in c.as_new_entries:
                lines.append(f"  - {label.capitalize()}: HMIS does not allow edits, so a new entry {c.done[attr]} "
                             f"was added that corrects {entry_id}")
            else:
                lines.append(f"  - {label.capitalize()} {entry_id}: updated")
        self.store.audit(draft.id, "correction_entered", now, draft.worker_id, version=draft.version,
                         entries=sorted(i for i in (c.case_note_id, c.service_id) if i),
                         changed_fields=c.changed_fields, as_new_entries=list(c.as_new_entries))
        draft.state, draft.submitted_at, draft.correction = "submitted", now, None
        self.store.save_draft(draft)
        self._say(draft.id, "receipt", draft.author, draft.channel, "correction_entered", client_id=draft.client_id,
                  client_label=draft.client_label, lines="\n".join(lines))
        self.store.schedule_email_deletion(draft.id, now + timedelta(hours=self.config.settings.email_retention_hours))
        self.purge_emails()
        self._finish_submission(draft)
        return Outcome("submitted", draft.id)

    def _enter(self, draft: Draft) -> Outcome:
        if draft.correction is not None:
            return self._enter_correction(draft)
        now = self.clock()
        draft.state = "confirmed"
        self.store.save_draft(draft)
        self._ensure_entry_key(draft)
        steps, calls = self._steps(draft)
        for step, id_attr, label in steps:
            if getattr(draft.entry, id_attr):
                continue  # recorded on an earlier attempt: never repeated
            result = calls[step]()
            self.store.audit(draft.id, "entry_step", now, step=step, ok=result.ok, code=result.code, identifier=result.identifier)
            self._replayed(draft, step, result)
            if not result.ok:
                return self._entry_failed(draft, label, result, steps, draft.entry.model_dump())
            setattr(draft.entry, id_attr, result.identifier)
            self.store.save_draft(draft)

        draft.state, draft.submitted_at = "submitted", now
        self.store.save_draft(draft)
        ids = draft.entry
        if draft.kind == "update":
            self._say(draft.id, "receipt", draft.author, draft.channel, "update_entered", client_id=draft.client_id,
                      client_label=draft.client_label, case_note_id=ids.case_note_id, service_id=ids.service_id)
        else:
            self._say(draft.id, "receipt", draft.author, draft.channel, "new_client_entered", client_id=ids.client_id,
                      enrollment_id=ids.enrollment_id, ce_enrollment_id=ids.ce_enrollment_id,
                      remaining="\n".join(f"  - {i}" for i in self.config.fields.remaining_in_hmis))
        v = draft.verification
        self.store.audit(draft.id, "submitted", now, draft.worker_id, version=draft.version,
                         hmis_ids=ids.model_dump(), changed_fields=sorted(draft.changed_by_worker),
                         **({"confirmed_distinct": True, "supervisor_review": v.supervisor_review}
                            if v is not None and v.decision == "different_person" else {}))
        self.store.schedule_email_deletion(draft.id, now + timedelta(hours=self.config.settings.email_retention_hours))
        self.purge_emails()
        self._finish_submission(draft)
        return Outcome("submitted", draft.id)

    # ------------------------------------------------------------------ housekeeping

    def purge_emails(self) -> list[str]:
        """Delete stored note, correction, and message copies whose retention has passed."""
        now = self.clock()
        refs = self.store.purge_emails(now)
        for ref in refs:
            self.store.audit(ref, "copies_deleted", now)
        return refs

    def expire_stale(self) -> list[str]:
        now = self.clock()
        limit = timedelta(hours=self.config.settings.supervisor_timeout_hours)
        expired = []
        for draft in self.store.drafts("in_review"):
            if draft.review_since and now - draft.review_since >= limit:
                draft.state = "expired"
                self.store.save_draft(draft)
                self.store.delete_match_key(draft.id)
                self.store.audit(draft.id, "expired_to_supervisor_queue", now, version=draft.version)
                hours = f"{limit.total_seconds() / 3600:.0f}"
                self._say(draft.id, "notice", draft.author, draft.channel, "expired_worker", hours=hours)
                self._say(draft.id, "supervisor", self.config.workers.supervisor_address, draft.channel,
                          "expired_supervisor", worker_id=draft.worker_id, hours=hours)
                expired.append(draft.id)
        return expired

    def delete_unsubmitted(self) -> list[str]:
        """Delete held notes and drafts that never reached submission, with their copies, after the
        configured days. Their audit records stay (they hold no note text)."""
        now = self.clock()
        limit = timedelta(days=self.config.settings.retention.unsubmitted_days)
        deleted = []
        for draft in self.store.drafts():
            if draft.state != "submitted" and now - draft.created_at >= limit:
                self.store.delete_draft(draft.id)
                self.store.audit(draft.id, "deleted_after_retention", now, state=draft.state)
                deleted.append(draft.id)
        for pending in self.store.all_pending():
            if now - pending.created_at >= limit:
                self.store.delete_pending_and_emails(pending.id)
                self.store.audit(pending.id, "deleted_after_retention", now, state="held")
                deleted.append(pending.id)
        return deleted

    # ------------------------------------------------------------------ views

    def query_log(self) -> list[dict]:
        """Every query for the staff audit view: type, parameters as recorded, and row counts. No returned values."""
        return self.store.audit_events_for_prefix("QRY-")

    def supervisor_queue(self) -> list[dict]:
        return [{"draft_id": d.id, "worker_id": d.worker_id, "version": d.version,
                 "in_review_since": d.review_since.isoformat() if d.review_since else None}
                for d in self.store.drafts("expired")]

    def audit_record(self, draft_id: str) -> dict:
        """Who confirmed, when, the versions, and which fields the worker changed. No note text."""
        draft = self.store.get_draft(draft_id)
        return {
            "draft_id": draft.id,
            "kind": draft.kind,
            "client_id": draft.client_id,
            "hmis_id_list": entry_ids(draft),
            "worker_id": draft.worker_id,
            "state": draft.state,
            "confirmed_by": draft.confirmed_by,
            "confirmed_at": draft.confirmed_at.isoformat() if draft.confirmed_at else None,
            "versions": list(range(1, draft.version + 1)),
            "changed_fields": sorted(draft.changed_by_worker),
            "parser": draft.parser,
            "model": draft.model,
            "prompt_version": draft.prompt_version,
            "parsed_at": draft.parsed_at.isoformat(),
            "hmis_ids": draft.entry.model_dump(),
            "submitted_at": draft.submitted_at.isoformat() if draft.submitted_at else None,
            "verification": None if draft.verification is None else {
                "checked": draft.verification.checked, "candidates": len(draft.verification.candidates),
                "grades": [c.grade for c in draft.verification.candidates], "decision": draft.verification.decision,
                "chosen": draft.verification.chosen, "reason": draft.verification.reason,
                "supervisor_review": draft.verification.supervisor_review},
            "events": self.store.audit_events(draft.id),
        }

    def staged_view(self, draft_id: str) -> dict | None:
        draft = self.store.get_draft(draft_id)
        return None if draft is None else staged_view(draft, self.config)

    # ------------------------------------------------------------------ messages (a channel may override the hooks)

    def _keep_note(self, ref: str, kind: str, note: Note) -> None:
        """Keep the worker's words (a note, a question, or corrections) until the retention rule deletes them."""
        self.store.add_email(ref=ref, kind=kind, direction="in", sender=note.author,
                             recipient=self.config.workers.intake_address.lower(), subject=note.title, body=note.text,
                             at=note.written_at)

    def _say(self, ref: str, kind: str, to: str, channel: str, key: str, **params) -> None:
        """Record message `key` to a worker or supervisor, in the words of the channel the note came from."""
        subject, body = render(channel, key, {"ref": ref, **params})
        self._send(ref, kind, to, subject, body, message_key=key)

    def _send(self, ref: str, kind: str, to: str, subject: str, body: str, *, message_key: str | None = None) -> None:
        """Record a worded message. The channel decides how it reaches the worker."""
        self.store.add_email(ref=ref, kind=kind, direction="out", sender=self.config.workers.intake_address,
                             recipient=to, subject=subject, body=body, at=self.clock(), message_key=message_key)

    def _deliver_review(self, draft: Draft) -> None:
        """Hook: show the worker the draft in review. The core alone records nothing (a screen reads the draft)."""

    def _deliver_verification(self, draft: Draft, lead: str | None) -> None:
        """Hook: show the worker an open same-name verification, with `lead` first when there is one. A screen
        reads the verification from the draft; the lead (why it is asked again) is kept as a message to show."""
        if lead:
            self._say(draft.id, "notice", draft.author, draft.channel, "verification_note", v=draft.version, lead=lead)
