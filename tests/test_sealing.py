"""add-web-application, Stage 4c: sealing a note on the device so that only the server can open it.

A note sealed in Node with real WebCrypto (ui/web/seal.js) must open in Python (app/sealing.py), and
any change to the envelope, or a different user, Idempotency-Key, kind, time, or key ID, must fail.
Keys are made at random for these tests and never written anywhere. Plan: design.md section 5a.
Synthetic data only.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.sealing import SEAL_KEYS_ENV, EnvelopeRefused, SealKeyMissing, Sealer, associated_data, new_private_key

from .conftest import REPO_ROOT
from .test_web_screens import node

OWNER = "j.alvarez"
KEY = "6f1c2a70-8b44-4f0e-9d13-3e1f6a7b9c11"
KIND = "new_client"
SAVED = "2026-10-07T14:31:00.000Z"
INNER = {"text": "Met Kim Placeholder. Café ✓. SSN ends 4821.", "title": "Kim, NW quadrant", "written_at": SAVED,
         "ssn_invalid_label": None, "contact": "stamp"}


@lru_cache(maxsize=4)
def private_key(n: int = 0) -> str:
    return new_private_key()


def py_seal(public: dict, owner: str, idempotency_key: str, kind: str, saved_at: str, inner: dict) -> dict:
    """The same envelope ui/web/seal.js makes, for tests that do not need Node."""
    der = base64.b64decode(public["public_key"])
    key = serialization.load_der_public_key(der)
    aes = os.urandom(32)
    nonce = os.urandom(12)
    aad = associated_data(1, public["key_id"], owner, idempotency_key, kind, saved_at)
    ciphertext = AESGCM(aes).encrypt(nonce, json.dumps(inner).encode("utf-8"), aad)
    wrapped = key.encrypt(aes, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return {"v": 1, "key_id": public["key_id"], "wrapped_key": b64(wrapped), "nonce": b64(nonce), "ciphertext": b64(ciphertext)}


def node_seal(public: dict, notes: list[dict]) -> dict:
    plan = {"module": str(REPO_ROOT / "ui" / "web" / "seal.js"), "key": public, "notes": notes}
    run = subprocess.run([node(), str(REPO_ROOT / "tests" / "seal_check.mjs")], input=json.dumps(plan), text=True, encoding="utf-8",
                         capture_output=True, check=False, timeout=60)
    assert run.returncode == 0, run.stderr[-2000:]
    return json.loads(run.stdout)


@pytest.fixture(scope="module")
def sealer() -> Sealer:
    return Sealer([private_key()])


@pytest.fixture(scope="module")
def sealed(sealer) -> dict:
    return node_seal(sealer.current(), [{"note": INNER, "owner": OWNER, "idempotencyKey": KEY, "kind": KIND, "savedAt": SAVED}])


def flip(b64: str) -> str:
    raw = bytearray(base64.b64decode(b64))
    raw[len(raw) // 2] ^= 1
    return base64.b64encode(bytes(raw)).decode("ascii")


def open_with(sealer: Sealer, envelope: dict, **changes):
    args = {"owner": OWNER, "idempotency_key": KEY, "kind": KIND, "saved_at": SAVED, **changes}
    return sealer.open(envelope, **args)


# Node seals, Python opens


def test_a_note_sealed_in_node_opens_in_python(sealer, sealed):
    envelope = sealed["sealed"][0]
    assert set(envelope) == {"v", "key_id", "wrapped_key", "nonce", "ciphertext"} and envelope["v"] == 1
    assert open_with(sealer, envelope) == INNER


def test_the_envelope_shows_nothing_of_the_note(sealed):
    text = json.dumps(sealed["sealed"][0])
    assert "Placeholder" not in text and "Kim" not in text and "4821" not in base64.b64decode(sealed["sealed"][0]["ciphertext"]).decode("latin-1")


def test_two_seals_of_the_same_note_differ(sealer):
    note = {"note": INNER, "owner": OWNER, "idempotencyKey": KEY, "kind": KIND, "savedAt": SAVED}
    a, b = node_seal(sealer.current(), [note, note])["sealed"]
    assert a["nonce"] != b["nonce"] and a["wrapped_key"] != b["wrapped_key"] and a["ciphertext"] != b["ciphertext"]


def test_the_page_checks_that_the_key_id_is_the_hash_of_the_key(sealed):
    assert sealed["verified"] is True and sealed["wrong_id_verified"] is False


# Any change fails


@pytest.mark.parametrize("field", ["ciphertext", "nonce", "wrapped_key"])
def test_a_changed_byte_is_refused(sealer, sealed, field):
    envelope = sealed["sealed"][0]
    with pytest.raises(EnvelopeRefused):
        open_with(sealer, {**envelope, field: flip(envelope[field])})


@pytest.mark.parametrize("change", [{"owner": "m.chen"}, {"idempotency_key": "7f1c2a70-8b44-4f0e-9d13-3e1f6a7b9c11"}, {"kind": "update"},
                                    {"saved_at": "2026-10-07T14:32:00.000Z"}], ids=["another user", "another key", "another kind", "another time"])
def test_swapped_metadata_is_refused(sealer, sealed, change):
    with pytest.raises(EnvelopeRefused) as refused:
        open_with(sealer, sealed["sealed"][0], **change)
    assert refused.value.code == "unreadable"


def test_an_unknown_format_is_refused(sealer, sealed):
    with pytest.raises(EnvelopeRefused):
        open_with(sealer, {**sealed["sealed"][0], "v": 2})


@pytest.mark.parametrize("bad", ["not base64 !!", "", "QUJD"])
@pytest.mark.parametrize("field", ["ciphertext", "nonce", "wrapped_key"])
def test_malformed_fields_are_refused_not_a_crash(sealer, sealed, field, bad):
    with pytest.raises(EnvelopeRefused):
        open_with(sealer, {**sealed["sealed"][0], field: bad})


def test_the_refusal_says_nothing_about_which_part_failed(sealer, sealed):
    envelope = sealed["sealed"][0]
    errors = set()
    for attempt in ({**envelope, "ciphertext": flip(envelope["ciphertext"])}, {**envelope, "wrapped_key": flip(envelope["wrapped_key"])}):
        with pytest.raises(EnvelopeRefused) as refused:
            open_with(sealer, attempt)
        errors.add((refused.value.code, str(refused.value)))
    assert len(errors) == 1


# Key IDs and rotation


def test_the_key_id_is_the_hash_of_the_public_key(sealer):
    import hashlib

    current = sealer.current()
    assert hashlib.sha256(base64.b64decode(current["public_key"])).hexdigest() == current["key_id"]


def test_an_old_key_id_still_opens_after_rotation(sealer, sealed):
    rotated = Sealer([private_key(1), private_key()])
    assert rotated.current()["key_id"] != sealer.current()["key_id"]
    assert open_with(rotated, sealed["sealed"][0]) == INNER


def test_new_notes_use_the_newest_key():
    rotated = Sealer([private_key(1), private_key()])
    assert rotated.current() == Sealer([private_key(1)]).current()


def test_an_unknown_key_id_is_refused(sealed):
    other = Sealer([private_key(1)])
    with pytest.raises(EnvelopeRefused) as refused:
        open_with(other, sealed["sealed"][0])
    assert refused.value.code == "unknown_key"


def test_a_key_id_cannot_point_at_another_key(sealer, sealed):
    rotated = Sealer([private_key(1), private_key()])
    swapped = {**sealed["sealed"][0], "key_id": rotated.current()["key_id"]}
    with pytest.raises(EnvelopeRefused):
        open_with(rotated, swapped)


# Where keys come from


def test_keys_come_from_the_environment_newest_first():
    env = {SEAL_KEYS_ENV: f"{private_key(1)}, {private_key()}"}
    settings = SimpleNamespace(retention=SimpleNamespace(mode="demo"))
    loaded = Sealer.from_environment(settings, env)
    assert loaded.current() == Sealer([private_key(1)]).current() and len(loaded.key_ids()) == 2


def test_production_needs_a_key():
    settings = SimpleNamespace(retention=SimpleNamespace(mode="production"))
    with pytest.raises(SealKeyMissing):
        Sealer.from_environment(settings, {})


def test_demo_mode_makes_a_key_in_memory_only_when_first_needed():
    settings = SimpleNamespace(retention=SimpleNamespace(mode="demo"))
    loaded = Sealer.from_environment(settings, {})
    assert loaded.key_ids() == []  # nothing generated until a page asks
    first = loaded.current()
    assert loaded.current() == first and loaded.key_ids() == [first["key_id"]]


def test_a_bad_key_never_appears_in_the_error():
    secret = base64.b64encode(b"this-is-not-a-key-" * 4).decode("ascii")
    settings = SimpleNamespace(retention=SimpleNamespace(mode="demo"))
    with pytest.raises(ValueError) as bad:
        Sealer.from_environment(settings, {SEAL_KEYS_ENV: secret})
    assert secret not in str(bad.value) and SEAL_KEYS_ENV in str(bad.value) and bad.value.__cause__ is None and bad.value.__suppress_context__


def test_a_short_key_is_refused():
    small = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der = small.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    with pytest.raises(ValueError, match="3072"):
        Sealer([base64.b64encode(der).decode("ascii")])


def test_no_private_key_in_repr_public_output_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    s = Sealer([private_key()])
    s.current()
    with pytest.raises(EnvelopeRefused):
        s.open({"v": 1, "key_id": s.current()["key_id"], "wrapped_key": "QUJD", "nonce": "QUJD", "ciphertext": "QUJD"},
               owner=OWNER, idempotency_key=KEY, kind=KIND, saved_at=SAVED)
    for seen in (repr(s), str(s), json.dumps(s.current()), caplog.text):
        assert private_key() not in seen and private_key()[40:80] not in seen


def test_the_key_script_puts_the_new_key_first_and_returns_only_its_id(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_seal_key", REPO_ROOT / "scripts" / "make_seal_key.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    env = tmp_path / ".env"
    env.write_text("OTHER=kept\n", encoding="utf-8")
    first = script.add_key(env)
    second = script.add_key(env)
    lines = env.read_text(encoding="utf-8").splitlines()
    assert "OTHER=kept" in lines and first != second and len(first) == 64
    (value,) = [line.split("=", 1)[1] for line in lines if line.startswith(SEAL_KEYS_ENV)]
    assert Sealer(value.split(",")).key_ids() == [second, first]


# The contact stamp: when the server last spoke to this user


NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)


def test_a_stamp_returns_its_time(sealer):
    assert sealer.contact_time(sealer.contact_stamp(OWNER, NOW), OWNER) == NOW


@pytest.mark.parametrize("stamp", ["", "abc", "j.alvarez.1.deadbeef", "a.b.c.d.e"])
def test_a_forged_stamp_is_refused(sealer, stamp):
    assert sealer.contact_time(stamp, OWNER) is None


def test_a_stamp_belongs_to_one_user(sealer):
    assert sealer.contact_time(sealer.contact_stamp(OWNER, NOW), "m.chen") is None


def test_a_changed_time_breaks_the_stamp(sealer):
    stamp = sealer.contact_stamp(OWNER, NOW)
    later = str(int((NOW + timedelta(hours=11)).timestamp()))
    forged = stamp.replace(str(int(NOW.timestamp())), later)
    assert forged != stamp and sealer.contact_time(forged, OWNER) is None


def test_a_stamp_survives_rotation(sealer):
    stamp = sealer.contact_stamp(OWNER, NOW)
    assert Sealer([private_key(1), private_key()]).contact_time(stamp, OWNER) == NOW
