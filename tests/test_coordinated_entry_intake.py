"""Spec: coordinated-entry-intake. One test per scenario, named after it."""

from __future__ import annotations

CLEAN = "01b_clean_new_client_complete"


def _entry_steps(intake, ref):
    return [e["step"] for e in intake.store.audit_events(ref) if e["event"] == "entry_step"]


# Requirement: Draft the Coordinated Entry enrollment


def test_region_stated(intake):
    draft = intake.draft(intake.receive_sample(CLEAN).ref)
    assert draft.value("ce_region") == "7"
    assert draft.value("ce_project_id") == "PRJ-CE-R7-DEMO"
    assert draft.fields["ce_project_id"].origin == "program_default"


def test_region_missing(intake):
    pending = intake.receive_sample("03_search_not_stated").ref
    ref = intake.reply(pending, "Searched HMIS, no match.").ref
    draft = intake.draft(ref)
    assert draft.value("ce_region") is None and draft.value("ce_project_id") is None  # not chosen
    assert any(f.field == "ce_region" and f.blocking for f in draft.flags)
    assert "Which Coordinated Entry region?" in intake.last_email(ref, "review").body


# Requirement: Draft the triage assessment fields


def test_triage_from_a_street_encounter(intake):
    draft = intake.draft(intake.receive_sample(CLEAN).ref)
    assert draft.value("assessment_contact_type") == "in_person_street_contact"
    assert draft.fields["assessment_contact_type"].origin == "program_default"
    assert draft.value("current_living_situation") == "place_not_meant_for_habitation"
    assert draft.fields["current_living_situation"].origin == "email"
    assert draft.value("record_contact") is True
    for name in ("assessment_location", "information_date", "verified_by_project", "contact_service"):
        assert draft.value(name), name


def test_household_type(intake):
    assert intake.draft(intake.receive_sample(CLEAN).ref).value("household_type") == "single_adult"


# Requirement: Show consent as pending


def test_email_says_the_neighbor_agreed(intake):
    ref = intake.receive_sample("05_privacy_traps").ref
    draft = intake.draft(ref)
    assert not any("consent" in name for name in draft.fields)  # never recorded as obtained
    body = intake.last_email(ref, "review").body
    assert "Client consent and signatures: PENDING. You complete the consent with the neighbor in HMIS." in body
    assert "Consent stays pending until you complete it with the neighbor in HMIS" in body


# Requirement: Leave scored and diversion assessments to the worker


def test_assessment_outstanding(intake):
    body = intake.last_email(intake.receive_sample(CLEAN).ref, "review").body
    remaining = body.split("REMAINING IN HMIS")[1]
    assert "VI-SPDAT" in remaining and "Diversion assessment" in remaining


# Requirement: Enter in the required order


def test_client_entry_fails(intake, mock_hmis_app):
    ref = intake.receive_sample(CLEAN).ref
    intake.fail_next("create_client", "missing_required_field")
    intake.reply(ref, "CONFIRM")
    assert intake.draft(ref).state == "failed"
    assert _entry_steps(intake, ref) == ["client"]  # the enrollments were not attempted
    assert mock_hmis_app.state.store.counts() == {"clients": 0, "enrollments": 0, "ce_enrollments": 0}


def test_enrollment_fails_after_client_entry(intake, mock_hmis_app):
    ref = intake.receive_sample(CLEAN).ref
    intake.fail_next("enroll_in_program", "service_unavailable")
    intake.reply(ref, "CONFIRM")
    draft = intake.draft(ref)
    assert _entry_steps(intake, ref) == ["client", "enrollment"]  # CE enrollment not attempted
    assert mock_hmis_app.state.store.counts()["ce_enrollments"] == 0
    notice = intake.last_email(ref, "notice").body
    recorded, not_recorded = notice.split("Not recorded:")
    assert draft.entry.client_id in recorded
    assert "the program enrollment" in not_recorded and "the Coordinated Entry enrollment" in not_recorded


def test_retry_resumes_after_the_recorded_steps(intake, mock_hmis_app):
    ref = intake.receive_sample(CLEAN).ref
    intake.fail_next("create_ce_enrollment", "service_unavailable")
    intake.reply(ref, "CONFIRM")
    first = intake.draft(ref).entry
    assert first.client_id and first.enrollment_id and not first.ce_enrollment_id
    intake.reply(ref, "RETRY")
    draft = intake.draft(ref)
    assert _entry_steps(intake, ref) == ["client", "enrollment", "ce_enrollment", "ce_enrollment"]
    assert draft.entry.client_id == first.client_id and draft.state == "submitted"
    assert mock_hmis_app.state.store.counts() == {"clients": 1, "enrollments": 1, "ce_enrollments": 1}
