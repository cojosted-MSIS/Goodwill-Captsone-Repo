"""The intake workflow (tasks 4.1 to 4.6).

Worker email -> authorized? -> parse -> searched HMIS? -> staged draft (in review) -> review v1
  -> plain-language corrections -> draft v2 -> review v2 ...
  -> CONFIRM from the author on the current version -> enter in order: client, program
     enrollment, Coordinated Entry enrollment -> receipt, audit, email copies deleted.
Unconfirmed drafts expire after the configured hours and go to the supervisor queue.

Before review, a new-client draft is checked against HMIS by name and date of birth (the
read-only lookup) and against other open drafts (a keyed hash). A match sends a same-name
verification email, and CONFIRM is refused until the worker replies SAME CLIENT <ID> or
DIFFERENT PERSON with a reason.

Writes: entry only. The gateway returns success or failure and the identifiers HMIS
assigns. Reads: only the three fixed read-only queries ("Query:" emails, app/queries.py),
which never change anything [TBC with CHIP]. Audit entries hold field names, versions,
times, and identifiers, never note text.
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from parser.interface import EmailParser, ParsedField, ParseResult
from parser.shared import (
    clean_case_note, first_sentence_matching, is_query_subject, is_update_subject, split_sentences, update_fields,
)

from .config_loader import AppConfig, Worker
from .dates import resolve_contact_phrase
from .drafts import Candidate, Correction, Draft, DraftField, Flag, PendingIntake, Verification
from .email_message import IntakeEmail
from .hmis_gateway import EntryResult, HmisGateway
from .hmis_reader import HmisReader, Neighbor, ReadRefused
from .match_key import match_key
from .queries import answer, audit_details, check, needs_more
from .review import ENTRY_FAILURES, compose_review, compose_verification, display, entry_ids, parse_token, staged_view
from .storage import Store
from .validation import validate

QUOTED_REPLY = re.compile(r"^\s*(>|On .+ wrote:\s*$|-{2,}\s*Original Message)", re.IGNORECASE)

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

SAME_CLIENT = re.compile(r"^\s*SAME\s+CLIENT\b\s*(?P<id>HMIS-C-\d+)?", re.IGNORECASE)
DIFFERENT_PERSON = re.compile(r"^\s*DIFFERENT\s+PERSON\b[\s:.,;-]*(?P<reason>.*)", re.IGNORECASE | re.DOTALL)
IDENTITY_FIELDS = ("first_name", "last_name", "date_of_birth")

PARSER_FLAG_FIELDS = {"ssn_known_invalid_pattern": "ssn_quality", "case_note_check": "case_note",
                      "length_of_stay_unstated": "length_of_stay"}


@dataclass(frozen=True)
class Outcome:
    action: str
    ref: str | None = None


def reply_text(body: str) -> str:
    """The worker's own words: everything above the quoted earlier message."""
    lines = []
    for line in body.splitlines():
        if QUOTED_REPLY.match(line):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _command(text: str) -> str:
    words = re.findall(r"[A-Za-z]+", text)
    return words[0].upper() if words else ""


