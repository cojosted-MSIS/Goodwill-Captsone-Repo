"""add-web-application, Stage 2b follow-ups: the staff role, and no emails for web drafts.

Specs: openspec/changes/add-web-application/specs/web-application/spec.md ("Sign in with a role",
"Staff audit views without neighbor information", "Keep email as an optional channel, off by
default"). The email channel is on in these tests (tests/conftest.py, Intake), so they show that
a draft made in the web app gets no review or verification email even then. Synthetic data only.
"""

from __future__ import annotations

import json

from .test_web_api import JORDAN, NOTE, ROBIN, STAFF

LONG_REASON = "He is about twenty years younger than the person in HMIS and has a different tattoo"


def sent(web, ref: str, kind: str) -> list:
    return [e for e in web.intake.store.emails(ref=ref, kind=kind) if e.direction == "out"]


# Drafts made in the web app get no emails, even with the email channel on


def test_a_web_draft_gets_no_review_email_even_with_email_on(web):
    assert web.intake.config.settings.channels.email.enabled is True
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    assert web.intake.draft(ref).channel == "web"
    fixed = alvarez.post(f"/api/v1/drafts/{ref}/corrections", json={"text": "It was the second time on the street, not the third."})
    assert fixed.json()["action"] == "revised"
    assert sent(web, ref, "review") == []
    update = alvarez.post("/api/v1/notes/update", json={"text": JORDAN}).json()["ref"]
    assert sent(web, update, "review") == []


def test_a_web_draft_gets_no_verification_email(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": ROBIN}).json()["ref"]
    assert web.intake.draft(ref).verification.open
    assert alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).json()["action"] == "verification"
    alvarez.post(f"/api/v1/drafts/{ref}/different-person", json={"reason": LONG_REASON})
    assert sent(web, ref, "verification") == [] and sent(web, ref, "review") == []


def test_a_held_web_note_stays_a_web_draft(web):
    alvarez = web.as_user("j.alvarez")
    held = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE.replace("Searched HMIS first, no match. ", "")}).json()
    ref = alvarez.post(f"/api/v1/held/{held['ref']}/searched", json={}).json()["ref"]
    assert web.intake.draft(ref).channel == "web" and sent(web, ref, "review") == []


def test_an_email_draft_still_gets_its_emails(web):
    ref = web.intake.receive_text(NOTE).ref
    assert web.intake.draft(ref).channel == "email"
    assert len(sent(web, ref, "review")) == 1
    robin = web.intake.receive_text(ROBIN).ref
    assert len(sent(web, robin, "verification")) == 1


# The staff role: read-only, signed in, and no note text or draft contents


def test_staff_sees_the_audit_without_neighbor_information(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": ROBIN, "title": "New client: Robin"}).json()["ref"]
    alvarez.post(f"/api/v1/drafts/{ref}/different-person", json={"reason": LONG_REASON})
    alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1})
    alvarez.post("/api/v1/queries/lookup", json={"first_name": "Pat", "last_name": "Example", "date_of_birth": "1975-03-04"})

    staff = web.as_user(STAFF)
    listed = staff.get("/api/v1/staff/drafts").json()
    assert [d["id"] for d in listed] == [ref] and listed[0]["state"] == "submitted"
    audit = staff.get(f"/api/v1/staff/drafts/{ref}/audit").json()
    assert audit["draft_id"] == ref and audit["verification"]["decision"] == "different_person"
    assert "verification_decided" in [e["event"] for e in audit["events"]]
    queries = staff.get("/api/v1/staff/queries").json()
    assert [q["query_type"] for q in queries] == ["lookup"]

    shown = json.dumps([listed, audit, queries])
    for private in ("Robin", "Demo", "1975", "5555", "twenty years younger", "Pat", "Example", "hygiene kit"):
        assert private not in shown, private


def test_staff_cannot_change_anything(web):
    staff = web.as_user(STAFF)
    assert staff.post("/api/v1/notes/new-client", json={"text": NOTE}).status_code == 403
    assert staff.get("/api/v1/drafts").status_code == 403  # a worker's draft contents
    assert staff.get("/api/v1/supervisor/queue").status_code == 403
    assert web.intake.store.drafts() == []


def test_staff_audit_of_an_unknown_draft_is_not_found(web):
    staff = web.as_user(STAFF)
    assert staff.get("/api/v1/staff/drafts/ENC-2026-01-01-9999/audit").status_code == 404


def test_staff_session_reports_the_role(web):
    me = web.as_user(STAFF).get("/api/v1/session").json()
    assert me["role"] == "staff" and me["project"] is None
