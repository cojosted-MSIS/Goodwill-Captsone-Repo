"""add-web-application, Stage 2b: the email channel is off by default, and the core takes a
channel-neutral Note.

Specs: openspec/changes/add-web-application/specs/web-application/spec.md ("Keep email as an
optional channel, off by default", "Use the same core for every use case"). Synthetic data only.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.api import build_service, create_app
from app.config_loader import load_config, with_email_channel
from app.email_message import IntakeEmail
from app.note import Note
from parser.rule_stub import RuleStubParser

from .conftest import REPO_ROOT, SAMPLE_EMAIL_DIR

WORKER = "j.alvarez@goodwill-outreach.example"
WHEN = datetime(2026, 10, 7, 10, 31, tzinfo=timezone(timedelta(hours=-4)))
NOTE = ("Met Kim Placeholder, DOB 1/2/1990, NW quadrant around 10:15am. Searched HMIS first, no match. Slept outside "
        "last night. Has been staying outside for over a year. Male, white, not Hispanic. Not a veteran. SSN ends 4821. "
        "Enroll in street outreach, CE region 7. Single adult. Gave water.")


# The email channel flag


def test_the_email_channel_is_off_in_the_shipped_configuration():
    assert load_config().settings.channels.email.enabled is False


def test_with_email_off_an_email_is_dropped_and_nothing_is_kept(intake):
    intake.service.config = with_email_channel(intake.config, False)
    out = intake.receive_text(NOTE)
    assert out.action == "dropped"
    assert intake.store.drafts() == [] and intake.store.emails() == []
    assert [e["event"] for e in intake.store.audit_events("inbox")] == ["dropped_email_channel_off"]


def test_with_email_off_the_email_routes_are_not_served(intake):
    intake.service.config = with_email_channel(intake.config, False)
    api = TestClient(create_app(intake.service, users=None))
    raw = (SAMPLE_EMAIL_DIR / "01b_clean_new_client_complete.txt").read_text(encoding="utf-8")
    assert api.post("/inbox", json={"raw": raw}).status_code == 404
    assert api.post("/mail/send", json={"sender": WORKER, "subject": "New client", "body": NOTE}).status_code == 404
    assert api.get(f"/mail/inbox/{WORKER}").status_code == 404
    assert api.get("/drafts/ENC-2026-10-07-0001").status_code == 404  # the unauthenticated demo views too
    assert api.get("/api/v1/auth/csrf").status_code == 200
    assert intake.store.drafts() == []


def test_the_email_demo_and_the_email_tests_switch_it_on(intake):
    assert intake.config.settings.channels.email.enabled is True  # tests/conftest.py, Intake
    assert build_service(db_path=":memory:", email_channel=True).config.settings.channels.email.enabled is True
    assert build_service(db_path=":memory:").config.settings.channels.email.enabled is False
    servers = (REPO_ROOT / "scripts" / "servers.py").read_text(encoding="utf-8")
    assert "--email-channel" in servers


# The channel-neutral note


def test_the_core_imports_nothing_from_the_email_message_module():
    tree = ast.parse((REPO_ROOT / "app" / "core.py").read_text(encoding="utf-8"))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "email_message" not in modules and "app.email_message" not in modules


def test_the_email_adapter_converts_an_email_to_a_note():
    email = IntakeEmail(sender=WORKER, recipient="outreach-intake@goodwill-secure.example", subject="New client: Kim",
                        sent_at=WHEN, body=NOTE)
    assert email.to_note() == Note(author=WORKER, title="New client: Kim", written_at=WHEN, text=NOTE, channel="email")


def test_the_parser_reads_a_note_and_an_email_the_same_way():
    config = load_config()
    parser = RuleStubParser(config)
    email = IntakeEmail(sender=WORKER, recipient="x", subject="New client: Kim", sent_at=WHEN, body=NOTE)
    from_email = parser.parse(email)
    from_note = parser.parse(email.to_note())
    assert from_note.fields == from_email.fields and from_note.case_note == from_email.case_note


def test_a_web_note_and_an_email_note_make_the_same_draft(intake):
    worker = intake.config.workers.worker_for(WORKER)
    web_ref = intake.service.new_client(Note(author=WORKER, title="New client: Kim", written_at=WHEN, text=NOTE), worker).ref
    email_ref = intake.receive_text(NOTE, subject="New client: Kim").ref
    web, email = intake.draft(web_ref), intake.draft(email_ref)
    assert {n: f.value for n, f in web.fields.items()} == {n: f.value for n, f in email.fields.items()}
