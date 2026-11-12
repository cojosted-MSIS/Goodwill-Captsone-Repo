"""add-web-application, Stage 2b: the /api/v1 routes over the intake core, with roles on the server.

Specs: openspec/changes/add-web-application/specs/web-application/spec.md ("Sign in with a role",
"Protect sessions", "Use the same core for every use case", "Web API over the core", "Label
entered drafts"). Every route is checked with no session, with the wrong role, and (when it
changes anything) without a valid CSRF token. Synthetic data only.
"""

from __future__ import annotations

import pytest

from .conftest import Web

NOTE = ("Met Kim Placeholder, DOB 1/2/1990, NW quadrant around 10:15am. Searched HMIS first, no match. Slept outside "
        "last night. Has been staying outside for over a year. Been on the street about 3 times in the last 3 years, "
        "around 14 months total. Started being homeless this time on 8/15/2025. Male, white, not Hispanic. Has a "
        "disabling condition (bad back). Not a veteran. SSN ends 4821. Enroll in street outreach, CE region 7. "
        "Single adult. Gave water and a hygiene kit. Follow up Thursday.")
ROBIN = NOTE.replace("Kim Placeholder", "Robin Demo").replace("1/2/1990", "9/9/1975").replace("4821", "5555")
JORDAN = ("Saw Jordan Sample (HMIS-C-000101) in the SW quadrant. Gave her a bus pass and water. "
          "Spent 20 minutes with her. Still staying outside.")
REF = "ENC-2026-10-07-0001"

# Every /api/v1 route: method, path, the role it needs (None: any signed-in user), and a valid body.
SEALED_BODY = {"kind": "new_client", "saved_at": "2026-10-07T15:00:00Z", "envelope": {"v": 1, "key_id": "0" * 64, "wrapped_key": "QUJD", "nonce": "QUJD", "ciphertext": "QUJD"}}
WORKER_ROUTES = [
    ("POST", "/api/v1/notes/sealed", SEALED_BODY),
    ("GET", "/api/v1/device/setup", None),
    ("GET", "/api/v1/drafts", None),
    ("GET", f"/api/v1/drafts/{REF}", None),
    ("GET", "/api/v1/messages", None),
    ("GET", "/api/v1/held", None),
    ("GET", "/api/v1/held/INT-0001", None),
    ("POST", "/api/v1/notes/new-client", {"text": NOTE}),
    ("POST", "/api/v1/notes/update", {"text": JORDAN}),
    ("GET", "/api/v1/queries/options", None),
    ("POST", "/api/v1/queries/briefing", {"quadrant": "SW"}),
    ("POST", "/api/v1/queries/lookup", {"client_id": "HMIS-C-000101"}),
    ("POST", "/api/v1/queries/status", {"status_type": "id_document", "client_id": "HMIS-C-000101"}),
    ("POST", "/api/v1/queries/no-contact", {}),
    ("POST", "/api/v1/held/INT-0001/searched", {}),
    ("POST", "/api/v1/held/UPD-0001/client", {"client_id": "HMIS-C-000109"}),
    ("POST", f"/api/v1/drafts/{REF}/confirm", {"version": 1}),
    ("POST", f"/api/v1/drafts/{REF}/retry", {}),
    ("POST", f"/api/v1/drafts/{REF}/corrections", {"text": "Veteran: didn't ask"}),
    ("POST", f"/api/v1/drafts/{REF}/same-client", {"client_id": "HMIS-C-000113"}),
    ("POST", f"/api/v1/drafts/{REF}/different-person", {"reason": "he is 20 years younger than the person in HMIS"}),
]
SUPERVISOR_ROUTES = [
    ("GET", "/api/v1/supervisor/queue", None),
    ("GET", "/api/v1/supervisor/flags", None),
    ("GET", "/api/v1/supervisor/drafts", None),
    ("GET", f"/api/v1/supervisor/drafts/{REF}", None),
]
STAFF_ROUTES = [
    ("GET", "/api/v1/staff/queries", None),
    ("GET", "/api/v1/staff/drafts", None),
    ("GET", f"/api/v1/staff/drafts/{REF}/audit", None),
]
ANY_ROLE_ROUTES = [("GET", "/api/v1/session", None), ("POST", "/api/v1/auth/sign-out", {})]
OPEN_ROUTES = {"/api/v1/auth/csrf", "/api/v1/auth/sign-in", "/api/v1/auth/sign-out-device", "/api/v1/ping"}
ALL = WORKER_ROUTES + SUPERVISOR_ROUTES + STAFF_ROUTES + ANY_ROLE_ROUTES
SUPERVISOR = "outreach.supervisor"
STAFF = "outreach.staff"
USER_OF_ROLE = {"worker": "j.alvarez", "supervisor": SUPERVISOR, "staff": STAFF}


