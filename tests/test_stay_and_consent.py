"""Fixes found by the model comparison (README "Evaluate REALLMS models").

1. Length of stay is kept only when its quote states how long. "Slept outside last night"
   says when, not how long, and a duration counted over the past three years is not a stay.
   Otherwise the field stays blank and flagged (spec: "Value not stated").
2. The generated case note never says consent was given or signed: consent stays pending
   (proposal: signatures and consent signing are shown as pending).
3. The times and months homeless checks skip the number in a window such as "in 3 years",
   so "first time on the street in 3 years" is one time, not three.

The replies below are the ones the models actually gave on the failing sample emails.
"""

from __future__ import annotations

import pytest

from app.config_loader import ConfigError, load_config
from parser.shared import clean_case_note

from .conftest import Intake
from .test_config import _edit
from .test_llm_parser import FakeReallms, blank_reply, email_with, make_parser

CONFIG = load_config()

SEARCH = {
    "01_clean_new_client": "Searched HMIS first, no match",
    "02_hedged_referral_trap": "Searched HMIS, nothing came up",
    "04_unknown_dob_and_street_name": "I checked HMIS and did not find him",
    "05_privacy_traps": "Searched HMIS, no hits",
}


def reply_for(stem: str, **values) -> dict:
    return blank_reply(hmis_search_stated="searched_no_match", hmis_search_quote=SEARCH[stem], **values)


def stay_flags(result):
    return [f for f in result.flags if f.startswith("length_of_stay_unstated")]


# 1. Length of stay


@pytest.mark.parametrize(
    ("stem", "quote", "label"),
    [
        ("01_clean_new_client", "Slept outside last night.", "one_night_or_less"),  # gpt-oss-120b, qwen3.8-27b
        ("04_unknown_dob_and_street_name", "Slept in a vehicle last night.", "one_night_or_less"),  # gpt-oss-120b
        # gemma-4-31B-it: "about 1 month" is the months homeless in the past three years
        ("02_hedged_referral_trap", "Slept outside last night, first time on the street in 3 years, about 1 month.",
         "one_month_to_under_90_days"),
    ],
)
def test_length_of_stay_without_a_stated_duration_is_blank_and_flagged(sample_emails, stem, quote, label):
    reply = reply_for(stem, length_of_stay=label, length_of_stay_quote=quote)
    result = make_parser(FakeReallms(reply)).parse(sample_emails[stem])
    assert result.ok, result.retry_reasons
    assert "length_of_stay" not in result.fields
    assert len(stay_flags(result)) == 1
    assert quote not in stay_flags(result)[0]  # flags name the field, never note text


def test_stated_duration_is_kept():
    body = "Met Ray Sample, Searched HMIS, no match. Been sleeping in his car for 2 weeks now."
    reply = blank_reply(length_of_stay="one_week_to_under_one_month",
                        length_of_stay_quote="Been sleeping in his car for 2 weeks now.")
    result = make_parser(FakeReallms(reply)).parse(email_with(body))
    assert result.ok and result.fields["length_of_stay"].value == "one_week_to_under_one_month"
    assert not stay_flags(result)


@pytest.mark.parametrize("phrase", ["a couple of nights", "three months", "a year"])
def test_number_words_count_as_a_duration(phrase):
    labels = {"a couple of nights": "two_to_six_nights", "three months": "ninety_days_to_under_one_year",
              "a year": "one_year_or_longer"}
    sentence = f"She has been staying at the shelter for {phrase}."
    reply = blank_reply(length_of_stay=labels[phrase], length_of_stay_quote=sentence)
    result = make_parser(FakeReallms(reply)).parse(email_with(f"Met Jo Sample. {sentence}"))
    assert result.ok, result.retry_reasons
    assert result.fields["length_of_stay"].value == labels[phrase]


def test_duration_that_does_not_match_the_label_is_retried_then_sent_to_review():
    body = "Met Ray Sample. Been sleeping in his car for 2 weeks now."
    bad = blank_reply(length_of_stay="two_to_six_nights", length_of_stay_quote="Been sleeping in his car for 2 weeks now.")
    result = make_parser(FakeReallms(bad, bad)).parse(email_with(body))
    assert result.failure.code == "invalid_output"
    assert any("length_of_stay: the duration in the quote does not match" in r for r in result.retry_reasons)


def test_refused_length_of_stay_needs_no_duration():
    body = "Met Ray Sample. He would not say how long he has been out there."
    reply = blank_reply(length_of_stay="client_refused",
                        length_of_stay_quote="He would not say how long he has been out there.")
    result = make_parser(FakeReallms(reply)).parse(email_with(body))
    assert result.ok and result.fields["length_of_stay"].value == "client_refused"
    assert not stay_flags(result)


