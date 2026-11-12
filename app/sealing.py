"""Open notes sealed on a worker's device (add-web-application, Stage 4c).

A device encrypts each queued note so that it can write the note but never read it back: a random
AES-GCM key per note, wrapped with this server's RSA-OAEP public key (ui/web/seal.js). Only the
private keys here can open it, and the server encrypts nothing itself.

  - Each envelope names its key by key ID, the SHA-256 of the public key. The server holds several
    private keys at once, so a rotation never strands a note. The first key is the current one.
  - The user ID, the Idempotency-Key, the note's kind, its time saved, the format version, and the
    key ID are AES-GCM associated data: a note cannot be moved to another user or replayed under
    another key without decryption failing.
  - A contact stamp records when the server last spoke to a user, signed so the device cannot
    change it. It lets the server enforce the offline limit against its own clock.

Private keys come from the environment (.env, git-ignored): base64 PKCS#8, separated by commas,
newest first. Required in production retention mode. In demo mode, when none is set, one is made in
memory the first time a page asks, so notes saved on a device do not survive a restart. A key is
never printed, logged, or returned. Production key custody is [TBC with Goodwill IT].
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SEAL_KEYS_ENV = "INTAKE_SEAL_PRIVATE_KEYS"
FORMAT_VERSION = 1
MIN_KEY_BITS = 3072
_OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
_STAMP_CONTEXT = b"outreach-contact-stamp-v1:"


class SealKeyMissing(RuntimeError):
    """Production retention mode without a sealing key: the system refuses to start."""


class EnvelopeRefused(Exception):
    """An envelope that cannot be opened. It never says which part failed."""

    def __init__(self, code: str) -> None:
        super().__init__("The envelope could not be opened.")
        self.code = code  # "unreadable" or "unknown_key"


def new_private_key() -> str:
    """A new private key as base64 PKCS#8, the form the environment variable holds."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=MIN_KEY_BITS)
    der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return base64.b64encode(der).decode("ascii")


def associated_data(version: int, key_id: str, owner: str, idempotency_key: str, kind: str, saved_at: str) -> bytes:
    """What each envelope is bound to. ui/web/seal.js builds exactly the same bytes."""
    fields = ["outreach-note", version, key_id, owner, idempotency_key, kind, saved_at]
    return json.dumps(fields, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _b64(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise EnvelopeRefused("unreadable")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise EnvelopeRefused("unreadable") from None


class _Key:
    __slots__ = ("private", "public_b64", "key_id", "stamp_key")

    def __init__(self, encoded: str) -> None:
        try:
            der = base64.b64decode(encoded.strip(), validate=True)
            private = serialization.load_der_private_key(der, password=None)
        except Exception:  # noqa: BLE001  (the value must never reach an error message)
            raise ValueError(f"An entry in {SEAL_KEYS_ENV} is not a valid private key.") from None
        if not isinstance(private, rsa.RSAPrivateKey) or private.key_size < MIN_KEY_BITS:
            raise ValueError(f"Each key in {SEAL_KEYS_ENV} must be RSA of at least {MIN_KEY_BITS} bits.")
        public = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.private = private
        self.public_b64 = base64.b64encode(public).decode("ascii")
        self.key_id = hashlib.sha256(public).hexdigest()
        self.stamp_key = hashlib.sha256(_STAMP_CONTEXT + der).digest()


class Sealer:
    """The server's private keys. Newest first; every key can open and check, only the first is offered."""

    def __init__(self, private_keys: Sequence[str] = ()) -> None:
        self._keys = [_Key(k) for k in private_keys]
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"Sealer({len(self._keys)} keys)"

    @classmethod
    def from_environment(cls, settings: Any, environ: Mapping[str, str] | None = None) -> Sealer:
        value = (os.environ if environ is None else environ).get(SEAL_KEYS_ENV, "")
        keys = [part for part in value.split(",") if part.strip()]
        if not keys and settings.retention.mode == "production":
            raise SealKeyMissing(f"{SEAL_KEYS_ENV} is not set. Production retention mode needs it in .env. The system will not start without it.")
        return cls(keys)

    def _ensure(self) -> list[_Key]:
        with self._lock:
            if not self._keys:  # demo mode: in memory for this run only
                self._keys.append(_Key(new_private_key()))
            return self._keys

    def key_ids(self) -> list[str]:
        return [k.key_id for k in self._keys]

    def current(self) -> dict[str, str]:
        """The public key new notes are sealed with."""
        key = self._ensure()[0]
        return {"key_id": key.key_id, "public_key": key.public_b64}

    def open(self, envelope: Mapping[str, Any], *, owner: str, idempotency_key: str, kind: str, saved_at: str) -> dict:
        """The note inside `envelope`, or EnvelopeRefused. Every failure after the key lookup looks the same."""
        if envelope.get("v") != FORMAT_VERSION:
            raise EnvelopeRefused("unreadable")
        key_id = envelope.get("key_id")
        key = next((k for k in self._keys if k.key_id == key_id), None)
        if key is None:
            raise EnvelopeRefused("unknown_key")
        wrapped, nonce, ciphertext = (_b64(envelope.get(f)) for f in ("wrapped_key", "nonce", "ciphertext"))
        aad = associated_data(FORMAT_VERSION, key_id, owner, idempotency_key, kind, saved_at)
        try:
            aes = key.private.decrypt(wrapped, _OAEP)
            if len(aes) != 32 or len(nonce) != 12:
                raise ValueError
            inner = json.loads(AESGCM(aes).decrypt(nonce, ciphertext, aad))
        except (InvalidTag, ValueError, RecursionError):
            raise EnvelopeRefused("unreadable") from None
        if not isinstance(inner, dict):
            raise EnvelopeRefused("unreadable")
        return inner

    def contact_stamp(self, username: str, at: datetime) -> str:
        """A stamp saying the server spoke to `username` at `at`."""
        seconds = str(int(at.timestamp()))
        return f"{seconds}.{self._sign(self._ensure()[0], username, seconds)}"

    def contact_time(self, stamp: str, username: str) -> datetime | None:
        """When the stamp was made, or None if it is forged, damaged, or someone else's."""
        seconds, dot, signature = stamp.partition(".")
        if not dot or not seconds.isascii() or not seconds.isdigit() or len(seconds) > 12:
            return None
        if not any(hmac.compare_digest(signature, self._sign(k, username, seconds)) for k in self._keys):
            return None
        return datetime.fromtimestamp(int(seconds), tz=timezone.utc)

    @staticmethod
    def _sign(key: _Key, username: str, seconds: str) -> str:
        return hmac.new(key.stamp_key, f"{username}\n{seconds}".encode("utf-8"), hashlib.sha256).hexdigest()
