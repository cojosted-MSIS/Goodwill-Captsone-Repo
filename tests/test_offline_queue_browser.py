"""add-web-application, Stage 4c: the encrypted queue in a real browser.

Runs tests/browser/offline_queue.mjs: real headless Chrome against a real app server that is
actually stopped to prove offline. Each step inspects local and session storage, IndexedDB, the
service worker cache, and every network request, and the server's log is searched afterward.
Envelopes read from the browser are opened here with the server's key, to prove what they hold.
Keys and passwords are random for each run. Synthetic data only.
"""

from __future__ import annotations

import json

import pytest

from app.sealing import Sealer

from .test_offline_browser import CAPTURE, NOTE, SENTINEL, SHELL_PATHS, run_scenario, seal_key

TITLE_SENTINEL = "ZZTITLE"
MASK_SENTINEL = "ZZMASKED"
REFUSED_SENTINEL = "ZZREFUSED"
REFUSED_TITLE_SENTINEL = "ZZREFTITLE"
EXPIRE_SENTINEL = "ZZEXPIRE"
FAILED_SENTINEL = "ZZFAILED"
WIPED_SENTINEL = "ZZWIPED"
SHARED_SENTINEL = "ZZSHARED"
FULL_SSN = "234-56-7891"
SENTINELS = [SENTINEL, TITLE_SENTINEL, MASK_SENTINEL, REFUSED_SENTINEL, REFUSED_TITLE_SENTINEL, EXPIRE_SENTINEL, FAILED_SENTINEL, WIPED_SENTINEL, SHARED_SENTINEL]
INSPECTIONS = ("signed_in", "a_inspect", "b_mid_inspect", "b_inspect", "c_in_form_inspect", "c_inspect", "d_inspect", "e_inspect", "e2_inspect", "f_inspect", "g_inspect",
               "h_inspect", "i_inspect", "i_chen_inspect", "j_timed_out_inspect", "j_chen_view_inspect", "j_after_chen_inspect", "j_owner_inspect")
REFUSED_NOTE = f"{REFUSED_SENTINEL} Her social is 234 56 7891."
OFFLINE_REQUEST_STEPS = ("a_requests", "c_requests")


def base_note(name: str, marker: str) -> str:
    return NOTE.replace("Kim Placeholder", name).replace(SENTINEL, marker)


@pytest.fixture(scope="module")
def queue(tmp_path_factory):
    return run_scenario(
        "offline_queue.mjs", tmp_path_factory.mktemp("offline-queue"), title=f"{TITLE_SENTINEL} Kim, NW quadrant",
        masked_note=base_note("Pat Placeholder", MASK_SENTINEL).replace("SSN ends 4821", f"SSN {FULL_SSN}"),
        refused_title=REFUSED_TITLE_SENTINEL, refused_note=REFUSED_NOTE, expiring_note=base_note("Lee Placeholder", EXPIRE_SENTINEL),
        failed_note=base_note("Dee Placeholder", FAILED_SENTINEL), wiped_note=base_note("Wyn Placeholder", WIPED_SENTINEL),
        shared_note=base_note("Sam Placeholder", SHARED_SENTINEL), sentinels=SENTINELS)


def rows(inspected: dict, store: str = "queue") -> list:
    return [value for _, value in inspected["idb"].get("outreach-device", {}).get(store, [])]


def meta(inspected: dict) -> dict:
    return dict(inspected["idb"].get("outreach-device", {}).get("meta", []))


def opened(row: dict) -> dict:
    return Sealer([seal_key()]).open(row["envelope"], owner=row["owner"], idempotency_key=row["idempotency_key"], kind=row["kind"], saved_at=row["saved_at"])


# What every inspection must show


@pytest.mark.parametrize("name", INSPECTIONS)
def test_no_note_text_is_stored_anywhere(queue, name):
    text = json.dumps(queue[0][name])
    for word in SENTINELS:
        assert word not in text, word
    assert "Placeholder" not in text and FULL_SSN not in text


@pytest.mark.parametrize("name", INSPECTIONS)
def test_local_and_session_storage_stay_empty(queue, name):
    assert queue[0][name]["local"] == {} and queue[0][name]["session"] == {}


@pytest.mark.parametrize("name", INSPECTIONS)
def test_the_cache_holds_only_the_shell(queue, name):
    caches = queue[0][name]["cache"]
    assert caches and all(set(urls) == SHELL_PATHS for urls in caches.values())


