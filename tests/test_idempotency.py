"""add-web-application, Stage 2c: idempotency keys on our writes and on HMIS entry operations.

Specs: openspec/changes/add-web-application/specs/offline-sync/spec.md ("Idempotency key per
submission") and specs/web-application/spec.md ("Idempotency keys on HMIS entry operations").
The failure this guards against: HMIS records an entry but its answer is lost, the worker
retries, and a second record must never be made. Synthetic data only.
"""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from app.hmis_gateway import HmisGateway

from .conftest import Intake, client_fields
from .test_web_api import NOTE, ROBIN

LONG_REASON = "He is about twenty years younger than the person in HMIS and has a different tattoo"
KEY = "3f1c9a52-6d0e-4b7a-9c1d-2e8f0a6b4c11"  # a client-made key (a random UUID in the web app)


def counts(web) -> dict[str, int]:
    return web.intake.hmis.app.state.store.counts()


def events(web, ref: str) -> list[str]:
    return [e["event"] for e in web.intake.store.audit_events(ref)]


def keyed(client, path: str, body: dict, key: str = KEY):
    return client.post(path, json=body, headers={"Idempotency-Key": key})


# Our own writes


def test_the_same_key_and_request_returns_the_original_result_and_makes_nothing_new(web):
    alvarez = web.as_user("j.alvarez")
    first = keyed(alvarez, "/api/v1/notes/new-client", {"text": NOTE})
    again = keyed(alvarez, "/api/v1/notes/new-client", {"text": NOTE})
    assert first.status_code == again.status_code == 200
    assert again.json()["action"] == first.json()["action"] == "drafted"
    assert again.json()["ref"] == first.json()["ref"]
    assert len(web.intake.store.drafts()) == 1


def test_the_same_key_with_a_different_request_is_refused(web):
    alvarez = web.as_user("j.alvarez")
    keyed(alvarez, "/api/v1/notes/new-client", {"text": NOTE})
    other = keyed(alvarez, "/api/v1/notes/new-client", {"text": NOTE.replace("Kim", "Kym")})
    assert other.status_code == 409
    elsewhere = keyed(alvarez, "/api/v1/notes/update", {"text": NOTE})  # same body, another route
    assert elsewhere.status_code == 409
    assert len(web.intake.store.drafts()) == 1


def test_keys_are_scoped_per_user(web):
    keyed(web.as_user("j.alvarez"), "/api/v1/notes/new-client", {"text": NOTE})
    chen = keyed(web.as_user("m.chen"), "/api/v1/notes/new-client", {"text": NOTE})
    assert chen.status_code == 200 and chen.json()["action"] == "drafted"
    assert len(web.intake.store.drafts()) == 2


def test_keys_expire_after_the_configured_time(web):
    keyed(web.as_user("j.alvarez"), "/api/v1/notes/new-client", {"text": NOTE})
    web.intake.clock.advance(hours=web.intake.config.settings.web.idempotency_key_hours, minutes=1)
    alvarez = web.as_user("j.alvarez")  # the old session idled out too
    later = keyed(alvarez, "/api/v1/notes/new-client", {"text": NOTE.replace("Kim", "Kym")})
    assert later.status_code == 200 and len(web.intake.store.drafts()) == 2


