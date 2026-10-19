"""Load and check the demo configuration.

Field definitions, validation rules, the worker list, programs, and settings live in
YAML files under config/. Code reads them only through this module, so changing a
field or rule means editing configuration, not code.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError, model_validator

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CONFIG_DIR_ENV = "HMIS_DEMO_CONFIG_DIR"

FieldType = Literal["string", "date", "enum", "multi_enum", "boolean", "text", "ssn_last4", "list"]
HmisOperation = Literal["create_client", "enroll_in_program", "create_ce_enrollment"]
DateAnchor = Literal["encounter_date", "email_date"]


class ConfigError(Exception):
    """A configuration file is missing, malformed, or inconsistent."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# fields.yaml


class EnumOption(_Strict):
    id: str
    label: str


class Condition(_Strict):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    field: str
    in_: list[str] = Field(alias="in", min_length=1)


class Section(_Strict):
    label: str
    hmis_operation: HmisOperation | None


class FieldDef(_Strict):
    section: str
    label: str
    type: FieldType
    enum: str | None = None
    max_items: PositiveInt | None = None
    required: bool = False
    required_when: Condition | None = None
    client_answer: bool = False
    fallback: Literal["email_date", "program_default"] | None = None
    fixed_value: str | bool | None = None

    @model_validator(mode="after")
    def _check(self) -> FieldDef:
        if self.type in ("enum", "multi_enum") and not self.enum:
            raise ValueError(f"type {self.type} needs an enum")
        if self.type not in ("enum", "multi_enum") and self.enum:
            raise ValueError(f"type {self.type} cannot have an enum")
        if self.required and self.required_when:
            raise ValueError("use required or required_when, not both")
        if self.fallback and self.fixed_value is not None:
            raise ValueError("use fallback or fixed_value, not both")
        if self.client_answer and (self.fallback or self.fixed_value is not None):
            raise ValueError("a client answer is never filled from a default or a fixed value")
        if self.fallback == "email_date" and self.type != "date":
            raise ValueError("an email_date fallback needs a date field")
        return self


class FieldsConfig(_Strict):
    sections: dict[str, Section]
    enums: dict[str, list[EnumOption]]
    fields: dict[str, FieldDef]
    remaining_in_hmis: list[str]

    @model_validator(mode="after")
    def _check(self) -> FieldsConfig:
        for name, options in self.enums.items():
            ids = [o.id for o in options]
            if len(ids) != len(set(ids)):
                raise ValueError(f"enum {name} has duplicate option ids")
        for name, f in self.fields.items():
            where = f"field {name}"
            if f.section not in self.sections:
                raise ValueError(f"{where}: unknown section {f.section!r}")
            if f.enum and f.enum not in self.enums:
                raise ValueError(f"{where}: unknown enum {f.enum!r}")
            if f.type == "enum" and isinstance(f.fixed_value, str) and f.fixed_value not in self.option_ids(name):
                raise ValueError(f"{where}: fixed value {f.fixed_value!r} is not an option")
            if f.required_when:
                other = self.fields.get(f.required_when.field)
                if other is None:
                    raise ValueError(f"{where}: required_when names unknown field {f.required_when.field!r}")
                if other.enum:
                    bad = set(f.required_when.in_) - set(self.option_ids(f.required_when.field))
                    if bad:
                        raise ValueError(f"{where}: required_when uses unknown options {sorted(bad)}")
        return self

    def option_ids(self, field_name: str) -> list[str]:
        enum = self.fields[field_name].enum
        return [o.id for o in self.enums[enum]] if enum else []

    def fields_in_section(self, section: str) -> dict[str, FieldDef]:
        return {n: f for n, f in self.fields.items() if f.section == section}


# validation.yaml


class DateRule(_Strict):
    not_before: date | None = None
    not_after: DateAnchor | None = None


class InvalidSsnPattern(_Strict):
    pattern: str
    label: str


class SsnRules(_Strict):
    invalid_full_number_patterns: list[InvalidSsnPattern]


class ConfidenceRules(_Strict):
    levels: list[str] = Field(min_length=1)
    flag: list[str]

    @model_validator(mode="after")
    def _check(self) -> ConfidenceRules:
        if set(self.flag) - set(self.levels):
            raise ValueError("confidence.flag lists a level not in confidence.levels")
        return self


class ValidationConfig(_Strict):
    dates: dict[str, DateRule]
    formats: dict[str, str]
    ssn: SsnRules
    confidence: ConfidenceRules

    @model_validator(mode="after")
    def _check(self) -> ValidationConfig:
        patterns = list(self.formats.values()) + [p.pattern for p in self.ssn.invalid_full_number_patterns]
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"bad regular expression {pattern!r}: {exc}") from exc
        return self


