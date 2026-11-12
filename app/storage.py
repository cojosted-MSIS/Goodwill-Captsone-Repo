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
-- Open new-client drafts only: a keyed hash of the normalized name and date of birth, never the values.
CREATE TABLE IF NOT EXISTS match_keys (draft_id TEXT PRIMARY KEY, match_key TEXT NOT NULL);
-- Web sessions (app/auth.py): a SHA-256 hash of the session token, never the token itself.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, created_at TEXT NOT NULL, last_seen TEXT NOT NULL
);
-- Idempotency-Key records for web writes (app/web_api.py): a hash of the key, never the key; a hash of
-- the request; and the result as action, ref, and message IDs only, never note text.
CREATE TABLE IF NOT EXISTS idempotency (
    username TEXT NOT NULL, key_hash TEXT NOT NULL, request_hash TEXT NOT NULL, state TEXT NOT NULL,
    result TEXT, created_at TEXT NOT NULL, PRIMARY KEY (username, key_hash)
);
"""

# Audit events renamed in add-web-application Stage 3a, so they name no channel. Rows written before
# keep their old name in the database and are read under the new one, with "renamed_from".
RENAMED_EVENTS = {
    "review_sent": "ready_for_review",
    "verification_sent": "verification_requested",
    "reply_ignored": "action_ignored",
    "reply_ignored_not_author": "action_ignored_not_author",
    "reply_after_expiry": "action_after_expiry",
    "verification_reply_refused": "verification_answer_refused",
    "email_copies_deleted": "copies_deleted",
}


def _event(name: str) -> dict[str, str]:
    new = RENAMED_EVENTS.get(name)
    return {"event": new, "renamed_from": name} if new else {"event": name}


# Email kinds that carry neighbor information and are deleted after submission.
NEIGHBOR_EMAIL_KINDS = ("intake", "review", "reply", "search_request", "missing_info", "notice", "query", "query_reply", "pick_client",
                        "verification", "correction")


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
    message_key: str | None = None  # the neutral key of a system message (app/messages.py)


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        # One connection is shared by the API's worker threads, so every method holds the lock
        # (see _locked below). Without it, two requests at once can interleave on the connection.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        self._db.executescript(SCHEMA)
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(emails)")}
        if "message_key" not in columns:  # a database made before Stage 3a
            with self._db:
                self._db.execute("ALTER TABLE emails ADD COLUMN message_key TEXT")

    # identifiers

    def next_id(self, prefix: str, day: date | None = None) -> str:
        name = f"{prefix}-{day.isoformat()}" if day else prefix
        with self._db:
            self._db.execute("INSERT INTO counters VALUES (?, 1) ON CONFLICT(name) DO UPDATE SET value = value + 1", (name,))
            (value,) = self._db.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()
        return f"{name}-{value:04d}"

    # The web demo's reset: changes when the demo is reset, so an open app knows to clear the device.

    def demo_epoch(self) -> int:
        row = self._db.execute("SELECT value FROM counters WHERE name = 'demo_epoch'").fetchone()
        return row[0] if row else 0

    def set_demo_epoch(self, value: int) -> None:
        with self._db:
            self._db.execute("INSERT INTO counters VALUES ('demo_epoch', ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value", (value,))

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
                  subject: str, body: str, at: datetime, message_key: str | None = None) -> int:
        with self._db:
            cur = self._db.execute(
                "INSERT INTO emails (ref, kind, direction, sender, recipient, subject, body, at, message_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ref, kind, direction, sender, recipient, subject, body, at.isoformat(), message_key),
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
            f"SELECT id, ref, kind, direction, sender, recipient, subject, body, at, message_key FROM emails{where} ORDER BY id",
            args
        )
        return [StoredEmail(*r[:8], datetime.fromisoformat(r[8]), r[9]) for r in rows]

    def move_emails(self, old_ref: str, new_ref: str) -> None:
        with self._db:
            self._db.execute("UPDATE emails SET ref = ? WHERE ref = ?", (new_ref, old_ref))

    def schedule_email_deletion(self, ref: str, delete_after: datetime) -> None:
        marks = ",".join("?" * len(NEIGHBOR_EMAIL_KINDS))
        with self._db:
            self._db.execute(f"UPDATE emails SET delete_after = ? WHERE ref = ? AND kind IN ({marks})",
                             (delete_after.isoformat(), ref, *NEIGHBOR_EMAIL_KINDS))

    def purge_emails(self, now: datetime) -> dict[str, int]:
        """Delete stored copies whose retention has passed. Returns how many were deleted for each ref."""
        rows = self._db.execute("SELECT ref, COUNT(id) FROM emails WHERE delete_after IS NOT NULL AND delete_after <= ? GROUP BY ref",
                                (now.isoformat(),)).fetchall()
        with self._db:
            self._db.execute("DELETE FROM emails WHERE delete_after IS NOT NULL AND delete_after <= ?", (now.isoformat(),))
        return {r[0]: r[1] for r in rows}

    # open-draft match keys (keyed hashes, add-existing-client-updates)

    def save_match_key(self, draft_id: str, match_key: str) -> None:
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO match_keys VALUES (?, ?)", (draft_id, match_key))

    def drafts_with_match_key(self, match_key: str, other_than: str) -> list[str]:
        rows = self._db.execute("SELECT draft_id FROM match_keys WHERE match_key = ? AND draft_id != ? ORDER BY draft_id",
                                (match_key, other_than))
        return [r[0] for r in rows]

    def delete_match_key(self, draft_id: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM match_keys WHERE draft_id = ?", (draft_id,))

    def match_key_count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM match_keys").fetchone()[0]

    # retention (add-existing-client-updates)

    def delete_draft(self, draft_id: str) -> int:
        """Delete a draft, its emails, and its match key. Its audit record stays. Returns the copies deleted."""
        with self._db:
            self._db.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
            copies = self._db.execute("DELETE FROM emails WHERE ref = ?", (draft_id,)).rowcount
            self._db.execute("DELETE FROM match_keys WHERE draft_id = ?", (draft_id,))
        return copies

    def all_pending(self) -> list[PendingIntake]:
        return [PendingIntake.model_validate_json(r[0]) for r in self._db.execute("SELECT data FROM pending ORDER BY id")]

    def delete_pending_and_emails(self, pending_id: str) -> int:
        """Delete a held note and its copies. Returns the copies deleted."""
        with self._db:
            self._db.execute("DELETE FROM pending WHERE id = ?", (pending_id,))
            return self._db.execute("DELETE FROM emails WHERE ref = ?", (pending_id,)).rowcount

    def audit_events_for_prefix(self, prefix: str) -> list[dict[str, Any]]:
        """Audit events of every ref with this prefix (for example every query), oldest first."""
        rows = self._db.execute("SELECT ref, at, event, actor, details FROM audit WHERE ref LIKE ? ORDER BY id", (f"{prefix}%",))
        return [{"ref": r[0], "at": r[1], **_event(r[2]), "actor": r[3], **json.loads(r[4])} for r in rows]

    # web sessions (app/auth.py): stored by a hash of the token only

    def save_session(self, token_hash: str, username: str, at: datetime) -> None:
        with self._db:
            self._db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (token_hash, username, at.isoformat(), at.isoformat()))

    def get_session(self, token_hash: str) -> tuple[str, datetime, datetime] | None:
        """(username, created_at, last_seen) for a session, if it exists."""
        row = self._db.execute("SELECT username, created_at, last_seen FROM sessions WHERE token_hash = ?",
                               (token_hash,)).fetchone()
        return None if row is None else (row[0], datetime.fromisoformat(row[1]), datetime.fromisoformat(row[2]))

    def touch_session(self, token_hash: str, at: datetime) -> None:
        with self._db:
            self._db.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (at.isoformat(), token_hash))

    def delete_session(self, token_hash: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    # Idempotency-Key records (app/web_api.py)

    def claim_idempotency(self, username: str, key_hash: str, request_hash: str, at: datetime,
                          expired_before: datetime) -> tuple[str, dict | None]:
        """One atomic step: forget expired keys, then ("new", None) after reserving the key, ("replay", result)
        for a finished request with the same hash, ("conflict", None) for a different request, or
        ("pending", None) while the first request is still running."""
        with self._db:
            self._db.execute("DELETE FROM idempotency WHERE created_at < ?", (expired_before.isoformat(),))
            row = self._db.execute("SELECT request_hash, state, result FROM idempotency WHERE username = ? AND key_hash = ?",
                                   (username, key_hash)).fetchone()
            if row is None:
                self._db.execute("INSERT INTO idempotency VALUES (?, ?, ?, 'pending', NULL, ?)",
                                 (username, key_hash, request_hash, at.isoformat()))
                return "new", None
        if row[0] != request_hash:
            return "conflict", None
        return ("replay", json.loads(row[2])) if row[1] == "done" else ("pending", None)

    def finish_idempotency(self, username: str, key_hash: str, result: dict) -> None:
        with self._db:
            self._db.execute("UPDATE idempotency SET state = 'done', result = ? WHERE username = ? AND key_hash = ?",
                             (json.dumps(result), username, key_hash))

    def release_idempotency(self, username: str, key_hash: str) -> None:
        """The request failed: forget the key so the same request can be sent again."""
        with self._db:
            self._db.execute("DELETE FROM idempotency WHERE username = ? AND key_hash = ? AND state = 'pending'",
                             (username, key_hash))

    # demo reset (app/demo_reset.py): drafts, pending notes, emails, audit and ID counters

    def reset(self) -> None:
        with self._db:
            for table in ("drafts", "pending", "emails", "audit", "counters", "match_keys", "idempotency"):
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
        return [{"at": r[0], **_event(r[1]), "actor": r[2], **json.loads(r[3])} for r in rows]


def _locked(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


for _name, _member in list(vars(Store).items()):
    if callable(_member) and not _name.startswith("__"):
        setattr(Store, _name, _locked(_member))
