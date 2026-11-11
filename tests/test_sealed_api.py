"""add-web-application, Stage 4c: the route that takes a sealed note, and the device's setup.

The server opens each envelope with its private keys, binds it to the signed-in user and the
Idempotency-Key, checks the times against its own clock, masks again, and only then runs the same
core action as a typed note. Specs: openspec/changes/add-web-application/specs/offline-sync/spec.md.
Plan: design.md section 5a. Synthetic data only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta

import pytest

from app.sealing import Sealer

from .conftest import Web
from .test_sealing import flip, private_key, py_seal
from .test_web_api import JORDAN, NOTE, SUPERVISOR

SEALED = "/api/v1/notes/sealed"
SETUP = "/api/v1/device/setup"
SIGN_OUT_DEVICE = "/api/v1/auth/sign-out-device"


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


@pytest.fixture
def sealed_web(intake) -> Web:
    return Web(intake, sealer=Sealer([private_key()]))


class Device:
    """A browser plus what the page knows: the setup, and how to seal and send a note."""

    def __init__(self, web: Web, username: str):
        self.web, self.username = web, username
        self.client = web.as_user(username)
        self.refresh()

    def refresh(self) -> None:
        self.setup = self.client.get(SETUP).json()

    def seal(self, text=NOTE, *, key=None, kind="new_client", written_at=None, title=None, label=None, contact=None, owner=None, extra=None):
        key = key or str(uuid.uuid4())
        at = iso(written_at or self.web.intake.clock())
        inner = {"text": text, "title": title, "written_at": at, "ssn_invalid_label": label,
                 "contact": self.setup["contact"] if contact is None else contact, **(extra or {})}
        return key, {"kind": kind, "saved_at": at, "envelope": py_seal(self.setup["seal"], owner or self.username, key, kind, at, inner)}

    def post(self, key: str, body: dict):
        return self.client.post(SEALED, json=body, headers={"Idempotency-Key": key})

    def send(self, text=NOTE, **options):
        key, body = self.seal(text, **options)
        return self.post(key, body)


@pytest.fixture
def device(sealed_web) -> Device:
    return Device(sealed_web, "j.alvarez")


def nothing_made(web: Web) -> bool:
    return web.intake.store.drafts() == [] and web.intake.store.all_pending() == []


# The setup


def test_the_setup_gives_the_public_key_rules_limits_and_a_stamp(device):
    s = device.setup
    assert set(s) == {"seal", "rules", "limits", "contact"}
    assert hashlib.sha256(base64.b64decode(s["seal"]["public_key"])).hexdigest() == s["seal"]["key_id"]
    assert set(s["seal"]) == {"key_id", "public_key"}
    assert s["limits"] == {"offline_write_hours": 12, "queue_expiry_hours": 72, "queue_warning_hours": 60}
    assert set(s["rules"]) == {"any_full_number", "possible_full_number", "invalid_full_number_patterns", "refused_message"}


def test_the_setup_never_holds_a_private_key(device):
    assert private_key() not in json.dumps(device.setup)


def test_the_limits_are_config_values():
    from app.config_loader import load_config

    web = load_config().settings.web
    assert (web.offline_write_hours, web.device_queue_hours, web.device_queue_warning_hours) == (12, 72, 60)


def test_the_idempotency_window_outlasts_the_queue():
    from app.config_loader import load_config

    web = load_config().settings.web
    assert web.idempotency_key_hours > web.device_queue_hours


# A sealed note becomes a draft, like a typed one


def test_a_sealed_note_is_drafted_for_the_signed_in_worker(device):
    r = device.send(title="Kim, NW quadrant")
    assert r.status_code == 200 and r.json()["action"] == "drafted"
    d = device.web.intake.draft(r.json()["ref"])
    assert d.author == "j.alvarez@goodwill-outreach.example" and d.subject == "Kim, NW quadrant" and d.state == "in_review"


def test_a_visit_note_goes_through_the_update_action(device):
    r = device.send(JORDAN, kind="update")
    assert r.json()["action"] == "drafted" and device.web.intake.draft(r.json()["ref"]).client_id == "HMIS-C-000101"


def test_nothing_reaches_hmis_when_a_sealed_note_arrives(device):
    device.send()
    assert device.web.intake.hmis.app.state.store.counts()["clients"] == 0


def test_the_note_keeps_the_time_it_was_written(device):
    written = device.web.intake.clock() - timedelta(hours=0)
    device.web.intake.clock.advance(hours=5)
    r = Device(device.web, "j.alvarez").send(written_at=written, contact=device.setup["contact"])
    d = device.web.intake.draft(r.json()["ref"])
    assert d.email_sent_at.astimezone(written.tzinfo) == written


def test_a_title_defaults_when_none_was_given(device):
    assert device.web.intake.draft(device.send().json()["ref"]).subject == "New client"


# The Idempotency-Key is required and binds the note


def test_the_key_is_required(device):
    _, body = device.seal()
    assert device.client.post(SEALED, json=body).status_code == 400 and nothing_made(device.web)


def test_a_malformed_key_is_refused(device):
    _, body = device.seal(key="short")
    assert device.post("short", body).status_code == 400 and nothing_made(device.web)


def test_the_same_upload_twice_makes_one_draft(device):
    key, body = device.seal()
    first, second = device.post(key, body), device.post(key, body)
    assert first.json()["ref"] == second.json()["ref"] and len(device.web.intake.store.drafts()) == 1


def test_a_late_retry_after_the_queue_limit_is_still_recognized(device):
    key, body = device.seal()
    first = device.post(key, body)
    device.web.intake.clock.advance(hours=73)
    again = Device(device.web, "j.alvarez").post(key, body)
    assert again.status_code == 200 and again.json()["ref"] == first.json()["ref"] and len(device.web.intake.store.drafts()) <= 1


def test_the_same_key_with_another_note_is_a_conflict(device):
    key, body = device.seal()
    device.post(key, body)
    _, other = device.seal(NOTE.replace("Kim", "Kit"), key=key)
    assert device.post(key, other).status_code == 409 and len(device.web.intake.store.drafts()) == 1


# Swapped envelopes are refused


def test_another_users_envelope_is_refused(sealed_web):
    alvarez, chen = Device(sealed_web, "j.alvarez"), Device(sealed_web, "m.chen")
    key, body = alvarez.seal()
    r = chen.post(key, body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "sealed_unreadable" and nothing_made(sealed_web)
    assert [e["actor"] for e in sealed_web.intake.store.audit_events("web") if e["event"] == "sealed_note_refused"] == ["m.chen"]


def test_a_refused_envelope_does_not_use_up_the_key(sealed_web):
    alvarez, chen = Device(sealed_web, "j.alvarez"), Device(sealed_web, "m.chen")
    key, body = alvarez.seal()
    chen.post(key, body)
    assert alvarez.post(key, body).json()["action"] == "drafted"


def test_an_envelope_under_another_key_is_refused(device):
    _, body = device.seal()
    r = device.post(str(uuid.uuid4()), body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "sealed_unreadable" and nothing_made(device.web)


@pytest.mark.parametrize("change", [{"kind": "update"}, {"saved_at": "2026-10-07T14:59:00Z"}], ids=["kind", "time"])
def test_changed_clear_metadata_is_refused(device, change):
    key, body = device.seal()
    assert device.post(key, {**body, **change}).status_code == 422 and nothing_made(device.web)


@pytest.mark.parametrize("field", ["ciphertext", "nonce", "wrapped_key"])
def test_a_changed_byte_is_refused(device, field):
    key, body = device.seal()
    env = {**body["envelope"], field: flip(body["envelope"][field])}
    assert device.post(key, {**body, "envelope": env}).status_code == 422 and nothing_made(device.web)


def test_an_unknown_key_id_is_refused(sealed_web):
    alvarez = Device(sealed_web, "j.alvarez")
    other = Web(sealed_web.intake, sealer=Sealer([private_key(1)]))
    key, body = alvarez.seal()
    c = other.as_user("j.alvarez")
    r = c.post(SEALED, json=body, headers={"Idempotency-Key": key})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "sealed_unknown_key" and nothing_made(sealed_web)


def test_an_old_key_id_still_opens_after_the_server_rotates(intake):
    old = Web(intake, sealer=Sealer([private_key()]))
    device = Device(old, "j.alvarez")
    key, body = device.seal()
    rotated = Web(intake, sealer=Sealer([private_key(1), private_key()]))
    c = rotated.as_user("j.alvarez")
    r = c.post(SEALED, json=body, headers={"Idempotency-Key": key})
    assert r.status_code == 200 and r.json()["action"] == "drafted"
    assert c.get(SETUP).json()["seal"]["key_id"] != device.setup["seal"]["key_id"]


def test_unknown_inner_fields_are_refused(device):
    r = device.send(extra={"author": "m.chen@goodwill-outreach.example"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "sealed_unreadable" and nothing_made(device.web)


def test_extra_body_fields_are_refused(device):
    key, body = device.seal()
    assert device.post(key, {**body, "author": "m.chen"}).status_code == 422 and nothing_made(device.web)


# Times, checked against the server's clock


def test_a_note_written_within_the_offline_limit_is_accepted(device):
    limit = device.web.intake.config.settings.web.offline_write_hours
    written = device.web.intake.clock() + timedelta(hours=limit)
    device.web.intake.clock.advance(hours=limit)
    d = Device(device.web, "j.alvarez")
    assert d.send(written_at=written, contact=device.setup["contact"]).status_code == 200


def test_a_note_written_past_the_offline_limit_is_refused(device):
    limit = device.web.intake.config.settings.web.offline_write_hours
    written = device.web.intake.clock() + timedelta(hours=limit, minutes=1)
    device.web.intake.clock.advance(hours=limit, minutes=2)
    d = Device(device.web, "j.alvarez")
    r = d.send(written_at=written, contact=device.setup["contact"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "sealed_offline_limit" and nothing_made(device.web)
    assert "12 hours" in r.json()["detail"]["message"]


def test_the_offline_limit_comes_from_config(intake):
    web_settings = intake.config.settings.web.model_copy(update={"offline_write_hours": 2})
    settings = intake.config.settings.model_copy(update={"web": web_settings})
    intake.service.config = intake.config.model_copy(update={"settings": settings})
    web = Web(intake, sealer=Sealer([private_key()]))
    device = Device(web, "j.alvarez")
    contact = device.setup["contact"]
    written = intake.clock() + timedelta(hours=2, minutes=1)
    intake.clock.advance(hours=3)
    d = Device(web, "j.alvarez")
    r = d.send(written_at=written, contact=contact)
    assert r.status_code == 422 and "2 hours" in r.json()["detail"]["message"]


def test_a_forged_contact_stamp_is_refused(device):
    r = device.send(contact="j.alvarez.1791000000.deadbeef")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "sealed_offline_limit" and nothing_made(device.web)


def test_another_users_contact_stamp_is_refused(sealed_web):
    alvarez, chen = Device(sealed_web, "j.alvarez"), Device(sealed_web, "m.chen")
    assert alvarez.send(contact=chen.setup["contact"]).status_code == 422 and nothing_made(sealed_web)


def test_a_note_from_the_future_is_refused(device):
    r = device.send(written_at=device.web.intake.clock() + timedelta(minutes=6))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "sealed_bad_time" and nothing_made(device.web)


def test_small_clock_differences_are_allowed(device):
    assert device.send(written_at=device.web.intake.clock() + timedelta(minutes=4)).status_code == 200


def test_a_note_older_than_the_queue_limit_is_refused(device):
    written = device.web.intake.clock()
    contact = device.setup["contact"]
    device.web.intake.clock.advance(hours=73)
    r = Device(device.web, "j.alvarez").send(written_at=written, contact=contact)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "sealed_expired" and nothing_made(device.web)


def test_a_note_written_before_its_stamp_is_refused(device):
    written = device.web.intake.clock() - timedelta(minutes=30)
    r = device.send(written_at=written)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "sealed_bad_time" and nothing_made(device.web)


def test_a_time_without_a_zone_is_refused(device):
    key = str(uuid.uuid4())
    at = "2026-10-07T15:00:00"
    inner = {"text": NOTE, "title": None, "written_at": at, "ssn_invalid_label": None, "contact": device.setup["contact"]}
    body = {"kind": "new_client", "saved_at": at, "envelope": py_seal(device.setup["seal"], "j.alvarez", key, "new_client", at, inner)}
    assert device.post(key, body).status_code == 422 and nothing_made(device.web)


# SSNs: the server masks again


def test_the_server_masks_a_full_number_again(device):
    r = device.send(NOTE.replace("SSN ends 4821", "SSN 234-56-4821"))
    assert r.status_code == 200 and r.json()["ssn"]["masked"] == 1
    assert "234-56" not in json.dumps(device.web.intake.draft(r.json()["ref"]).model_dump(mode="json"))


def test_the_server_refuses_another_form_of_a_full_number(device):
    r = device.send("Her social is 234 56 7891.")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ssn_possible_full_number" and nothing_made(device.web)


def test_a_refused_note_does_not_use_up_the_key(device):
    key, body = device.seal("Her social is 234 56 7891.")
    device.post(key, body)
    assert device.post(key, body).status_code == 422  # a refusal, never a replay


def test_a_title_cannot_hold_a_full_number(device):
    r = device.send(title="Kim 234-56-7891")
    assert device.web.intake.draft(r.json()["ref"]).subject == "Kim ***-**-7891"


def test_a_title_in_another_form_is_refused(device):
    r = device.send(title="social 234 56 7891")
    assert r.status_code == 422 and nothing_made(device.web)


def test_the_typed_route_guards_a_title_too(web):
    web.sign_in("j.alvarez")
    r = web.client.post("/api/v1/notes/new-client", json={"text": NOTE, "title": "Kim 234-56-7891"})
    assert web.intake.draft(r.json()["ref"]).subject == "Kim ***-**-7891"
    assert web.client.post("/api/v1/notes/new-client", json={"text": NOTE, "title": "social 234 56 7891"}).status_code == 422


def test_a_known_invalid_label_travels_with_the_note(device):
    label = device.setup["rules"]["invalid_full_number_patterns"][0]["label"]
    r = device.send(NOTE.replace("SSN ends 4821", "SSN ***-**-6789"), label=label)
    flags = json.dumps(device.web.intake.draft(r.json()["ref"]).model_dump(mode="json"))
    assert label in flags


def test_an_unknown_label_is_dropped(device):
    r = device.send(NOTE.replace("SSN ends 4821", "SSN ***-**-6789"), label="ZZFREETEXT in a label")
    assert "ZZFREETEXT" not in json.dumps(device.web.intake.draft(r.json()["ref"]).model_dump(mode="json"))


# What is kept and logged


def test_no_note_text_in_the_audit_or_logs_on_a_refusal(sealed_web, caplog):
    caplog.set_level(logging.DEBUG)
    alvarez, chen = Device(sealed_web, "j.alvarez"), Device(sealed_web, "m.chen")
    key, body = alvarez.seal("ZZSENTINEL note text")
    chen.post(key, body)
    assert "ZZSENTINEL" not in caplog.text and key not in caplog.text
    assert "ZZSENTINEL" not in json.dumps(sealed_web.intake.store.audit_events("web")) and key not in json.dumps(sealed_web.intake.store.audit_events("web"))


def test_every_upload_answer_is_no_store(device):
    assert device.send().headers["cache-control"] == "no-store"
    assert device.send("Her social is 234 56 7891.").headers["cache-control"] == "no-store"


def test_the_setup_is_no_store(device):
    assert device.client.get(SETUP).headers["cache-control"] == "no-store"


# Finishing a sign-out made while offline


ORIGIN = {"Origin": "http://testserver"}


def test_the_pending_sign_out_ends_the_session_in_one_request(sealed_web):
    c = sealed_web.as_user("j.alvarez")
    del c.headers["X-CSRF-Token"]
    r = c.post(SIGN_OUT_DEVICE, headers=ORIGIN)
    assert r.status_code == 200 and r.json() == {"signed_out": True} and r.headers["cache-control"] == "no-store"
    assert c.get("/api/v1/session").status_code == 401
    assert [e["event"] for e in sealed_web.intake.store.audit_events("AUTH")].count("sign_out") == 1


def test_the_pending_sign_out_needs_no_live_session(sealed_web):
    r = sealed_web.new_client().post(SIGN_OUT_DEVICE, headers=ORIGIN)
    assert r.status_code == 200 and r.json() == {"signed_out": True}


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://attacker.example"}, {"Origin": "null"}], ids=["no origin", "another site", "null origin"])
def test_the_pending_sign_out_refuses_other_origins(sealed_web, headers):
    c = sealed_web.as_user("j.alvarez")
    assert c.post(SIGN_OUT_DEVICE, headers=headers).status_code == 403
    assert c.get("/api/v1/session").status_code == 200


def test_the_pending_sign_out_clears_the_cookie(sealed_web):
    c = sealed_web.as_user("j.alvarez")
    r = c.post(SIGN_OUT_DEVICE, headers=ORIGIN)
    assert "hmis_session=" in r.headers.get("set-cookie", "") and 'Max-Age=0' in r.headers.get("set-cookie", "")


def test_a_supervisor_gets_no_device_setup(sealed_web):
    assert sealed_web.as_user(SUPERVISOR).get(SETUP).status_code == 403