def test_review_email_asks_for_the_length_of_stay(hmis, sample_emails):
    stem = "01_clean_new_client"
    reply = reply_for(stem, first_name="Pat", last_name="Example", name_quote="Met Pat Example",
                      prior_living_situation="place_not_meant_for_habitation",
                      prior_living_situation_quote="Slept outside last night.",
                      length_of_stay="one_night_or_less", length_of_stay_quote="Slept outside last night.")
    intake = Intake(hmis, parser=make_parser(FakeReallms(reply)))
    ref = intake.receive_sample(stem).ref
    draft = intake.draft(ref)
    assert draft.value("length_of_stay") is None
    assert any(f.code == "length_of_stay_unstated" and f.field == "length_of_stay" for f in draft.parser_flags)
    assert "does not say how long" in intake.last_email(ref, "review").body


def test_length_of_stay_rule_needs_its_bucket(config_copy):
    _edit(config_copy / "mappings.yaml", lambda d: d["buckets"].pop("length_of_stay_days"))
    with pytest.raises(ConfigError, match="length_of_stay_days"):
        load_config(config_copy)


# 2. Consent in the case note

# What gemma-4-31B-it, gpt-oss-120b and qwen3.8-27b all wrote for 05_privacy_traps.
SIGNED_NOTE = "Met Alex D. He reported sleeping outside. He agreed to share his information and signed."


def test_case_note_never_says_consent_was_signed(sample_emails):
    stem = "05_privacy_traps"
    reply = reply_for(stem, case_note=SIGNED_NOTE)
    result = make_parser(FakeReallms(reply)).parse(sample_emails[stem])
    assert result.ok, result.retry_reasons
    note = result.case_note.lower()
    for word in ("signed", "agreed to share", "consent was"):
        assert word not in note
    assert result.case_note == "Met Alex D. He reported sleeping outside. [consent pending]."
    assert "consent_mentioned" in result.notices
    assert not any(f.startswith("case_note_check") for f in result.flags)


@pytest.mark.parametrize("note", [
    "Consent signed. Gave water.",
    "Gave water; client gave verbal consent for HMIS.",
    "Signature obtained on the release of information. Gave water.",
])
def test_consent_statements_become_pending(note):
    cleaned, flags = clean_case_note(note, CONFIG)
    assert "[consent pending]" in cleaned and "Gave water" in cleaned
    for word in ("signed", "consent for", "signature", "release of information"):
        assert word not in cleaned.lower()
    assert flags == []


def test_source_sentences_are_not_rewritten_for_consent(sample_emails):
    stem = "05_privacy_traps"
    reply = reply_for(stem, case_note="Met Alex D.")
    result = make_parser(FakeReallms(reply)).parse(sample_emails[stem])
    assert "[consent pending]" not in result.hmis_search_stated.source


def test_rewritten_case_note_is_scrubbed_too(hmis, monkeypatch):
    intake = Intake(hmis)
    pending = intake.receive_sample("03_search_not_stated").ref
    ref = intake.reply(pending, "Searched HMIS, no match.").ref
    monkeypatch.setattr(intake.service.parser, "regenerate_case_note",
                        lambda note, corrections, fields: "Met Lee P. Consent form signed today.")
    assert intake.reply(ref, "Veteran: no").action == "revised"
    note = intake.draft(ref).value("case_note")
    assert "signed" not in note.lower() and "[consent pending]" in note


# 3. Times homeless: the number in a time window such as "in 3 years" is not a count


def test_first_time_in_3_years_passes_as_one_time(sample_emails):
    stem = "02_hedged_referral_trap"
    quote = "first time on the street in 3 years, about 1 month"
    reply = reply_for(stem, times_homeless_past_three_years="one_time", times_homeless_quote=quote,
                      months_homeless_past_three_years="months_1", months_homeless_quote=quote)
    result = make_parser(FakeReallms(reply)).parse(sample_emails[stem])
    assert result.ok and result.attempts == 1, result.retry_reasons
    assert result.fields["times_homeless_past_three_years"].value == "one_time"
    assert result.fields["months_homeless_past_three_years"].value == "months_1"


@pytest.mark.parametrize(("label", "passes"), [("three_times", True), ("one_time", False)])
def test_3_times_in_the_last_3_years_is_still_three_times(sample_emails, label, passes):
    stem = "01_clean_new_client"
    reply = reply_for(stem, times_homeless_past_three_years=label,
                      times_homeless_quote="Been on the street about 3 times in the last 3 years")
    result = make_parser(FakeReallms(reply, reply)).parse(sample_emails[stem])
    if passes:
        assert result.ok, result.retry_reasons
        assert result.fields["times_homeless_past_three_years"].value == "three_times"
    else:
        assert not result.ok
        assert any("times_homeless_past_three_years: the number in the quote does not match one_time" in r
                   for r in result.retry_reasons)


def test_months_after_a_3_year_window_are_read_as_months(sample_emails):
    stem = "01_clean_new_client"
    quote = "in the last 3 years, around 14 months total"
    good = reply_for(stem, months_homeless_past_three_years="more_than_12_months", months_homeless_quote=quote)
    assert make_parser(FakeReallms(good)).parse(sample_emails[stem]).ok
    bad = reply_for(stem, months_homeless_past_three_years="months_3", months_homeless_quote=quote)
    result = make_parser(FakeReallms(bad, bad)).parse(sample_emails[stem])
    assert any("months_homeless_past_three_years: the number in the quote does not match" in r for r in result.retry_reasons)
