"""Workflow-level scenarios from encounter-email-intake and new-client-enrollment."""

from __future__ import annotations

import json

from parser.interface import ParseResult, ParserFailure

from .conftest import Intake

CLEAN = "01b_clean_new_client_complete"


# encounter-email-intake: Accept messages only from authorized workers


def test_message_from_an_unrecognized_sender(intake):
    outcome = intake.receive_text("Met Pat Example. Searched HMIS, no match.", sender="someone@elsewhere.example")
    assert outcome.action == "dropped"
    assert intake.store.emails() == []  # not stored and no reply with neighbor information
    assert intake.store.drafts() == []


# encounter-email-intake: Require a statement that the worker searched HMIS


def test_worker_states_no_match(intake, mock_hmis_app):
    outcome = intake.receive_sample(CLEAN)
    assert outcome.action == "drafted"
    assert intake.draft(outcome.ref).value("first_name") == "Pat"
    assert mock_hmis_app.state.store.counts()["clients"] == 0


def test_search_not_stated(intake):
    outcome = intake.receive_sample("03_search_not_stated")
    assert outcome.action == "search_requested"
    assert intake.store.drafts() == []  # no draft until the worker confirms
    assert "confirm that you searched HMIS" in intake.last_email(outcome.ref, "search_request").body
    assert intake.reply(outcome.ref, "Will do later").action == "search_requested"
    assert intake.store.drafts() == []
    drafted = intake.reply(outcome.ref, "Searched HMIS, no match.")
    assert drafted.action == "drafted"
    draft = intake.draft(drafted.ref)
    assert draft.version == 1 and draft.value("first_name") == "Lee"
    assert {e.kind for e in intake.store.emails(ref=drafted.ref)} >= {"intake", "search_request", "reply", "review"}


# encounter-email-intake: Fill draft fields only from the email


def test_value_not_stated(intake):
    pending = intake.receive_sample("03_search_not_stated").ref
    ref = intake.reply(pending, "Searched HMIS, no match.").ref
    draft = intake.draft(ref)
    assert draft.value("race") is None
    assert any(f.field == "race" for f in draft.flags)
    assert "Race: NOT STATED" in intake.last_email(ref, "review").body


def test_source_and_confidence_recorded(intake):
    draft = intake.draft(intake.receive_sample(CLEAN).ref)
    for field in draft.fields.values():
        if field.origin == "email":
            assert field.source and field.confidence


def test_generated_text_marked_for_review(intake):
    ref = intake.receive_sample(CLEAN).ref
    assert intake.draft(ref).fields["case_note"].origin == "generated"
    assert "CASE NOTE (generated from your note: read it for wording" in intake.last_email(ref, "review").body


# encounter-email-intake: Label values that come from program defaults or email metadata


def test_program_default_shown(intake):
    body = intake.last_email(intake.receive_sample(CLEAN).ref, "review").body
    assert "Verified by project: Horizon House Street Outreach (demo placeholder)  [program default]" in body


def test_encounter_date_taken_from_the_email_date(intake):
    ref = intake.receive_sample(CLEAN).ref
    draft = intake.draft(ref)
    assert draft.value("enrollment_date") == "2026-10-07" and draft.fields["enrollment_date"].origin == "email_date"
    assert "Enrollment date: 10/07/2026  [email date]" in intake.last_email(ref, "review").body


def test_relative_contact_date_resolved_from_the_email_date(intake):
    pending = intake.receive_sample("03_search_not_stated").ref  # "Met Lee Placeholder this morning"
    draft = intake.draft(intake.reply(pending, "Searched HMIS, no match.").ref)
    assert draft.value("enrollment_date") == "2026-10-12"
    assert draft.fields["enrollment_date"].origin == "email_date"


def test_client_answers_never_defaulted(intake):
    pending = intake.receive_sample("03_search_not_stated").ref
    draft = intake.draft(intake.reply(pending, "Searched HMIS, no match.").ref)
    for name in ("race", "ethnicity", "gender", "veteran_status", "disabling_condition", "ssn_quality"):
        assert draft.value(name) is None, name


