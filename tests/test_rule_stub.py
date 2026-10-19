"""Task 3.2 and 3.4: the rule-based stub on every sample email, and the shared rules.

Tests are named after spec scenarios in encounter-email-intake and new-client-enrollment.
"""

from __future__ import annotations

import pytest

from app.config_loader import load_config
from parser.evaluation import evaluate, load_expected
from parser.factory import build_parser
from parser.rule_stub import RuleStubParser

CONFIG = load_config()
EXPECTED = load_expected()


@pytest.fixture(scope="module")
def parsed(sample_emails):
    parser = RuleStubParser(CONFIG)
    return {stem: parser.parse(email) for stem, email in sample_emails.items()}


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_stub_parses_sample_email_as_expected(parsed, stem):
    assert evaluate(parsed[stem], EXPECTED[stem], CONFIG).problems == []


def test_every_sample_email_has_an_expected_parse(sample_emails):
    assert set(sample_emails) == set(EXPECTED)


def test_stub_is_the_default_parser():
    assert isinstance(build_parser(CONFIG), RuleStubParser)


# encounter-email-intake


def test_worker_states_no_match(parsed):
    stated = parsed["01_clean_new_client"].hmis_search_stated
    assert stated.value is True
    assert "Searched HMIS" in stated.source


def test_search_not_stated(parsed):
    assert parsed["03_search_not_stated"].hmis_search_stated is None


def test_value_not_stated(parsed):
    fields = parsed["03_search_not_stated"].fields
    for name in ("race", "gender", "veteran_status", "ce_region", "ssn_quality"):
        assert name not in fields


def test_source_and_confidence_recorded(parsed):
    for field in parsed["01b_clean_new_client_complete"].fields.values():
        assert field.source
        assert field.confidence in ("high", "medium", "low")


def test_client_did_not_know_their_birth_date(parsed):
    fields = parsed["04_unknown_dob_and_street_name"].fields
    assert fields["dob_quality"].value == "client_doesnt_know"
    assert "date_of_birth" not in fields


def test_silent_on_a_required_value(parsed):
    fields = parsed["03_search_not_stated"].fields
    assert "ssn_last4" not in fields and "ssn_quality" not in fields


def test_precise_location_in_the_email(parsed):
    result = parsed["05_privacy_traps"]
    assert result.fields["service_area"].value == "sw"
    assert "precise_location_not_recorded" in result.notices
    assert "overpass" not in result.fields["service_area"].source.lower()
    assert "[precise location removed]" in result.fields["service_area"].source


def test_third_party_mentioned(parsed):
    result = parsed["05_privacy_traps"]
    assert "third_party_not_recorded" in result.notices
    stored = " ".join([result.case_note] + [f.source for f in result.fields.values()])
    assert "Jordan" not in stored and "warrant" not in stored


# new-client-enrollment


def test_neighbor_gave_a_street_name(parsed):
    assert parsed["04_unknown_dob_and_street_name"].fields["name_quality"].value == "partial_street_or_code_name"


def test_full_name_given(parsed):
    field = parsed["01_clean_new_client"].fields["name_quality"]
    assert field.value == "full_name_reported"
    assert "Pat Example" in field.source


def test_full_number_in_the_email(parsed):
    result = parsed["05_privacy_traps"]
    assert result.fields["ssn_last4"].value == "6789"
    assert "123-45" not in result.model_dump_json()


def test_known_invalid_number(parsed):
    result = parsed["05_privacy_traps"]
    assert "ssn_quality" not in result.fields
    flag = next(f for f in result.flags if f.startswith("ssn_known_invalid_pattern"))
    assert "6789" not in flag


def test_neighbor_does_not_remember(parsed):
    fields = parsed["04_unknown_dob_and_street_name"].fields
    assert fields["times_homeless_past_three_years"].value == "client_doesnt_know"
    assert "months_homeless_past_three_years" not in fields


def test_email_mentions_income(parsed):
    result = parsed["05_privacy_traps"]
    assert "unsupported_assessment_mentioned" in result.notices
    assert "income" not in result.case_note.lower()


def test_hedged_refusal_in_the_case_note(parsed):
    note = parsed["02_hedged_referral_trap"].case_note.lower()
    assert "declined" in note
    assert "accepted" not in note


def test_case_note_generated(parsed):
    note = parsed["01b_clean_new_client_complete"].case_note
    assert note.startswith("Met Pat E.")
    assert "bad back" not in note and "1975" not in note and "4821" not in note