def test_two_requests_at_once_with_the_same_key_give_one_result(web, monkeypatch):
    alvarez = web.as_user("j.alvarez")
    real, calls = web.intake.service.new_client, []

    def slow(note, worker):
        calls.append(1)
        time.sleep(0.4)  # the second request arrives while the first is still running
        return real(note, worker)

    monkeypatch.setattr(web.intake.service, "new_client", slow)
    start, results = threading.Barrier(2), []

    def send():
        start.wait()
        results.append(keyed(alvarez, "/api/v1/notes/new-client", {"text": NOTE}))

    threads = [threading.Thread(target=send) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(calls) == 1 and len(web.intake.store.drafts()) == 1
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json()["ref"] == results[1].json()["ref"]


def test_a_request_that_fails_frees_its_key(web, monkeypatch):
    alvarez = web.as_user("j.alvarez")
    real = web.intake.service.new_client

    def broken(note, worker):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(web.intake.service, "new_client", broken)
    with pytest.raises(RuntimeError):
        keyed(alvarez, "/api/v1/notes/new-client", {"text": NOTE})
    monkeypatch.setattr(web.intake.service, "new_client", real)
    assert keyed(alvarez, "/api/v1/notes/new-client", {"text": NOTE}).json()["action"] == "drafted"


def test_a_confirm_replayed_by_key_enters_once(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    first = keyed(alvarez, f"/api/v1/drafts/{ref}/confirm", {"version": 1}, key="confirm-key-0001")
    again = keyed(alvarez, f"/api/v1/drafts/{ref}/confirm", {"version": 1}, key="confirm-key-0001")
    assert first.json()["action"] == again.json()["action"] == "submitted"
    assert counts(web)["clients"] == 1


def test_replays_are_audited_with_the_type_and_draft_only(web):
    alvarez = web.as_user("j.alvarez")
    ref = keyed(alvarez, "/api/v1/notes/new-client", {"text": NOTE}).json()["ref"]
    keyed(alvarez, "/api/v1/notes/new-client", {"text": NOTE})
    replay = [e for e in web.intake.store.audit_events(ref) if e["event"] == "idempotent_replay"]
    assert replay == [{"at": replay[0]["at"], "event": "idempotent_replay", "actor": None, "type": "new_client"}]
    everything = json.dumps(web.intake.store._db.execute("SELECT * FROM audit").fetchall())
    stored = json.dumps(web.intake.store._db.execute("SELECT * FROM idempotency").fetchall())
    assert KEY not in everything and KEY not in stored  # only a hash of the key is kept
    assert "Kim" not in stored and "Placeholder" not in stored  # no note text in the replay record


def test_a_key_must_be_reasonable(web):
    alvarez = web.as_user("j.alvarez")
    for bad in ("", "x" * 300, "has spaces in it"):
        assert keyed(alvarez, "/api/v1/notes/new-client", {"text": NOTE}, key=bad).status_code == 400
    assert web.intake.store.drafts() == []


# HMIS entry operations


class Spy(HmisGateway):
    """Records the key of each entry call and the draft's stored key at that moment."""

    def __init__(self, http, intake_ref):
        super().__init__(http)
        self.calls, self.intake_ref = [], intake_ref

    def _post(self, path, fields, id_key, *, idempotency_key=None, **extra):
        stored = self.intake_ref[0].store.get_draft(self.intake_ref[1]).entry_key if self.intake_ref else None
        self.calls.append((path, idempotency_key, stored))
        return super()._post(path, fields, id_key, idempotency_key=idempotency_key, **extra)


def test_the_hmis_key_is_saved_with_the_draft_before_the_first_call(hmis):
    holder: list = []
    intake = Intake(hmis, gateway=Spy(hmis, holder))
    ref = intake.receive_text(NOTE).ref
    holder.extend([intake, ref])
    assert intake.draft(ref).entry_key is None  # made only when the worker confirms
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    key = intake.draft(ref).entry_key
    assert key and [c[1] for c in intake.gateway.calls] == [f"{key}:client", f"{key}:enrollment", f"{key}:ce_enrollment"]
    assert all(stored == key for _, _, stored in intake.gateway.calls)  # already stored when HMIS was called


@pytest.mark.parametrize("step", ["create_client", "enroll_in_program"])
def test_hmis_records_the_entry_but_the_answer_is_lost_then_a_retry_makes_no_second_record(web, step):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    web.intake.fail_next(step, "lost_response")
    failed = alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).json()
    assert failed["action"] == "entry_failed" and web.intake.draft(ref).last_failure == "timeout"
    recorded = counts(web)
    key = web.intake.draft(ref).entry_key
    assert alvarez.post(f"/api/v1/drafts/{ref}/retry").json()["action"] == "submitted"
    assert counts(web) == {**recorded, "enrollments": 1, "ce_enrollments": 1}
    assert counts(web)["clients"] == 1 and web.intake.draft(ref).entry_key == key
    assert "hmis_idempotent_replay" in events(web, ref)


def test_a_lost_answer_does_not_reopen_the_same_name_verification(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": ROBIN}).json()["ref"]
    alvarez.post(f"/api/v1/drafts/{ref}/different-person", json={"reason": LONG_REASON})
    before = web.intake.draft(ref).verification
    checks = events(web, ref).count("same_name_found")
    web.intake.fail_next("create_client", "lost_response")
    assert alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).json()["action"] == "entry_failed"
    # Retried by confirming again, as a worker might: still no new verification.
    assert alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).json()["action"] == "submitted"
    draft = web.intake.draft(ref)
    assert draft.verification == before and draft.verification.decision == "different_person"
    assert events(web, ref).count("same_name_found") == checks and counts(web)["clients"] == 1