def call(client, method: str, path: str, body):
    return client.request(method, path, json=body) if body is not None else client.request(method, path)


def test_the_route_table_covers_every_api_route(web):
    paths = {p for p in web.app.openapi()["paths"] if p.startswith("/api/v1")}
    listed = {p.replace(REF, "{ref}").replace("INT-0001", "{ref}").replace("UPD-0001", "{ref}") for _, p, _ in ALL}
    assert paths == listed | OPEN_ROUTES


# Server-side roles: no session, the wrong role, and no CSRF token


@pytest.mark.parametrize(("method", "path", "body"), ALL)
def test_every_route_needs_a_session(web, method, path, body):
    assert call(web.client, method, path, body).status_code == 401


@pytest.mark.parametrize("role", ["supervisor", "staff"])
@pytest.mark.parametrize(("method", "path", "body"), WORKER_ROUTES)
def test_every_worker_route_refuses_the_other_roles(web, method, path, body, role):
    web.sign_in(USER_OF_ROLE[role])
    assert call(web.client, method, path, body).status_code == 403
    assert web.intake.store.drafts() == [] and web.intake.store.all_pending() == []


@pytest.mark.parametrize("role", ["worker", "staff"])
@pytest.mark.parametrize(("method", "path", "body"), SUPERVISOR_ROUTES)
def test_supervisor_routes_refuse_the_other_roles(web, method, path, body, role):
    web.sign_in(USER_OF_ROLE[role])
    assert call(web.client, method, path, body).status_code == 403


@pytest.mark.parametrize("role", ["worker", "supervisor"])
@pytest.mark.parametrize(("method", "path", "body"), STAFF_ROUTES)
def test_staff_routes_refuse_the_other_roles(web, method, path, body, role):
    web.sign_in(USER_OF_ROLE[role])
    assert call(web.client, method, path, body).status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), [r for r in ALL if r[0] == "POST"])
@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_every_state_changing_route_needs_the_csrf_token(web, method, path, body, token):
    web.sign_in(SUPERVISOR if path in [p for _, p, _ in SUPERVISOR_ROUTES] else "j.alvarez")
    del web.client.headers["X-CSRF-Token"]
    headers = {"X-CSRF-Token": token} if token else {}
    r = web.client.request(method, path, json=body, headers=headers)
    assert r.status_code == 403
    assert web.intake.store.drafts() == [] and web.intake.store.all_pending() == []
    assert not [e for e in web.intake.store.audit_events_for_prefix("QRY-")]


def test_a_csrf_token_from_another_session_is_refused(web):
    other = web.as_user("m.chen")
    web.sign_in("j.alvarez")
    r = web.client.post("/api/v1/notes/new-client", json={"text": NOTE},
                        headers={"X-CSRF-Token": other.headers["X-CSRF-Token"]})
    assert r.status_code == 403 and web.intake.store.drafts() == []


# Each IntakeCore action through the API


def test_new_client_note_to_confirm_and_entry(web):
    web.sign_in("j.alvarez")
    out = web.client.post("/api/v1/notes/new-client", json={"text": NOTE, "title": "New client: Kim"}).json()
    assert out["action"] == "drafted"
    ref = out["ref"]
    draft = web.client.get(f"/api/v1/drafts/{ref}").json()
    assert draft["state"] == "in_review" and draft["status_label"] == "In review"
    assert draft["review"]["version"] == 1 and draft["receipt"] is None
    assert web.intake.hmis.app.state.store.counts()["clients"] == 0  # nothing written before the confirm
    assert web.client.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).json()["action"] == "submitted"
    done = web.client.get(f"/api/v1/drafts/{ref}").json()
    assert done["status_label"] == "Entered in HMIS" and done["receipt"]["hmis_ids"]
    listed = web.client.get("/api/v1/drafts").json()
    assert [(d["id"], d["status_label"]) for d in listed] == [(ref, "Entered in HMIS")]
    assert web.intake.hmis.app.state.store.counts()["clients"] == 1


