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
            "hours_left": 71, "reason": None, "ref": None, **changes}


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


@pytest.mark.parametrize("name", ["home", "offline_home"])
def test_my_notes_shows_saved_notes(screens, name):
    words = " ".join(text_of(screens[name]).split())
    assert "Saved on this device" in words and "Saved on device" in words