@pytest.mark.parametrize("word", SENTINELS + ["Placeholder", FULL_SSN])
def test_no_request_ever_carries_note_text(queue, word):
    for r in queue[0]["all_requests"]:
        assert word not in r["url"] and word not in (r["postData"] or ""), r["url"]


@pytest.mark.parametrize("word", SENTINELS + ["Placeholder", FULL_SSN])
def test_the_server_log_holds_no_note_text(queue, word):
    assert queue[1] and word not in queue[1]


def test_the_server_log_holds_no_key_or_password(queue):
    _, log, passwords = queue
    assert seal_key() not in log and seal_key()[60:120] not in log and not [p for p in passwords.values() if p in log]


def test_no_content_security_violations(queue):
    assert queue[0]["violations"] == []


def test_every_api_answer_is_no_store(queue):
    answered = [r for r in queue[0]["all_requests"] if "/api/" in r["url"] and r.get("status")]
    assert len(answered) > 15 and all(r["cacheControl"] == "no-store" and not r["fromServiceWorker"] for r in answered)


def test_the_browser_profile_files_hold_no_note_text(queue):
    """Supporting evidence only: storage engines may compress values."""
    assert queue[0]["profile_hits"] == []


# A. Saved offline


def test_the_offline_form_says_what_will_happen(queue):
    f = queue[0]["a_form"]
    assert CAPTURE in f["text"] and f["button"] == "Save on this device"
    assert f["form"] == "off" and f["textarea"] == ["off", "false"]


def test_a_note_written_offline_shows_on_my_notes_with_time_and_status_only(queue):
    home = queue[0]["a_home"]
    assert home["pill"] == "Offline" and "Saved on device" in home["text"] and "Note saved" in home["text"]
    for word in (TITLE_SENTINEL, SENTINEL, "Kim"):
        assert word not in home["text"] and word not in home["html"]


def test_the_stored_record_is_an_envelope_and_clear_metadata_only(queue):
    (row,) = rows(queue[0]["a_inspect"])
    assert set(row) == {"id", "owner", "kind", "idempotency_key", "saved_at", "status", "retries", "reason", "envelope"}
    assert set(row["envelope"]) == {"v", "key_id", "wrapped_key", "nonce", "ciphertext"}
    assert row["owner"] == "j.alvarez" and row["status"] == "saved" and row["id"] == row["idempotency_key"]


def test_the_envelope_opens_with_the_server_key_only(queue):
    (row,) = rows(queue[0]["a_inspect"])
    inner = opened(row)
    assert SENTINEL in inner["text"] and TITLE_SENTINEL in inner["title"]
    with pytest.raises(Exception):
        Sealer([seal_key()]).open(row["envelope"], owner="m.chen", idempotency_key=row["idempotency_key"], kind=row["kind"], saved_at=row["saved_at"])


def test_saving_offline_sends_nothing(queue):
    answered = [r for r in queue[0]["a_requests"] if r.get("status") == 200]
    assert answered and all(r["fromServiceWorker"] and "/api/" not in r["url"] for r in answered)
    assert not [r for r in queue[0]["a_requests"] if r["method"] == "POST"]


def test_the_device_holds_no_private_key(queue):
    text = json.dumps(queue[0]["a_inspect"])
    assert seal_key() not in text and seal_key()[60:120] not in text
    setup = meta(queue[0]["a_inspect"])["setup"]
    assert set(setup) == {"owner", "seal", "rules", "limits", "contact", "received_at"} and set(setup["seal"]) == {"key_id", "public_key"}


# B. Masking


def test_a_full_number_is_shown_masked_before_anything_is_saved(queue):
    out = queue[0]
    assert out["b_saved_after_first_press"] == 0 and FULL_SSN not in out["b_form"]["text"] and "***-**-7891" in out["b_form"]["text"]
    assert "345-67" not in out["b_form"]["title"] and "***-**-8912" in out["b_form"]["title"]
    assert "hidden" in out["b_form"]["page"]


def test_the_sealed_note_holds_only_the_masked_number(queue):
    row = next(r for r in rows(queue[0]["b_inspect"]) if MASK_SENTINEL in opened(r)["text"])
    inner = opened(row)
    assert FULL_SSN not in inner["text"] and "***-**-7891" in inner["text"] and "345-67" not in inner["title"]


