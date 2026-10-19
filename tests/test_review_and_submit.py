"""Spec: review-and-submit. One test per scenario, named after it."""

from __future__ import annotations

import json

import httpx

from app.hmis_gateway import HmisGateway

from .conftest import Intake

CLEAN = "01b_clean_new_client_complete"


# Requirement: Stage the record before anything is entered


def test_draft_staged(intake, mock_hmis_app):
    outcome = intake.receive_sample(CLEAN)
    draft = intake.draft(outcome.ref)
    assert draft.state == "in_review"
    assert draft.flags == [] and draft.parser_flags == []  # 01b parses with zero flags
    assert mock_hmis_app.state.store.counts() == {"clients": 0, "enrollments": 0, "ce_enrollments": 0}


def test_staged_view(intake):
    ref = intake.receive_sample(CLEAN).ref
    view = intake.service.staged_view(ref)
    assert "Submission is blocked until the worker replies CONFIRM" in view["status"]
    rows = {r["column"]: r for r in view["rows"]}
    assert rows["first_name"]["value"] == "Pat"
    assert rows["first_name"]["type"] == "string"
    assert rows["first_name"]["source"].startswith("from your note")
    assert rows["first_name"]["confidence"] in ("high", "medium", "low")
    assert rows["assessment_contact_type"]["source"] == "program default"
    assert rows["case_note"]["confidence"] == "review"
    for row in view["rows"]:
        assert {"value", "type", "source", "confidence"} <= set(row)


# Requirement: Validate drafts without silent correction


def test_impossible_date(intake):
    ref = intake.receive_text("Met Pat Example, DOB 3/4/2030, SW quadrant. Searched HMIS, no match. Slept outside last night.").ref
    draft = intake.draft(ref)
    assert draft.value("date_of_birth") == "2030-03-04"  # unchanged
    assert any(f.field == "date_of_birth" and f.code == "date" for f in draft.flags)
    assert "Date of birth 03/04/2030 is after the encounter date" in intake.last_email(ref, "review").body


def test_edit_reruns_validation(intake):
    ref = intake.receive_text("Met Pat Example, DOB 3/4/2030, SW quadrant. Searched HMIS, no match. Slept outside last night.").ref
    intake.reply(ref, "DOB 3/4/1975")
    draft = intake.draft(ref)
    assert draft.version == 2
    assert draft.value("date_of_birth") == "1975-03-04"
    assert not any(f.field == "date_of_birth" for f in draft.flags)


# Requirement: Send a review email


def test_review_email_content(intake):
    ref = intake.receive_sample("02_hedged_referral_trap").ref
    review = intake.last_email(ref, "review")
    assert review.subject == f"Please confirm: New client: Sam Sample 10/9 [{ref} v1]"
    assert review.recipient == "j.alvarez@goodwill-outreach.example"
    body = review.body
    assert "First name: Sam" in body and "Household type: NOT STATED" in body  # fields and flags
    assert "FLAGGED" in body and "Household type is missing" in body
    assert "REMAINING IN HMIS" in body and "VI-SPDAT" in body
    assert "Draft v1" in body and "version 1" in body
    assert "Nothing has been sent to HMIS" in body
    assert "***-**-" not in body or "4821" not in body


# Requirement: Accept plain-language corrections


def test_worker_corrects_a_field(intake):
    ref = intake.receive_text(
        "Met Pat Example, DOB 3/4/1975, SW quadrant. Searched HMIS, no match. Slept outside last night. "
        "This is his second time on the street in 3 years.").ref
    assert intake.draft(ref).value("times_homeless_past_three_years") == "two_times"
    outcome = intake.reply(ref, "it was the third time on the street, not the second")
    draft = intake.draft(ref)
    assert outcome.action == "revised"
    assert draft.value("times_homeless_past_three_years") == "three_times"
    assert draft.fields["times_homeless_past_three_years"].origin == "worker"
    assert "three times" in draft.value("case_note")  # case note regenerated to match
    review = intake.last_email(ref, "review")
    assert review.subject.endswith(f"[{ref} v2]")
    assert "from your reply" in review.body


