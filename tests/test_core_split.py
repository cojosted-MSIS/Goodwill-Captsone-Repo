"""add-web-application, Stage 2a: the intake core is channel-neutral and the email channel is an adapter.

The core (app/core.py) has one method per worker action and no email parsing; the email
channel (app/email_channel.py) routes emails to those methods. Synthetic data only.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone

from app.core import IntakeCore
from app.email_channel import IntakeService
from app.note import Note

from .conftest import REPO_ROOT, Intake

WORKER = "j.alvarez@goodwill-outreach.example"
NOTE = ("Met Kim Placeholder, DOB 1/2/1990, NW quadrant around 10:15am. Searched HMIS first, no match. Slept outside "
        "last night. Has been staying outside for over a year. Been on the street about 3 times in the last 3 years, "
        "around 14 months total. Started being homeless this time on 8/15/2025. Male, white, not Hispanic. Has a "
        "disabling condition (bad back). Not a veteran. SSN ends 4821. Enroll in street outreach, CE region 7. "
        "Single adult. Gave water and a hygiene kit. Follow up Thursday.")


def core_for(intake: Intake) -> IntakeCore:
    """The core alone, wired like the email service, with no channel."""
    s = intake.service
    return IntakeCore(s.config, s.store, s.parser, s.gateway, clock=s.clock, reader=s.reader)


def note(body: str = NOTE, subject: str = "New client: Kim") -> Note:
    """The core takes a channel-neutral Note (Stage 2b), never an email."""
    return Note(author=WORKER, title=subject, written_at=datetime(2026, 10, 7, 10, 31, tzinfo=timezone(timedelta(hours=-4))),
                text=body)


def test_email_service_is_the_core_plus_the_email_channel():
    assert issubclass(IntakeService, IntakeCore)
    actions = ("new_client", "update", "ask", "confirm_search", "pick_client", "confirm", "retry", "correct",
               "same_client", "different_person")
    assert all(callable(getattr(IntakeCore, a)) for a in actions)
    assert not hasattr(IntakeCore, "receive")  # routing an email is the channel's job


def test_core_imports_nothing_email_specific():
    tree = ast.parse((REPO_ROOT / "app" / "core.py").read_text(encoding="utf-8"))
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert not names & {"compose_review", "compose_verification", "parse_token", "reply_text",
                        "is_query_subject", "is_update_subject", "review_subject"}


def test_core_runs_the_whole_flow_without_a_channel(intake):
    core = core_for(intake)
    worker = intake.config.workers.worker_for(WORKER)
    out = core.new_client(note(), worker)
    draft = core.store.get_draft(out.ref)
    assert out.action == "drafted" and draft.state == "in_review"
    assert core.store.emails(ref=out.ref, kind="review") == []  # no review email: a screen reads the draft
    assert core.confirm(out.ref, WORKER, worker, version=1).action == "submitted"
    assert core.store.get_draft(out.ref).entry.client_id == "HMIS-C-000001"


def test_core_refuses_a_confirmation_from_someone_else(intake):
    core = core_for(intake)
    worker = intake.config.workers.worker_for(WORKER)
    ref = core.new_client(note(), worker).ref
    other = intake.config.workers.worker_for("m.chen@goodwill-outreach.example")
    assert core.confirm(ref, "m.chen@goodwill-outreach.example", other, version=1).action == "ignored"
    assert core.store.get_draft(ref).state == "in_review"


def test_core_corrects_and_records_only_the_workers_words(intake):
    core = core_for(intake)
    worker = intake.config.workers.worker_for(WORKER)
    ref = core.new_client(note(), worker).ref
    out = core.correct(ref, WORKER, worker, note("It was the second time on the street, not the third."))
    assert out.action == "revised" and core.store.get_draft(ref).version == 2
    assert [e.body for e in core.store.emails(ref=ref, kind="correction")] == [
        "It was the second time on the street, not the third."]


def test_retry_does_nothing_while_in_review(intake):
    core = core_for(intake)
    worker = intake.config.workers.worker_for(WORKER)
    ref = core.new_client(note(), worker).ref
    assert core.retry(ref, WORKER, worker).action == "not_failed"
    assert core.store.get_draft(ref).state == "in_review"


def test_email_reply_keeps_only_the_words_above_the_quote_as_a_correction(intake):
    ref = intake.receive_text(NOTE).ref
    intake.reply(ref, "It was the second time on the street, not the third.")
    corrections = [e.body for e in intake.store.emails(ref=ref, kind="correction")]
    assert corrections == ["It was the second time on the street, not the third."]  # the quoted text is not kept here
    assert any("> earlier message quoted here" in e.body for e in intake.store.emails(ref=ref, kind="reply"))


def test_same_name_actions_wait_for_an_open_verification(intake):
    core = core_for(intake)
    worker = intake.config.workers.worker_for(WORKER)
    ref = core.new_client(note(), worker).ref  # no same-name match for Kim Placeholder
    assert core.same_client(ref, WORKER, worker, "HMIS-C-000101").action == "not_waiting"
    assert core.different_person(ref, WORKER, worker, "a reason").action == "not_waiting"
