"""add-web-application, Stage 3d: what the supervisor and staff screens read from the API.

Specs: openspec/changes/add-web-application/specs/web-application/spec.md ("Supervisor queue
screen", "Supervisor views without neighbor information", "Staff audit views without neighbor
information"). No session and wrong-role checks for every route are in tests/test_web_api.py.
Synthetic data only.
"""

from __future__ import annotations

import json
import re

import pytest

from app.audit_text import DESCRIPTIONS, describe

from .conftest import REPO_ROOT
from .test_channel_wording import EMAIL_COMMANDS, EMAIL_WORDS
from .test_web_api import NOTE, ROBIN, STAFF, SUPERVISOR

LONG_REASON = "He is about twenty years younger than the person in HMIS and has a different tattoo"
PRIVATE = ("Robin", "Demo", "Kim", "Placeholder", "1975", "1990", "5555", "4821", "hygiene kit", "bad back")


def hours(web) -> int:
    return web.intake.config.settings.supervisor_timeout_hours


def flagged_draft(web, reason: str = LONG_REASON) -> str:
    """A draft decided DIFFERENT PERSON although the SSN digits matched, then entered."""
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": ROBIN, "title": "New client: Robin"}).json()["ref"]
    assert alvarez.post(f"/api/v1/drafts/{ref}/different-person", json={"reason": reason}).json()["action"] == "verified_different"
    assert alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).json()["action"] == "submitted"
    assert web.intake.draft(ref).verification.supervisor_review
    return ref


# The 48-hour queue


def test_the_queue_lists_drafts_not_confirmed_in_time_in_plain_words(web):
    ref = web.as_user("j.alvarez").post("/api/v1/notes/new-client", json={"text": NOTE, "title": "Kim, NW"}).json()["ref"]
    web.intake.clock.advance(hours=hours(web) + 2)
    queue = web.as_user(SUPERVISOR).get("/api/v1/supervisor/queue").json()
    assert [(q["draft_id"], q["worker_id"], q["version"], q["status_label"], q["hours_waiting"]) for q in queue] == [
        (ref, "j.alvarez", 1, "Not confirmed in time", hours(web) + 2)]
    assert not [p for p in PRIVATE if p in json.dumps(queue)]


def test_the_48_hour_rule_holds_without_a_maintenance_job(web):
    """Nothing calls expire_stale here: the web app applies the rule itself."""
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    web.intake.clock.advance(hours=hours(web))
    alvarez = web.as_user("j.alvarez")
    assert alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).json()["action"] == "expired"
    assert web.intake.hmis.app.state.store.counts()["clients"] == 0
    assert [e["event"] for e in web.intake.store.audit_events(ref)].count("expired_to_supervisor_queue") == 1


def test_a_draft_within_48_hours_is_not_in_the_queue(web):
    web.as_user("j.alvarez").post("/api/v1/notes/new-client", json={"text": NOTE})
    web.intake.clock.advance(hours=hours(web) - 1)
    assert web.as_user(SUPERVISOR).get("/api/v1/supervisor/queue").json() == []


# The audit flag for matching SSN digits


def test_the_flag_shows_only_that_it_exists_the_draft_and_the_reason(web):
    ref = flagged_draft(web)
    flags = web.as_user(SUPERVISOR).get("/api/v1/supervisor/flags").json()
    assert flags == [{"draft_id": ref, "flag": "Entered as a different person although the last four SSN digits matched.",
                      "reason": LONG_REASON}]


def test_the_reason_never_shows_digits_or_a_date(web):
    reason = "His digits 5555 match but he was born 9/9/1975 and is plainly much younger than the person in HMIS"
    flagged_draft(web, reason)
    shown = web.as_user(SUPERVISOR).get("/api/v1/supervisor/flags").json()[0]["reason"]
    assert "5555" not in shown and "1975" not in shown and "9/9" not in shown
    assert "[number hidden]" in shown and "[date hidden]" in shown and "much younger" in shown


def test_a_decision_without_matching_digits_is_not_flagged(web):
    alvarez = web.as_user("j.alvarez")
    note = ROBIN.replace("SSN ends 5555", "SSN ends 1111")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": note}).json()["ref"]
    assert alvarez.post(f"/api/v1/drafts/{ref}/different-person", json={"reason": "a much younger man"}).json()["action"] == "verified_different"
    supervisor = web.as_user(SUPERVISOR)
    assert supervisor.get("/api/v1/supervisor/flags").json() == []
    assert "much younger" not in json.dumps(supervisor.get(f"/api/v1/supervisor/drafts/{ref}").json())


# Each draft's state and audit trail


def test_the_draft_view_shows_state_and_audit_without_neighbor_information(web):
    ref = flagged_draft(web)
    supervisor = web.as_user(SUPERVISOR)
    listed = supervisor.get("/api/v1/supervisor/drafts").json()
    assert [(d["id"], d["status_label"], d["flagged"]) for d in listed] == [(ref, "Entered in HMIS", True)]
    view = supervisor.get(f"/api/v1/supervisor/drafts/{ref}").json()
    assert view["status_label"] == "Entered in HMIS" and view["worker_id"] == "j.alvarez" and view["flagged"] is True
    assert all(set(e) == {"at", "actor", "event", "what"} for e in view["events"])
    assert "Worker confirmed version 1." in [e["what"] for e in view["events"]]
    text = json.dumps([listed, view])
    assert not [p for p in PRIVATE if p in text] and "twenty years younger" not in text and "New client: Robin" not in text