def test_retry_after_a_normal_failure(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    web.intake.fail_next("create_client", "service_unavailable")
    assert alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).json()["action"] == "entry_failed"
    assert counts(web)["clients"] == 0
    assert alvarez.post(f"/api/v1/drafts/{ref}/retry").json()["action"] == "submitted"
    assert counts(web)["clients"] == 1


def test_retry_after_a_timeout_that_saved_nothing(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    web.intake.fail_next("create_client", "timeout")
    assert alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1}).json()["action"] == "entry_failed"
    assert counts(web)["clients"] == 0 and web.intake.draft(ref).last_failure == "timeout"
    assert alvarez.post(f"/api/v1/drafts/{ref}/retry").json()["action"] == "submitted"
    assert counts(web)["clients"] == 1


def test_the_hmis_key_cannot_be_changed_through_the_api(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    web.intake.fail_next("create_client", "lost_response")
    alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1})
    key = web.intake.draft(ref).entry_key
    assert alvarez.post(f"/api/v1/drafts/{ref}/retry", json={"entry_key": "mine"}).status_code == 422
    assert alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1, "entry_key": "mine"}).status_code == 422
    # A new Idempotency-Key for our own request is a new request to us, but HMIS still gets the stored key.
    assert keyed(alvarez, f"/api/v1/drafts/{ref}/retry", {}, key="another-key-0001").json()["action"] == "submitted"
    assert web.intake.draft(ref).entry_key == key and counts(web)["clients"] == 1


def test_a_new_version_gets_a_new_hmis_key(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/update", json={"text": "Saw Jordan Sample (HMIS-C-000101) in the SW quadrant. "
                                                      "Gave her a bus pass and water. Spent 20 minutes with her."}).json()["ref"]
    alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1})
    first = web.intake.draft(ref).entry_key
    alvarez.post(f"/api/v1/drafts/{ref}/corrections", json={"text": "It was 45 minutes, not 20."})
    assert alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 2}).json()["action"] == "submitted"
    assert web.intake.draft(ref).entry_key not in (None, first)


def test_the_same_name_check_and_the_duplicate_backstop_still_work(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    alvarez.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1})
    second = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    assert web.intake.draft(second).verification.open  # Kim is in HMIS now: verification, not a silent entry
    gateway = web.intake.gateway
    fields = client_fields(first_name="Kim", last_name="Placeholder", date_of_birth="1990-01-02")
    assert gateway.create_client(fields, idempotency_key="a-brand-new-key").code == "possible_duplicate"


# The mock HMIS and the gateway


def test_the_mock_replays_a_key_and_refuses_it_for_another_request(hmis):
    body = {"fields": client_fields(first_name="Lane", last_name="Sample", date_of_birth="1970-05-05")}
    first = hmis.post("/clients", json=body, headers={"Idempotency-Key": "mock-key-1"})
    again = hmis.post("/clients", json=body, headers={"Idempotency-Key": "mock-key-1"})
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json() and again.headers.get("Idempotent-Replay") == "true"
    changed = {"fields": {**body["fields"], "first_name": "Lena"}}
    reused = hmis.post("/clients", json=changed, headers={"Idempotency-Key": "mock-key-1"})
    assert reused.status_code == 422 and reused.json()["code"] == "idempotency_key_reused"
    assert hmis.app.state.store.counts()["clients"] == 1


def test_the_gateway_sends_the_key_and_reports_a_timeout():
    seen = []

    def answer(request):
        seen.append(request.headers.get("Idempotency-Key"))
        raise httpx.ReadTimeout("no answer", request=request)

    gateway = HmisGateway(httpx.Client(base_url="http://127.0.0.1:8765", transport=httpx.MockTransport(answer)))
    result = gateway.add_service("HMIS-C-000101", {"service_type": "water"}, idempotency_key="k-1:service")
    assert seen == ["k-1:service"] and not result.ok and result.code == "timeout"
