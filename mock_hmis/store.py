"""Records held by the mock HMIS, in a SQLite database.

This stands in for HMIS's own database. The entry routes write to it through this class.
Nothing in the HTTP service reads it back. The intake system reads it only through the
read-only views below (see app/hmis_reader.py), on a connection that cannot write, which
stands in for read-only SQL access to the real HMIS [TBC with CHIP and the HMIS
administrator].

Synthetic seed data (sample-data/hmis_seed.yaml) is loaded on start and on reset.
Clients entered through the interface start at the client prefix plus 000001.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from .rules import IdPrefixes

DEFAULT_SEED = Path(__file__).resolve().parent.parent / "sample-data" / "hmis_seed.yaml"

# Views the intake system may read. Anything else is refused by its read-only connection.
READ_VIEWS = ("v_clients", "v_contacts", "v_id_documents", "v_housing_assessments")

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, date_of_birth TEXT, ssn_last4 TEXT,
    name_key TEXT, fields TEXT NOT NULL, visible_to TEXT NOT NULL DEFAULT 'all', seeded INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS enrollments (
    enrollment_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, fields TEXT NOT NULL,
    visible_to TEXT NOT NULL DEFAULT 'all'
);
CREATE TABLE IF NOT EXISTS ce_enrollments (
    ce_enrollment_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, fields TEXT NOT NULL,
    visible_to TEXT NOT NULL DEFAULT 'all'
);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, contact_date TEXT NOT NULL, quadrant TEXT,
    visible_to TEXT NOT NULL DEFAULT 'all'
);
CREATE TABLE IF NOT EXISTS id_documents (
    id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, doc_type TEXT NOT NULL, status TEXT NOT NULL,
    status_date TEXT NOT NULL, visible_to TEXT NOT NULL DEFAULT 'all'
);
CREATE TABLE IF NOT EXISTS housing_assessments (
    id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, status TEXT NOT NULL, status_date TEXT NOT NULL,
    visible_to TEXT NOT NULL DEFAULT 'all'
);
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);

CREATE VIEW IF NOT EXISTS v_clients AS
    SELECT client_id, first_name, substr(last_name, 1, 1) AS last_initial, name_key, date_of_birth, ssn_last4,
           visible_to
    FROM clients;
CREATE VIEW IF NOT EXISTS v_contacts AS
    SELECT client_id, contact_date, quadrant, visible_to FROM contacts;
CREATE VIEW IF NOT EXISTS v_id_documents AS
    SELECT client_id, doc_type, status, status_date, visible_to FROM id_documents;
CREATE VIEW IF NOT EXISTS v_housing_assessments AS
    SELECT client_id, status, status_date, visible_to FROM housing_assessments;
"""

TABLES = ("clients", "enrollments", "ce_enrollments", "contacts", "id_documents", "housing_assessments", "counters")


def name_key(first: Any, last: Any) -> str | None:
    """First and last name without case, spacing, or punctuation, for exact matching."""
    if not first or not last:
        return None
    return re.sub(r"[^a-z]", "", f"{first}{last}".lower()) or None


