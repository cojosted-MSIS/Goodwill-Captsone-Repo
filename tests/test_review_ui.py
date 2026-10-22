"""Task 5, stage 1: the phone screens' routes (compose, inbox, review email, reply, receipt).

Scenario A is the clean note confirmed on the first reply (mockups A1, A5). Scenario B is
the scripted parser error the worker corrects (B1, B5 to B7). Every worker action goes
through /mail/send, the same workflow as the intake inbox.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.api import UI_DIR, create_app, demo_parser
from app.config_loader import ConfigError, load_config
from app.demo import load_scenarios
from parser.rule_stub import RuleStubParser

from .conftest import Intake

WORKER = "j.alvarez@goodwill-outreach.example"
CONFIG = load_config()


@pytest.fixture
def phone(hmis):
    intake = Intake(hmis, parser=demo_parser(CONFIG, RuleStubParser(CONFIG)))
    api = TestClient(create_app(intake.service))
    api.intake = intake
    return api


def scenario(api, sid):
    return next(s for s in api.get("/demo/scenarios").json() if s["id"] == sid)


def send(api, subject, body):
    out = api.post("/mail/send", json={"sender": WORKER, "subject": subject, "body": body})
    assert out.status_code == 200, out.text
    return out.json()


def start(api, sid):
    s = scenario(api, sid)
    return send(api, s["subject"], s["body"])


def latest_review(api):
    mail = next(m for m in api.get(f"/mail/inbox/{WORKER}").json() if m["kind"] == "review")
    return api.get(f"/mail/message/{mail['id']}").json()


def all_rows(review):
    return {f["name"]: f for s in review["sections"] for f in s["fields"] + s["collapsed"]}


# Screen 0 and 1: home and compose


def test_ui_is_served_and_home_redirects(phone):
    assert phone.get("/", follow_redirects=False).headers["location"] == "/ui/"
    page = phone.get("/ui/")
    assert page.status_code == 200 and "app.js" in page.text
    assert phone.get("/ui/app.js").status_code == 200 and phone.get("/ui/style.css").status_code == 200


def test_scenarios_prefill_the_compose_screen(phone):
    a, b = scenario(phone, "A"), scenario(phone, "B")
    assert a["sender"] == b["sender"] == WORKER
    assert not a["scripted"] and a["scripted_label"] is None
    assert b["scripted"] and "Scripted demo example" in b["scripted_label"]
    assert "not a live model result" in b["scripted_label"]


def test_scripted_error_must_quote_the_note(tmp_path):
    (tmp_path / "note.txt").write_text(
        "From: j.alvarez@goodwill-outreach.example\nTo: outreach-intake@goodwill-secure.example\n"
        "Subject: New client\nDate: Fri, 09 Oct 2026 14:42:00 -0400\n\nMet Jo Sample.\n", encoding="utf-8")
    (tmp_path / "s.yaml").write_text(
        "X:\n  title: t\n  summary: s\n  email: note.txt\n  scripted:\n    label: l\n    fields:\n"
        "      current_living_situation: {value: emergency_shelter, source: not in the note, confidence: high}\n",
        encoding="utf-8")
    with pytest.raises(ConfigError, match="not in the note"):
        load_scenarios(CONFIG, tmp_path / "s.yaml")


# Scenario A: screens 2, 3 and 5


def test_scenario_a_clean_note_to_receipt(phone):
    out = start(phone, "A")
    assert out["action"] == "drafted"
    inbox = phone.get(f"/mail/inbox/{WORKER}").json()
    assert inbox[0]["kind"] == "review" and inbox[0]["current"] and inbox[0]["version"] == 1

    mail = latest_review(phone)
    r = mail["review"]
    assert mail["current"] and r["confirm_allowed"] and r["missing"] == [] and r["confirm_blocked_reason"] is None
    assert not r["revised"] and r["scripted_label"] is None and r["parser"] == "rule_stub"
    assert "Nothing has been sent to HMIS" in r["footer"]
    dob = all_rows(r)["date_of_birth"]
    assert dob["value"] == "03/04/1975" and dob["origin_label"] == "from your note" and "3/4/1975" in dob["source"]
    assert all_rows(r)["ssn_last4"]["value"] == "***-**-4821"
    assert r["case_note"]

    assert phone.get(f"/drafts/{out['ref']}/receipt").status_code == 409  # not submitted yet
    confirmed = send(phone, f"Re: {mail['subject']}", "CONFIRM")
    assert confirmed == {"action": "submitted", "ref": out["ref"]}
    receipt = phone.get(f"/drafts/{out['ref']}/receipt").json()
    ids = {i["label"]: i["value"] for i in receipt["hmis_ids"]}
    assert ids["Client ID"].startswith("HMIS-C-") and ids["Program enrollment ID"] and ids["Coordinated Entry enrollment ID"]
    assert receipt["changed_by_worker"] == [] and "never searched HMIS" in receipt["search_note"]
    assert any(m["kind"] == "receipt" for m in phone.get(f"/mail/inbox/{WORKER}").json())


def test_scenario_a_needs_every_field_so_nothing_is_collapsed(phone):
    start(phone, "A")
    r = latest_review(phone)["review"]
    assert all(not s["collapsed"] for s in r["sections"])


def test_collapsed_fields_are_blank_and_unflagged(phone):
    # Staying with family: the homelessness history fields are not needed for this neighbor.
    send(phone, "New client: Jo Sample 10/7", (
        "Met Jo Sample, DOB 5/6/1990, NW quadrant. Searched HMIS, no match. "
        "Staying with her sister for now. Female."))
    r = latest_review(phone)["review"]
    shown = [f for s in r["sections"] for f in s["fields"]]
    collapsed = [f for s in r["sections"] for f in s["collapsed"]]
    assert collapsed, "fields this neighbor does not need are collapsed"
    assert all(f["value"] is None and not f["flags"] for f in collapsed)
    assert all(f["value"] is not None or f["flags"] for f in shown)
    assert "case_note" not in all_rows(r)


# Scenario B: the scripted error, the missing field, the blocked CONFIRM, the correction


def test_scenario_b_shows_the_scripted_error_and_blocks_confirm(phone):
    ref = start(phone, "B")["ref"]
    mail = latest_review(phone)
    r = mail["review"]
    assert r["parser"] == "scripted_demo" and "Scripted demo example" in r["scripted_label"]
    current = all_rows(r)["current_living_situation"]
    assert current["value"] == "Emergency shelter" and current["confidence"] == "high"
    assert current["source"].startswith("Offered her a bed at the women's shelter")
    assert r["missing"] == ["Veteran status"]
    vet = all_rows(r)["veteran_status"]
    assert vet["missing"] and vet["flags"]
    assert not r["confirm_allowed"] and "Veteran status" in r["confirm_blocked_reason"]

    # Typing CONFIRM anyway is refused by the workflow too, and nothing is entered.
    assert send(phone, f"Re: {mail['subject']}", "CONFIRM")["action"] == "still_missing"
    assert phone.intake.draft(ref).state == "in_review" and phone.intake.draft(ref).entry.client_id is None
    assert phone.get(f"/mail/inbox/{WORKER}").json()[0]["kind"] == "missing_info"


def test_scenario_b_correction_then_confirm(phone):
    ref = start(phone, "B")["ref"]
    v1 = latest_review(phone)
    reply = scenario(phone, "B")["suggested_reply"]
    quoted = "\n".join(f"> {line}" for line in v1["body"].splitlines())
    assert send(phone, f"Re: {v1['subject']}", f"{reply}\n\n{quoted}")["action"] == "revised"

    v2 = latest_review(phone)
    r = v2["review"]
    assert r["revised"] and r["version"] == 2 and r["confirm_allowed"] and r["missing"] == []
    current = all_rows(r)["current_living_situation"]
    assert current["value"] == "Place not meant for habitation" and current["origin"] == "worker"
    assert current["origin_label"] == "from your reply"
    assert all_rows(r)["veteran_status"]["value"] == "No"
    assert "women's shelter" not in r["case_note"]  # the case note was rewritten to match

    old = phone.get(f"/mail/message/{v1['id']}").json()
    assert not old["current"] and old["review"] is None and old["draft_version"] == 2

    assert send(phone, f"Re: {v2['subject']}", "CONFIRM")["action"] == "submitted"
    receipt = phone.get(f"/drafts/{ref}/receipt").json()
    assert set(receipt["changed_by_worker"]) == {"Current living situation", "Veteran status"}


def test_an_edited_scenario_note_is_parsed_normally(phone):
    s = scenario(phone, "B")
    send(phone, s["subject"], s["body"] + " Not a veteran.")
    r = latest_review(phone)["review"]
    assert r["parser"] == "rule_stub" and r["scripted_label"] is None
    assert all_rows(r)["current_living_situation"]["value"] == "Place not meant for habitation"


def test_search_not_stated_goes_through_the_phone(phone):
    out = send(phone, "New client: Lee 10/7", (
        "Met Lee Placeholder, DOB 7/2/1991, NW quadrant. Slept outside last night."))
    assert out["action"] == "search_requested"
    mail = phone.get(f"/mail/message/{phone.get(f'/mail/inbox/{WORKER}').json()[0]['id']}").json()
    assert mail["kind"] == "search_request" and mail["review"] is None
    assert send(phone, f"Re: {mail['subject']}", "Searched HMIS, no match.")["action"] == "drafted"


# Safety


def test_unknown_sender_is_dropped(phone):
    out = phone.post("/mail/send", json={"sender": "someone@example.com", "subject": "x", "body": "Met Pat."}).json()
    assert out["action"] == "dropped"


def test_only_outgoing_mail_can_be_opened(phone):
    start(phone, "A")
    incoming = [e for e in phone.intake.store.emails() if e.direction == "in"]
    assert incoming and phone.get(f"/mail/message/{incoming[0].id}").status_code == 404


def test_ui_never_writes_html_from_data():
    script = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", script)


def test_key_never_reaches_the_browser(phone, monkeypatch):
    fake = "test-key-do-not-log-0123456789"
    monkeypatch.setenv("LLM_API_KEY", fake)
    start(phone, "B")
    mail = latest_review(phone)
    responses = [phone.get(p).text for p in ("/ui/", "/ui/app.js", "/demo/scenarios", "/demo/drafts",
                                             f"/mail/inbox/{WORKER}", f"/mail/message/{mail['id']}")]
    assert not any(fake in r or "LLM_API_KEY" in r for r in responses)
    static = " ".join(p.read_text(encoding="utf-8") for p in UI_DIR.iterdir())
    assert "api_key" not in static.lower() and "authorization" not in static.lower()


# Parser selection: the stub by default, REALLMS by flag or INTAKE_PARSER


def test_default_parser_is_the_stub_wrapped_for_the_demo(monkeypatch):
    from app.api import build_service
    from parser.scripted_demo import ScriptedDemoParser

    monkeypatch.delenv("INTAKE_PARSER", raising=False)
    service = build_service(db_path=":memory:")
    assert isinstance(service.parser, ScriptedDemoParser) and service.parser.base.name == "rule_stub"


@pytest.mark.parametrize(("env", "flag", "expected"), [
    ("reallms", None, "reallms"), (None, "reallms", "reallms"), ("reallms", "rule_stub", "rule_stub")])
def test_reallms_is_chosen_by_flag_or_env(monkeypatch, env, flag, expected):
    import app.api as api_module

    chosen = {}

    def fake_build_parser(config, *, model=None, parser=None, **_):
        chosen["parser"], chosen["model"] = parser, model
        return RuleStubParser(config)

    monkeypatch.setattr(api_module, "build_parser", fake_build_parser)
    if env:
        monkeypatch.setenv("INTAKE_PARSER", env)
    else:
        monkeypatch.delenv("INTAKE_PARSER", raising=False)
    api_module.build_service(db_path=":memory:", parser=flag)
    assert chosen["parser"] == expected


def test_unknown_parser_name_is_refused():
    from parser.factory import build_parser

    with pytest.raises(ValueError, match="unknown parser"):
        build_parser(CONFIG, parser="gpt")
