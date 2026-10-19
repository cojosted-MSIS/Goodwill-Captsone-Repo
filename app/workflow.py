"""The intake workflow (tasks 4.1 to 4.6).

Worker email -> authorized? -> parse -> searched HMIS? -> staged draft (in review) -> review v1
  -> plain-language corrections -> draft v2 -> review v2 ...
  -> CONFIRM from the author on the current version -> enter in order: client, program
     enrollment, Coordinated Entry enrollment -> receipt, audit, email copies deleted.
Unconfirmed drafts expire after the configured hours and go to the supervisor queue.

Entry only: the gateway returns success or failure and the identifiers HMIS assigns.
Nothing is ever read from HMIS. Audit entries hold field names, versions, times, and
identifiers, never note text.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from parser.interface import EmailParser, ParsedField, ParseResult
from parser.shared import first_sentence_matching, split_sentences

from .config_loader import AppConfig, Worker
from .dates import resolve_contact_phrase
from .drafts import Draft, DraftField, Flag, PendingIntake
from .email_message import IntakeEmail
from .hmis_gateway import EntryResult, HmisGateway
from .review import compose_review, parse_token, staged_view
from .storage import Store
from .validation import validate

QUOTED_REPLY = re.compile(r"^\s*(>|On .+ wrote:\s*$|-{2,}\s*Original Message)", re.IGNORECASE)

# Entry order and which draft section goes to each HMIS operation.
ENTRY_STEPS = [
    ("client", "client_id", "the client record"),
    ("enrollment", "enrollment_id", "the program enrollment"),
    ("ce_enrollment", "ce_enrollment_id", "the Coordinated Entry enrollment"),
]

PARSER_FLAG_FIELDS = {"ssn_known_invalid_pattern": "ssn_quality", "case_note_check": "case_note"}


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
                 clock: Callable[[], datetime] | None = None) -> None:
        self.config = config
        self.store = store
        self.parser = parser
        self.gateway = gateway
        self.clock = clock or (lambda: datetime.now(timezone.utc))

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
            return self._draft_reply(email, worker, ref, version)
        return self._new_note(email, worker)

    def _new_note(self, email: IntakeEmail, worker: Worker) -> Outcome:
        now = self.clock()
        result = self.parser.parse(email)
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
                draft.parser_flags.append(Flag(
                    code="contact_date", field="enrollment_date",
                    message=f"Your note says the contact was \"{phrase.value}\", which could not be pinned to one day. "
                            "The enrollment date uses the date of your email. Check it."))
            origin, source, value = "email_date", None, sent.isoformat()
            draft.encounter_date = sent
        for name in ("enrollment_date", "information_date"):
            current = draft.fields.get(name)
            if current is None or current.origin in ("email_date", "email") or origin_if_stated == "worker":
                draft.fields[name] = DraftField(value=value, origin=origin, source=source, confidence="high")

    def _apply_defaults(self, draft: Draft) -> None:
        programs = self.config.programs
        region = programs.ce_regions.get(str(draft.value("ce_region") or ""))
        for name, f in self.config.fields.fields.items():
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
        self._validate(draft)
        draft.state = "in_review"
        draft.review_since = draft.review_since or now
        self.store.save_draft(draft)
        subject, body = compose_review(draft, self.config)
        self._send(draft.id, "review", draft.author, subject, body)
        self.store.audit(draft.id, "review_sent", now, version=draft.version,
                         flags=[f.code for f in draft.all_flags], blocking=len(draft.blocking_flags))

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
            return Outcome("already_submitted", ref)
        if draft.state == "failed" and command in ("RETRY", "CONFIRM"):
            self.store.audit(ref, "retry_requested", now, worker.worker_id)
            return self._enter(draft)
        if draft.state != "in_review":
            self._send(ref, "notice", draft.author, f"Draft not in review [{ref}]",
                       "This draft is not waiting for review. If it could not be drafted, please resend your note.")
            return Outcome("ignored", ref)

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

        parsable = self.config.parsable_fields()
        changes = {n: f for n, f in (result.fields.items() if result else []) if n in parsable
                   and (draft.fields.get(n) is None or draft.fields[n].value != f.value)}
        if not changes and not (result and result.contact_date_phrase):
            self.store.audit(draft.id, "rephrase_requested", now, worker.worker_id, version=draft.version)
            self._send(draft.id, "notice", draft.author, f"Please rephrase [{draft.id} v{draft.version}]",
                       "I could not match your reply to any field. Please rephrase, for example "
                       "\"Living situation: staying outside\" or \"It was the third time on the street\". "
                       f"Draft v{draft.version} is unchanged.")
            return Outcome("rephrase", draft.id)

        for name, f in changes.items():
            draft.fields[name] = DraftField(value=f.value, origin="worker", source=f.source, confidence="high")
            draft.parser_flags = [flag for flag in draft.parser_flags if flag.field != name]
        if result.contact_date_phrase and resolve_contact_phrase(result.contact_date_phrase.value, draft.email_sent_at.date()):
            self._set_contact_date(draft, result.contact_date_phrase, origin_if_stated="worker")
            changes.setdefault("enrollment_date", None)
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

    def _regenerate_case_note(self, draft: Draft) -> None:
        intake = self.store.emails(ref=draft.id, kind="intake")
        replies = [reply_text(e.body) for e in self.store.emails(ref=draft.id, kind="reply")]
        corrections = "\n".join(r for r in replies if _command(r) not in ("CONFIRM", "RETRY"))
        fields = {n: ParsedField(value=f.value, source=f.source or "", confidence=f.confidence or "high")
                  for n, f in draft.fields.items() if n != "case_note"}
        note = self.parser.regenerate_case_note(intake[0].body if intake else "", corrections, fields)
        draft.parser_flags = [f for f in draft.parser_flags if f.code != "case_note_stale"]
        if note:
            draft.fields["case_note"] = DraftField(value=note, origin="generated")
        else:
            draft.parser_flags.append(Flag(code="case_note_stale", field="case_note",
                                           message="The case note could not be rewritten to match your changes. Check it."))

    # Entry into HMIS (entry only)

    def _payload(self, draft: Draft, section: str) -> dict:
        return {name: draft.value(name) for name in self.config.fields.fields_in_section(section)
                if draft.value(name) not in (None, "", [])}

    def _enter(self, draft: Draft) -> Outcome:
        now = self.clock()
        draft.state = "confirmed"
        self.store.save_draft(draft)
        calls: dict[str, Callable[[], EntryResult]] = {
            "client": lambda: self.gateway.create_client(self._payload(draft, "client")),
            "enrollment": lambda: self.gateway.enroll_in_program(draft.entry.client_id, self._payload(draft, "enrollment")),
            "ce_enrollment": lambda: self.gateway.create_ce_enrollment(draft.entry.client_id, self._payload(draft, "ce_enrollment")),
        }
        for step, id_attr, label in ENTRY_STEPS:
            if getattr(draft.entry, id_attr):
                continue  # recorded on an earlier attempt: never repeated
            result = calls[step]()
            self.store.audit(draft.id, "entry_step", now, step=step, ok=result.ok, code=result.code, identifier=result.identifier)
            if not result.ok:
                draft.state, draft.last_failure = "failed", result.code
                self.store.save_draft(draft)
                recorded = [f"  - {lbl}: {getattr(draft.entry, attr)}" for _, attr, lbl in ENTRY_STEPS if getattr(draft.entry, attr)]
                missing = [f"  - {lbl}" for _, attr, lbl in ENTRY_STEPS if not getattr(draft.entry, attr)]
                self._send(draft.id, "notice", draft.author, f"Not entered in HMIS [{draft.id}]",
                           f"HMIS did not accept {label}. Reason: {result.reason or result.code}.\n\n"
                           "Recorded in HMIS:\n" + ("\n".join(recorded) or "  (nothing)") + "\n\n"
                           "Not recorded:\n" + "\n".join(missing) + "\n\n"
                           "Your confirmed draft is kept. Reply RETRY to try again; steps already recorded will not be repeated.")
                return Outcome("entry_failed", draft.id)
            setattr(draft.entry, id_attr, result.identifier)
            self.store.save_draft(draft)

        draft.state, draft.submitted_at = "submitted", now
        self.store.save_draft(draft)
        ids = draft.entry
        self._send(draft.id, "receipt", draft.author, f"Submitted to HMIS [{draft.id}]",
                   "HMIS accepted the entries. Identifiers HMIS assigned:\n"
                   f"  - Client ID: {ids.client_id}\n  - Program enrollment ID: {ids.enrollment_id}\n"
                   f"  - Coordinated Entry enrollment ID: {ids.ce_enrollment_id}\n\n"
                   "Still to complete in HMIS:\n" + "\n".join(f"  - {i}" for i in self.config.fields.remaining_in_hmis))
        self.store.audit(draft.id, "submitted", now, draft.worker_id, version=draft.version,
                         hmis_ids=ids.model_dump(), changed_fields=sorted(draft.changed_by_worker))
        self.store.schedule_email_deletion(draft.id, now + timedelta(hours=self.config.settings.email_retention_hours))
        self.purge_emails()
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

    def supervisor_queue(self) -> list[dict]:
        return [{"draft_id": d.id, "worker_id": d.worker_id, "version": d.version,
                 "in_review_since": d.review_since.isoformat() if d.review_since else None}
                for d in self.store.drafts("expired")]

    def audit_record(self, draft_id: str) -> dict:
        """Who confirmed, when, the versions, and which fields the worker changed. No note text."""
        draft = self.store.get_draft(draft_id)
        return {
            "draft_id": draft.id,
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