class MockHmisStore:
    def __init__(self, prefixes: IdPrefixes, db_path: str | Path | None = None,
                 seed_path: Path | None = DEFAULT_SEED, today: date | None = None) -> None:
        self._prefixes = prefixes
        if db_path is None:  # a private file per instance, so tests never share records
            fd, name = tempfile.mkstemp(prefix="mock-hmis-", suffix=".db")
            os.close(fd)
            db_path = name
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._seed_path = seed_path
        self._today = today
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        self.reset()

    # setup

    def reset(self) -> None:
        """Delete every record, restart the ID counter, and load the seed data again."""
        with self._lock, self._db:
            for table in TABLES:
                self._db.execute(f"DELETE FROM {table}")
            if self._seed_path is not None:
                self._load_seed(yaml.safe_load(Path(self._seed_path).read_text(encoding="utf-8")) or {})

    def _load_seed(self, data: dict) -> None:
        today = self._today or date.today()

        def day(days_ago: int) -> str:
            return (today - timedelta(days=int(days_ago))).isoformat()

        for c in data.get("clients", []):
            visible = c.get("visible_to", "all")
            dob = str(c["date_of_birth"])
            fields = {"first_name": c["first_name"], "last_name": c["last_name"], "date_of_birth": dob}
            self._db.execute(
                "INSERT INTO clients (client_id, first_name, last_name, date_of_birth, ssn_last4, name_key, fields,"
                " visible_to, seeded) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (c["id"], c["first_name"], c["last_name"], dob, c.get("ssn_last4"),
                 name_key(c["first_name"], c["last_name"]), json.dumps(fields), visible))
            for k in c.get("contacts", []):
                self._db.execute("INSERT INTO contacts (client_id, contact_date, quadrant, visible_to) VALUES (?, ?, ?, ?)",
                                 (c["id"], day(k["days_ago"]), k.get("quadrant"), visible))
            for d in c.get("id_documents", []):
                self._db.execute(
                    "INSERT INTO id_documents (client_id, doc_type, status, status_date, visible_to) VALUES (?, ?, ?, ?, ?)",
                    (c["id"], d["doc_type"], d["status"], day(d["days_ago"]), visible))
            for h in c.get("housing_assessments", []):
                self._db.execute(
                    "INSERT INTO housing_assessments (client_id, status, status_date, visible_to) VALUES (?, ?, ?, ?)",
                    (c["id"], h["status"], day(h["days_ago"]), visible))

    def _next_id(self, prefix: str) -> str:
        """The next identifier from one counter shared by every entry, skipping seeded IDs."""
        while True:
            self._db.execute("INSERT INTO counters VALUES ('entry', 1) ON CONFLICT(name) DO UPDATE SET value = value + 1")
            (value,) = self._db.execute("SELECT value FROM counters WHERE name = 'entry'").fetchone()
            candidate = f"{prefix}-{value:06d}"
            if not self._db.execute("SELECT 1 FROM clients WHERE client_id = ?", (candidate,)).fetchone():
                return candidate

    # entry operations (the HTTP service is the only caller)

    def add_client(self, fields: dict[str, Any]) -> str:
        with self._lock, self._db:
            client_id = self._next_id(self._prefixes.client)
            self._db.execute(
                "INSERT INTO clients (client_id, first_name, last_name, date_of_birth, ssn_last4, name_key, fields)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (client_id, fields.get("first_name"), fields.get("last_name"), fields.get("date_of_birth"),
                 fields.get("ssn_last4"), name_key(fields.get("first_name"), fields.get("last_name")),
                 json.dumps(fields, default=str)))
            return client_id

    def has_client(self, client_id: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM clients WHERE client_id = ?", (client_id,)).fetchone() is not None

    def has_program_enrollment(self, client_id: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM enrollments WHERE client_id = ?", (client_id,)).fetchone() is not None

    def add_enrollment(self, client_id: str, fields: dict[str, Any]) -> str:
        with self._lock, self._db:
            enrollment_id = self._next_id(self._prefixes.enrollment)
            self._db.execute("INSERT INTO enrollments (enrollment_id, client_id, fields) VALUES (?, ?, ?)",
                             (enrollment_id, client_id, json.dumps(fields, default=str)))
            return enrollment_id

    def add_ce_enrollment(self, client_id: str, fields: dict[str, Any]) -> str:
        with self._lock, self._db:
            ce_id = self._next_id(self._prefixes.ce_enrollment)
            self._db.execute("INSERT INTO ce_enrollments (ce_enrollment_id, client_id, fields) VALUES (?, ?, ?)",
                             (ce_id, client_id, json.dumps(fields, default=str)))
            # The Coordinated Entry contact becomes a contact record. The quadrant is not part of
            # this entry, so it stays unknown [TBC: whether HMIS records a location per contact].
            if fields.get("information_date"):
                self._db.execute("INSERT INTO contacts (client_id, contact_date, quadrant) VALUES (?, ?, NULL)",
                                 (client_id, str(fields["information_date"])))
            return ce_id

    def possible_duplicate(self, match_on: list[str], fields: dict[str, Any]) -> bool:
        """True when an existing client matches on every match field. Blank values never match."""
        wanted = [_normalize(fields.get(name)) for name in match_on]
        if any(v is None for v in wanted):
            return False
        with self._lock:
            rows = self._db.execute("SELECT fields FROM clients").fetchall()
        return any([_normalize(json.loads(r[0]).get(name)) for name in match_on] == wanted for r in rows)

    def counts(self) -> dict[str, int]:
        """Totals of records entered through the interface (not the seed). For in-process tests only."""
        with self._lock:
            one = lambda sql: self._db.execute(sql).fetchone()[0]  # noqa: E731
            return {
                "clients": one("SELECT COUNT(*) FROM clients WHERE seeded = 0"),
                "enrollments": one("SELECT COUNT(*) FROM enrollments"),
                "ce_enrollments": one("SELECT COUNT(*) FROM ce_enrollments"),
            }

    def close(self) -> None:
        with self._lock:
            self._db.close()


def _normalize(value: Any) -> Any:
    if value is None or value == "":
        return None
    return value.strip().lower() if isinstance(value, str) else value
