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


class Draft(BaseModel):
    id: str
    author: str  # the worker's email address
    worker_id: str
    subject: str
    state: DraftState
    version: int = 1
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

    def value(self, name: str) -> Any:
        f = self.fields.get(name)
        return None if f is None else f.value

    @property
    def blocking_flags(self) -> list[Flag]:
        return [f for f in self.flags + self.parser_flags if f.blocking]

    @property
    def all_flags(self) -> list[Flag]:
        return self.flags + self.parser_flags


class PendingIntake(BaseModel):
    """A note held while the worker confirms they searched HMIS. Not a draft."""

    id: str
    author: str
    subject: str
    email_sent_at: datetime
    created_at: datetime
    parse: dict  # the ParseResult, as JSON