# encounter-email-intake: Never make up answers for the client


def test_client_did_not_know_their_birth_date(intake):
    draft = intake.draft(intake.receive_sample("04_unknown_dob_and_street_name").ref)
    assert draft.value("dob_quality") == "client_doesnt_know"
    assert draft.value("date_of_birth") is None
    assert not any(f.field == "date_of_birth" and f.blocking for f in draft.flags)


def test_silent_on_a_required_value(intake):
    pending = intake.receive_sample("03_search_not_stated").ref
    draft = intake.draft(intake.reply(pending, "Searched HMIS, no match.").ref)
    assert draft.value("ssn_quality") is None
    assert any(f.field == "ssn_quality" and f.blocking for f in draft.flags)


# encounter-email-intake: Minimize location and exclude third parties


def test_precise_location_in_the_email(intake):
    ref = intake.receive_sample("05_privacy_traps").ref
    draft = intake.draft(ref)
    assert draft.value("service_area") == "sw"
    stored = draft.model_dump_json()
    assert "overpass" not in stored and "Example St" not in stored
    assert "Only the quadrant was recorded" in intake.last_email(ref, "review").body


def test_third_party_mentioned(intake):
    ref = intake.receive_sample("05_privacy_traps").ref
    stored = intake.draft(ref).model_dump_json() + intake.last_email(ref, "review").body
    assert "Jordan" not in stored and "warrant" not in stored


# encounter-email-intake: Ask for missing required fields


def test_required_field_missing(intake):
    ref = intake.receive_sample("02_hedged_referral_trap").ref
    body = intake.last_email(ref, "review").body
    assert "FLAGGED" in body and "Household type is missing" in body


def test_worker_supplies_the_detail(intake):
    ref = intake.receive_sample("02_hedged_referral_trap").ref
    outcome = intake.reply(ref, "Single adult.")
    draft = intake.draft(ref)
    assert outcome.ref == ref and draft.version == 2
    assert draft.value("household_type") == "single_adult" and draft.fields["household_type"].origin == "worker"


# new-client-enrollment


def test_enrollment_date_defaults_to_the_encounter_date(intake):
    test_encounter_date_taken_from_the_email_date(intake)


def test_back_dated_enrollment(intake):
    ref = intake.receive_text("Met Pat Example on 10/5, SW quadrant. Searched HMIS, no match. Slept outside last night.").ref
    draft = intake.draft(ref)
    assert draft.value("enrollment_date") == "2026-10-05" and draft.fields["enrollment_date"].origin == "email"


def test_project_not_stated(intake):
    ref = intake.receive_text("Met Pat Example, SW quadrant. Searched HMIS, no match. Slept outside last night.").ref
    draft = intake.draft(ref)
    assert draft.value("project_id") is None
    assert "Which project should the neighbor be enrolled in?" in intake.last_email(ref, "review").body


def test_prior_living_situation_is_a_place_not_meant_for_habitation(intake):
    ref = intake.receive_sample("02_hedged_referral_trap").ref
    draft = intake.draft(ref)
    assert draft.value("prior_living_situation") == "place_not_meant_for_habitation"
    asked = {f.field for f in draft.flags if f.code == "missing"}
    assert {"length_of_stay", "approx_date_homelessness_started"} <= asked
    assert "needed because prior living situation" in intake.last_email(ref, "review").body


def test_neighbor_does_not_remember(intake):
    draft = intake.draft(intake.receive_sample("04_unknown_dob_and_street_name").ref)
    assert draft.value("times_homeless_past_three_years") == "client_doesnt_know"


def test_email_mentions_income(intake):
    ref = intake.receive_sample("05_privacy_traps").ref
    assert not any("income" in n for n in intake.draft(ref).fields)
    remaining = intake.last_email(ref, "review").body.split("REMAINING IN HMIS")[1]
    assert "Income and benefits" in remaining


