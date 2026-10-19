"""Task 1.2: field definitions and validation rules come from configuration files."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.config_loader import CONFIG_DIR_ENV, ConfigError, load_config
from mock_hmis.rules import OPERATIONS, RulesError, load_rules
from mock_hmis.service import create_app

from .conftest import client_fields


def _edit(path: Path, change) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_shipped_configuration_loads():
    config = load_config()
    assert config.fields.fields
    assert config.settings.supervisor_timeout_hours == 48
    assert config.workers.worker_for("J.Alvarez@goodwill-outreach.example").worker_id == "j.alvarez"


def test_config_directory_can_be_overridden(config_copy, monkeypatch):
    _edit(config_copy / "settings.yaml", lambda d: d.update(supervisor_timeout_hours=24))
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config_copy))
    assert load_config().settings.supervisor_timeout_hours == 24


def test_adding_a_field_needs_only_configuration(config_copy):
    def add(d):
        d["fields"]["preferred_name"] = {
            "section": "client", "label": "Preferred name", "type": "string", "client_answer": True,
        }

    _edit(config_copy / "fields.yaml", add)
    assert "preferred_name" in load_config(config_copy).fields.fields_in_section("client")


def test_unknown_enum_reference_is_rejected(config_copy):
    _edit(config_copy / "fields.yaml", lambda d: d["fields"]["gender"].update(enum="no_such_enum"))
    with pytest.raises(ConfigError, match="unknown enum"):
        load_config(config_copy)


def test_required_when_naming_an_unknown_option_is_rejected(config_copy):
    _edit(config_copy / "fields.yaml", lambda d: d["fields"]["last_name"]["required_when"].update({"in": ["made_up"]}))
    with pytest.raises(ConfigError, match="unknown options"):
        load_config(config_copy)


def test_client_answers_never_defaulted(config_copy):
    """Spec scenario: Client answers never defaulted (configuration cannot give one a default)."""
    _edit(config_copy / "fields.yaml", lambda d: d["fields"]["veteran_status"].update(fallback="program_default"))
    with pytest.raises(ConfigError, match="never filled from a default"):
        load_config(config_copy)


def test_program_default_must_be_configured(config_copy):
    _edit(config_copy / "programs.yaml", lambda d: d["program_defaults"].pop("verified_by_project"))
    with pytest.raises(ConfigError, match="no default is configured"):
        load_config(config_copy)


def test_program_default_enum_value_must_be_an_option(config_copy):
    _edit(config_copy / "programs.yaml", lambda d: d["program_defaults"].update(assessment_contact_type="drive_by"))
    with pytest.raises(ConfigError, match="not an option"):
        load_config(config_copy)


def test_bad_regular_expression_is_rejected(config_copy):
    _edit(config_copy / "validation.yaml", lambda d: d["formats"].update(ssn_last4="^(\\d{4}$"))
    with pytest.raises(ConfigError, match="bad regular expression"):
        load_config(config_copy)


def test_date_rule_on_a_non_date_field_is_rejected(config_copy):
    _edit(config_copy / "validation.yaml", lambda d: d["dates"].update(first_name={"not_after": "email_date"}))
    with pytest.raises(ConfigError, match="not a date field"):
        load_config(config_copy)


def test_missing_configuration_file_is_reported(config_copy):
    (config_copy / "workers.yaml").unlink()
    with pytest.raises(ConfigError, match="missing configuration file"):
        load_config(config_copy)


@pytest.mark.parametrize("number", ["123-45-6789", "999-99-9999", "111-11-1111", "777777777", "000-12-3456", "512-00-4471"])
def test_known_invalid_ssn_patterns_match(number):
    patterns = [p.pattern for p in load_config().validation.ssn.invalid_full_number_patterns]
    assert any(re.search(p, number) for p in patterns)


def test_plausible_synthetic_ssn_is_not_flagged():
    patterns = [p.pattern for p in load_config().validation.ssn.invalid_full_number_patterns]
    assert not any(re.search(p, "512-38-4471") for p in patterns)


def test_invalid_ssn_labels_never_contain_a_full_number():
    for p in load_config().validation.ssn.invalid_full_number_patterns:
        assert not re.search(r"\d{3}-?\d{2}-?\d{4}", p.label), p.label


def test_name_quality_triggers_come_from_configuration():
    triggers = load_config().mappings.shared.name_quality.partial_triggers
    assert {"goes by", "street name", "nickname"} <= set(triggers)


def test_stub_rule_with_an_unknown_option_is_rejected(config_copy):
    _edit(config_copy / "mappings.yaml", lambda d: d["stub_rules"][0]["sets"].update(gender={"value": "man"}))
    with pytest.raises(ConfigError, match="unknown option"):
        load_config(config_copy)


def test_stub_rule_cannot_set_a_program_default(config_copy):
    _edit(config_copy / "mappings.yaml",
          lambda d: d["stub_rules"].append({"pattern": "x", "sets": {"verified_by_project": {"value": "x"}}}))
    with pytest.raises(ConfigError, match="not a field a parser may fill"):
        load_config(config_copy)


def test_parser_setting_accepts_only_known_parsers(config_copy):
    _edit(config_copy / "settings.yaml", lambda d: d.update(parser="chatbot"))
    with pytest.raises(ConfigError):
        load_config(config_copy)


def test_api_key_is_never_in_configuration():
    text = " ".join(p.read_text(encoding="utf-8") for p in (load_config.__globals__["DEFAULT_CONFIG_DIR"]).glob("*.yaml"))
    assert "api_key" not in text.lower().replace("reallms_api_key", "")


# The mock HMIS reads config/hmis.yaml. These check it agrees with the draft fields.


def test_hmis_rules_cover_exactly_the_three_entry_operations():
    assert set(load_rules().operations) == set(OPERATIONS)


def test_every_field_hmis_accepts_is_a_draft_field_in_the_matching_section():
    config = load_config()
    rules = load_rules()
    for section_name, section in config.fields.sections.items():
        if section.hmis_operation is None:
            continue
        drafted = set(config.fields.fields_in_section(section_name))
        assert set(rules.operations[section.hmis_operation].accepted) == drafted, section_name


def test_every_field_hmis_requires_is_required_in_the_draft():
    """A draft that passes its own required checks must not be rejected by HMIS for a missing field."""
    config = load_config()
    rules = load_rules()
    fields = config.fields.fields
    for op in rules.operations.values():
        for name in op.required:
            assert fields[name].required, name
        for cond in op.required_when:
            draft_rule = fields[cond.field].required_when
            assert fields[cond.field].required or (
                draft_rule and draft_rule.field == cond.when.field and set(draft_rule.in_) <= set(cond.when.in_)
            ), cond.field


def test_changing_hmis_rules_changes_mock_behavior(config_copy):
    _edit(config_copy / "hmis.yaml", lambda d: d["operations"]["create_client"]["required"].append("last_name"))
    app = create_app(load_rules(config_copy / "hmis.yaml"))
    with TestClient(app) as client:
        response = client.post("/clients", json={"fields": client_fields(last_name=None, name_quality="partial_street_or_code_name")})
    assert response.status_code == 422
    assert "last_name" in response.json()["reason"]


def test_hmis_rules_naming_an_unaccepted_field_are_rejected(config_copy):
    _edit(config_copy / "hmis.yaml", lambda d: d["operations"]["create_client"]["required"].append("full_ssn"))
    with pytest.raises(RulesError, match="does not accept"):
        load_rules(config_copy / "hmis.yaml")
