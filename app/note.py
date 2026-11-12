"""What a worker wrote, from any channel (add-web-application, Stage 2).

The intake core (app/core.py) takes a Note for every note, question, and set of corrections.
Each channel makes one: the web API from the signed-in worker and the text they typed, the
email channel from an email (IntakeEmail.to_note). The core never sees an email.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

Channel = Literal["web", "email"]


@dataclass(frozen=True)
class Note:
    author: str            # the worker's address: the identity every later action is checked against
    title: str             # a short label: an email subject, or the title given on screen
    written_at: datetime   # when the worker wrote it, with a time zone
    text: str              # the worker's own words
    channel: Channel = "web"  # where it came from: only drafts from the email channel get emails
    # A web note arrives with full SSNs masked (app/ssn_guard.py). When the masked number was a known
    # invalid one (validation.yaml), its label travels here so the parser can still flag it.
    ssn_invalid_label: str | None = None


class ConvertsToNote(Protocol):
    def to_note(self) -> Note: ...


def as_note(message: Note | ConvertsToNote) -> Note:
    """A Note, or anything a channel can turn into one (an IntakeEmail)."""
    return message if isinstance(message, Note) else message.to_note()