# C. Refused


def test_refused_text_stays_only_in_the_open_form(queue):
    out = queue[0]
    assert out["c_form"]["text"] == REFUSED_NOTE and "last four digits" in out["c_form"]["page"] and out["c_saved"] == 0


def test_leaving_the_screen_discards_refused_text(queue):
    assert queue[0]["c_after_leaving"] == ""


def test_no_envelope_holds_refused_text(queue):
    for row in rows(queue[0]["c_inspect"]):
        if row.get("envelope"):
            inner = opened(row)
            assert REFUSED_SENTINEL not in inner["text"] and REFUSED_TITLE_SENTINEL not in (inner["title"] or "")


def test_refused_text_causes_no_write_request(queue):
    assert not [r for r in queue[0]["c_requests"] if r["method"] == "POST"]


def test_refused_text_is_not_sent_even_online(queue):
    out = queue[0]
    assert out["e2_form"]["text"] == REFUSED_NOTE and "last four digits" in out["e2_form"]["page"]
    assert not [r for r in out["e2_requests"] if r["method"] == "POST"]


# D. Expiry


def test_the_warning_shows_from_60_hours(queue):
    assert "will be deleted" in queue[0]["d_warning"]


def test_at_72_hours_the_envelope_is_gone_and_a_notice_stays(queue):
    out = queue[0]
    assert out["d_stopped"] is True
    assert "expired before it could be uploaded. Nothing was sent." in out["d_expired"]
    expired = [r for r in rows(out["d_inspect"]) if r["status"] == "expired"]
    assert len(expired) == 1 and set(expired[0]) == {"id", "owner", "saved_at", "status"}


def test_the_notice_can_be_dismissed(queue):
    assert "expired before" not in queue[0]["d_dismissed"]


# E. Upload


def test_after_upload_the_status_is_uploaded_and_the_envelopes_are_gone(queue):
    out = queue[0]
    assert "Uploaded" in out["e_home"] and "Saved on device" not in out["e_home"]
    assert all("envelope" not in r for r in rows(out["e_inspect"]))
    assert all(r["status"] == "uploaded" and r["ref"] for r in rows(out["e_inspect"]))


def test_uploaded_rows_link_to_the_server_screens(queue):
    out = queue[0]
    for row in rows(out["e_inspect"]):
        assert row["ref"] in out["e_html"]


def test_uploads_send_only_the_envelope_with_the_key_made_at_save(queue):
    out = queue[0]
    posts = [r for r in out["e_requests"] if r["method"] == "POST" and r["url"].endswith("/notes/sealed")]
    saved_keys = {r["idempotency_key"] for r in rows(out["b_inspect"]) if r.get("envelope")}
    assert len(posts) == 2
    for p in posts:
        assert set(json.loads(p["postData"])) == {"kind", "saved_at", "envelope"} and p["status"] == 200
    assert {r["id"] for r in rows(out["e_inspect"])} == saved_keys


def test_the_server_has_exactly_the_uploaded_notes(queue):
    out = queue[0]
    assert len(out["e_drafts"]) + len(out["e_held"]) == 2
    assert FULL_SSN not in json.dumps(out["e_drafts"])


# F. A failed upload


def test_a_failed_upload_is_saved_as_an_envelope(queue):
    out = queue[0]
    assert out["f_home"]["pill"] == "Offline" and "Saved on device" in out["f_home"]["text"]
    row = next(r for r in rows(out["f_inspect"]) if r.get("envelope"))
    assert FAILED_SENTINEL in opened(row)["text"]


def test_the_failed_attempt_used_the_same_key(queue):
    out = queue[0]
    row = next(r for r in rows(out["f_inspect"]) if r.get("envelope"))
    attempts = [r for r in out["f_requests"] if r["method"] == "POST" and r["url"].endswith("/notes/sealed")]
    assert len(attempts) == 1 and attempts[0]["headers"]["Idempotency-Key"] == row["idempotency_key"]
    assert json.loads(attempts[0]["postData"])["envelope"] == row["envelope"]


# G. Sign-out warns


def test_sign_out_warns_about_unsent_notes(queue):
    words = queue[0]["g_warning"]
    assert "1 note" in words and "deleted from this device" in words and "Upload my notes first" in words


