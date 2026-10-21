"""Dates written in a note, read in code (never by a model).

parse_written_date reads a date exactly as the worker wrote it. It returns None for
anything that is not a full day, month, and year: a partial date is never completed.

resolve_contact_phrase turns the words saying when the contact happened ("this morning",
"Tuesday", "on 10/5") into a date, using the email's sent date for relative phrases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

MONTHS = {
    m: i
    for i, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
         ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"),
         ("nov", "november"), ("dec", "december")],
        start=1,
    )
    for m in names
}
WEEKDAYS = {name: i for i, name in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
WEEKDAY_SHORT = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}


def _year(text: str, reference: date) -> int:
    year = int(text)
    if len(text) == 2:
        # Two-digit years: a year after this one belongs to the previous century.
        year += 2000 if year <= reference.year % 100 else 1900
    return year


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_written_date(text: str, reference: date) -> date | None:
    """A full date as written (3/4/1975, 3/14/78, March 4, 1975, 4 March 1975, 1975-03-04), else None."""
    t = text.strip().lower().rstrip(".,")
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t):
        return _safe(int(m[1]), int(m[2]), int(m[3]))
    if m := re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})", t):
        return _safe(_year(m[3], reference), int(m[1]), int(m[2]))
    if m := re.fullmatch(r"([a-z]+)\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})", t):
        month = MONTHS.get(m[1])
        return _safe(int(m[3]), month, int(m[2])) if month else None
    if m := re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? ([a-z]+),? (\d{4})", t):
        month = MONTHS.get(m[2])
        return _safe(int(m[3]), month, int(m[1])) if month else None
    return None


@dataclass(frozen=True)
class ResolvedDate:
    value: date
    kind: Literal["stated", "relative"]  # stated: the note gives the date; relative: worked out from the email date


def resolve_contact_phrase(phrase: str, sent: date) -> ResolvedDate | None:
    """The contact date for a phrase, or None when it cannot be pinned to one day ("last week")."""
    t = phrase.strip().lower()
    if full := re.search(r"\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})\b", t):
        value = parse_written_date(full.group(0), sent)
        return ResolvedDate(value, "stated") if value else None
    if m := re.search(r"\b(\d{1,2})/(\d{1,2})\b", t):
        value = _safe(sent.year, int(m[1]), int(m[2]))
        if value and value > sent:
            value = _safe(sent.year - 1, int(m[1]), int(m[2]))
        return ResolvedDate(value, "stated") if value else None
    if re.search(r"\b(today|this morning|this afternoon|this evening|tonight)\b", t):
        return ResolvedDate(sent, "relative")
    if re.search(r"\b(yesterday|last night)\b", t):
        return ResolvedDate(sent - timedelta(days=1), "relative")
    for word in re.findall(r"[a-z]+", t):
        weekday = WEEKDAYS.get(word, WEEKDAY_SHORT.get(word))
        if weekday is not None:
            back = (sent.weekday() - weekday) % 7
            if "last" in t.split() and back == 0:
                back = 7
            return ResolvedDate(sent - timedelta(days=back), "relative")
    return None
