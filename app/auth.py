"""Web sign-in, server-side sessions, and CSRF tokens (add-web-application, Stage 2b).

Passwords. The demo accounts in config/users.yaml are synthetic. Each password is read from the
environment (.env, git-ignored) when the app starts, and only a salted scrypt hash of it is
kept, in memory. No password is stored in the repository, the database, a log, or the audit.
Production sign-in (likely single sign-on) is [TBC with Goodwill IT].

Sessions. A random token in an HttpOnly, SameSite=Strict cookie, Secure over https. The store
keeps only a SHA-256 hash of the token with the username and two times, so a copy of the
database cannot be used to sign in. Idle and absolute timeouts come from settings.yaml (web).
Signing out deletes the session on the server.

CSRF. Every state-changing /api/v1 request carries the X-CSRF-Token header. After sign-in the
token is an HMAC of the session token: bound to that session and never stored. Before sign-in,
the sign-in form uses a double-submit token (a random value in its own cookie that must match
the header).

Brute force. Failed sign-ins are counted per username, known or not, and attempts per client
address, in memory. A username is locked for a while after too many failures, and every
refusal gives the same answer, so no answer reveals whether a username exists. With more than
one app process the counts would need a shared store [TBC with Goodwill IT].
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config_loader import AppConfig, SignInSettings, WebSettings, Worker
from .storage import Store

SESSION_COOKIE = "hmis_session"
SIGN_IN_COOKIE = "hmis_sign_in_csrf"
CSRF_HEADER = "X-CSRF-Token"

# scrypt from the standard library: 16 MB of memory per hash, a 16-byte random salt per password.
SCRYPT_N, SCRYPT_R, SCRYPT_P, KEY_BYTES = 2**14, 8, 1, 32


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_BYTES)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        name, n, r, p, salt, key = stored.split("$")
        if name != "scrypt":
            return False
        expected = base64.urlsafe_b64decode(key)
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.urlsafe_b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_for(session_token: str) -> str:
    """The CSRF token of a session: derived from the session token, so it is never stored."""
    return hmac.new(session_token.encode("utf-8"), b"hmis-csrf-v1", hashlib.sha256).hexdigest()


def same_token(sent: str | None, expected: str | None) -> bool:
    return bool(sent) and bool(expected) and hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8"))


# Users


@dataclass(frozen=True)
class User:
    username: str
    role: str  # worker or supervisor
    display_name: str
    worker: Worker | None = None  # a worker's record: address (the identity on drafts) and project

    @property
    def address(self) -> str | None:
        return self.worker.address.lower() if self.worker else None

    @property
    def project(self) -> str | None:
        return self.worker.project if self.worker else None

    def public(self) -> dict:
        return {"username": self.username, "role": self.role, "display_name": self.display_name, "project": self.project}


class UserDirectory:
    """The sign-in accounts, with a salted hash of each password read from `env`. No password is kept."""

    def __init__(self, config: AppConfig, env: Mapping[str, str]) -> None:
        self._users: dict[str, User] = {}
        self._hashes: dict[str, str] = {}
        self.missing: list[str] = []  # names of password variables that are not set (never their values)
        for a in config.users.accounts:
            worker = config.workers.worker_for(a.worker) if a.worker else None
            name = worker.display_name if worker else (a.display_name or a.username)
            self._users[a.username] = User(a.username, a.role, name, worker)
            password = env.get(a.password_env)
            if password:
                self._hashes[a.username] = hash_password(password)
            else:
                self.missing.append(a.password_env)
        # Checked against for unknown usernames, so a sign-in takes as long whether or not the name exists.
        self._decoy = hash_password(secrets.token_urlsafe(18))

    @classmethod
    def from_environment(cls, config: AppConfig) -> UserDirectory:
        return cls(config, os.environ)

    def get(self, username: str | None) -> User | None:
        return self._users.get(username) if username else None

    def check(self, username: str, password: str) -> User | None:
        stored = self._hashes.get(username)
        ok = verify_password(password, stored or self._decoy)
        return self._users[username] if ok and stored else None


# Sessions


class Sessions:
    def __init__(self, store: Store, settings: WebSettings, clock: Callable[[], datetime]) -> None:
        self.store = store
        self.idle = timedelta(minutes=settings.session_idle_minutes)
        self.absolute = timedelta(hours=settings.session_absolute_hours)
        self.clock = clock

    def start(self, user: User) -> str:
        """A new session, with a new random token (never one the browser offered)."""
        token = secrets.token_urlsafe(32)
        self.store.save_session(token_hash(token), user.username, self.clock())
        return token

    def resolve(self, token: str) -> tuple[str | None, str | None]:
        """(username, None) for a live session, (username, "idle" or "absolute") for one that just expired
        and was deleted, and (None, None) for no session."""
        key = token_hash(token)
        row = self.store.get_session(key)
        if row is None:
            return None, None
        username, created, last_seen = row
        now = self.clock()
        expired = "absolute" if now - created >= self.absolute else "idle" if now - last_seen >= self.idle else None
        if expired:
            self.store.delete_session(key)
            return username, expired
        self.store.touch_session(key, now)
        return username, None

    def end(self, token: str) -> None:
        self.store.delete_session(token_hash(token))


# Brute force


class SignInGuard:
    """Failed sign-ins per username and attempts per client address, in memory. Never logged or stored."""

    def __init__(self, rules: SignInSettings, clock: Callable[[], datetime]) -> None:
        self.rules = rules
        self.clock = clock
        self.window = timedelta(minutes=rules.window_minutes)
        self._failures: dict[str, deque[datetime]] = {}
        self._attempts: dict[str, deque[datetime]] = {}
        self._locked_until: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def _recent(self, table: dict[str, deque[datetime]], key: str, now: datetime) -> deque[datetime]:
        times = table.setdefault(key, deque())
        while times and now - times[0] >= self.window:
            times.popleft()
        return times

    def refused(self, username: str, client: str) -> str | None:
        """Count this attempt. "rate_limited" or "locked" when it must be refused, else None."""
        now = self.clock()
        with self._lock:
            if len(self._attempts) > 10_000:  # forget clients with no recent attempts
                self._attempts = {k: v for k, v in self._attempts.items() if v and now - v[-1] < self.window}
            attempts = self._recent(self._attempts, client, now)
            if len(attempts) >= self.rules.max_attempts_per_client:
                return "rate_limited"
            attempts.append(now)
            until = self._locked_until.get(username)
            if until is not None and until > now:
                return "locked"
            self._locked_until.pop(username, None)
            return None

    def failed(self, username: str) -> bool:
        """Record a failure. True when it locks the username."""
        now = self.clock()
        with self._lock:
            failures = self._recent(self._failures, username, now)
            failures.append(now)
            if len(failures) < self.rules.max_failures:
                return False
            self._failures.pop(username, None)
            self._locked_until[username] = now + timedelta(minutes=self.rules.lockout_minutes)
            return True

    def succeeded(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username, None)
