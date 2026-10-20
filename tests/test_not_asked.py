"""Spec: encounter-email-intake, scenario "Worker says a question was not asked"."""

from __future__ import annotations

import pytest
import yaml

from app.config_loader import ConfigError, load_config
from parser.llm_v2 import build_schema

from .test_config import _edit

CONFIG = load_config()


def _search_confirmed_draft(intake):
    pending = intake.receive_sample("03_search_not_stated").ref
    return intake.reply(pending, "Searched HMIS, no match.").ref


def test_worker_says_a_question_was_not_asked(intake):
    ref = _search_confirmed_draft(intake)
    outcome = intake.reply(ref, "Didn't ask about race, ethnicity, or gender.")
    draft = intake.draft(ref)
    assert outcome.action == "revised" and draft.version == 2
    assert draft.value("race") == ["data_not_collected"]
    assert draft.value("gender") == ["data_not_collected"]
    assert draft.value("ethnicity") == "data_not_collected"
    assert draft.fields["race"].origin == "worker"
    assert "Didn't ask about race" in draft.fields["race"].source
    assert not any(f.field in ("race", "ethnicity", "gender") for f in draft.flags)
    assert "Race: Data not collected" in intake.last_email(ref, "review").body


def test_field_labelled_not_asked(intake):
    ref = _search_confirmed_draft(intake)
    intake.reply(ref, "Veteran: didn't ask")
    assert intake.draft(ref).value("veteran_status") == "data_not_collected"


def test_not_asked_in_the_original_note(intake):
    ref = intake.receive_text(
        "Met Pat Example, DOB 3/4/1975, SW quadrant. Searched HMIS, no match. Slept outside last night. "
        "I did not ask about his SSN.").ref
    draft = intake.draft(ref)
    assert draft.value("ssn_quality") == "data_not_collected"
    assert draft.fields["ssn_quality"].origin == "email"


def test_bare_didnt_ask_asks_which_question(intake):
    ref = _search_confirmed_draft(intake)
    before = intake.draft(ref).model_dump()
    assert intake.reply(ref, "didn't ask").action == "rephrase"
    assert "Which question did you not ask?" in intake.last_email(ref).body
    assert intake.draft(ref).model_dump() == before


def test_a_stated_answer_is_not_replaced(intake):
    ref = intake.receive_text(
        "Met Pat Example, SW quadrant. Searched HMIS, no match. Male. Didn't ask about gender identity details.").ref
    assert intake.draft(ref).value("gender") == ["male"]


def test_the_model_can_never_choose_data_not_collected():
    text = yaml.safe_dump(build_schema(CONFIG))
    assert "data_not_collected" not in text


def test_not_asked_topics_must_allow_data_not_collected(config_copy):
    _edit(config_copy / "mappings.yaml",
          lambda d: d["shared"]["not_asked"]["topics"].update(household_type=["household"]))
    with pytest.raises(ConfigError, match="data_not_collected"):
        load_config(config_copy)