def test_correction_cannot_be_understood(intake):
    ref = intake.receive_sample(CLEAN).ref
    before = intake.draft(ref).model_dump()
    outcome = intake.reply(ref, "the weather was nice today")
    assert outcome.action == "rephrase"
    assert "Please rephrase" in intake.last_email(ref).subject
    assert intake.draft(ref).model_dump() == before


# Requirement: Enter only after CONFIRM from the author


def test_worker_confirms(intake, mock_hmis_app):
    ref = intake.receive_sample(CLEAN).ref
    outcome = intake.reply(ref, "CONFIRM")
    draft = intake.draft(ref)
    assert outcome.action == "submitted"
    assert draft.confirmed_by == "j.alvarez@goodwill-outreach.example" and draft.confirmed_at is not None
    events = [e["event"] for e in intake.store.audit_events(ref)]
    assert events.index("confirmed") < events.index("entry_step")
    assert mock_hmis_app.state.store.counts() == {"clients": 1, "enrollments": 1, "ce_enrollments": 1}


def test_confirm_from_someone_else(intake, mock_hmis_app):
    ref = intake.receive_sample(CLEAN).ref
    outcome = intake.reply(ref, "CONFIRM", sender="m.chen@goodwill-outreach.example")
    assert outcome.action == "ignored"
    assert intake.draft(ref).state == "in_review"
    assert mock_hmis_app.state.store.counts()["clients"] == 0


def test_confirm_of_an_old_version(intake, mock_hmis_app):
    ref = intake.receive_sample("02_hedged_referral_trap").ref
    intake.reply(ref, "Single adult.")
    assert intake.draft(ref).version == 2
    outcome = intake.reply(ref, "CONFIRM", version=1)
    assert outcome.action == "old_version"
    notice = intake.last_email(ref)
    assert "Please review version 2" in notice.subject and "Nothing has been entered" in notice.body
    assert intake.draft(ref).state == "in_review"
    assert mock_hmis_app.state.store.counts()["clients"] == 0


def test_confirm_with_required_fields_missing_is_not_entered(intake, mock_hmis_app):
    ref = intake.receive_sample("02_hedged_referral_trap").ref
    outcome = intake.reply(ref, "CONFIRM")
    assert outcome.action == "still_missing"
    assert "Household type is missing" in intake.last_email(ref, "missing_info").body
    assert mock_hmis_app.state.store.counts()["clients"] == 0


# Requirement: Enter into HMIS without reading from it


def test_entry_succeeds(intake):
    ref = intake.receive_sample(CLEAN).ref
    intake.reply(ref, "CONFIRM")
    draft = intake.draft(ref)
    assert draft.state == "submitted"
    receipt = intake.last_email(ref, "receipt")
    for identifier in (draft.entry.client_id, draft.entry.enrollment_id, draft.entry.ce_enrollment_id):
        assert identifier and identifier in receipt.body


def test_entry_fails_when_hmis_rejects(intake):
    ref = intake.receive_sample(CLEAN).ref
    intake.fail_next("create_client", "possible_duplicate")
    outcome = intake.reply(ref, "CONFIRM")
    draft = intake.draft(ref)
    assert outcome.action == "entry_failed" and draft.state == "failed"
    notice = intake.last_email(ref, "notice")
    assert "possible duplicate" in notice.body.lower()
    assert draft.value("first_name") == "Pat"  # the confirmed draft is kept for a retry


def test_entry_fails_when_hmis_cannot_be_reached(hmis):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    gateway = HmisGateway(httpx.Client(base_url="http://hmis.test", transport=httpx.MockTransport(refuse)))
    intake = Intake(hmis, gateway=gateway)
    ref = intake.receive_sample(CLEAN).ref
    intake.reply(ref, "CONFIRM")
    assert intake.draft(ref).state == "failed"
    assert "could not be reached" in intake.last_email(ref, "notice").body


def test_only_entry_operations_are_used(hmis):
    calls = []

    class Spy(HmisGateway):
        def _post(self, path, fields, id_key):
            calls.append(path)
            return super()._post(path, fields, id_key)

    intake = Intake(hmis, gateway=Spy(hmis))
    ref = intake.receive_sample(CLEAN).ref
    assert calls == []  # drafting never touches HMIS
    intake.reply(ref, "CONFIRM")
    assert [c.split("/")[-1] for c in calls] == ["clients", "enrollments", "ce-enrollments"]


