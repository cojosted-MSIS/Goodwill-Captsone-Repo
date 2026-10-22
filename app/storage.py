"""SQLite storage for drafts, the simulated inbox and outbox, and the audit trail.

This is the intake system's own staging store. It is never HMIS: the system writes to HMIS
only through app/hmis_gateway.py and reads nothing back except identifiers.
Audit details hold field names, versions, times, and identifiers only, never note text.
"""

from __future__ import annotations

import functools
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .drafts import Draft, DraftState, PendingIntake

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, state TEXT NOT NULL, author TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pending (id TEXT PRIMARY KEY, author TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT, kind TEXT NOT NULL, direction TEXT NOT NULL,
    sender TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
    at TEXT NOT NULL, delete_after TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL, at TEXT NOT NULL, event TEXT NOT NULL,
    actor TEXT, details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""

# Email kinds that carry neighbor information and are deleted after submission.
NEIGHBOR_EMAIL_KINDS = ("intake", "review", "reply", "search_request", "missing_info", "notice")


@dataclass(frozen=True)
class StoredEmail:
    id: int
    ref: str | None
    kind: str
    direction: str
    sender: str
    recipient: str
    subject: str
    body: str
    at: datetime


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        # One connection is shared by the API's worker threads, so every method holds the lock
        # (see _locked below). Without it, two requests at once can interleave on the connection.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        self._db.executescript(SCHEMA)

    # identifiers

    def next_id(self, prefix: str, day: date | None = None) -> str:
        name = f"{prefix}-{day.isoformat()}" if day else prefix
        with self._db:
            self._db.execute("INSERT INTO counters VALUES (?, 1) ON CONFLICT(name) DO UPDATE SET value = value + 1", (name,))
            (value,) = self._db.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()
        return f"{name}-{value:04d}"

    # drafts

    def save_draft(self, draft: Draft) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO drafts VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET state = excluded.state, data = excluded.data",
                (draft.id, draft.state, draft.author, draft.model_dump_json()),
            )

    def get_draft(self, draft_id: str) -> Draft | None:
        row = self._db.execute("SELECT data FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        return Draft.model_validate_json(row[0]) if row else None

    def drafts(self, state: DraftState | None = None) -> list[Draft]:
        query, args = "SELECT data FROM drafts", ()
        if state:
            query, args = query + " WHERE state = ?", (state,)
        return [Draft.model_validate_json(r[0]) for r in self._db.execute(query + " ORDER BY id", args)]

    # pending intakes (waiting for the worker to confirm the HMIS search)

    def save_pending(self, pending: PendingIntake) -> None:
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO pending VALUES (?, ?, ?)", (pending.id, pending.author, pending.model_dump_json()))

    def get_pending(self, pending_id: str) -> PendingIntake | None:
        row = self._db.execute("SELECT data FROM pending WHERE id = ?", (pending_id,)).fetchone()
        return PendingIntake.model_validate_json(row[0]) if row else None

    def delete_pending(self, pending_id: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM pending WHERE id = ?", (pending_id,))

    # emails (inbound copies and the simulated outbox)

    def add_email(self, *, ref: str | None, kind: str, direction: str, sender: str, recipient: str,
                  subject: str, body: str, at: datetime) -> int:
        with self._db:
            cur = self._db.execute(
                "INSERT INTO emails (ref, kind, direction, sender, recipient, subject, body, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ref, kind, direction, sender, recipient, subject, body, at.isoformat()),
            )
        return cur.lastrowid

    def emails(self, *, ref: str | None = None, recipient: str | None = None, kind: str | None = None) -> list[StoredEmail]:
        clauses, args = [], []
        for column, value in (("ref", ref), ("recipient", recipient), ("kind", kind)):
            if value is not None:
                clauses.append(f"{column} = ?")
                args.append(value)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._db.execute(
            f"SELECT id, ref, kind, direction, sender, recipient, subject, body, at FROM emails{where} ORDER BY id", args
        )
        return [StoredEmail(*r[:8], datetime.fromisoformat(r[8])) for r in rows]

    def move_emails(self, old_ref: str, new_ref: str) -> None:
        with self._db:
            self._db.execute("UPDATE emails SET ref = ? WHERE ref = ?", (new_ref, old_ref))

    def schedule_email_deletion(self, ref: str, delete_after: datetime) -> None:
        marks = ",".join("?" * len(NEIGHBOR_EMAIL_KINDS))
        with self._db:
            self._db.execute(f"UPDATE emails SET delete_after = ? WHERE ref = ? AND kind IN ({marks})",
                             (delete_after.isoformat(), ref, *NEIGHBOR_EMAIL_KINDS))

    def purge_emails(self, now: datetime) -> list[str]:
        """Delete email copies whose retention has passed. Returns the refs affected."""
        rows = self._db.execute("SELECT DISTINCT ref FROM emails WHERE delete_after IS NOT NULL AND delete_after <= ?",
                                (now.isoformat(),)).fetchall()
        with self._db:
            self._db.execute("DELETE FROM emails WHERE delete_after IS NOT NULL AND delete_after <= ?", (now.isoformat(),))
        return [r[0] for r in rows]

    # demo reset (app/demo_reset.py): drafts, pending notes, emails, audit and ID counters

    def reset(self) -> None:
        with self._db:
            for table in ("drafts", "pending", "emails", "audit", "counters"):
                self._db.execute(f"DELETE FROM {table}")
            # Email and audit row numbers restart too (SQLite keeps AUTOINCREMENT sequences otherwise).
            self._db.execute("DELETE FROM sqlite_sequence WHERE name IN ('emails', 'audit')")

    # audit

    def audit(self, ref: str, event: str, at: datetime, actor: str | None = None, **details: Any) -> None:
        with self._db:
            self._db.execute("INSERT INTO audit (ref, at, event, actor, details) VALUES (?, ?, ?, ?, ?)",
                             (ref, at.isoformat(), event, actor, json.dumps(details, default=str, sort_keys=True)))

    def audit_events(self, ref: str) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT at, event, actor, details FROM audit WHERE ref = ? ORDER BY id", (ref,))
        return [{"at": r[0], "event": r[1], "actor": r[2], **json.loads(r[3])} for r in rows]


def _locked(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


for _name, _member in list(vars(Store).items()):
    if callable(_member) and not _name.startswith("__"):
        setattr(Store, _name, _locked(_member))
