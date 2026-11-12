"""add-web-application, Stage 4d: sync in a real browser against the real server.

Runs tests/browser/offline_sync.mjs: real headless Chrome, a real app server that is actually
stopped to prove offline, real lost responses (the server handled the request and the browser lost
the answer), two real tabs, and a really expired session. Each step inspects local and session
storage, IndexedDB, the service worker cache, and every network request, and the server's log and
audit are read afterward. Keys and passwords are random for each run. Synthetic data only.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.sealing import Sealer

from .test_offline_browser import NOTE, SENTINEL, SHELL_PATHS, run_scenario, seal_key
from .test_sealing import py_seal

MARK = "ZZSYNC"
MARKS = ["AUTOA", "AUTOB", "OPEN", "LOSTB", "DIRECT", "LIMITED", "MANUAL", "TABA", "TABB", "TABC", "EXPA", "EXPB", "STALE", "OVERLIMIT", "SSNREF", "MISMATCH", "CONFA", "CONFB"]
WORDS = [MARK + m for m in MARKS] + ["Placeholder", "234 56 7891"]
INSPECTED = [("s1_saved", "inspect"), ("s1_uploading", "inspect"), ("s1_done", "inspect"), ("s2", "inspect"), ("s3", "inspect"), ("s3b_saved", "inspect"), ("s3b", "inspect"),
             ("s4_saved", "inspect"), ("s4", "inspect"), ("s5", "inspect"), ("s6", "inspect"), ("s7_prompt", "inspect"), ("s7", "inspect"), ("s8", "inspect"), ("s9", "inspect"),
             ("s9_deleted", "inspect"), ("s10", "inspect")]


def note(mark: str, name: str) -> str:
    return NOTE.replace("Kim Placeholder", f"{name} Placeholder").replace(SENTINEL, MARK + mark)


def row(sealer: Sealer, *, seal_owner: str = "j.alvarez", key: str | None = None, text: str, contact_at: datetime, written: datetime) -> dict:
    key = key or str(uuid.uuid4())
    at = written.isoformat().replace("+00:00", "Z")
    inner = {"text": text, "title": None, "written_at": at, "ssn_invalid_label": None, "contact": sealer.contact_stamp(seal_owner, contact_at)}
    envelope = py_seal(sealer.current(), seal_owner, key, "new_client", at, inner)
    return {"id": key, "owner": "j.alvarez", "kind": "new_client", "idempotency_key": key, "saved_at": at, "status": "saved", "retries": 0, "reason": None, "envelope": envelope}


@pytest.fixture(scope="module")
def sync(tmp_path_factory):
    sealer = Sealer([seal_key()])
    now = datetime.now(timezone.utc)
    conflict_key = str(uuid.uuid4())
    tmp = tmp_path_factory.mktemp("offline-sync")
    notes = {"auto_1": note("AUTOA", "Ana"), "auto_2": note("AUTOB", "Bea"), "open": note("OPEN", "Cal"), "lost_2": note("LOSTB", "Eli"),
             "direct": note("DIRECT", "Fay"), "limited": note("LIMITED", "Gus"), "manual": note("MANUAL", "Hal"), "tabs": [note("TABA", "Ira"), note("TABB", "Jon"), note("TABC", "Kai")],
             "expired_1": note("EXPA", "Lou"), "expired_2": note("EXPB", "Max"), "stale": note("STALE", "Ned")}
    rows = {"over_limit": row(sealer, text=note("OVERLIMIT", "Oda"), contact_at=now - timedelta(hours=13), written=now),
            "ssn": row(sealer, text=f"{MARK}SSNREF Her social is 234 56 7891.", contact_at=now, written=now),
            "mismatch": row(sealer, seal_owner="m.chen", text=note("MISMATCH", "Pia"), contact_at=now, written=now),
            "conflict_first": row(sealer, key=conflict_key, text=note("CONFA", "Quy"), contact_at=now, written=now)}
    conflict_second = row(sealer, key=conflict_key, text=note("CONFB", "Rae"), contact_at=now, written=now)
    conflict_second["saved_at"] = rows["conflict_first"]["saved_at"]
    out, log, passwords = run_scenario("offline_sync.mjs", tmp, notes=notes, rows=rows, conflict_second=conflict_second)
    return out, log, passwords, tmp / "intake.db", rows


def queue_rows(inspected: dict) -> list:
    return [value for _, value in inspected["idb"].get("outreach-device", {}).get("queue", [])]


def opened(r: dict) -> dict:
    return Sealer([seal_key()]).open(r["envelope"], owner=r["owner"], idempotency_key=r["idempotency_key"], kind=r["kind"], saved_at=r["saved_at"])


def audit(db) -> list[dict]:
    conn = sqlite3.connect(db)
    try:
        names = [r[1] for r in conn.execute("PRAGMA table_info(audit)")]
        return [dict(zip(names, r)) for r in conn.execute("SELECT * FROM audit")]
    finally:
        conn.close()


# What every step must show


@pytest.mark.parametrize(("step", "field"), INSPECTED, ids=[s for s, _ in INSPECTED])
def test_no_note_text_is_stored_anywhere(sync, step, field):
    text = json.dumps(sync[0][step][field])
    for word in WORDS:
        assert word not in text, word


@pytest.mark.parametrize(("step", "field"), INSPECTED, ids=[s for s, _ in INSPECTED])
def test_storage_and_cache_stay_clean(sync, step, field):
    seen = sync[0][step][field]
    assert seen["local"] == {} and seen["session"] == {}
    assert seen["cache"] and all(set(urls) == SHELL_PATHS for urls in seen["cache"].values())


@pytest.mark.parametrize("word", WORDS)
def test_no_request_carries_note_text(sync, word):
    for r in sync[0]["all_requests"]:
        assert word not in r["url"] and word not in (r["postData"] or ""), r["url"]


@pytest.mark.parametrize("word", WORDS)
def test_the_server_log_holds_no_note_text(sync, word):
    assert sync[1] and word not in sync[1]


def test_the_server_log_holds_no_key_or_password(sync):
    _, log, passwords, _, _ = sync
    assert seal_key() not in log and seal_key()[60:120] not in log and not [p for p in passwords.values() if p in log]


def test_no_content_security_violations(sync):
    assert sync[0]["violations"] == []


# Upload when the connection returns


def test_saving_offline_sends_nothing(sync):
    assert not [r for r in sync[0]["s1_saved"]["requests"] if r["method"] == "POST"]
    assert sync[0]["s1_saved"]["pill"] == "Offline" and "Saved on device" in sync[0]["s1_saved"]["text"]


def test_the_status_and_the_header_show_uploading(sync):
    u = sync[0]["s1_uploading"]
    assert "Uploading" in u["text"] and u["pill"] == "Uploading"
    assert [r["status"] for r in queue_rows(u["inspect"])].count("uploading") == 1


def test_one_upload_at_a_time_in_one_tab(sync):
    assert sync[0]["s1_held_at_once"] == 1


def test_the_notes_upload_by_themselves_and_appear_for_review(sync):
    d = sync[0]["s1_done"]
    assert d["pill"] == "Online" and "Uploaded" in d["text"] and "In review" in d["text"]
    assert all(r["status"] == "uploaded" and "envelope" not in r for r in queue_rows(d["inspect"]))
    assert len([r for r in d["requests"] if r["url"].endswith("/notes/sealed") and r.get("status") == 200]) == 2


def test_the_worker_reviews_on_the_server_screen(sync):
    assert "Confirm" in sync[0]["s1_review"]["text"] and sync[0]["s1_review"]["confirm"] is False


def test_opening_the_review_clears_only_that_row(sync):
    assert len(sync[0]["s1_rows_after_open"]) == 1


def test_opening_the_app_uploads_what_is_waiting(sync):
    posts = [r for r in sync[0]["s2"]["requests"] if r["url"].endswith("/notes/sealed") and r["method"] == "POST"]
    assert [r["status"] for r in posts] == [200]


# Exactly one draft


def test_a_lost_response_then_a_retry_makes_one_draft(sync):
    s = sync[0]["s3"]
    assert s["dropped"] == 2 and s["after"] == s["before"] + 1
    assert len(s["requests"]) == 2 and s["requests"][1]["status"] == 200


def test_the_retry_used_the_original_key_and_envelope(sync):
    s = sync[0]["s3"]
    for r in s["requests"]:
        assert r["headers"]["Idempotency-Key"] == s["key"] and json.loads(r["postData"])["envelope"] == s["envelope"]


def test_the_server_really_handled_the_lost_request(sync):
    log = sync[1]
    assert log.count('"POST /api/v1/notes/sealed HTTP/1.1" 200') >= 2


def test_a_lost_response_while_online_is_saved_and_makes_one_draft(sync):
    out = sync[0]
    assert "Saved on device" in out["s3b_saved"]["text"]
    s = out["s3b"]
    assert s["after"] == s["before"] + 1 and len(s["requests"]) == 2
    a, b = s["requests"]
    assert a["headers"]["Idempotency-Key"] == b["headers"]["Idempotency-Key"] and a["postData"] == b["postData"]


def test_replays_are_audited_with_no_key(sync):
    events = audit(sync[3])
    replays = [e for e in events if e["event"] == "idempotent_replay"]
    assert len(replays) >= 2
    for e in replays:
        assert "sealed_new_client" in json.dumps(e)


# 429 and Retry-After


def test_retry_after_is_respected(sync):
    out = sync[0]
    assert out["s4_seen_early"] == 1 and "Saved on device" in out["s4_saved"]["text"]
    assert out["s4"]["attempts"] == 2 and out["s4"]["gap_ms"] >= 3900


# The manual button


def test_the_manual_button_stays_as_a_fallback(sync):
    out = sync[0]
    assert "Upload my saved notes" in out["s5_waiting"]["text"] and out["s5_waiting"]["pill"] == "Online"
    assert [r["status"] for r in out["s5"]["requests"]] == [200]


# Two tabs


def test_two_tabs_upload_one_at_a_time(sync):
    assert sync[0]["s6"]["max_in_flight"] == 1


def test_two_tabs_send_each_note_once(sync):
    s = sync[0]["s6"]
    assert len(s["keys"]) == 3 and sorted(x["key"] for x in s["seen"]) == sorted(s["keys"])
    assert len([r for r in s["requests"] if r.get("status") == 200]) == 3


def test_the_other_tab_shows_the_result(sync):
    assert "Uploaded" in sync[0]["s6"]["other_tab_text"]


# Expired session


def test_an_expired_session_asks_to_sign_in_and_keeps_the_notes(sync):
    p = sync[0]["s7_prompt"]
    assert "Sign in to upload your 2 saved notes" in p["text"] and "Please sign in again" not in p["text"]
    assert p["sign_out_shown"] is False
    kept = [r for r in queue_rows(p["inspect"]) if r.get("envelope")]
    assert len(kept) == 2 and all(r["status"] == "saved" for r in kept)


def test_an_expired_session_stops_the_uploads(sync):
    assert not [r for r in sync[0]["s7_prompt"]["requests"] if r["url"].endswith("/notes/sealed")]


def test_uploads_resume_after_sign_in(sync):
    s = sync[0]["s7"]
    assert [r["status"] for r in s["requests"]] == [200, 200] and "Uploaded" in s["text"]


def test_a_stale_csrf_token_is_refreshed_and_the_note_goes_once(sync):
    s = sync[0]["s8"]
    assert [r["status"] for r in s["requests"]] == [403, 200] and s["after"] == s["before"] + 1
    a, b = s["requests"]
    assert a["headers"]["Idempotency-Key"] == b["headers"]["Idempotency-Key"] and a["postData"] == b["postData"]


# Refused


def row_named(sync, name: str) -> dict:
    wanted = sync[4][name]["id"]
    return next(r for r in queue_rows(sync[0]["s9"]["inspect"]) if r["id"] == wanted)


@pytest.mark.parametrize(("name", "phrase", "can_retry"), [("over_limit", "12 hours", False), ("ssn", "last four digits", False), ("mismatch", "could not be opened", True)])
def test_a_refused_note_needs_attention_with_a_plain_reason(sync, name, phrase, can_retry):
    r = row_named(sync, name)
    assert r["status"] == "attention" and phrase in r["reason"] and r["can_retry"] is can_retry and r["envelope"]
    assert r["reason"] in sync[0]["s9"]["text"]


@pytest.mark.parametrize("name", ["over_limit", "ssn", "mismatch"])
def test_a_reason_holds_no_note_content(sync, name):
    reason = row_named(sync, name)["reason"]
    for word in WORDS:
        assert word not in reason


def test_the_header_says_needs_attention(sync):
    assert sync[0]["s9"]["pill"] == "Needs attention"


def test_nothing_was_drafted_from_a_refused_note(sync):
    assert all(r["status"] in (200, 422) for r in sync[0]["s9"]["requests"])
    assert len([r for r in sync[0]["s9"]["requests"] if r["status"] == 422]) == 3


def test_try_again_is_shown_only_where_it_can_help(sync):
    html = sync[0]["s9"]["html"]
    assert f'data-action="retry-note" data-ref="{sync[4]["mismatch"]["id"]}"' in html
    assert f'data-ref="{sync[4]["over_limit"]["id"]}"' not in html and f'data-ref="{sync[4]["ssn"]["id"]}"' not in html


def test_a_real_409_never_makes_a_second_draft(sync):
    c = sync[0]["s9_conflict"]
    assert [r["status"] for r in c["requests"]] == [409] and c["after"] == c["before"]
    assert c["row"]["status"] == "attention" and "idempotency" not in c["row"]["reason"].lower() and c["row"]["can_retry"] is False


def test_try_again_resends_the_same_envelope_under_the_same_key(sync):
    s = sync[0]["s9_retry"]
    original = sync[4]["mismatch"]
    assert [r["status"] for r in s["requests"]] == [422] and s["row"]["status"] == "attention"
    assert s["requests"][0]["headers"]["Idempotency-Key"] == original["idempotency_key"]
    assert json.loads(s["requests"][0]["postData"])["envelope"] == original["envelope"]


def test_delete_warns_then_removes_the_note(sync):
    out = sync[0]
    assert "write it again" in out["s9_warning"] and "cannot be read" in out["s9_warning"]
    assert sync[4]["over_limit"]["id"] not in out["s9_deleted"]["rows"]


# Quiet while offline


def test_the_app_stays_quiet_while_offline(sync):
    s = sync[0]["s10"]
    assert s["stopped"] is True and len(s["requests"]) <= 3
    assert all(r["url"].endswith("/api/v1/ping") and r["method"] == "GET" for r in s["requests"])


# The audit


def test_uploads_are_audited_with_type_and_count_only(sync):
    events = [e for e in audit(sync[3]) if e["event"] == "sealed_note_uploaded"]
    assert len(events) >= 12
    text = json.dumps(events)
    for word in WORDS:
        assert word not in text
    for key in (r["idempotency_key"] for r in sync[4].values()):
        assert key not in text