def test_case_note_sent_with_the_program_enrollment(hmis):
    from app.hmis_gateway import HmisGateway

    sent: dict[str, dict] = {}

    class Spy(HmisGateway):
        def _post(self, path, fields, id_key):
            sent[path.split("/")[-1]] = dict(fields)
            return super()._post(path, fields, id_key)

    intake = Intake(hmis, gateway=Spy(hmis))
    ref = intake.receive_sample(CLEAN).ref
    note = intake.draft(ref).value("case_note")
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    assert sent["enrollments"]["case_note"] == note
    assert "case_note" not in sent["clients"] and "case_note" not in sent["ce-enrollments"]
    assert "service_area" not in json.dumps(sent)  # quadrant stays in the draft and case note only
    assert note not in json.dumps(intake.service.audit_record(ref))


def test_uncertain_date_of_birth(intake):
    ref = intake.receive_text("Met Sam Demo, NE quadrant. Searched HMIS, no hits. DOB he gave is 3/14/1978 but could be 3/16. "
                              "Slept outside last night.").ref
    draft = intake.draft(ref)
    assert draft.value("dob_quality") == "approximate_or_partial_dob_reported"
    assert draft.value("date_of_birth") is None
    assert any(f.code == "uncertain_dob" for f in draft.flags)


def test_hedged_refusal_in_the_case_note(intake):
    note = intake.draft(intake.receive_sample("02_hedged_referral_trap").ref).value("case_note").lower()
    assert "declined" in note and "accepted" not in note


def test_only_the_last_four_digits_given(intake):
    draft = intake.draft(intake.receive_sample(CLEAN).ref)
    assert draft.value("ssn_last4") == "4821"
    assert draft.value("ssn_quality") == "approximate_or_partial_ssn_reported"
    assert draft.fields["ssn_quality"].confidence == "high"
    assert not any(f.field in ("ssn_last4", "ssn_quality") for f in draft.all_flags)


# Parser failures are flagged for the worker, never a silent empty draft


class FailingParser:
    name = "failing"

    def parse(self, email):
        return ParseResult(parser="reallms:gemma-4-31B-it", model="gemma-4-31B-it", prompt_version="intake-v2.1",
                           failure=ParserFailure(code="invalid_output", message="The AI parser's draft did not pass the intake checks."))

    def regenerate_case_note(self, note, corrections, fields):
        return None


def test_parser_failure_is_flagged_for_the_worker(hmis, mock_hmis_app):
    intake = Intake(hmis, parser=FailingParser())
    outcome = intake.receive_sample(CLEAN)
    draft = intake.draft(outcome.ref)
    assert outcome.action == "parse_failed" and draft.state == "draft" and draft.fields == {}
    assert draft.blocking_flags and "did not pass" in intake.last_email(outcome.ref, "notice").body
    assert intake.reply(outcome.ref, "CONFIRM").action == "ignored"
    assert mock_hmis_app.state.store.counts()["clients"] == 0
    events = intake.store.audit_events(outcome.ref)
    assert events[0]["event"] == "parse_failed" and events[0]["model"] == "gemma-4-31B-it"


def test_complete_basic_information(intake):
    """new-client-enrollment, scenario "Complete basic information"."""
    ref = intake.receive_sample("01_clean_new_client").ref
    draft = intake.draft(ref)
    note = intake.store.emails(ref=ref, kind="intake")[0].body
    expected = {"first_name": "Pat", "last_name": "Example", "date_of_birth": "1975-03-04",
                "race": ["white"], "ethnicity": "non_hispanic_latino", "gender": ["male"],
                "disabling_condition": "yes", "veteran_status": "no"}
    for name, value in expected.items():
        field = draft.fields[name]
        assert field.value == value, name
        assert field.origin == "email" and field.source and field.source in note, name
