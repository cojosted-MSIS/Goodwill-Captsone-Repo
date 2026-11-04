"""Read-only access to HMIS for the four fixed query types (add-hmis-readonly-queries, add-no-contact-query).

This stands in for read-only SQL access to the real HMIS, which is unconfirmed [TBC with
CHIP and the HMIS administrator]. The guardrails, in code:
- the connection is opened read-only (`mode=ro`) and set to `query_only`;
- an authorizer refuses everything except SELECT reads of the allowlisted views;
- the only SQL that runs is the fixed text below, with every value bound as a parameter;
- results are capped at the row limit, filtered by the worker's project visibility.
Writes to HMIS never come through here; they go only through the entry operations.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from mock_hmis.store import READ_VIEWS, name_key

ALLOWED_FUNCTIONS = {"max", "count", "substr", "coalesce"}

# Fixed query text. Values are bound with ?; nothing from an email is ever put in here.
BRIEFING_COUNT = """
SELECT COUNT(DISTINCT c.client_id) FROM v_clients c JOIN v_contacts k ON k.client_id = c.client_id
WHERE k.quadrant = ? AND k.contact_date >= ? AND k.contact_date <= ?
  AND c.visible_to IN ('all', ?) AND k.visible_to IN ('all', ?)
"""
BRIEFING_ROWS = """
SELECT c.client_id, c.first_name, c.last_initial, MAX(k.contact_date) AS last_contact
FROM v_clients c JOIN v_contacts k ON k.client_id = c.client_id
WHERE k.quadrant = ? AND k.contact_date >= ? AND k.contact_date <= ?
  AND c.visible_to IN ('all', ?) AND k.visible_to IN ('all', ?)
GROUP BY c.client_id ORDER BY last_contact DESC, c.client_id LIMIT ?
"""
OPEN_ID_DOCUMENTS = """
SELECT client_id, doc_type, status FROM v_id_documents
WHERE client_id = ? AND visible_to IN ('all', ?) AND status = 'requested'
"""
OPEN_HOUSING = """
SELECT client_id, status FROM v_housing_assessments
WHERE client_id = ? AND visible_to IN ('all', ?) AND status = 'scheduled'
"""
LOOKUP_BY_NAME = """
SELECT client_id, first_name, last_initial, ssn_last4, entered_date FROM v_clients
WHERE name_key = ? AND date_of_birth = ? AND visible_to IN ('all', ?) ORDER BY client_id LIMIT ?
"""
LOOKUP_BY_ID = """
SELECT client_id, first_name, last_initial, ssn_last4, entered_date FROM v_clients
WHERE client_id = ? AND visible_to IN ('all', ?) LIMIT 1
"""
ENROLLMENTS = """
SELECT COUNT(client_id), COUNT(exit_date) FROM v_enrollments WHERE client_id = ? AND visible_to IN ('all', ?)
"""
LAST_SERVICE = """
SELECT service_type FROM v_services
WHERE client_id = ? AND visible_to IN ('all', ?) ORDER BY service_date DESC LIMIT 1
"""
LAST_CONTACT = """
SELECT contact_date, quadrant FROM v_contacts
WHERE client_id = ? AND visible_to IN ('all', ?) ORDER BY contact_date DESC LIMIT 1
"""
# No-contact watchlist (add-no-contact-query): each visible neighbor with an active enrollment, with the
# date and quadrant of the last contact. SQLite takes the quadrant from the row with the latest date.
NO_CONTACT_LAST = """
SELECT c.client_id, c.first_name, c.last_initial, MAX(k.contact_date) AS last_contact, k.quadrant AS quadrant
FROM v_clients c JOIN v_contacts k ON k.client_id = c.client_id
WHERE c.visible_to IN ('all', ?) AND k.visible_to IN ('all', ?)
  AND c.client_id IN (SELECT e.client_id FROM v_enrollments e WHERE e.exit_date IS NULL AND e.visible_to IN ('all', ?))