# workers.yaml, programs.yaml, settings.yaml


class Worker(_Strict):
    address: str
    worker_id: str
    display_name: str


class WorkersConfig(_Strict):
    intake_address: str
    authorized_workers: list[Worker]
    supervisor_address: str

    def worker_for(self, address: str) -> Worker | None:
        wanted = address.strip().lower()
        return next((w for w in self.authorized_workers if w.address.lower() == wanted), None)


class Project(_Strict):
    project_id: str
    label: str
    aliases: list[str]


class CeRegion(_Strict):
    ce_project_id: str
    assessment_location: str


class ProgramsConfig(_Strict):
    projects: dict[str, Project]
    ce_regions: dict[str, CeRegion]
    program_defaults: dict[str, str]


class ReallmsSettings(_Strict):
    base_url: str
    model: str = Field(min_length=1)
    fallback_models: list[str] = []
    fallback_requires_prompt_style: str
    temperature: float = Field(ge=0, le=2)
    timeout_seconds: float = Field(gt=0)
    max_tokens: PositiveInt | None = None
    http_retries: int = Field(ge=0)
    backoff_seconds: float = Field(ge=0)

    @property
    def allowed_models(self) -> list[str]:
        return [self.model, *self.fallback_models]


class Settings(_Strict):
    supervisor_timeout_hours: PositiveInt
    email_retention_hours: int = Field(ge=0)
    parser: Literal["rule_stub", "reallms"]
    reallms: ReallmsSettings
    hmis_base_url: str
    hmis_timeout_seconds: float = Field(gt=0)


# mappings.yaml


class SetSpec(_Strict):
    value: str | None = None
    group: str | None = None
    convert: str | None = None
    map: dict[str, str] | None = None
    confidence: Literal["high", "medium", "low"] | None = None

    @model_validator(mode="after")
    def _check(self) -> SetSpec:
        if (self.value is None) == (self.group is None):
            raise ValueError("give exactly one of value or group")
        if self.convert and not (
            self.convert in ("date_mdy", "lower", "list_items") or self.convert.startswith("bucket:")
        ):
            raise ValueError(f"unknown convert {self.convert!r}")
        return self


class StubRule(_Strict):
    pattern: str
    case_sensitive: bool = False
    sets: dict[str, SetSpec] = Field(min_length=1)


class CaseNoteRule(_Strict):
    pattern: str
    text: str


class Bucket(_Strict):
    max: PositiveInt | None
    value: str


class NameQualityRules(_Strict):
    partial_triggers: list[str]
    full_value: str
    partial_value: str


class SharedSsnRules(_Strict):
    full_number: str
    any_full_number: str
    full_number_quality: str


class Notice(_Strict):
    label: str
    patterns: list[str] = Field(min_length=1)
    scrub: list[str] = []
    replacement: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Notice:
        if bool(self.scrub) != (self.replacement is not None):
            raise ValueError("scrub and replacement go together")
        return self


class SharedRules(_Strict):
    name_quality: NameQualityRules
    ssn: SharedSsnRules
    hmis_search: list[str] = Field(min_length=1)
    notices: dict[str, Notice]


class LlmChecks(_Strict):
    hedges: list[str] = Field(min_length=1)
    living_hints: dict[str, list[str]]
    answer_words: dict[Literal["client_refused", "client_doesnt_know"], list[str]]
    negation_words: list[str]
    label_words: dict[str, dict[str, list[str]]]


class MappingsConfig(_Strict):
    sentence_split: str
    hedge_words: list[str]
    shared: SharedRules
    buckets: dict[str, list[Bucket]]
    stub_rules: list[StubRule]
    stub_case_note: list[CaseNoteRule]
    stub_contact_date: list[str]
    stub_hearsay_words: list[str]
    llm_checks: LlmChecks

    @model_validator(mode="after")
    def _check(self) -> MappingsConfig:
        patterns = [self.sentence_split, self.shared.ssn.full_number, self.shared.ssn.any_full_number]
        patterns += self.shared.hmis_search + self.stub_contact_date
        for pattern in self.stub_contact_date:
            if "(?P<phrase>" not in pattern:
                raise ValueError("stub_contact_date patterns need a (?P<phrase>...) group")
        patterns += [p for n in self.shared.notices.values() for p in n.patterns + n.scrub]
        patterns += [r.pattern for r in self.stub_rules] + [r.pattern for r in self.stub_case_note]
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"bad regular expression {pattern!r}: {exc}") from exc
        if "(?P<number>" not in self.shared.ssn.full_number:
            raise ValueError("shared.ssn.full_number needs a (?P<number>...) group")
        for name, buckets in self.buckets.items():
            if not buckets or buckets[-1].max is not None:
                raise ValueError(f"bucket {name} must end with an open bucket (max: null)")
        for rule in self.stub_rules:
            groups = re.compile(rule.pattern).groupindex
            for spec in rule.sets.values():
                if spec.group and spec.group not in groups:
                    raise ValueError(f"rule {rule.pattern!r} has no group {spec.group!r}")
                if spec.convert and spec.convert.startswith("bucket:") and spec.convert[7:] not in self.buckets:
                    raise ValueError(f"unknown bucket in {spec.convert!r}")
        return self