def test_an_unknown_draft_is_not_found(web):
    assert web.as_user(SUPERVISOR).get("/api/v1/supervisor/drafts/ENC-2026-01-01-9999").status_code == 404


def test_supervisor_views_write_no_audit(web):
    """The existing rules audit HMIS reads, actions, and sign-ins, not views [TBC with Goodwill]."""
    ref = flagged_draft(web)
    supervisor = web.as_user(SUPERVISOR)
    before = web.intake.store._db.execute("SELECT COUNT(id) FROM audit").fetchone()[0]
    for path in ("queue", "flags", "drafts", f"drafts/{ref}"):
        assert supervisor.get(f"/api/v1/supervisor/{path}").status_code == 200
    assert web.intake.store._db.execute("SELECT COUNT(id) FROM audit").fetchone()[0] == before


# Supervisors cannot run worker actions, on real drafts


@pytest.mark.parametrize(("path", "body"), [
    ("drafts/{ref}/confirm", {"version": 1}), ("drafts/{ref}/retry", {}), ("drafts/{ref}/corrections", {"text": "Veteran: yes"}),
    ("drafts/{ref}/same-client", {"client_id": "HMIS-C-000113"}), ("drafts/{ref}/different-person", {"reason": LONG_REASON}),
    ("notes/new-client", {"text": NOTE}), ("notes/update", {"text": NOTE}), ("queries/briefing", {"quadrant": "SW"}),
    ("queries/lookup", {"client_id": "HMIS-C-000101"}), ("queries/no-contact", {}),
])
def test_a_supervisor_cannot_run_a_worker_action(web, path, body):
    ref = web.as_user("j.alvarez").post("/api/v1/notes/new-client", json={"text": ROBIN}).json()["ref"]
    before = web.intake.draft(ref).model_dump()
    supervisor = web.as_user(SUPERVISOR)
    assert supervisor.post(f"/api/v1/{path.format(ref=ref)}", json=body).status_code == 403
    assert web.intake.draft(ref).model_dump() == before and len(web.intake.store.drafts()) == 1
    assert web.intake.hmis.app.state.store.counts()["clients"] == 0
    assert web.intake.store.audit_events_for_prefix("QRY-") == []


# Staff


def test_staff_views_have_plain_descriptions_and_no_neighbor_information(web):
    ref = flagged_draft(web)
    web.as_user("j.alvarez").post("/api/v1/queries/lookup", json={"first_name": "Robin", "last_name": "Demo", "date_of_birth": "1975-09-09"})
    staff = web.as_user(STAFF)
    listed = staff.get("/api/v1/staff/drafts").json()
    assert listed[0]["status_label"] == "Entered in HMIS"
    audit = staff.get(f"/api/v1/staff/drafts/{ref}/audit").json()
    assert audit["status_label"] == "Entered in HMIS" and all(e["what"] for e in audit["events"])
    queries = staff.get("/api/v1/staff/queries").json()
    assert queries[0]["what"] == "Lookup by name and date of birth (both given). 3 rows."  # 2 in the seed, and the one just entered
    text = json.dumps([listed, audit, queries])
    assert not [p for p in PRIVATE if p in text] and "twenty years younger" not in text


def test_staff_never_see_the_first_word_of_a_reply(web):
    """An email reply after expiry records its first word, which could be a name."""
    ref = web.intake.receive_text(NOTE).ref
    web.intake.clock.advance(hours=hours(web))
    web.intake.service.expire_stale()
    web.intake.reply(ref, "Kim was younger than I said")
    assert any(e.get("command") == "KIM" for e in web.intake.store.audit_events(ref))
    audit = web.as_user(STAFF).get(f"/api/v1/staff/drafts/{ref}/audit").json()
    assert "KIM" not in json.dumps(audit)


# Plain descriptions of audit events


def test_every_audit_event_has_a_plain_description():
    source = (REPO_ROOT / "app" / "core.py").read_text(encoding="utf-8")
    names = set(re.findall(r'\.audit\([^,]+, "([a-z_]+)"', source)) | set(re.findall(r'worker, "([a-z_]+)"', source))
    assert len(names) > 25 and names - set(DESCRIPTIONS) == set()
    assert {"idempotent_replay", "hmis_idempotent_replay", "web_refused_not_owner"} <= set(DESCRIPTIONS)


def test_descriptions_have_no_email_wording_and_never_echo_free_text():
    event = {"version": 2, "from_version": 1, "to_version": 2, "step": "client", "ok": True, "identifier": "HMIS-C-1", "code": "x",
             "candidates": 1, "decision": "different_person", "reason": "secret words", "command": "SECRETWORD", "chosen": "HMIS-C-1",
             "client_id": "HMIS-C-1", "type": "confirm", "rows": 1, "query_type": "briefing", "quadrant": "sw", "supervisor_review": True,
             "blocking": ["ce_region"], "changed_fields": ["veteran_status"], "confirmed": 1, "current": 2, "refused": "reason_too_short"}
    for name in DESCRIPTIONS:
        what = describe({**event, "event": name})
        assert what and not EMAIL_WORDS.search(what) and not EMAIL_COMMANDS.search(what), name
        assert "secret" not in what.lower(), name


def test_an_unknown_event_is_described_without_its_details():
    assert describe({"event": "something_new", "reason": "secret"}) == "Recorded event."
