"""add-web-application, Stage 4c: the device queue's rules, and how the screens show it.

The rules run in Node with real WebCrypto, a fake clock, and an in-memory store (tests/queue_check.mjs);
the screens render with the same code the browser runs. The real browser is in
tests/test_offline_queue_browser.py. Plan: design.md section 5a. Synthetic data only.
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest

from .conftest import REPO_ROOT
from .test_web_screens import buttons, node, render, text_of

CASES = [
    "save_keeps_only_the_envelope_and_clear_metadata", "the_key_is_made_at_save_and_never_changes", "the_four_status_words",
    "a_new_note_shows_time_and_status_only", "uploading_shows_while_the_upload_runs", "uploaded_deletes_the_envelope",
    "a_failed_upload_stays_saved", "a_refused_note_needs_attention_and_keeps_its_envelope", "an_expired_session_keeps_the_envelope_and_stops",
    "one_upload_at_a_time_per_note", "a_note_left_uploading_is_recovered", "no_warning_before_60_hours", "a_warning_from_60_hours",
    "not_expired_before_72_hours", "expired_at_72_hours_leaves_a_notice_with_no_content", "a_notice_stays_until_dismissed",
    "only_the_owner_can_dismiss", "expiry_covers_every_account", "an_uploaded_row_goes_when_opened", "an_uploaded_row_goes_after_the_queue_limit",
    "another_account_sees_only_a_count", "another_accounts_uploaded_and_expired_rows_are_not_counted", "upload_all_sends_only_the_owners_notes",
    "a_note_needing_attention_is_not_retried_by_upload_all", "unsent_counts_saved_and_attention", "classify_each_answer",
    "writing_is_allowed_up_to_the_limit", "gate_with_nothing_pending_sends_nothing", "gate_clears_only_after_the_server_answers",
    "gate_keeps_the_flag_when_the_request_fails", "gate_keeps_the_flag_when_the_server_refuses", "gate_runs_one_request_at_a_time",
    "gate_can_be_retried_after_a_failure",
    "sync_uploads_when_the_connection_returns", "sync_does_nothing_while_not_ready", "backoff_doubles_to_a_cap", "backoff_has_jitter_and_never_passes_the_cap",
    "a_failure_waits_before_the_next_try", "success_clears_the_backoff", "the_connection_returning_skips_the_backoff", "the_manual_button_skips_the_backoff",
    "retry_after_is_never_cut_short", "a_long_retry_after_outlasts_the_backoff_cap", "backoff_is_shared_between_tabs", "only_one_timer_at_a_time",
    "another_tab_holding_the_lock_means_no_attempt", "no_second_run_inside_one_tab", "an_expired_session_stops_until_resumed", "a_failed_direct_send_starts_the_backoff",
    "retry_after_in_seconds_or_a_date", "classify_carries_retry_after", "a_conflict_still_running_waits", "a_real_conflict_needs_attention_in_plain_words",
    "only_reasons_with_a_code_are_shown", "try_again_is_offered_only_where_the_cause_can_change", "try_again_resends_the_same_envelope_and_key",
    "try_again_is_refused_where_it_cannot_help", "try_again_belongs_to_the_owner", "delete_removes_a_refused_note", "delete_is_only_for_refused_notes",
    "wait_carries_retry_after_to_the_scheduler", "a_note_added_during_a_run_is_picked_up", "progress_is_reported", "offline_checks_slow_down_to_a_cap",
    "offline_checks_are_limited_per_minute", "a_long_offline_stretch_stays_under_the_limit",
]


@pytest.fixture(scope="module")
def results() -> dict:
    plan = {"web": (REPO_ROOT / "ui" / "web").as_posix()}
    run = subprocess.run([node(), str(REPO_ROOT / "tests" / "queue_check.mjs")], input=json.dumps(plan), text=True, encoding="utf-8",
                         capture_output=True, check=False, timeout=120)
    assert run.returncode == 0, run.stderr[-3000:]
    return json.loads(run.stdout)


def test_every_case_is_listed(results):
    assert set(results) == set(CASES)


@pytest.mark.parametrize("name", CASES)
def test_queue_rule(results, name):
    assert results[name] == "ok", results[name]


# The screens


SAVED_AT = "2026-11-09T15:31:00.000Z"
NOW = "2026-11-09T16:00:00.000Z"


def note(**changes) -> dict:
    return {"id": "6f1c2a70-0001", "status": "saved", "label": "Saved on device", "saved_at": SAVED_AT, "warning": False,
            "hours_left": 71, "reason": None, "ref": None, "can_retry": False, **changes}


def view(**changes) -> dict:
    return {"mine": [], "notices": [], "others": 0, "unsent": 0, "uploadable": 0, "uploading": 0, "needsAttention": 0, "now": NOW, **changes}


USER = {"display_name": "Jordan Alvarez"}


@pytest.fixture
def screens(tmp_path):
    return render(tmp_path, {
        "saved": ("deviceNotes", [view(mine=[note()], unsent=1, uploadable=1), {"online": True}]),
        "saved_offline": ("deviceNotes", [view(mine=[note()], unsent=1, uploadable=1), {"online": False}]),
        "other_day": ("deviceNotes", [view(mine=[note()], unsent=1, now="2026-11-12T16:00:00.000Z"), {"online": True}]),
        "warning": ("deviceNotes", [view(mine=[note(warning=True, hours_left=9)], unsent=1), {"online": False}]),
        "attention": ("deviceNotes", [view(mine=[note(status="attention", label="Needs attention", reason="A fixed <reason>.")], unsent=1), {"online": True}]),
        "uploading": ("deviceNotes", [view(mine=[note(status="uploading", label="Uploading")], unsent=1), {"online": True}]),
        "uploaded": ("deviceNotes", [view(mine=[note(status="uploaded", label="Uploaded", ref="ENC-2026-11-09-0001")]), {"online": True}]),
        "uploaded_held": ("deviceNotes", [view(mine=[note(status="uploaded", label="Uploaded", ref="INT-0001")]), {"online": True}]),
        "tombstone": ("deviceNotes", [view(notices=[{"id": "x1", "saved_at": SAVED_AT}]), {"online": False}]),
        "one_other": ("deviceNotes", [view(others=1), {"online": True}]),
        "two_others": ("deviceNotes", [view(others=2), {"online": True}]),
        "empty": ("deviceNotes", [view(), {"online": True}]),
        "warn_online": ("signOutWarning", [{"count": 2, "online": True}]),
        "warn_offline": ("signOutWarning", [{"count": 1, "online": False}]),
        "finishing": ("finishingSignOut", []),
        "attention_final": ("deviceNotes", [view(mine=[note(status="attention", label="Needs attention", reason="A reason.")], unsent=1), {"online": True}]),
        "attention_retry": ("deviceNotes", [view(mine=[note(status="attention", label="Needs attention", reason="A reason.", can_retry=True)], unsent=1), {"online": True}]),
        "attention_offline": ("deviceNotes", [view(mine=[note(status="attention", label="Needs attention", reason="A reason.", can_retry=True)], unsent=1), {"online": False}]),
        "delete_warning": ("deleteNoteWarning", [{"id": "6f1c2a70-0001"}]),
        "sign_in_prompt": ("signIn", [{"uploadCount": 2}]),
        "sign_in_prompt_one": ("signIn", [{"uploadCount": 1}]),
        "sign_in_plain": ("signIn", [{}]),
        "form_online": ("noteForm", [{"kind": "new"}]),
        "form_offline": ("noteForm", [{"kind": "new", "online": False}]),
        "form_masked": ("noteForm", [{"kind": "new", "online": False, "text": "SSN ***-**-7891", "notice": "A notice."}]),
        "form_blocked": ("noteForm", [{"kind": "new", "online": False, "blocked": "A blocked reason."}]),
        "home": ("home", [{"user": USER, "device": view(mine=[note()], unsent=1, uploadable=1)}]),
        "offline_home": ("offlineHome", [{"user": USER, "device": view(mine=[note()], unsent=1, uploadable=1)}]),
    })


def test_a_saved_note_shows_time_and_status_only(screens):
    words = " ".join(text_of(screens["saved"]).split())
    assert re.search(r"Note saved \d{1,2}:\d\d (AM|PM)", words) and "Saved on device" in words
    assert "New client" not in words and "Visit" not in words


def test_a_note_from_another_day_shows_the_date(screens):
    assert re.search(r"Note saved Nov \d{1,2}, \d{1,2}:\d\d (AM|PM)", " ".join(text_of(screens["other_day"]).split()))


def test_a_warning_says_how_long_is_left(screens):
    words = " ".join(text_of(screens["warning"]).split())
    assert "9 hours" in words and "will be deleted" in words


def test_needs_attention_shows_the_reason_escaped(screens):
    assert "A fixed &lt;reason&gt;." in screens["attention"] and "Needs attention" in text_of(screens["attention"])


def test_uploading_has_its_word(screens):
    assert "Uploading" in text_of(screens["uploading"])


def test_uploaded_links_to_the_review_or_the_held_note(screens):
    assert 'href="#/drafts/ENC-2026-11-09-0001"' in screens["uploaded"] and 'href="#/held/INT-0001"' in screens["uploaded_held"]
    assert "not in HMIS" in " ".join(text_of(screens["uploaded"]).split())


def test_the_tombstone_says_nothing_was_sent(screens):
    words = " ".join(text_of(screens["tombstone"]).split())
    assert re.search(r"A note saved Nov \d{1,2} expired before it could be uploaded\. Nothing was sent\.", words)
    assert 'data-action="dismiss"' in screens["tombstone"] and "data-local" in screens["tombstone"]


def test_another_account_gets_one_line_with_no_time_or_kind(screens):
    one, two = " ".join(text_of(screens["one_other"]).split()), " ".join(text_of(screens["two_others"]).split())
    assert "1 note from another account is waiting on this device" in one
    assert "2 notes from another account are waiting on this device" in two
    for words in (one, two):
        assert "Note saved" not in words and "New client" not in words and not re.search(r"\d:\d\d", words)
    assert "upload-all" not in screens["one_other"]


def test_upload_is_offered_only_online(screens):
    assert 'data-action="upload-all"' in screens["saved"] and 'data-action="upload-all"' not in screens["saved_offline"]


def test_nothing_shows_when_the_queue_is_empty(screens):
    assert screens["empty"].strip() == ""


def test_the_sign_out_warning_online_offers_upload(screens):
    page = screens["warn_online"]
    words = " ".join(text_of(page).split())
    assert "2 notes" in words and "deleted from this device" in words
    assert 'data-action="upload-all"' in page and 'data-action="sign-out-wipe"' in page and 'href="#/"' in page


def test_the_sign_out_warning_offline_says_upload_needs_a_connection(screens):
    page = screens["warn_offline"]
    words = " ".join(text_of(page).split())
    assert "1 note " in words and "needs a connection" in words
    assert 'data-action="upload-all"' not in page and 'data-action="sign-out-wipe"' in page


def test_the_sign_out_buttons_say_what_they_do(screens):
    for name in ("warn_online", "warn_offline"):
        for label in buttons(screens[name]):
            assert len(label.split()) >= 2, label


def test_finishing_a_sign_out_has_no_sign_in_form(screens):
    assert "form" not in screens["finishing"] and "finishing" in text_of(screens["finishing"])


@pytest.mark.parametrize("name", ["form_online", "form_offline"])
def test_note_fields_turn_off_browser_memory(screens, name):
    page = screens[name]
    assert re.search(r'<form[^>]*autocomplete="off"', page)
    for field in (r'<input id="note-title"[^>]*', r'<textarea id="note-text"[^>]*'):
        tag = re.search(field, page).group(0)
        assert 'autocomplete="off"' in tag and 'spellcheck="false"' in tag


def test_the_button_says_what_happens(screens):
    assert "Draft my note" in buttons(screens["form_online"])
    assert "Save on this device" in buttons(screens["form_offline"])


def test_the_masked_form_shows_the_masked_text_and_a_notice(screens):
    assert "SSN ***-**-7891" in screens["form_masked"] and "A notice." in screens["form_masked"]


def test_a_blocked_form_cannot_be_submitted(screens):
    page = screens["form_blocked"]
    assert "A blocked reason." in page and re.search(r'<button type="submit"[^>]*disabled', page)


def test_a_final_refusal_offers_only_delete(screens):
    page = screens["attention_final"]
    assert 'data-action="retry-note"' not in page and 'href="#/device/6f1c2a70-0001/delete"' in page


def test_a_changeable_refusal_offers_try_again(screens):
    assert 'data-action="retry-note" data-ref="6f1c2a70-0001"' in screens["attention_retry"]


def test_try_again_needs_a_connection(screens):
    assert 'data-action="retry-note"' not in screens["attention_offline"] and "/delete" in screens["attention_offline"]


def test_the_delete_warning_says_it_must_be_written_again(screens):
    page = screens["delete_warning"]
    words = " ".join(text_of(page).split())
    assert "cannot be read" in words and "write it again" in words and "never reached" in words
    assert 'data-action="discard-note" data-ref="6f1c2a70-0001" data-local="1"' in page and 'href="#/"' in page
    for label in buttons(page):
        assert len(label.split()) >= 2, label


def test_the_sign_in_prompt_gives_the_count(screens):
    assert "Sign in to upload your 2 saved notes" in text_of(screens["sign_in_prompt"])
    assert "Sign in to upload your 1 saved note" in text_of(screens["sign_in_prompt_one"]) and "1 saved notes" not in text_of(screens["sign_in_prompt_one"])
    assert "Sign in to upload" not in text_of(screens["sign_in_plain"])


def test_the_saved_notes_have_a_place_that_can_be_refreshed(screens):
    assert 'id="device-notes"' in screens["home"] and 'id="device-notes"' in screens["offline_home"]


@pytest.mark.parametrize("name", ["home", "offline_home"])
def test_my_notes_shows_saved_notes(screens, name):
    words = " ".join(text_of(screens[name]).split())
    assert "Saved on this device" in words and "Saved on device" in words
