"""Task 5.2: the staff screens (parser run, mapped draft, staged record, submitted record and audit).

The mapped draft, staged record and audit screens read routes the phone tests already cover
(/drafts/{id}/review, /drafts/{id}, /drafts/{id}/audit). This file covers the parser run route
and the staff page itself.
"""

from __future__ import annotations

import re

import pytest

from app.api import UI_DIR
from app.config_loader import load_config
from app.staff import instructions
from parser.llm_v2 import PROMPT_VERSION

from .test_review_ui import WORKER, latest_review, phone, scenario, send, start  # noqa: F401  (phone is a fixture)

CONFIG = load_config()


def run(api, ref):
    out = api.get(f"/staff/drafts/{ref}/run")
    assert out.status_code == 200, out.text
    return out.json()


def test_staff_page_is_served_and_writes_no_html():
    for name in ("staff.html", "staff.js", "staff.css", "common.js"):
        assert (UI_DIR / name).exists()
    for script in ("common.js", "app.js", "staff.js"):
        text = (UI_DIR / script).read_text(encoding="utf-8")
        assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", text), script


def test_parser_run_for_scenario_a(phone):
    ref = start(phone, "A")["ref"]
    r = run(phone, ref)
    assert r["parser"] == "rule_stub" and r["model"] is None and not r["scripted"]
    assert r["instructions"]["title"].startswith("Rule-based stub")
    assert r["elapsed_seconds"] is not None and r["attempts"] == 1
    rows = {f["name"]: f for f in r["output"]}
    assert rows["date_of_birth"]["value"] == "03/04/1975" and "DOB 3/4/1975" in rows["date_of_birth"]["source"]
    assert not any(f["scripted"] for f in r["output"])
    assert r["note"].startswith("Met Pat Example") and r["case_note"]


def test_parser_run_marks_the_scripted_error_and_keeps_it_after_correction(phone):
    ref = start(phone, "B")["ref"]
    v1 = latest_review(phone)
    send(phone, f"Re: {v1['subject']}", scenario(phone, "B")["suggested_reply"])
    r = run(phone, ref)
    assert r["scripted"] and r["instructions"]["title"].startswith("Scripted demo parser")
    rows = {f["name"]: f for f in r["output"]}
    # The run shows what the parser produced (v1), not the worker's correction.
    assert rows["current_living_situation"]["value"] == "Emergency shelter" and rows["current_living_situation"]["scripted"]
    assert [n for n, f in rows.items() if f["scripted"]] == ["current_living_situation"]
    assert "veteran_status" not in rows


def test_note_is_shown_cleaned_and_not_at_all_after_purge(phone):
    body = (
        "Met Alex Demo at the camp behind the Example St and Sample Ave overpass, SW quadrant. DOB 1/15/1969. "
        "Searched HMIS, no hits. His friend Jordan was with him and has a warrant, so keep an eye out. "
        "SSN 123-45-6789. Male, white, not Hispanic.")
    ref = send(phone, "New client: Alex Demo 10/7", body)["ref"]
    r = run(phone, ref)
    note = r["note"]
    assert "123-45" not in note and "***-**-6789" in note
    assert "Example St" not in note and "overpass" not in note
    assert "Jordan" not in note and "warrant" not in note
    assert "masked" in r["note_status"]

    phone.intake.store.schedule_email_deletion(ref, phone.intake.clock())
    phone.post("/maintenance/purge-emails")
    r = run(phone, ref)
    assert r["note"] is None and "deleted under the retention rule" in r["note_status"]
    assert r["output"]  # the verified output stays with the draft


def test_instructions_follow_the_parser_that_made_the_draft(phone):
    ref = start(phone, "A")["ref"]
    draft = phone.intake.draft(ref)
    reallms = instructions(draft.model_copy(update={"parser": "reallms:gemma-4-31B-it", "prompt_version": PROMPT_VERSION}), CONFIG)
    assert reallms["title"] == f"REALLMS prompt {PROMPT_VERSION}"
    assert "[the worker's note is inserted here, unchanged]" in reallms["text"] and "{note}" not in reallms["text"]
    assert "Searched HMIS first, no match. Slept outside last night." not in reallms["text"]  # the draft's own note


def test_unknown_draft_is_404(phone):
    assert phone.get("/staff/drafts/ENC-2026-01-01-9999/run").status_code == 404


def test_run_route_never_calls_hmis(phone, monkeypatch):
    ref = start(phone, "A")["ref"]
    monkeypatch.setattr(phone.intake.service.gateway, "_http", None)
    assert phone.get(f"/staff/drafts/{ref}/run").status_code == 200
    for path in (f"/drafts/{ref}", f"/drafts/{ref}/review", f"/drafts/{ref}/audit"):
        assert phone.get(path).status_code == 200


def test_run_holds_no_key(phone, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key-do-not-log-0123456789")
    ref = start(phone, "B")["ref"]
    assert "test-key-do-not-log" not in phone.get(f"/staff/drafts/{ref}/run").text


@pytest.mark.parametrize("path", ["/ui/staff.html", "/ui/staff.js", "/ui/common.js"])
def test_staff_files_are_served(phone, path):
    assert phone.get(path).status_code == 200


def test_submitted_record_marks_worker_fields_and_has_the_audit_trail(phone):
    ref = start(phone, "B")["ref"]
    send(phone, f"Re: {latest_review(phone)['subject']}", scenario(phone, "B")["suggested_reply"])
    send(phone, f"Re: {latest_review(phone)['subject']}", "CONFIRM")
    rows = {r["column"]: r for r in phone.get(f"/drafts/{ref}").json()["rows"]}
    assert rows["current_living_situation"]["confidence"] == "worker"
    assert rows["veteran_status"]["confidence"] == "worker"
    assert rows["first_name"]["confidence"] == "high"
    audit = phone.get(f"/drafts/{ref}/audit").json()
    events = [e["event"] for e in audit["events"]]
    for event in ("draft_created", "review_sent", "corrections_applied", "confirmed", "entry_step", "submitted",
                  "email_copies_deleted"):
        assert event in events
    assert all(audit["hmis_ids"].values())
    note = scenario(phone, "B")["body"]
    assert note[:40] not in str(audit)