# Whole configuration


class AppConfig(_Strict):
    fields: FieldsConfig
    validation: ValidationConfig
    workers: WorkersConfig
    programs: ProgramsConfig
    settings: Settings
    mappings: MappingsConfig

    @model_validator(mode="after")
    def _check(self) -> AppConfig:
        known = self.fields.fields
        self._check_mappings(known)
        for name, rule in self.validation.dates.items():
            if name not in known or known[name].type != "date":
                raise ValueError(f"validation.dates: {name!r} is not a date field")
        for name in self.validation.formats:
            if name not in known:
                raise ValueError(f"validation.formats: unknown field {name!r}")
        region_fields = set(CeRegion.model_fields)
        for name, f in known.items():
            if f.fallback != "program_default":
                continue
            if name not in self.programs.program_defaults and name not in region_fields:
                raise ValueError(f"field {name!r} has a program_default fallback but no default is configured")
        for name, value in self.programs.program_defaults.items():
            f = known.get(name)
            if f is None or f.fallback != "program_default":
                raise ValueError(f"program_defaults: {name!r} is not a field with a program_default fallback")
            if f.enum and value not in self.fields.option_ids(name):
                raise ValueError(f"program_defaults: {value!r} is not an option for {name!r}")
        return self

    def _check_mappings(self, known: dict[str, FieldDef]) -> None:
        m = self.mappings
        for name, buckets in m.buckets.items():
            for b in buckets:
                if not any(b.value in self.fields.option_ids(f) for f in known):
                    raise ValueError(f"bucket {name}: {b.value!r} is not an option of any field")
        nq = m.shared.name_quality
        for value in (nq.full_value, nq.partial_value):
            if value not in self.fields.option_ids("name_quality"):
                raise ValueError(f"shared.name_quality: {value!r} is not a name_quality option")
        if m.shared.ssn.full_number_quality not in self.fields.option_ids("ssn_quality"):
            raise ValueError("shared.ssn.full_number_quality is not an ssn_quality option")
        checks = m.llm_checks
        living = set(self.fields.option_ids("prior_living_situation"))
        if set(checks.living_hints) - living:
            raise ValueError(f"llm_checks.living_hints: unknown options {sorted(set(checks.living_hints) - living)}")
        for name, labels in checks.label_words.items():
            if name not in known:
                raise ValueError(f"llm_checks.label_words: unknown field {name!r}")
            bad = set(labels) - set(self.fields.option_ids(name))
            if bad:
                raise ValueError(f"llm_checks.label_words.{name}: unknown options {sorted(bad)}")
        parsable = set(self.parsable_fields())
        for rule in m.stub_rules:
            for name, spec in rule.sets.items():
                if name not in parsable:
                    raise ValueError(f"stub rule sets {name!r}, which is not a field a parser may fill")
                options = self.fields.option_ids(name)
                if spec.value is not None and options and spec.value not in options:
                    raise ValueError(f"stub rule sets {name!r} to unknown option {spec.value!r}")
                if spec.map and options and set(spec.map.values()) - set(options):
                    raise ValueError(f"stub rule maps {name!r} to unknown options")

    def parsable_fields(self) -> dict[str, FieldDef]:
        """Fields a parser may fill from the email.

        Fixed values and program defaults are not parsed, and generated text (the case
        note) is returned separately.
        """
        return {
            n: f
            for n, f in self.fields.fields.items()
            if f.fixed_value is None and f.fallback != "program_default" and f.type != "text"
        }


_FILES = {
    "fields": "fields.yaml",
    "validation": "validation.yaml",
    "workers": "workers.yaml",
    "programs": "programs.yaml",
    "settings": "settings.yaml",
    "mappings": "mappings.yaml",
}


def config_dir() -> Path:
    """The configuration directory, overridable with HMIS_DEMO_CONFIG_DIR."""
    return Path(os.environ.get(CONFIG_DIR_ENV, DEFAULT_CONFIG_DIR))


def read_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"missing configuration file {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc


def load_config(directory: Path | str | None = None) -> AppConfig:
    """Load every configuration file and check that they agree with each other."""
    base = Path(directory) if directory is not None else config_dir()
    raw = {key: read_yaml(base / name) for key, name in _FILES.items()}
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"configuration in {base} is invalid:\n{exc}") from exc
