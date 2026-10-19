"""Read a worker email from the simulated intake inbox.

Inbox files are plain RFC 5322 text (headers, blank line, body). Only synthetic
messages belong in the inbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email import message_from_string, policy
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path


class EmailFormatError(ValueError):
    """An inbox file is missing a header the intake needs."""


@dataclass(frozen=True)
class IntakeEmail:
    sender: str
    recipient: str
    subject: str
    sent_at: datetime
    body: str


def parse_email_text(text: str) -> IntakeEmail:
    message = message_from_string(text, policy=policy.default)
    for header in ("From", "To", "Subject", "Date"):
        if not message[header]:
            raise EmailFormatError(f"missing {header} header")
    try:
        sent_at = parsedate_to_datetime(message["Date"])
    except (TypeError, ValueError) as exc:
        raise EmailFormatError("unreadable Date header") from exc
    if sent_at.tzinfo is None:
        raise EmailFormatError("Date header has no time zone")
    return IntakeEmail(
        sender=parseaddr(message["From"])[1].lower(),
        recipient=parseaddr(message["To"])[1].lower(),
        subject=str(message["Subject"]).strip(),
        sent_at=sent_at,
        body=message.get_content().strip(),
    )


def load_email_file(path: Path | str) -> IntakeEmail:
    return parse_email_text(Path(path).read_text(encoding="utf-8"))
