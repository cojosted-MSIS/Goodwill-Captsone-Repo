"""Staged drafts (task 4.1). A draft is never entered into HMIS until its author confirms it.

States: draft (not yet in review, for example when parsing failed), in_review, confirmed,
submitted, failed, expired. Every field keeps where its value came from (origin), the
sentence it came from (source), and the parser's confidence.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

DraftState = Literal["draft", "in_review", "confirmed", "submitted", "failed", "expired"]

# Where a value came from. Shown beside the value in the review email and the staged view.
Origin = Literal["email", "email_date", "program_default", "fixed", "worker", "generated"]

ORIGIN_LABELS: dict[str, str] = {
    "email": "from your note",
    "email_date": "email date",
    "program_default": "program default",
    "fixed": "set by the system",
    "worker": "from your reply",
    "generated": "generated, check the wording",
}


class DraftField(BaseModel):
    value: Any
    origin: Origin
    source: str | None = None  # the sentence the value came from, when it came from text
    confidence: Literal["high", "medium", "low"] | None = None


class Flag(BaseModel):
    code: str
    message: str
    field: str | None = None
    blocking: bool = False  # a blocking flag stops entry until the worker fixes it


class EntryProgress(BaseModel):
    """Identifiers HMIS assigned. Kept so a retry resumes from the step that failed."""

    client_id: str | None = None
    enrollment_id: str | None = None
    ce_enrollment_id: str | None = None
    case_note_id: str | None = None  # update drafts (add-existing-client-updates)
    service_id: str | None = None


class Correction(BaseModel):
    """A correction to entries this system already made for an update draft."""

    case_note_id: str | None = None  # the entries being corrected
    service_id: str | None = None
    changed_fields: list[str] = []  # field names only
    done: dict[str, str] = {}  # step -> the ID HMIS returned, so a retry is never repeated
    as_new_entries: list[str] = []  # steps entered as a new correcting entry because HMIS forbids edits


class Candidate(BaseModel):
    """A client in HMIS with the same name and date of birth as a new-client draft. Minimal data only."""

    client_id: str
    label: str  # first name and last initial
    quadrant: str | None = None
    last_contact: str | None = None
    entered: str | None = None  # the date the record was entered in HMIS
    enrollment: str | None = None  # "active" or "exited"
    last_service: str | None = None  # the last service type's label
    grade: Literal["likely_same", "hard_stop", "warning"]


class Verification(BaseModel):
    """The same-name and date-of-birth check on a new-client draft (add-existing-client-updates)."""

    checked: bool  # False when the lookup could not run (no full name and date of birth, or HMIS unreadable)
    not_checked_reason: str | None = None
    checked_key: str | None = None  # the keyed hash the lookup ran for (never the name or date of birth)
    candidates: list[Candidate] = []
    # Two or more strong matches (name, date of birth, and SSN digits): they may be duplicates of each
    # other in HMIS, so no single candidate is recommended. Client IDs only.
    possible_duplicates: list[str] = []
    decision: Literal["same_client", "different_person"] | None = None
    chosen: str | None = None
    reason: str | None = None  # after the shared privacy cleaning
    supervisor_review: bool = False  # DIFFERENT PERSON although the SSN digits matched

    @property
    def open(self) -> bool:
        return bool(self.candidates) and self.decision is None


class Draft(BaseModel):
    id: str
    author: str  # the worker's email address
    worker_id: str
    subject: str
    state: DraftState
    version: int = 1
    kind: Literal["new_client", "update"] = "new_client"
    client_id: str | None = None  # update drafts: the HMIS client, checked through the read-only lookup
    client_label: str | None = None  # first name and last initial, for review emails
    correction: Correction | None = None  # set while correcting entries already made
    verification: Verification | None = None  # new-client drafts: the same-name check
    update_in_hmis_yourself: list[dict[str, str]] = []  # SAME CLIENT: demographics shown, never written
    visit_note: str | None = None  # SAME CLIENT: the note's sentences about this visit, for case note rewrites
    email_sent_at: datetime
    encounter_date: date
    created_at: datetime
    review_since: datetime | None = None  # when the draft entered review
    fields: dict[str, DraftField] = {}
    flags: list[Flag] = []  # validation flags, recomputed for every version
    parser_flags: list[Flag] = []  # flags the parser raised about the note
    notices: list[str] = []
    changed_by_worker: list[str] = []  # field names only
    parser: str
    model: str | None = None
    prompt_version: str
    parsed_at: datetime
    entry: EntryProgress = EntryProgress()
    # The parser's verified output for version 1 (never the raw model reply), for the parser run view.
    parse_output: dict[str, Any] | None = None
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    submitted_at: datetime | None = None
    last_failure: str | None = None
    stubbed: bool = False  # production retention: reduced to IDs, states, versions, and times

    def value(self, name: str) -> Any:
        f = self.fields.get(name)
        return None if f is None else f.value

    @property
    def blocking_flags(self) -> list[Flag]:
        return [f for f in self.flags + self.parser_flags if f.blocking]

    @property
    def all_flags(self) -> list[Flag]:
        return self.flags + self.parser_flags

    def as_stub(self) -> Draft:
        """Production retention mode: what stays after submission (IDs, states, versions, times)."""
        verification = None if self.verification is None else Verification(
            checked=self.verification.checked, decision=self.verification.decision, chosen=self.verification.chosen,
            supervisor_review=self.verification.supervisor_review)
        return self.model_copy(update={
            "subject": "", "client_label": None, "fields": {}, "flags": [], "parser_flags": [], "notices": [],
            "parse_output": None, "update_in_hmis_yourself": [], "visit_note": None, "correction": None,
            "verification": verification,
            "stubbed": True,
        })


class PendingIntake(BaseModel):
    """A note held while the worker confirms they searched HMIS, or picks which client an
    update is for. Not a draft."""

    id: str
    author: str
    subject: str
    email_sent_at: datetime
    created_at: datetime
    parse: dict  # the ParseResult, as JSON
    kind: Literal["search", "pick_client"] = "search"
    candidates: list[str] = []  # client IDs offered to the worker (pick_client only)