# Requirement: Resume a failed entry from the failed step


def test_retry_after_a_partial_failure(intake, mock_hmis_app):
    ref = intake.receive_sample(CLEAN).ref
    intake.fail_next("enroll_in_program", "service_unavailable")
    intake.reply(ref, "CONFIRM")
    first_client = intake.draft(ref).entry.client_id
    assert first_client and intake.draft(ref).state == "failed"
    outcome = intake.reply(ref, "RETRY")
    draft = intake.draft(ref)
    assert outcome.action == "submitted"
    assert draft.entry.client_id == first_client
    assert mock_hmis_app.state.store.counts() == {"clients": 1, "enrollments": 1, "ce_enrollments": 1}


# Requirement: Send unconfirmed drafts to a supervisor queue


def test_draft_not_confirmed_in_time(intake, mock_hmis_app):
    ref = intake.receive_sample(CLEAN).ref
    intake.clock.advance(hours=47)
    assert intake.service.expire_stale() == []
    intake.clock.advance(hours=1)
    assert intake.service.expire_stale() == [ref]
    assert intake.draft(ref).state == "expired"
    assert [q["draft_id"] for q in intake.service.supervisor_queue()] == [ref]
    assert "supervisor's queue" in intake.last_email(ref, "notice").body  # the worker is notified
    supervisor = intake.last_email(ref, "supervisor")
    assert supervisor.recipient == intake.config.workers.supervisor_address
    assert "Pat" not in supervisor.subject + supervisor.body  # no neighbor details to the supervisor
    assert mock_hmis_app.state.store.counts()["clients"] == 0


def test_confirm_after_expiry(intake, mock_hmis_app):
    ref = intake.receive_sample(CLEAN).ref
    intake.clock.advance(hours=49)
    intake.service.expire_stale()
    outcome = intake.reply(ref, "CONFIRM")
    assert outcome.action == "expired"
    assert "supervisor's queue" in intake.last_email(ref, "notice").body
    assert mock_hmis_app.state.store.counts()["clients"] == 0


# Requirement: Keep an audit record and delete email copies


def test_confirmed_submission(intake):
    ref = intake.receive_sample("02_hedged_referral_trap").ref
    intake.reply(ref, "Single adult. Gave her a bus pass. Been outside about a month, homeless since 9/10/2026.")
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    record = intake.service.audit_record(ref)
    assert record["worker_id"] == "j.alvarez" and record["confirmed_by"] == "j.alvarez@goodwill-outreach.example"
    assert record["confirmed_at"] and record["versions"] == [1, 2]
    assert record["changed_fields"] == ["approx_date_homelessness_started", "contact_service", "household_type", "length_of_stay"]
    assert record["model"] is None and record["prompt_version"] == "rule_stub" and record["parsed_at"]
    text = json.dumps(record)
    for phrase in ("Offered a shelter bed", "Sam", "declined", "bus pass", "Met "):
        assert phrase not in text  # no email text and no case note in the audit record


def test_email_copies_removed(intake):
    ref = intake.receive_sample(CLEAN).ref
    assert {e.kind for e in intake.store.emails(ref=ref)} == {"intake", "review"}
    intake.reply(ref, "CONFIRM")
    assert [e.kind for e in intake.store.emails(ref=ref)] == ["receipt"]
    assert "email_copies_deleted" in [e["event"] for e in intake.store.audit_events(ref)]


def test_email_copies_removed_within_a_retention_limit(hmis):
    intake = Intake(hmis)
    intake.service.config = intake.config.model_copy(update={
        "settings": intake.config.settings.model_copy(update={"email_retention_hours": 24})})
    ref = intake.receive_sample(CLEAN).ref
    intake.reply(ref, "CONFIRM")
    assert "intake" in {e.kind for e in intake.store.emails(ref=ref)}
    intake.clock.advance(hours=24)
    assert intake.service.purge_emails() == [ref]
    assert [e.kind for e in intake.store.emails(ref=ref)] == ["receipt"]
