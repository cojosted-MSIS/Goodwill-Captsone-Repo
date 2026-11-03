"""The open-draft match key (add-existing-client-updates).

The read-only lookup sees clients already in HMIS, not drafts still open here, so two workers
drafting the same neighbor would both pass it. Each open new-client draft therefore keeps only
a keyed hash (HMAC-SHA256) of the normalized first name, last name, and date of birth. The
values themselves are never kept for matching.

The key comes from the environment (.env, git-ignored), never from the repo. It is required in
production retention mode. In demo mode, when none is set, a random key is made in memory for
the run and written nowhere. The key is never printed or logged.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from collections.abc import Mapping

from .config_loader import Settings


class MatchKeyMissing(RuntimeError):
    """Production retention mode without a match key: the system refuses to start."""


def load_match_key(settings: Settings, environ: Mapping[str, str] | None = None) -> bytes:
    env = settings.retention.match_key_env
    value = (os.environ if environ is None else environ).get(env, "")
    if value:
        return value.encode("utf-8")
    if settings.retention.mode == "production":
        raise MatchKeyMissing(f"{env} is not set. Production retention mode needs it in .env (a long random value). "
                              "The system will not start without it.")
    return secrets.token_bytes(32)  # demo mode: in memory for this run only


def _normalize(text: object) -> str:
    return re.sub(r"[^a-z]", "", str(text).lower())


def match_key(key: bytes, first: object, last: object, date_of_birth: object) -> str:
    message = f"{_normalize(first)}|{_normalize(last)}|{date_of_birth}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()