class IntakeService:
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

    # Inbox

    def receive(self, email: IntakeEmail) -> Outcome:
        worker = self.config.workers.worker_for(email.sender)
        if worker is None or email.recipient != self.config.workers.intake_address.lower():
            # Dropped unread: nothing is stored or replied, so no neighbor information leaves.
            self.store.audit("inbox", "dropped_unauthorized_sender", self.clock())
            return Outcome("dropped")
        token = parse_token(email.subject)
        if token is not None:
            ref, version = token
            if ref.startswith("INT-"):
                return self._search_reply(email, worker, ref)
            if ref.startswith("UPD-"):
                return self._pick_client_reply(email, worker, ref)
            return self._draft_reply(email, worker, ref, version)
        if is_query_subject(email.subject, self.config):
            return self._query(email, worker)
        if is_update_subject(email.subject, self.config):
            return self._update_note(email, worker)
        return self._new_note(email, worker)

    # Updates to a client already in HMIS (add-existing-client-updates)

    def _notice(self, ref: str, to: str, subject: str, body: str, action: str, worker: Worker, event: str, **details) -> Outcome:
        self.store.audit(ref, event, self.clock(), worker.worker_id, **details)
        self._send(ref, "notice", to, subject, body)
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

    def _update_note(self, email: IntakeEmail, worker: Worker) -> Outcome:
        now = self.clock()
        ref = self.store.next_id("UPD")
        self._keep_copy(ref, "intake", email)
        started = time.perf_counter()
        result = self.parser.parse(email)
        result = result.model_copy(update={"elapsed_seconds": round(time.perf_counter() - started, 2)})
        if not result.ok:
            return self._notice(ref, email.sender, f"Could not draft: {email.subject} [{ref}]",
                                f"{result.failure.message}\n\nPlease resend your note as a new email.",
                                "parse_failed", worker, "parse_failed", code=result.failure.code)
        pattern = re.compile(self.config.settings.updates.client_id_in_text, re.IGNORECASE)
        ids = sorted({m.group("id").upper() for m in pattern.finditer(f"{email.subject}\n{email.body}")})
        if len(ids) > 1:
            return self._notice(ref, email.sender, f"Which client? [{ref}]",
                                f"Your note gives more than one client ID: {', '.join(ids)}. Nothing was drafted. "
                                "Please resend the note with the one client ID it is about.",
                                "client_ids_disagree", worker, "update_client_ids_disagree", count=len(ids))
        if ids:
            client_id = ids[0]
            if not re.fullmatch(self.config.settings.hmis_queries.client_id_pattern, client_id):
                return self._notice(ref, email.sender, f"Check the client ID [{ref}]",
                                    f"The client ID {client_id} is not in the HMIS format (for example HMIS-C-000101). "
                                    "Nothing was drafted. Please check the ID and resend the note.",
                                    "client_id_invalid", worker, "update_client_id_invalid")
            found = self._lookup(ref, worker, client_id=client_id)
            if found is None:
                return self._notice(ref, email.sender, f"Could not check the client [{ref}]",
                                    "HMIS could not be read to check the client ID, so nothing was drafted. Please try again later.",
                                    "client_check_failed", worker, "update_client_check_failed")
            if not found:
                return self._notice(ref, email.sender, f"Client not found [{ref}]",
                                    f"No client with the ID {client_id} was found. Nothing was drafted. "
                                    "Please check the ID, or send a \"New client:\" note for someone not in HMIS yet.",
                                    "client_not_found", worker, "update_client_not_found", client_id=client_id)
            draft = self._create_update_draft(result, email, worker, now, found[0], ref)
            self._enter_review(draft, now)
            return Outcome("drafted", draft.id)

        first, last = result.fields.get("first_name"), result.fields.get("last_name")
        dob = result.fields.get("date_of_birth")
        if not (first and last and dob):
            return self._notice(ref, email.sender, f"Which client? [{ref}]",
                                "To add this update I need the client's HMIS client ID, or their first and last name "
                                "with the full date of birth. Nothing was drafted. Please resend the note with it.",
                                "client_id_needed", worker, "update_client_id_needed")
        found = self._lookup(ref, worker, first=first.value, last=last.value, dob=date.fromisoformat(dob.value))
        if found is None:
            return self._notice(ref, email.sender, f"Could not check the client [{ref}]",
                                "HMIS could not be read to find the client, so nothing was drafted. Please try again later.",
                                "client_check_failed", worker, "update_client_check_failed")
        if not found:
            return self._notice(ref, email.sender, f"Client not found [{ref}]",
                                "No client with that name and date of birth was found in HMIS, so nothing was drafted. "
                                "For someone not in HMIS yet, send a \"New client:\" note.",
                                "client_not_found", worker, "update_client_not_found", client_id=None)
        pending = PendingIntake(id=ref, author=email.sender, subject=email.subject, email_sent_at=email.sent_at,
                                created_at=now, parse=result.model_dump(mode="json"), kind="pick_client",
                                candidates=[n.client_id for n in found])
        self.store.save_pending(pending)
        self.store.audit(ref, "update_client_candidates", now, worker.worker_id, candidates=len(found))
        self._send(ref, "pick_client", email.sender, f"Which client? {email.subject} [{ref}]", self._candidates_body(found))
        return Outcome("pick_client", ref)

    @staticmethod
    def _candidates_body(found: list[Neighbor]) -> str:
        lines = [f"I found {len(found)} client{'s' if len(found) != 1 else ''} with that name and date of birth. "
                 "Reply CLIENT <ID> with the one this update is for. Nothing has been drafted or sent to HMIS.", ""]
        for n in found:
            where = f" in the {n.quadrant.upper()} quadrant" if n.quadrant else ""
            last = (f"last contact {date.fromisoformat(n.last_contact):%m/%d/%Y}" if n.last_contact
                    else "no contact recorded")
            lines.append(f"  - {n.client_id}  {n.first_name} {n.last_initial}.  {last}{where}")
        return "\n".join(lines)

    def _pick_client_reply(self, email: IntakeEmail, worker: Worker, ref: str) -> Outcome:
        now = self.clock()
        pending = self.store.get_pending(ref)
        if pending is None or pending.kind != "pick_client" or email.sender != pending.author:
            self.store.audit(ref, "reply_ignored", now, worker.worker_id)
            return Outcome("ignored", ref)
        self._keep_copy(ref, "reply", email)
        m = re.search(r"\bCLIENT\s+(?P<id>HMIS-C-\d+)\b", reply_text(email.body), re.IGNORECASE)
        chosen = m.group("id").upper() if m else None
        if chosen not in pending.candidates:
            self._send(ref, "pick_client", email.sender, f"Which client? {pending.subject} [{ref}]",
                       "Please reply CLIENT <ID> with one of these client IDs: " + ", ".join(pending.candidates)
                       + ". Nothing has been drafted or sent to HMIS.")
            return Outcome("pick_client", ref)
        found = self._lookup(ref, worker, client_id=chosen) or []
        if not found:
            return self._notice(ref, email.sender, f"Client not found [{ref}]",
                                f"The client {chosen} could not be found now, so nothing was drafted.",
                                "client_not_found", worker, "update_client_not_found", client_id=chosen)
        intake = next(e for e in self.store.emails(ref=ref, kind="intake"))
        original = IntakeEmail(sender=pending.author, recipient=intake.recipient, subject=pending.subject,
                               sent_at=pending.email_sent_at, body=intake.body)
        result = ParseResult.model_validate(pending.parse)
        draft = self._create_update_draft(result, original, worker, now, found[0], ref)
        self.store.move_emails(ref, draft.id)
        self.store.delete_pending(ref)
        self.store.audit(draft.id, "update_client_chosen", now, worker.worker_id, client_id=chosen, from_ref=ref)
        self._enter_review(draft, now)
        return Outcome("drafted", draft.id)

    def _create_update_draft(self, result: ParseResult, email: IntakeEmail, worker: Worker, now: datetime,
                             client: Neighbor, ref: str) -> Draft:
        draft = self._base_draft(result, email, worker, now)
        draft.kind, draft.client_id = "update", client.client_id
        draft.client_label = f"{client.first_name} {client.last_initial}."
        parsed = update_fields(result, email, self.config)
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

    # Read-only queries (add-hmis-readonly-queries): never a draft, never a write

    def _query(self, email: IntakeEmail, worker: Worker) -> Outcome:
        now = self.clock()
        ref = self.store.next_id("QRY")
        self._keep_copy(ref, "query", email)
        request = self.parser.parse_query(email)
        subject = f"HMIS answer: {email.subject} [{ref}]"
        if request.failure is not None:
            self.store.audit(ref, "query_refused", now, worker.worker_id, query_type=None, refused=request.failure.code)
            body, action = request.failure.message, "query_failed"
        else:
            q = check(request, self.config, now.astimezone().date())
            if not q.ok:
                self.store.audit(ref, "query_refused", now, worker.worker_id, **audit_details(q, None))
                body, action = needs_more(q), "query_needs_more"
            elif self.reader is None:
                self.store.audit(ref, "query_refused", now, worker.worker_id, **{**audit_details(q, None), "refused": "unavailable"})
                body, action = "HMIS queries are not available in this setup. No query was run.", "query_unavailable"
            else:
                try:
                    body, rows = answer(q, self.reader, self.config, worker.project, now.astimezone().date())
                except ReadRefused:
                    self.store.audit(ref, "query_refused", now, worker.worker_id, **{**audit_details(q, None), "refused": "read_failed"})
                    body, action = "HMIS could not be read right now. No query was run. Please try again later.", "query_failed"
                else:
                    self.store.audit(ref, "query", now, worker.worker_id, **audit_details(q, rows))
                    body = body + f"\n\nFrom HMIS as of {now.astimezone():%m/%d/%Y %I:%M %p}. Only records your project can see are included. Nothing in HMIS was changed by this question."
                    action = "query_answered"
        self._send(ref, "query_reply", email.sender, subject, body)
        hours = self.config.settings.hmis_queries.email_retention_hours
        self.store.schedule_email_deletion(ref, now + timedelta(hours=hours))
        return Outcome(action, ref)

    def _new_note(self, email: IntakeEmail, worker: Worker) -> Outcome:
        now = self.clock()
        started = time.perf_counter()
        result = self.parser.parse(email)
        result = result.model_copy(update={"elapsed_seconds": round(time.perf_counter() - started, 2)})
        if not result.ok:
            draft = self._base_draft(result, email, worker, now)
            draft.parser_flags = [Flag(code="parser_failed", message=result.failure.message, blocking=True)]
            self._keep_copy(draft.id, "intake", email)
            self.store.save_draft(draft)
            self.store.audit(draft.id, "parse_failed", now, worker.worker_id, code=result.failure.code,
                             parser=result.parser, model=result.model, prompt_version=result.prompt_version,
                             attempts=result.attempts)
            self._send(draft.id, "notice", draft.author, f"Could not draft: {email.subject} [{draft.id}]",
                       f"{result.failure.message}\n\nPlease resend your note as a new email.")
            return Outcome("parse_failed", draft.id)

        if result.hmis_search_stated is None:
            pending = PendingIntake(id=self.store.next_id("INT"), author=email.sender, subject=email.subject,
                                    email_sent_at=email.sent_at, created_at=now, parse=result.model_dump(mode="json"))
            self.store.save_pending(pending)
            self._keep_copy(pending.id, "intake", email)
            self.store.audit(pending.id, "hmis_search_not_stated", now, worker.worker_id)
            self._send(pending.id, "search_request", email.sender, f"Please confirm HMIS search: {email.subject} [{pending.id}]",
                       "Before I draft a new client, please confirm that you searched HMIS and found no existing record.\n"
                       "Reply \"Searched HMIS, no match\" once you have. Nothing has been drafted or sent to HMIS.")
            return Outcome("search_requested", pending.id)

        draft = self._create_draft(result, email, worker, now)
        self._keep_copy(draft.id, "intake", email)
        self._enter_review(draft, now)
        return Outcome("drafted", draft.id)

    def _search_reply(self, email: IntakeEmail, worker: Worker, ref: str) -> Outcome:
        now = self.clock()
        pending = self.store.get_pending(ref)
        if pending is None or email.sender != pending.author:
            self.store.audit(ref, "reply_ignored", now, worker.worker_id)
            return Outcome("ignored", ref)
        self._keep_copy(ref, "reply", email)
        text = reply_text(email.body)
        stated = _command(text) in ("CONFIRM", "YES") or any(
            first_sentence_matching(split_sentences(text, self.config) or [text], p)
            for p in self.config.mappings.shared.hmis_search
        )
        if not stated:
            self._send(ref, "search_request", email.sender, f"Please confirm HMIS search: {pending.subject} [{ref}]",
                       "I still need you to confirm that you searched HMIS and found no existing record.\n"
                       "Reply \"Searched HMIS, no match\" once you have. Nothing has been drafted or sent to HMIS.")
            return Outcome("search_requested", ref)

        intake = next(e for e in self.store.emails(ref=ref, kind="intake"))
        original = IntakeEmail(sender=pending.author, recipient=intake.recipient, subject=pending.subject,
                               sent_at=pending.email_sent_at, body=intake.body)
        result = ParseResult.model_validate(pending.parse)
        sentence = (split_sentences(text, self.config) or [text])[0]
        result = result.model_copy(update={"hmis_search_stated": ParsedField(value=True, source=sentence, confidence="high")})
        draft = self._create_draft(result, original, worker, now)
        self.store.move_emails(ref, draft.id)
        self.store.delete_pending(ref)
        self.store.audit(draft.id, "hmis_search_confirmed_by_worker", now, worker.worker_id, pending_id=ref)
        self._enter_review(draft, now)
        return Outcome("drafted", draft.id)

    # Drafts

    def _base_draft(self, result: ParseResult, email: IntakeEmail, worker: Worker, now: datetime) -> Draft:
        return Draft(
            id=self.store.next_id("ENC", email.sent_at.date()), author=email.sender, worker_id=worker.worker_id,
            subject=email.subject, state="draft", email_sent_at=email.sent_at, encounter_date=email.sent_at.date(),
            created_at=now, parser=result.parser, model=result.model, prompt_version=result.prompt_version,
            parsed_at=result.parsed_at,
        )

    def _create_draft(self, result: ParseResult, email: IntakeEmail, worker: Worker, now: datetime) -> Draft:
        draft = self._base_draft(result, email, worker, now)
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
        # The case note is marked as generated by its origin and its heading in the review email.
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

    def _set_contact_date(self, draft: Draft, phrase: ParsedField | None, *, origin_if_stated: str) -> None:
        """Enrollment and information dates from the contact date phrase, else the email date."""
        sent = draft.email_sent_at.date()
        resolved = resolve_contact_phrase(phrase.value, sent) if phrase else None
        draft.parser_flags = [f for f in draft.parser_flags if f.code != "contact_date"]
        if resolved:
            stated = resolved.kind == "stated"
            origin = origin_if_stated if stated else "email_date"
            source = phrase.source if stated else phrase.value
            value, draft.encounter_date = resolved.value.isoformat(), resolved.value
        else:
            if phrase:
                field = "service_date" if draft.kind == "update" else "enrollment_date"
                draft.parser_flags.append(Flag(
                    code="contact_date", field=field,
                    message=f"Your note says the contact was \"{phrase.value}\", which could not be pinned to one day. "
                            f"The {'service' if draft.kind == 'update' else 'enrollment'} date uses the date of your email. Check it."))
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
        subject, body = compose_review(draft, self.config)
        self._send(draft.id, "review", draft.author, subject, body)
        self.store.audit(draft.id, "review_sent", now, version=draft.version,
                         flags=[f.code for f in draft.all_flags], blocking=len(draft.blocking_flags))

    # Same name and date of birth verification (add-existing-client-updates)

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
        draft.verification = Verification(checked=True, checked_key=key, candidates=[
            Candidate(client_id=n.client_id, label=f"{n.first_name} {n.last_initial}.", quadrant=n.quadrant,
                      last_contact=n.last_contact,
                      grade=("hard_stop" if not (digits and n.ssn_last4) else
                             "likely_same" if str(digits) == n.ssn_last4 else "warning"))
            for n in found])
        if found:
            self.store.audit(draft.id, "same_name_found", now, worker.worker_id, candidates=len(found),
                             grades=[c.grade for c in draft.verification.candidates])

    def _send_verification(self, draft: Draft, now: datetime, lead: str | None = None) -> None:
        subject, body = compose_verification(draft, self.config, lead)
        self._send(draft.id, "verification", draft.author, subject, body)
        self.store.audit(draft.id, "verification_sent", now, version=draft.version,
                         candidates=len(draft.verification.candidates),
                         grades=[c.grade for c in draft.verification.candidates])

    def _verification_reply(self, draft: Draft, text: str, worker: Worker, now: datetime) -> Outcome | None:
        """SAME CLIENT <ID> or DIFFERENT PERSON with a reason. None when the reply is neither."""
        v = draft.verification
        ids = [c.client_id for c in v.candidates]
        if m := SAME_CLIENT.match(text):
            chosen = (m.group("id") or "").upper()
            if chosen not in ids:
                self.store.audit(draft.id, "verification_reply_refused", now, worker.worker_id, refused="not_a_candidate")
                self._send_verification(draft, now, "Please reply SAME CLIENT with one of these client IDs: "
                                        + ", ".join(ids) + ".")
                return Outcome("verification", draft.id)
            return self._same_client(draft, chosen, worker, now)
        if m := DIFFERENT_PERSON.match(text):
            reason = " ".join(m.group("reason").split())
            likely = any(c.grade == "likely_same" for c in v.candidates)
            minimum = self.config.settings.verification.min_reason_length_matching_digits if likely else 1
            if len(reason) < minimum:
                self.store.audit(draft.id, "verification_reply_refused", now, worker.worker_id,
                                 refused="reason_missing" if not reason else "reason_too_short", length=len(reason))
                lead = ("Please say why this is a different person, for example \"DIFFERENT PERSON: she is 20 years "
                        "younger than the person in HMIS\"." if not reason else
                        f"Because the SSN digits match, please give a fuller reason (at least {minimum} characters).")
                self._send_verification(draft, now, lead + " CONFIRM is not accepted yet.")
                return Outcome("verification", draft.id)
            v.decision, v.reason, v.supervisor_review = "different_person", clean_case_note(reason, self.config)[0], likely
            self.store.audit(draft.id, "verification_decided", now, worker.worker_id, decision="different_person",
                             candidates=len(ids), grades=[c.grade for c in v.candidates], reason=v.reason,
                             supervisor_review=likely)
            self._enter_review(draft, now)
            return Outcome("verified_different", draft.id)
        return None

    def _same_client(self, draft: Draft, client_id: str, worker: Worker, now: datetime) -> Outcome:
        """SAME CLIENT: the new-client draft becomes an update draft for that client."""
        found = self._lookup(draft.id, worker, client_id=client_id) or []
        if not found:
            return self._notice(draft.id, draft.author, f"Client not found [{draft.id}]",
                                f"The client {client_id} could not be found now, so nothing was changed. Please try again later.",
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
        email = IntakeEmail(sender=draft.author, recipient=self.config.workers.intake_address, subject=draft.subject,
                            sent_at=draft.email_sent_at, body=intake[0].body if intake else "")
        result = ParseResult(parser=draft.parser, model=draft.model, prompt_version=draft.prompt_version,
                             parsed_at=draft.parsed_at, fields=stated)
        old = draft.fields
        draft.kind, draft.client_id = "update", client.client_id
        draft.client_label = f"{client.first_name} {client.last_initial}."
        draft.fields = {n: DraftField(value=f.value, origin=old[n].origin if n in old else "email", source=f.source,
                                      confidence=f.confidence) for n, f in update_fields(result, email, self.config).items()}
        if "enrollment_date" in old:
            draft.fields["service_date"] = old["enrollment_date"]
        if "case_note" in old:
            draft.fields["case_note"] = old["case_note"]
        keep = set(self.config.fields.update_draft.fields)
        draft.parser_flags = [f for f in draft.parser_flags if f.field in keep or (f.field is None and f.code != "open_draft_same_name")]
        draft.changed_by_worker = [n for n in draft.changed_by_worker if n in keep]
        v.decision, v.chosen = "same_client", client.client_id
        self._apply_defaults(draft)
        self.store.delete_match_key(draft.id)  # no longer a new-client draft
        self.store.audit(draft.id, "verification_decided", now, worker.worker_id, decision="same_client",
                         chosen=client.client_id, candidates=len(v.candidates), grades=[c.grade for c in v.candidates])
        draft.version += 1
        self._enter_review(draft, now)
        return Outcome("verified_same", draft.id)

    # Replies to a review

    def _draft_reply(self, email: IntakeEmail, worker: Worker, ref: str, version: int | None) -> Outcome:
        now = self.clock()
        draft = self.store.get_draft(ref)
        if draft is None or email.sender != draft.author:
            # A CONFIRM or a correction from anyone but the note's author is ignored.
            self.store.audit(ref, "reply_ignored_not_author", now, worker.worker_id)
            return Outcome("ignored", ref)
        self._keep_copy(ref, "reply", email)
        text = reply_text(email.body)
        command = _command(text)

        if draft.state == "expired":
            self.store.audit(ref, "reply_after_expiry", now, worker.worker_id, command=command or "changes")
            self._send(ref, "notice", draft.author, f"Draft is with your supervisor [{ref}]",
                       "This draft was not confirmed in time and is now in your supervisor's queue. "
                       "Nothing has been entered into HMIS. Please talk with your supervisor.")
            return Outcome("expired", ref)
        if draft.state == "submitted":
            if draft.kind == "update" and command not in ("CONFIRM", "RETRY"):
                return self._correct_after_entry(draft, email, text, worker, now)
            return Outcome("already_submitted", ref)
        if draft.state == "failed" and command in ("RETRY", "CONFIRM"):
            self.store.audit(ref, "retry_requested", now, worker.worker_id)
            return self._enter(draft)
        if draft.state != "in_review":
            self._send(ref, "notice", draft.author, f"Draft not in review [{ref}]",
                       "This draft is not waiting for review. If it could not be drafted, please resend your note.")
            return Outcome("ignored", ref)

        v = draft.verification
        if draft.kind == "new_client" and v is not None and v.open:
            if (outcome := self._verification_reply(draft, text, worker, now)) is not None:
                return outcome
            if command == "CONFIRM":
                self.store.audit(ref, "confirm_blocked_verification", now, worker.worker_id, version=draft.version)
                self._send_verification(draft, now, "CONFIRM is not accepted yet: HMIS has a client with the same name "
                                        "and date of birth. Please reply SAME CLIENT <ID> or DIFFERENT PERSON with a reason.")
                return Outcome("verification", ref)
        if command == "CONFIRM":
            if version != draft.version:
                self.store.audit(ref, "confirm_of_old_version", now, worker.worker_id, confirmed=version, current=draft.version)
                self._send(ref, "notice", draft.author, f"Please review version {draft.version} [{ref} v{draft.version}]",
                           f"You confirmed version {version}, but version {draft.version} was sent after it. "
                           f"Please review version {draft.version} and reply CONFIRM to that email. "
                           "Nothing has been entered into HMIS.")
                return Outcome("old_version", ref)
            if draft.blocking_flags:
                self.store.audit(ref, "confirm_blocked", now, worker.worker_id, version=draft.version,
                                 blocking=[f.field or f.code for f in draft.blocking_flags])
                listed = "\n".join(f"  - {f.message}" for f in draft.blocking_flags)
                self._send(ref, "missing_info", draft.author, f"Still needed before entry [{ref} v{draft.version}]",
                           f"Draft v{draft.version} cannot be entered yet. Please reply with:\n{listed}\n"
                           "Nothing has been entered into HMIS.")
                return Outcome("still_missing", ref)
            draft.state, draft.confirmed_at, draft.confirmed_by = "confirmed", now, email.sender
            self.store.save_draft(draft)
            self.store.audit(ref, "confirmed", now, worker.worker_id, version=draft.version)
            return self._enter(draft)
        return self._corrections(draft, email, text, worker, now)

    def _corrections(self, draft: Draft, email: IntakeEmail, text: str, worker: Worker, now: datetime) -> Outcome:
        result = self.parser.parse(IntakeEmail(sender=email.sender, recipient=email.recipient, subject=email.subject,
                                               sent_at=email.sent_at, body=text)) if text else None
        if result is not None and not result.ok:
            self._send(draft.id, "notice", draft.author, f"Could not read your changes [{draft.id} v{draft.version}]",
                       f"{result.failure.message}\nDraft v{draft.version} is unchanged.")
            return Outcome("parse_failed", draft.id)

        parsable = self.config.parsable_fields(draft.kind)
        reply = IntakeEmail(sender=email.sender, recipient=email.recipient, subject=email.subject,
                            sent_at=email.sent_at, body=text)
        found = (update_fields(result, reply, self.config) if draft.kind == "update" else result.fields) if result else {}
        changes = {n: f for n, f in found.items() if n in parsable
                   and (draft.fields.get(n) is None or draft.fields[n].value != f.value)}
        if not changes and not (result and result.contact_date_phrase):
            self.store.audit(draft.id, "rephrase_requested", now, worker.worker_id, version=draft.version)
            if re.search(r"\b(?:didn't|did not|never|not) ask", text, re.IGNORECASE):
                hint = ("Which question did you not ask? Please name it, for example "
                        "\"Didn't ask about race\" or \"Veteran: didn't ask\".")
            else:
                hint = ("I could not match your reply to any field. Please rephrase, for example "
                        "\"Living situation: staying outside\" or \"It was the third time on the street\".")
            self._send(draft.id, "notice", draft.author, f"Please rephrase [{draft.id} v{draft.version}]",
                       f"{hint} Draft v{draft.version} is unchanged.")
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

    def _correct_after_entry(self, draft: Draft, email: IntakeEmail, text: str, worker: Worker, now: datetime) -> Outcome:
        """A reply to an update's receipt: a new version that corrects the entries already made."""
        if draft.stubbed:
            return self._notice(draft.id, draft.author, f"Correct it in HMIS [{draft.id}]",
                                "The details of this update are no longer kept here (production retention), so it cannot be "
                                "corrected by email. Please correct it in HMIS. Nothing was changed.",
                                "correction_refused", worker, "correction_refused_stubbed")
        own = {i for i in (draft.entry.case_note_id, draft.entry.service_id, draft.client_id) if i}
        named = {m.group(0).upper() for m in ENTRY_ID_IN_TEXT.finditer(text)}
        if named - own:
            return self._notice(draft.id, draft.author, f"Correct it in HMIS [{draft.id}]",
                                "That entry was not made by this system for this update, so it cannot be corrected here. "
                                "Please correct it in HMIS. Nothing was changed.",
                                "correction_refused", worker, "correction_refused_not_our_entry")
        before = {n: f.value for n, f in draft.fields.items()}
        draft.correction = Correction(case_note_id=draft.entry.case_note_id, service_id=draft.entry.service_id)
        outcome = self._corrections(draft, email, text, worker, now)
        if outcome.action != "revised":
            return outcome  # nothing understood: the entries and the draft are unchanged
        draft.correction.changed_fields = sorted(n for n, f in draft.fields.items()
                                                 if f.origin == "worker" and before.get(n) != f.value)
        self.store.save_draft(draft)
        self.store.audit(draft.id, "correction_drafted", now, worker.worker_id, version=draft.version,
                         entries=sorted(i for i in (draft.correction.case_note_id, draft.correction.service_id) if i),
                         changed_fields=draft.correction.changed_fields)
        return outcome

    def _regenerate_case_note(self, draft: Draft) -> None:
        intake = self.store.emails(ref=draft.id, kind="intake")
        replies = [reply_text(e.body) for e in self.store.emails(ref=draft.id, kind="reply")]
        corrections = "\n".join(r for r in replies if _command(r) not in ("CONFIRM", "RETRY"))
        fields = {n: ParsedField(value=f.value, source=f.source or "", confidence=f.confidence or "high")
                  for n, f in draft.fields.items() if n != "case_note"}
        note = self.parser.regenerate_case_note(intake[0].body if intake else "", corrections, fields)
        draft.parser_flags = [f for f in draft.parser_flags if f.code != "case_note_stale"]
        draft.parser_flags = [f for f in draft.parser_flags if f.code != "case_note_check"]
        if note:
            note, note_flags = clean_case_note(note, self.config)
            draft.fields["case_note"] = DraftField(value=note, origin="generated")
            draft.parser_flags += [self._parser_flag(f) for f in note_flags]
        else:
            draft.parser_flags.append(Flag(code="case_note_stale", field="case_note",
                                           message="The case note could not be rewritten to match your changes. Check it."))

    # Writes to HMIS (entry operations only)

    def _payload(self, draft: Draft, section: str) -> dict:
        if draft.kind == "update":
            if section == "case_note":
                return {"note_date": draft.value("service_date"), "case_note": draft.value("case_note")}
            names = [n for n in self.config.fields.update_draft.fields if n != "case_note"]
        else:
            names = list(self.config.fields.fields_in_section(section))
        return {name: draft.value(name) for name in names if draft.value(name) not in (None, "", [])}

    def _steps(self, draft: Draft) -> tuple[list[tuple[str, str, str]], dict[str, Callable[[], EntryResult]]]:
        if draft.kind == "update":
            return UPDATE_STEPS, {
                "case_note": lambda: self.gateway.add_case_note(draft.client_id, self._payload(draft, "case_note")),
                "service": lambda: self.gateway.add_service(draft.client_id, self._payload(draft, "service")),
            }
        return ENTRY_STEPS, {
            "client": lambda: self._create_client(draft),
            "enrollment": lambda: self.gateway.enroll_in_program(draft.entry.client_id, self._payload(draft, "enrollment")),
            "ce_enrollment": lambda: self.gateway.create_ce_enrollment(draft.entry.client_id, self._payload(draft, "ce_enrollment")),
        }

    def _create_client(self, draft: Draft) -> EntryResult:
        v = draft.verification
        payload = self._payload(draft, "client")
        if v is None or v.decision != "different_person":
            return self.gateway.create_client(payload)
        # The worker replied DIFFERENT PERSON: entered with the confirmed-distinct override and the reason.
        self.store.audit(draft.id, "confirmed_distinct_override", self.clock(), candidates=len(v.candidates),
                         supervisor_review=v.supervisor_review)
        return self.gateway.create_client(payload, confirmed_distinct_reason=v.reason)

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
        self._send(draft.id, "notice", draft.author, f"Not entered in HMIS [{draft.id}]",
                   f"HMIS did not accept {label}. Reason: {result.reason or result.code}.\n"
                   f"What this means: {ENTRY_FAILURES.get(result.code or '', ENTRY_FAILURES['unexpected_response'])}\n\n"
                   "Recorded in HMIS:\n" + ("\n".join(recorded) or "  (nothing)") + "\n\n"
                   "Not recorded:\n" + "\n".join(missing) + "\n\n"
                   "Your confirmed draft is kept. Reply RETRY to try again; steps already recorded will not be repeated.")
        return Outcome("entry_failed", draft.id)

    def _enter_correction(self, draft: Draft) -> Outcome:
        """Enter a correction to entries already made: an update, or a new correcting entry if HMIS forbids edits."""
        now = self.clock()
        c = draft.correction
        draft.state = "confirmed"
        self.store.save_draft(draft)
        service_fields = set(self.config.fields.update_draft.fields) - {"case_note"}
        todo = [("case_note_id", "the case note", c.case_note_id, "case_note")]
        if set(c.changed_fields) & service_fields:
            todo.append(("service_id", "the service entry", c.service_id, "service"))
        for attr, label, entry_id, section in todo:
            if attr in c.done or not entry_id:
                continue
            payload = self._payload(draft, section)
            update = self.gateway.update_case_note if section == "case_note" else self.gateway.update_service
            result = update(entry_id, payload)
            if not result.ok and result.code == "edit_not_allowed":
                if section == "case_note":
                    payload = {**payload, "case_note": f"Corrects case note {entry_id}: {payload['case_note']}"}
                add = self.gateway.add_case_note if section == "case_note" else self.gateway.add_service
                result = add(draft.client_id, {**payload, "corrects": entry_id})
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
        self._send(draft.id, "receipt", draft.author, f"Correction entered in HMIS [{draft.id}]",
                   f"HMIS accepted the correction for client {draft.client_id} ({draft.client_label}):\n"
                   + "\n".join(lines) + "\n\nTo correct these entries again, reply to this email with the change.")
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
        steps, calls = self._steps(draft)
        for step, id_attr, label in steps:
            if getattr(draft.entry, id_attr):
                continue  # recorded on an earlier attempt: never repeated
            result = calls[step]()
            self.store.audit(draft.id, "entry_step", now, step=step, ok=result.ok, code=result.code, identifier=result.identifier)
            if not result.ok:
                return self._entry_failed(draft, label, result, steps, draft.entry.model_dump())
            setattr(draft.entry, id_attr, result.identifier)
            self.store.save_draft(draft)

        draft.state, draft.submitted_at = "submitted", now
        self.store.save_draft(draft)
        ids = draft.entry
        if draft.kind == "update":
            self._send(draft.id, "receipt", draft.author, f"Submitted to HMIS [{draft.id}]",
                       f"HMIS accepted the update for client {draft.client_id} ({draft.client_label}). "
                       "Identifiers HMIS assigned:\n"
                       f"  - Case note ID: {ids.case_note_id}\n  - Service ID: {ids.service_id}\n\n"
                       "To correct these entries, reply to this email with the change, for example "
                       "\"It was 45 minutes, not 30\". Only you can correct them, and CONFIRM is needed again.")
        else:
            self._send(draft.id, "receipt", draft.author, f"Submitted to HMIS [{draft.id}]",
                       "HMIS accepted the entries. Identifiers HMIS assigned:\n"
                       f"  - Client ID: {ids.client_id}\n  - Program enrollment ID: {ids.enrollment_id}\n"
                       f"  - Coordinated Entry enrollment ID: {ids.ce_enrollment_id}\n\n"
                       "Still to complete in HMIS:\n" + "\n".join(f"  - {i}" for i in self.config.fields.remaining_in_hmis))
        v = draft.verification
        self.store.audit(draft.id, "submitted", now, draft.worker_id, version=draft.version,
                         hmis_ids=ids.model_dump(), changed_fields=sorted(draft.changed_by_worker),
                         **({"confirmed_distinct": True, "supervisor_review": v.supervisor_review}
                            if v is not None and v.decision == "different_person" else {}))
        self.store.schedule_email_deletion(draft.id, now + timedelta(hours=self.config.settings.email_retention_hours))
        self.purge_emails()
        self._finish_submission(draft)
        return Outcome("submitted", draft.id)

    # Housekeeping

    def purge_emails(self) -> list[str]:
        now = self.clock()
        refs = self.store.purge_emails(now)
        for ref in refs:
            self.store.audit(ref, "email_copies_deleted", now)
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
                self._send(draft.id, "notice", draft.author, f"Moved to your supervisor's queue [{draft.id}]",
                           f"Draft {draft.id} was not confirmed within {limit.total_seconds() / 3600:.0f} hours and is now "
                           "in your supervisor's queue. Nothing was entered into HMIS.")
                self._send(draft.id, "supervisor", self.config.workers.supervisor_address,
                           f"Unconfirmed draft {draft.id} from {draft.worker_id}",
                           f"Draft {draft.id} from {draft.worker_id} has not been confirmed for "
                           f"{limit.total_seconds() / 3600:.0f} hours. Nothing was entered into HMIS.")
                expired.append(draft.id)
        return expired

    def delete_unsubmitted(self) -> list[str]:
        """Delete held notes and drafts that never reached submission, with their emails, after the
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

    # Email helpers

    def _keep_copy(self, ref: str, kind: str, email: IntakeEmail) -> None:
        self.store.add_email(ref=ref, kind=kind, direction="in", sender=email.sender, recipient=email.recipient,
                             subject=email.subject, body=email.body, at=email.sent_at)

    def _send(self, ref: str, kind: str, to: str, subject: str, body: str) -> None:
        self.store.add_email(ref=ref, kind=kind, direction="out", sender=self.config.workers.intake_address,
                             recipient=to, subject=subject, body=body, at=self.clock())