def test_confirm_of_an_old_version_writes_nothing(web):
    web.sign_in("j.alvarez")
    ref = web.client.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    fixed = web.client.post(f"/api/v1/drafts/{ref}/corrections", json={"text": "It was the second time on the street, not the third."})
    assert fixed.json()["action"] == "revised"
    assert web.client.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).json()["action"] == "old_version"
    assert web.intake.hmis.app.state.store.counts()["clients"] == 0
    assert web.client.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 2}).json()["action"] == "submitted"


def test_held_note_becomes_a_draft_once_the_worker_says_they_searched(web):
    web.sign_in("j.alvarez")
    out = web.client.post("/api/v1/notes/new-client", json={"text": NOTE.replace("Searched HMIS first, no match. ", "")}).json()
    assert out["action"] == "search_requested" and out["ref"].startswith("INT-")
    assert any(m["kind"] == "search_request" for m in out["messages"])
    done = web.client.post(f"/api/v1/held/{out['ref']}/searched", json={}).json()
    assert done["action"] == "drafted" and done["ref"].startswith("ENC-")


def test_update_note_with_a_client_id_and_with_candidates(web):
    web.sign_in("j.alvarez")
    out = web.client.post("/api/v1/notes/update", json={"text": JORDAN}).json()
    assert out["action"] == "drafted" and web.intake.draft(out["ref"]).client_id == "HMIS-C-000101"
    held = web.client.post("/api/v1/notes/update", json={"text": "Talked with Sam Example, DOB 2/14/1980, SE quadrant. Gave water."}).json()
    assert held["action"] == "pick_client"
    picked = web.client.post(f"/api/v1/held/{held['ref']}/client", json={"client_id": "HMIS-C-000109"}).json()
    assert picked["action"] == "drafted" and web.intake.draft(picked["ref"]).client_id == "HMIS-C-000109"


def test_same_name_verification_same_client_and_different_person(web):
    web.sign_in("j.alvarez")
    first = web.client.post("/api/v1/notes/new-client", json={"text": ROBIN}).json()
    view = web.client.get(f"/api/v1/drafts/{first['ref']}").json()
    assert view["verification"] is not None and view["review"] is None
    assert web.client.post(f"/api/v1/drafts/{first['ref']}/confirm", json={"version": 1}).json()["action"] == "verification"
    same = web.client.post(f"/api/v1/drafts/{first['ref']}/same-client", json={"client_id": "HMIS-C-000113"}).json()
    assert same["action"] == "verified_same"

    second = web.client.post("/api/v1/notes/new-client", json={"text": ROBIN}).json()
    other = web.client.post(f"/api/v1/drafts/{second['ref']}/different-person",
                            json={"reason": "He is about twenty years younger than the person in HMIS and has a different tattoo"})
    assert other.json()["action"] == "verified_different"


def test_retry_after_a_failed_entry(web):
    web.sign_in("j.alvarez")
    ref = web.client.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    assert web.client.post(f"/api/v1/drafts/{ref}/retry", json={}).json()["action"] == "not_failed"
    web.intake.fail_next("create_client", "service_unavailable")
    failed = web.client.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).json()
    assert failed["action"] == "entry_failed"
    assert web.client.get(f"/api/v1/drafts/{ref}").json()["status_label"] == "Needs attention"
    assert web.client.post(f"/api/v1/drafts/{ref}/retry", json={}).json()["action"] == "submitted"


# Queries keep every limit: fixed types, row limit, window, visibility, minimal replies, audit


