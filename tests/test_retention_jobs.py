"""add-web-application: the retention jobs run in the web app, with the email channel on or off.

Specs: openspec/changes/add-web-application/specs/web-application/spec.md ("Run the retention jobs
without the email channel") and specs/review-and-submit/spec.md. A fake clock moves time on. The
audit of a deletion records its type and count only, never content. Synthetic data only.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.api import create_app, run_housekeeping_every
from app.config_loader import with_email_channel

from .conftest import Web
from .test_web_api import NOTE

WORKER = "j.alvarez"
HELD_NOTE = NOTE.replace("Searched HMIS first, no match. ", "")
TITLE = "Kim, NW quadrant"


def keep_copies_for(intake, hours: int) -> None:
    """Keep stored copies for a while after submission (the shipped setting deletes them at once)."""
    settings = intake.service.config.settings.model_copy(update={"email_retention_hours": hours})
    intake.service.config = intake.service.config.model_copy(update={"settings": settings})


@pytest.fixture(params=[False, True], ids=["email_off", "email_on"])
def site(request, intake) -> Web:
    intake.service.config = with_email_channel(intake.config, request.param)
    return Web(intake)


def days(site) -> int:
    return site.intake.config.settings.retention.unsubmitted_days


def deletion_events(site, ref: str, event: str) -> list[dict]:
    return [{k: v for k, v in e.items() if k != "at"} for e in site.intake.store.audit_events(ref) if e["event"] == event]


def visit(site) -> None:
    """Any signed-in request, after the clock has moved on."""
    assert site.as_user(WORKER).get("/api/v1/session").status_code == 200


# Stored copies after their retention time


def test_stored_copies_are_deleted_after_their_retention_time(site):
    keep_copies_for(site.intake, 24)
    worker = site.as_user(WORKER)
    ref = worker.post("/api/v1/notes/new-client", json={"text": NOTE, "title": TITLE}).json()["ref"]
    worker.post(f"/api/v1/drafts/{ref}/corrections", json={"text": "It was the second time on the street, not the third."})
    assert worker.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 2}).json()["action"] == "submitted"
    assert site.intake.store.emails(ref=ref, kind="intake")  # still within the retention time

    site.intake.clock.advance(hours=23)
    visit(site)
    assert site.intake.store.emails(ref=ref, kind="intake") and deletion_events(site, ref, "copies_deleted") == []

    site.intake.clock.advance(hours=1)
    visit(site)
    assert site.intake.store.emails(ref=ref, kind="intake") == [] and site.intake.store.emails(ref=ref, kind="correction") == []
    events = deletion_events(site, ref, "copies_deleted")
    assert len(events) == 1 and events[0]["deletion_type"] == "stored_copies" and events[0]["count"] >= 2
    assert set(events[0]) == {"event", "actor", "deletion_type", "count"} and events[0]["actor"] is None


# The seven-day deletion


def test_an_unsubmitted_draft_is_deleted_after_seven_days(site):
    ref = site.as_user(WORKER).post("/api/v1/notes/new-client", json={"text": NOTE, "title": TITLE}).json()["ref"]
    site.intake.clock.advance(days=days(site), seconds=-1)
    visit(site)
    assert site.intake.draft(ref) is not None and site.intake.draft(ref).state == "expired"  # the 48-hour rule, not yet deleted
    site.intake.clock.advance(seconds=1)
    visit(site)
    assert site.intake.draft(ref) is None and site.intake.store.emails(ref=ref) == []
    assert deletion_events(site, ref, "deleted_after_retention")[0]["deletion_type"] == "unsubmitted_draft"


def test_a_held_note_is_deleted_after_seven_days(site):
    ref = site.as_user(WORKER).post("/api/v1/notes/new-client", json={"text": HELD_NOTE, "title": TITLE}).json()["ref"]
    site.intake.clock.advance(days=days(site))
    visit(site)
    assert site.intake.store.get_pending(ref) is None and site.intake.store.emails(ref=ref) == []
    events = deletion_events(site, ref, "deleted_after_retention")
    assert events == [{"event": "deleted_after_retention", "actor": None, "deletion_type": "held_note", "count": events[0]["count"]}]
    assert events[0]["count"] >= 1


def test_a_submitted_draft_is_kept(site):
    worker = site.as_user(WORKER)
    ref = worker.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    worker.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1})
    site.intake.clock.advance(days=days(site) + 1)
    visit(site)
    assert site.intake.draft(ref).state == "submitted"


def test_the_audit_of_a_deletion_holds_no_content(site):
    keep_copies_for(site.intake, 24)
    worker = site.as_user(WORKER)
    entered = worker.post("/api/v1/notes/new-client", json={"text": NOTE, "title": TITLE}).json()["ref"]
    worker.post(f"/api/v1/drafts/{entered}/confirm", json={"version": 1})
    worker.post("/api/v1/notes/new-client", json={"text": NOTE.replace("Kim", "Kit"), "title": "Kit, NW quadrant"})
    worker.post("/api/v1/notes/new-client", json={"text": HELD_NOTE.replace("Kim", "Kai"), "title": "Kai, NW quadrant"})
    site.intake.clock.advance(days=days(site))
    visit(site)
    rows = site.intake.store._db.execute("SELECT event, actor, details FROM audit WHERE event IN "
                                         "('copies_deleted', 'deleted_after_retention')").fetchall()
    assert len(rows) == 3
    for _, actor, details in rows:
        assert actor is None and set(json.loads(details)) == {"deletion_type", "count"}
    text = json.dumps(rows)
    assert not [w for w in ("Kim", "Kit", "Kai", "Placeholder", "NW quadrant", "in_review", "expired") if w in text]


def test_each_deletion_is_audited_once(site):
    ref = site.as_user(WORKER).post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    site.intake.clock.advance(days=days(site))
    visit(site)
    visit(site)
    assert len(deletion_events(site, ref, "deleted_after_retention")) == 1


# Without anyone signed in


def test_the_jobs_run_on_a_timer_with_nobody_signed_in(site):
    ref = site.as_user(WORKER).post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    site.intake.clock.advance(days=days(site))
    stop = run_housekeeping_every(site.intake.service, 0.01)
    try:
        for _ in range(300):
            if site.intake.draft(ref) is None:
                break
            time.sleep(0.01)
    finally:
        stop.set()
    assert site.intake.draft(ref) is None


def test_the_timer_survives_a_failed_run(intake, monkeypatch):
    calls = []

    def broken():
        calls.append(1)
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(intake.service, "housekeeping", broken)
    stop = run_housekeeping_every(intake.service, 0.01)
    try:
        for _ in range(300):
            if len(calls) >= 2:
                break
            time.sleep(0.01)
    finally:
        stop.set()
    assert len(calls) >= 2


# The email channel, and its maintenance routes


def test_an_emailed_note_is_deleted_by_the_same_job(intake):
    site = Web(intake)  # the fixture has the email channel on
    ref = intake.receive_text(NOTE).ref
    intake.clock.advance(days=intake.config.settings.retention.unsubmitted_days)
    visit(site)
    assert intake.draft(ref) is None
    assert deletion_events(site, ref, "deleted_after_retention")[0]["deletion_type"] == "unsubmitted_draft"


def test_the_email_demo_routes_record_the_same_audit(intake):
    api = TestClient(create_app(intake.service))
    ref = intake.receive_text(NOTE).ref
    held = intake.receive_text(HELD_NOTE).ref
    intake.clock.advance(days=intake.config.settings.retention.unsubmitted_days)
    assert sorted(api.post("/maintenance/delete-unsubmitted").json()["deleted"]) == sorted([ref, held])
    for r, kind in ((ref, "unsubmitted_draft"), (held, "held_note")):
        event = [e for e in intake.store.audit_events(r) if e["event"] == "deleted_after_retention"][0]
        assert event["deletion_type"] == kind and event["count"] >= 1 and "state" not in event
