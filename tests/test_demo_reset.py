"""Demo only: the reset that clears the mock HMIS and the staging store between live runs.

It must work only against the local mock HMIS, never a real HMIS, and no email can trigger it.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config_loader import load_config
from app.demo_reset import DemoResetRefused, is_loopback, reset_demo

from .conftest import Intake
from .test_config import _edit
from .test_review_ui import WORKER, latest_review, phone, scenario, send, start  # noqa: F401  (phone is a fixture)

RESET = {"confirm": "reset demo"}


def run_scenario_a(api):
    ref = start(api, "A")["ref"]
    assert send(api, f"Re: {latest_review(api)['subject']}", "CONFIRM")["action"] == "submitted"
    return ref


def test_reset_clears_everything_and_restarts_the_ids(phone):
    first = run_scenario_a(phone)
    start(phone, "B")
    assert phone.post("/demo/reset", json=RESET).status_code == 200
    assert phone.get("/demo/drafts").json() == []
    assert phone.get(f"/mail/inbox/{WORKER}").json() == []
    assert phone.intake.store.audit_events(first) == []
    # The same note runs again cleanly: no duplicate, and the IDs start at 0001 again.
    again = run_scenario_a(phone)
    assert again == first and again.endswith("-0001")
    ids = phone.get(f"/drafts/{again}/receipt").json()["hmis_ids"]
    assert [i["value"] for i in ids] == ["HMIS-C-000001", "HMIS-E-000002", "HMIS-CE-000003"]


def test_reset_needs_the_confirmation_phrase(phone):
    run_scenario_a(phone)
    for body in ({}, {"confirm": ""}, {"confirm": "yes"}):
        assert phone.post("/demo/reset", json=body).status_code == 422
    assert phone.get("/demo/drafts").json() != []


@pytest.mark.parametrize("text", ["reset demo", "RESET", "Please reset the demo"])
def test_no_email_or_reply_can_reset(phone, text):
    ref = run_scenario_a(phone)
    send(phone, "reset demo", text)  # a new note
    send(phone, f"Re: Submitted to HMIS [{ref}]", text)  # a reply to a draft
    assert phone.intake.draft(ref).state == "submitted"
    assert any(e["event"] == "submitted" for e in phone.intake.store.audit_events(ref))


def test_reset_refuses_a_hmis_that_is_not_local_before_any_request(config_copy, hmis):
    _edit(config_copy / "settings.yaml", lambda d: d.update(hmis_base_url="https://hmis.example.org/api"))
    intake = Intake(hmis)
    intake.service.config = load_config(config_copy)
    calls = []
    admin = httpx.Client(base_url="https://hmis.example.org/api",
                         transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(204)))
    ref = intake.receive_sample("01b_clean_new_client_complete").ref
    with pytest.raises(DemoResetRefused, match="demo only"):
        reset_demo(intake.service, admin)
    assert calls == [] and intake.draft(ref) is not None

    api = TestClient(create_app(intake.service, hmis_admin=admin))
    out = api.post("/demo/reset", json=RESET)
    assert out.status_code == 409 and "not a local mock HMIS" in out.json()["detail"]
    assert calls == [] and intake.draft(ref) is not None


def test_reset_refuses_a_hmis_that_does_not_answer_as_the_mock(hmis):
    intake = Intake(hmis)
    ref = intake.receive_sample("01b_clean_new_client_complete").ref
    for answer in (httpx.Response(204), httpx.Response(200, json={}), httpx.Response(204, headers={"X-Mock-HMIS": "no"})):
        admin = httpx.Client(base_url="http://127.0.0.1:8765", transport=httpx.MockTransport(lambda r, a=answer: a))
        with pytest.raises(DemoResetRefused, match="did not answer as the mock"):
            reset_demo(intake.service, admin)
        assert intake.draft(ref) is not None  # nothing in the staging store was cleared


def test_reset_when_the_mock_is_not_running(hmis):
    intake = Intake(hmis)

    def refuse(request):
        raise httpx.ConnectError("connection refused")

    admin = httpx.Client(base_url="http://127.0.0.1:8765", transport=httpx.MockTransport(refuse))
    with pytest.raises(DemoResetRefused, match="did not answer"):
        reset_demo(intake.service, admin)


@pytest.mark.parametrize(("url", "local"), [
    ("http://127.0.0.1:8765", True), ("http://localhost:8765", True), ("http://[::1]:8765", True),
    ("https://hmis.example.org", False), ("http://10.0.0.5:8765", False), ("http://127.0.0.1.example.org", False),
])
def test_only_loopback_addresses_count_as_local(url, local):
    assert is_loopback(url) is local


def test_shipped_setting_points_at_a_local_mock():
    assert is_loopback(load_config().settings.hmis_base_url)


def test_reset_button_is_labelled_demo_only():
    from app.api import UI_DIR

    script = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "Reset demo (demo only)" in script and "never a real one" in script


def test_reset_restarts_email_numbers_too(phone):
    run_scenario_a(phone)
    phone.post("/demo/reset", json=RESET)
    start(phone, "A")
    assert [m["id"] for m in phone.get(f"/mail/inbox/{WORKER}").json()] == [2]  # 1 is the stored note