def test_a_query_is_answered_audited_and_never_a_draft(web):
    """Queries are fixed forms since Stage 3c; tests/test_web_queries.py covers them in full."""
    web.sign_in("j.alvarez")
    out = web.client.post("/api/v1/queries/briefing", json={"quadrant": "SW"}).json()
    assert out["action"] == "query_answered" and out["ref"].startswith("QRY-")
    logged = web.intake.store.audit_events(out["ref"])
    assert [e["event"] for e in logged] == ["query"] and logged[0]["actor"] == "j.alvarez"
    assert logged[0]["query_type"] == "briefing" and "rows" in logged[0]
    assert web.intake.store.drafts() == []


def test_a_query_missing_its_details_runs_nothing(web):
    web.sign_in("j.alvarez")
    out = web.client.post("/api/v1/queries/lookup", json={}).json()
    assert out["action"] == "query_needs_more"
    assert [e["event"] for e in web.intake.store.audit_events(out["ref"])] == ["query_refused"]


def test_query_uses_the_signed_in_workers_project(web, monkeypatch):
    """Visibility comes from the worker record linked to the account, never from the request."""
    seen = {}
    from app import core

    original = core.structured

    def spy(q, reader, config, project, today):
        seen["project"] = project
        return original(q, reader, config, project, today)

    monkeypatch.setattr(core, "structured", spy)
    web.sign_in("m.chen")
    r = web.client.post("/api/v1/queries/briefing", json={"quadrant": "SW", "project": "another_project"})
    assert r.status_code == 422  # a project is never taken from the request
    web.client.post("/api/v1/queries/briefing", json={"quadrant": "SW"})
    assert seen["project"] == web.intake.config.workers.worker_for("m.chen@goodwill-outreach.example").project


# A worker sees only their own drafts


def test_a_worker_cannot_see_or_act_on_another_workers_draft(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    held = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE.replace("Searched HMIS first, no match. ", "")}).json()["ref"]
    chen = web.as_user("m.chen")
    assert chen.get(f"/api/v1/drafts/{ref}").status_code == 404
    assert chen.get("/api/v1/drafts").json() == []
    assert chen.get("/api/v1/messages").json() == []
    assert chen.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).status_code == 404
    assert chen.post(f"/api/v1/drafts/{ref}/corrections", json={"text": "Veteran: yes"}).status_code == 404
    assert chen.post(f"/api/v1/held/{held}/searched", json={}).status_code == 404
    assert web.intake.draft(ref).state == "in_review" and web.intake.draft(ref).version == 1
    assert web.intake.hmis.app.state.store.counts()["clients"] == 0


# The supervisor queue


def test_the_supervisor_sees_expired_drafts(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    web.intake.clock.advance(hours=web.intake.config.settings.supervisor_timeout_hours)
    web.intake.service.expire_stale()
    supervisor = web.as_user(SUPERVISOR)
    queue = supervisor.get("/api/v1/supervisor/queue").json()
    assert [q["draft_id"] for q in queue] == [ref]
    assert alvarez.get("/api/v1/session").status_code == 401  # 48 hours idle: signed out
    alvarez = web.as_user("j.alvarez")
    assert alvarez.get(f"/api/v1/drafts/{ref}").json()["status_label"] == "With your supervisor"


def test_session_reports_the_role(web):
    supervisor = web.as_user(SUPERVISOR)
    me = supervisor.get("/api/v1/session").json()
    assert me["role"] == "supervisor" and me["project"] is None


def test_a_signed_in_worker_cannot_act_for_another_worker_by_naming_them(web):
    web.sign_in("j.alvarez")
    r = web.client.post("/api/v1/notes/new-client", json={"text": NOTE, "author": "m.chen@goodwill-outreach.example"})
    assert r.status_code == 422  # the author is always the signed-in worker, never a field


def test_unknown_draft_is_not_found(web):
    web.sign_in("j.alvarez")
    assert web.client.get("/api/v1/drafts/ENC-2026-01-01-9999").status_code == 404


def test_the_web_needs_no_email_channel(intake):
    from app.config_loader import with_email_channel

    intake.service.config = with_email_channel(intake.config, False)
    web = Web(intake)
    web.sign_in("j.alvarez")
    assert web.client.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["action"] == "drafted"
