"""The intake API over the workflow (simulated inbox, outbox, staged view)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app

from .conftest import SAMPLE_EMAIL_DIR


def test_inbox_to_staged_view_to_confirm(intake):
    api = TestClient(create_app(intake.service))
    raw = (SAMPLE_EMAIL_DIR / "01b_clean_new_client_complete.txt").read_text(encoding="utf-8")
    ref = api.post("/inbox", json={"raw": raw}).json()["ref"]

    view = api.get(f"/drafts/{ref}").json()
    assert view["state"] == "in_review" and "blocked until the worker replies CONFIRM" in view["status"]

    phone = api.get("/outbox/j.alvarez@goodwill-outreach.example").json()
    review = [e for e in phone if e["kind"] == "review"][-1]
    reply = (f"From: j.alvarez@goodwill-outreach.example\nTo: outreach-intake@goodwill-secure.example\n"
             f"Subject: Re: {review['subject']}\nDate: Wed, 07 Oct 2026 10:40:00 -0400\n\nCONFIRM\n")
    assert api.post("/inbox", json={"raw": reply}).json()["action"] == "submitted"
    assert api.get(f"/drafts/{ref}").json()["hmis_ids"]["client_id"].startswith("HMIS-C-")
    assert api.get(f"/drafts/{ref}/audit").json()["confirmed_by"] == "j.alvarez@goodwill-outreach.example"


def test_bad_email_and_unknown_draft(intake):
    api = TestClient(create_app(intake.service))
    assert api.post("/inbox", json={"raw": "no headers here"}).status_code == 422
    assert api.get("/drafts/ENC-2026-01-01-9999").status_code == 404


def test_supervisor_queue_and_expire(intake):
    api = TestClient(create_app(intake.service))
    ref = intake.receive_sample("01b_clean_new_client_complete").ref
    intake.clock.advance(hours=48)
    assert api.post("/maintenance/expire").json() == {"expired": [ref]}
    assert [q["draft_id"] for q in api.get("/supervisor-queue").json()] == [ref]