def test_the_warning_can_upload_first(queue):
    out = queue[0]
    assert [r["status"] for r in out["g_requests"] if r["method"] == "POST" and r["url"].endswith("/notes/sealed")] == [200]
    assert all("envelope" not in r for r in rows(out["g_inspect"]))


# H. Sign-out while offline


def test_offline_sign_out_warns_first(queue):
    assert "needs a connection" in queue[0]["h_warning"] and "deleted from this device" in queue[0]["h_warning"]


def test_offline_sign_out_wipes_the_device_immediately(queue):
    out = queue[0]
    assert out["h_stopped"] is True
    assert rows(out["h_inspect"]) == []
    m = meta(out["h_inspect"])
    assert "profile" not in m and "setup" not in m and m["pending_sign_out"]
    assert "Signing in needs a connection" in out["h_after"]


# I. The sign-out goes first


def session_requests(requests: list) -> list:
    return [r for r in requests if not r["url"].endswith("/api/v1/ping")]


def test_the_sign_out_request_is_sent_before_any_other(queue):
    requests = session_requests(queue[0]["i_requests"])
    assert requests and requests[0]["url"].endswith("/api/v1/auth/sign-out-device")
    first_other = next(i for i, r in enumerate(requests) if not r["url"].endswith("/api/v1/auth/sign-out-device"))
    assert requests[first_other - 1].get("status") == 200  # the last sign-out attempt finished first


def test_no_other_request_until_it_completes(queue):
    requests = session_requests(queue[0]["i_requests"])
    done = next(i for i, r in enumerate(requests) if r["url"].endswith("/api/v1/auth/sign-out-device") and r.get("status") == 200)
    assert all(r["url"].endswith("/api/v1/auth/sign-out-device") for r in requests[:done])


def test_the_connection_check_sends_no_session(queue):
    pings = [r for r in queue[0]["all_requests"] if r["url"].endswith("/api/v1/ping") and r.get("status")]
    assert pings and all(r["sentCookie"] is False for r in pings)


def test_the_sign_out_request_carries_the_session_it_ends(queue):
    done = [r for r in queue[0]["i_requests"] if r["url"].endswith("/api/v1/auth/sign-out-device") and r.get("status") == 200]
    assert len(done) == 1 and done[0]["sentCookie"] is True


def test_nobody_can_sign_in_while_the_sign_out_is_unfinished(queue):
    out = queue[0]
    assert out["i_blocked_form"] is False and "finishing" in out["i_blocked_text"]
    assert out["i_blocked_flag"] is True and out["i_blocked_session"] == 200


def test_the_old_session_really_ended(queue):
    out = queue[0]
    assert out["i_old_session"] == 401 and "pending_sign_out" not in meta(out["i_inspect"])


def test_the_next_worker_signs_in_with_their_own_session(queue):
    out = queue[0]
    assert out["i_chen_session"]["username"] == "m.chen" and meta(out["i_chen_inspect"])["profile"]["username"] == "m.chen"
    assert "another account" not in out["i_chen_home"]  # the first worker's notes were wiped


# J. Timed-out sessions and shared devices


def test_a_timed_out_session_keeps_the_envelope(queue):
    out = queue[0]
    assert "Sign in" in out["j_timed_out_text"]
    (row,) = [r for r in rows(out["j_timed_out_inspect"]) if r.get("envelope")]
    assert row["owner"] == "j.alvarez" and SHARED_SENTINEL in opened(row)["text"]


def test_another_account_sees_only_that_a_note_is_waiting(queue):
    out = queue[0]
    assert "1 note from another account is waiting on this device" in out["j_chen_text"]
    for shown in (out["j_chen_text"], out["j_chen_html"]):
        assert "Note saved" not in shown and "Saved on device" not in shown and "upload-all" not in shown


def test_the_server_refuses_it_too(queue):
    f = queue[0]["j_forced"]
    assert f["status"] == 422 and f["code"] == "sealed_unreadable" and f["drafts"] == []


def test_another_accounts_sign_out_leaves_the_owners_note(queue):
    out = queue[0]
    (row,) = [r for r in rows(out["j_after_chen_inspect"]) if r.get("envelope")]
    assert row["owner"] == "j.alvarez"


def test_the_owner_can_still_upload_it(queue):
    out = queue[0]
    assert "Uploaded" in out["j_owner_text"] and all("envelope" not in r for r in rows(out["j_owner_inspect"]))
