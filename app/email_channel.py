"""The email channel over the intake core (add-web-application, Stage 2).

Everything that is specific to email lives here; every use case and rule is in app/core.py.
This adapter:
  - accepts mail only from senders on the authorized worker list, sent to the intake address;
  - routes by subject: a reference token ([ENC-... v2], [INT-...], [UPD-...]) means a reply,
    "Query:" a read-only question, "Update:" an update note, anything else a new-client note;
  - reads the worker's own words above the quoted earlier message, and the commands in them
    (CONFIRM, RETRY, SAME CLIENT <ID>, DIFFERENT PERSON: <reason>, CLIENT <ID>);
  - turns each email into a channel-neutral Note (app/note.py) for the core;
  - keeps a copy of each accepted email, and writes the review and verification emails.

The web application is the main channel. Email is optional and off by default
(settings.yaml channels.email.enabled); while it is off every email is dropped unread. Whether
email stays as a fallback is [TBC with the sponsors] (openspec/changes/add-web-application).
"""

from __future__ import annotations

import re

from parser.shared import is_query_subject, is_update_subject

from .core import IntakeCore, Outcome
from .drafts import Draft
from .email_message import IntakeEmail
from .note import Note
from .review import compose_review, compose_verification, parse_token

QUOTED_REPLY = re.compile(r"^\s*(>|On .+ wrote:\s*$|-{2,}\s*Original Message)", re.IGNORECASE)
SAME_CLIENT = re.compile(r"^\s*SAME\s+CLIENT\b\s*(?P<id>HMIS-C-\d+)?", re.IGNORECASE)
DIFFERENT_PERSON = re.compile(r"^\s*DIFFERENT\s+PERSON\b[\s:.,;-]*(?P<reason>.*)", re.IGNORECASE | re.DOTALL)
CLIENT_PICK = re.compile(r"\bCLIENT\s+(?P<id>HMIS-C-\d+)\b", re.IGNORECASE)


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


class IntakeService(IntakeCore):
    """The intake core reached by email (the simulated inbox and the phone screens' /mail routes)."""

    def receive(self, email: IntakeEmail) -> Outcome:
        if not self.config.settings.channels.email.enabled:
            # The email channel is off: dropped unread, nothing stored or replied.
            self.store.audit("inbox", "dropped_email_channel_off", self.clock())
            return Outcome("dropped")
        worker = self.config.workers.worker_for(email.sender)
        if worker is None or email.recipient != self.config.workers.intake_address.lower():
            # Dropped unread: nothing is stored or replied, so no neighbor information leaves.
            self.store.audit("inbox", "dropped_unauthorized_sender", self.clock())
            return Outcome("dropped")
        token = parse_token(email.subject)
        if token is not None:
            ref, version = token
            text = reply_text(email.body)
            keep = lambda: self._keep_copy(ref, "reply", email)  # noqa: E731
            if ref.startswith("INT-"):
                return self.confirm_search(ref, email.sender, worker, text,
                                           explicit=_command(text) in ("CONFIRM", "YES"), on_accepted=keep)
            if ref.startswith("UPD-"):
                m = CLIENT_PICK.search(text)
                return self.pick_client(ref, email.sender, worker, m.group("id") if m else None, on_accepted=keep)
            return self._draft_reply(email, worker, ref, version, text, keep)
        note = email.to_note()
        if is_query_subject(email.subject, self.config):
            return self.ask(note, worker)
        if is_update_subject(email.subject, self.config):
            return self.update(note, worker)
        return self.new_client(note, worker)

    def _draft_reply(self, email: IntakeEmail, worker, ref: str, version: int | None, text: str, keep) -> Outcome:
        """Turn a reply to a review, verification, or receipt email into one core action."""
        command = _command(text)
        draft = self.store.get_draft(ref)
        in_review = draft is not None and draft.state == "in_review"
        if in_review and self._verification_open(draft):
            if m := SAME_CLIENT.match(text):
                return self.same_client(ref, email.sender, worker, m.group("id") or "", on_accepted=keep)
            if m := DIFFERENT_PERSON.match(text):
                return self.different_person(ref, email.sender, worker, m.group("reason"), on_accepted=keep)
        if command == "CONFIRM":
            return self.confirm(ref, email.sender, worker, version, on_accepted=keep)
        if command == "RETRY" and not in_review:
            return self.retry(ref, email.sender, worker, on_accepted=keep)
        corrections = Note(author=email.sender, title=email.subject, written_at=email.sent_at, text=text)
        return self.correct(ref, email.sender, worker, corrections, on_accepted=keep, audit_command=command or "changes")

    # Email delivery

    def _keep_copy(self, ref: str, kind: str, email: IntakeEmail) -> None:
        self._keep_note(ref, kind, email.to_note())

    def _emails_for(self, draft: Draft) -> bool:
        """Only a draft that came in by email gets emails, and only while the channel is on. A draft made in
        the web app never gets one, even with the email channel on: its screens read the draft."""
        return self.config.settings.channels.email.enabled and draft.channel == "email"

    def _deliver_review(self, draft: Draft) -> None:
        if not self._emails_for(draft):
            return super()._deliver_review(draft)
        subject, body = compose_review(draft, self.config)
        self._send(draft.id, "review", draft.author, subject, body, message_key="review")

    def _deliver_verification(self, draft: Draft, lead: str | None) -> None:
        if not self._emails_for(draft):
            return super()._deliver_verification(draft, lead)
        subject, body = compose_verification(draft, self.config, lead)
        self._send(draft.id, "verification", draft.author, subject, body, message_key="verification")