GROUP BY c.client_id
"""
NO_CONTACT_COUNT = f"""
SELECT COUNT(CASE WHEN last_contact < ? THEN client_id END), COUNT(CASE WHEN last_contact >= ? THEN client_id END)
FROM ({NO_CONTACT_LAST}) WHERE last_contact <= ? AND (? IS NULL OR quadrant = ?)
"""
NO_CONTACT_ROWS = f"""
SELECT client_id, first_name, last_initial, last_contact, quadrant FROM ({NO_CONTACT_LAST})
WHERE last_contact <= ? AND (? IS NULL OR quadrant = ?) ORDER BY last_contact, client_id LIMIT ?
"""
STATUS_ID_DOCUMENTS = """
SELECT doc_type, status, status_date FROM v_id_documents
WHERE client_id = ? AND visible_to IN ('all', ?) ORDER BY status_date DESC LIMIT ?
"""
STATUS_HOUSING = """
SELECT 'housing_assessment', status, status_date FROM v_housing_assessments
WHERE client_id = ? AND visible_to IN ('all', ?) ORDER BY status_date DESC LIMIT ?
"""


class ReadRefused(Exception):
    """A read the guardrails do not allow. Never shown to the worker with any data."""


@dataclass(frozen=True)
class Neighbor:
    client_id: str
    first_name: str
    last_initial: str
    last_contact: str | None = None
    quadrant: str | None = None
    open_items: tuple[str, ...] = ()
    ssn_last4: str | None = None  # kept for verification grading only; never put in a reply
    entered: str | None = None  # the date the record was entered in HMIS
    enrollment: str | None = None  # "active", "exited", or None when no enrollment is recorded
    last_service_type: str | None = None  # an option ID; the label comes from config


@dataclass(frozen=True)
class Briefing:
    total: int
    neighbors: list[Neighbor]


@dataclass(frozen=True)
class Watchlist:
    past: int  # how many are past the limit (all of them, not only the rows shown)
    approaching: int
    neighbors: list[Neighbor]  # most overdue first, at most the row limit


@dataclass(frozen=True)
class StatusRow:
    kind: str
    status: str
    status_date: str


def _authorizer(action: int, arg1: str | None, arg2: str | None, db_name: str | None, source: str | None) -> int:
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and (arg1 in READ_VIEWS or source in READ_VIEWS):
        return sqlite3.SQLITE_OK  # an allowlisted view, or a table read through one
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in ALLOWED_FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class HmisReader:
    def __init__(self, database: str | Path, row_limit: int) -> None:
        self.database = Path(database)
        self.row_limit = row_limit

    def connect(self) -> sqlite3.Connection:
        """A connection that cannot write and can read only the allowlisted views."""
        if not self.database.exists():
            raise ReadRefused("HMIS cannot be read right now")
        conn = sqlite3.connect(f"{self.database.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
        conn.execute("PRAGMA query_only = ON")
        conn.set_authorizer(_authorizer)
        return conn

    def _rows(self, sql: str, params: tuple) -> list[tuple]:
        conn = self.connect()
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.DatabaseError as exc:
            raise ReadRefused("the read was refused") from exc
        finally:
            conn.close()

    # briefing

    def briefing(self, quadrant: str, since: date, today: date, project: str) -> Briefing:
        window = (quadrant, since.isoformat(), today.isoformat(), project, project)
        (total,) = self._rows(BRIEFING_COUNT, window)[0]
        neighbors = [Neighbor(client_id, first, initial, last, quadrant, self._open_items(client_id, project))
                     for client_id, first, initial, last in self._rows(BRIEFING_ROWS, (*window, self.row_limit))]
        return Briefing(total=total, neighbors=neighbors)

    def _open_items(self, client_id: str, project: str) -> tuple[str, ...]:
        items = []
        if self._rows(OPEN_ID_DOCUMENTS, (client_id, project)):
            items.append("ID document pending")
        if self._rows(OPEN_HOUSING, (client_id, project)):
            items.append("housing assessment scheduled")
        return tuple(items)

    # no-contact watchlist

    def no_contact(self, listed_from: date, past_before: date, quadrant: str | None, project: str) -> Watchlist:
        """Neighbors whose last contact was on or before `listed_from`; those before `past_before` are past."""
        scope = (project, project, project)
        where = (listed_from.isoformat(), quadrant, quadrant)
        past, approaching = self._rows(NO_CONTACT_COUNT, (past_before.isoformat(), past_before.isoformat(), *scope, *where))[0]
        rows = self._rows(NO_CONTACT_ROWS, (*scope, *where, self.row_limit))
        neighbors = [Neighbor(client_id, first, initial, last, quad, self._open_items(client_id, project))
                     for client_id, first, initial, last, quad in rows]
        return Watchlist(past=past, approaching=approaching, neighbors=neighbors)

    # lookup

    def _with_last_contact(self, row: tuple, project: str) -> Neighbor:
        client_id, first, initial, last4, entered = row
        contact = self._rows(LAST_CONTACT, (client_id, project))
        last, quadrant = contact[0] if contact else (None, None)
        total, exited = self._rows(ENROLLMENTS, (client_id, project))[0]
        enrollment = None if not total else "active" if total > exited else "exited"
        service = self._rows(LAST_SERVICE, (client_id, project))
        return Neighbor(client_id, first, initial, last, quadrant, (), last4, entered, enrollment,
                        service[0][0] if service else None)

    def lookup_by_name(self, first: str, last: str, dob: date, project: str) -> list[Neighbor]:
        key = name_key(first, last)
        rows = self._rows(LOOKUP_BY_NAME, (key, dob.isoformat(), project, self.row_limit))
        return [self._with_last_contact(r, project) for r in rows]

    def lookup_by_id(self, client_id: str, project: str) -> list[Neighbor]:
        return [self._with_last_contact(r, project) for r in self._rows(LOOKUP_BY_ID, (client_id, project))]

    # status

    def status(self, client_id: str, status_type: str, project: str) -> list[StatusRow]:
        sql = STATUS_ID_DOCUMENTS if status_type == "id_document" else STATUS_HOUSING
        return [StatusRow(*r) for r in self._rows(sql, (client_id, project, self.row_limit))]
