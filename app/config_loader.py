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
HmisOperation = Literal["create_client", "enroll_in_program", "create_ce_enrollment", "add_case_note", "add_service"]
DraftKind = Literal["new_client", "update"]
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
    draft_kind: DraftKind = "new_client"  # which kind of draft uses this section


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
    also_sent_with: list[str] = []  # other sections whose HMIS entry also carries this field

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


class UpdateDraftConfig(_Strict):
    """The fields of an update draft for a client already in HMIS, in review order."""

    fields: list[str] = Field(min_length=1)
    required: list[str]


class FieldsConfig(_Strict):
    sections: dict[str, Section]
    enums: dict[str, list[EnumOption]]
    fields: dict[str, FieldDef]
    remaining_in_hmis: list[str]
    update_draft: UpdateDraftConfig

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
            for other_section in f.also_sent_with:
                if other_section not in self.sections:
                    raise ValueError(f"{where}: also_sent_with names unknown section {other_section!r}")
            if f.required_when:
                other = self.fields.get(f.required_when.field)
                if other is None:
                    raise ValueError(f"{where}: required_when names unknown field {f.required_when.field!r}")
                if other.enum:
                    bad = set(f.required_when.in_) - set(self.option_ids(f.required_when.field))
                    if bad:
                        raise ValueError(f"{where}: required_when uses unknown options {sorted(bad)}")
        u = self.update_draft
        unknown = [n for n in u.fields if n not in self.fields]
        if unknown:
            raise ValueError(f"update_draft names unknown fields {unknown}")
        if set(u.required) - set(u.fields):
            raise ValueError("update_draft.required must be among update_draft.fields")
        if "case_note" not in u.fields:
            raise ValueError("update_draft.fields must include case_note")
        return self

    def option_ids(self, field_name: str) -> list[str]:
        enum = self.fields[field_name].enum
        return [o.id for o in self.enums[enum]] if enum else []

    def fields_in_section(self, section: str) -> dict[str, FieldDef]:
        """Fields entered with this section's HMIS operation, including fields also sent with it."""
        return {n: f for n, f in self.fields.items() if f.section == section or section in f.also_sent_with}

    def fields_for(self, kind: str) -> dict[str, FieldDef]:
        """The draft fields for a new-client draft or an update draft, with the update's required setting."""
        if kind == "update":
            u = self.update_draft
            return {n: self.fields[n].model_copy(update={"required": n in u.required, "required_when": None})
                    for n in u.fields}
        return {n: f for n, f in self.fields.items() if self.sections[f.section].draft_kind == "new_client"}


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
    project: str = Field(min_length=1)  # visibility for read-only queries [TBC with CHIP]


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
    not_recommended_models: list[str] = []  # refused unless explicitly overridden
    fallback_requires_prompt_style: str
    temperature: float = Field(ge=0, le=2)
    timeout_seconds: float = Field(gt=0)
    max_tokens: PositiveInt | None = None
    http_retries: int = Field(ge=0)
    backoff_seconds: float = Field(ge=0)

    @property
    def allowed_models(self) -> list[str]:
        return [self.model, *self.fallback_models]

    @model_validator(mode="after")
    def _check_not_recommended(self) -> ReallmsSettings:
        overlap = set(self.not_recommended_models) & set(self.allowed_models)
        if overlap:
            raise ValueError(f"reallms: {sorted(overlap)} cannot be both allowed and not recommended")
        return self


class HmisQueriesSettings(_Strict):
    """Read-only queries (add-hmis-readonly-queries)."""

    database: str  # the mock HMIS SQLite file, opened read-only; relative to the repo root
    subject_prefix: str = Field(min_length=1)
    row_limit: PositiveInt
    briefing_window_days: PositiveInt
    no_contact_days: PositiveInt  # the no-contact watchlist limit [TBC with Horizon House]
    no_contact_warning_days: PositiveInt  # how many days before the limit a neighbor is listed as approaching
    client_id_pattern: str  # [TBC: the real HMIS client ID format]
    status_types: dict[str, str]  # id -> label shown in replies [TBC with Horizon House]
    email_retention_hours: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> HmisQueriesSettings:
        if self.no_contact_warning_days >= self.no_contact_days:
            raise ValueError("no_contact_warning_days must be smaller than no_contact_days")
        try:
            re.compile(self.client_id_pattern)
        except re.error as exc:
            raise ValueError(f"hmis_queries.client_id_pattern: {exc}") from exc
        if not set(self.status_types) <= {"id_document", "housing_assessment"}:
            raise ValueError("hmis_queries.status_types: only id_document and housing_assessment are supported")
        return self


class UpdatesSettings(_Strict):
    """Updates to clients already in HMIS (add-existing-client-updates)."""

    subject_prefix: str = Field(min_length=1)
    client_id_in_text: str

    @model_validator(mode="after")
    def _check(self) -> UpdatesSettings:
        try:
            pattern = re.compile(self.client_id_in_text)
        except re.error as exc:
            raise ValueError(f"updates.client_id_in_text: {exc}") from exc
        if "id" not in pattern.groupindex:
            raise ValueError("updates.client_id_in_text needs a (?P<id>...) group")
        return self


class VerificationSettings(_Strict):
    min_reason_length_matching_digits: PositiveInt
    update_in_hmis_yourself: list[str] = []


class RetentionSettings(_Strict):
    mode: Literal["demo", "production"]
    unsubmitted_days: PositiveInt
    match_key_env: str = Field(min_length=1)


class SignInSettings(_Strict):
    max_failures: PositiveInt
    window_minutes: PositiveInt
    lockout_minutes: PositiveInt
    max_attempts_per_client: PositiveInt


class WebSettings(_Strict):
    """The web application's sessions and sign-in limits (add-web-application)."""

    session_idle_minutes: PositiveInt
    session_absolute_hours: PositiveInt
    cookie_secure: Literal["auto", True, False]
    sign_in: SignInSettings
    idempotency_key_hours: PositiveInt  # how long a used Idempotency-Key is remembered for its user
    idempotency_wait_seconds: float = Field(gt=0)  # how long a repeat waits for the first request to finish
    housekeeping_minutes: PositiveInt  # how often the server runs the time-based rules on its own
    offline_write_hours: PositiveInt  # how long after last reaching the server a device may save notes
    device_queue_hours: PositiveInt  # a note not uploaded within this is deleted from the device
    device_queue_warning_hours: PositiveInt  # the note shows a warning from this age
    device_clock_skew_minutes: PositiveInt  # how far a device's clock may differ from the server's

    @model_validator(mode="after")
    def _check(self) -> WebSettings:
        if self.session_idle_minutes > self.session_absolute_hours * 60:
            raise ValueError("web.session_idle_minutes cannot be longer than web.session_absolute_hours")
        if self.device_queue_warning_hours >= self.device_queue_hours:
            raise ValueError("web.device_queue_warning_hours must be shorter than web.device_queue_hours")
        if self.idempotency_key_hours <= self.device_queue_hours:
            raise ValueError("web.idempotency_key_hours must be longer than web.device_queue_hours")
        if self.offline_write_hours > self.device_queue_hours:
            raise ValueError("web.offline_write_hours cannot be longer than web.device_queue_hours")
        return self


class EmailChannelSettings(_Strict):
    enabled: bool


class ChannelSettings(_Strict):
    email: EmailChannelSettings


class DemoSettings(_Strict):
    # The parser-run, mapped-draft, and staged-record views show draft contents. Demo only
    # [TBC with Goodwill: who needs them].
    draft_content_views: bool
    web_reset: bool  # the web demo's reset route and device wipe. Never on in production


class Settings(_Strict):
    supervisor_timeout_hours: PositiveInt
    email_retention_hours: int = Field(ge=0)
    parser: Literal["rule_stub", "reallms"]
    reallms: ReallmsSettings
    hmis_base_url: str
    hmis_timeout_seconds: float = Field(gt=0)
    hmis_queries: HmisQueriesSettings
    updates: UpdatesSettings
    verification: VerificationSettings
    retention: RetentionSettings
    web: WebSettings
    channels: ChannelSettings
    demo: DemoSettings


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
    possible_full_number: str  # web notes: an SSN word and seven or more digits in another grouping
    full_number_quality: str


class Notice(_Strict):
    label: str
    patterns: list[str] = Field(min_length=1)
    scrub: list[str] = []
    replacement: str | None = None
    case_note_only: bool = False  # scrub only the generated case note, not source sentences

    @model_validator(mode="after")
    def _check(self) -> Notice:
        if bool(self.scrub) != (self.replacement is not None):
            raise ValueError("scrub and replacement go together")
        return self


class NotAskedRules(_Strict):
    patterns: list[str] = Field(min_length=1)
    topics: dict[str, list[str]]


class ServiceTypeRule(_Strict):
    pattern: str
    value: str


class TimeSpentRule(_Strict):
    pattern: str
    minutes: PositiveInt | None = None  # fixed minutes, or the pattern captures (?P<minutes>...)

    @model_validator(mode="after")
    def _check(self) -> TimeSpentRule:
        if self.minutes is None and "(?P<minutes>" not in self.pattern:
            raise ValueError("shared.time_spent: a rule needs minutes or a (?P<minutes>...) group")
        return self


class SharedRules(_Strict):
    name_quality: NameQualityRules
    ssn: SharedSsnRules
    service_type: list[ServiceTypeRule] = Field(min_length=1)
    time_spent: list[TimeSpentRule] = Field(min_length=1)
    not_asked: NotAskedRules
    hmis_search: list[str] = Field(min_length=1)
    notices: dict[str, Notice]


class LengthOfStayCheck(_Strict):
    duration: str
    lookback: str
    number_words: dict[str, int]
    unit_days: dict[str, int]

    @model_validator(mode="after")
    def _check(self) -> LengthOfStayCheck:
        for pattern in (self.duration, self.lookback):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"bad regular expression {pattern!r}: {exc}") from exc
        if "(?P<number>" not in self.duration or "(?P<unit>" not in self.duration:
            raise ValueError("llm_checks.length_of_stay.duration needs (?P<number>...) and (?P<unit>...) groups")
        return self


class LlmChecks(_Strict):
    hedges: list[str] = Field(min_length=1)
    living_hints: dict[str, list[str]]
    answer_words: dict[Literal["client_refused", "client_doesnt_know"], list[str]]
    negation_words: list[str]
    label_words: dict[str, dict[str, list[str]]]
    length_of_stay: LengthOfStayCheck


class StubQueryRules(_Strict):
    """How the rule-based stub reads a "Query:" email (add-hmis-readonly-queries)."""

    status_words: list[str]
    lookup_words: list[str]
    no_contact_words: list[str]
    briefing_words: list[str]
    quadrant: str
    quadrant_map: dict[str, Literal["nw", "ne", "sw", "se"]]
    status_types: dict[str, list[str]]
    client_id: str
    date_of_birth: str
    name: str
    not_names: list[str]

    @model_validator(mode="after")
    def _check(self) -> StubQueryRules:
        patterns = [*self.status_words, *self.lookup_words, *self.no_contact_words, *self.briefing_words,
                    self.quadrant, self.client_id,
                    self.date_of_birth, self.name, *(p for ps in self.status_types.values() for p in ps)]
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"stub_query: bad regular expression {pattern!r}: {exc}") from exc
        for pattern, group in ((self.quadrant, "q"), (self.client_id, "id"), (self.date_of_birth, "d")):
            if f"(?P<{group}>" not in pattern:
                raise ValueError(f"stub_query: {pattern!r} needs a (?P<{group}>...) group")
        if "(?P<first>" not in self.name or "(?P<last>" not in self.name:
            raise ValueError("stub_query.name needs (?P<first>...) and (?P<last>...) groups")
        return self


class MappingsConfig(_Strict):
    sentence_split: str
    hedge_words: list[str]
    shared: SharedRules
    buckets: dict[str, list[Bucket]]
    stub_rules: list[StubRule]
    stub_case_note: list[CaseNoteRule]
    stub_contact_date: list[str]
    stub_hearsay_words: list[str]
    stub_query: StubQueryRules
    llm_checks: LlmChecks

    @model_validator(mode="after")
    def _check(self) -> MappingsConfig:
        patterns = [self.sentence_split, self.shared.ssn.full_number, self.shared.ssn.any_full_number,
                    self.shared.ssn.possible_full_number]
        patterns += self.shared.hmis_search + self.stub_contact_date + self.shared.not_asked.patterns
        for pattern in self.shared.not_asked.patterns:
            if "(?P<topic>" not in pattern:
                raise ValueError("shared.not_asked patterns need a (?P<topic>...) group")
        for pattern in self.stub_contact_date:
            if "(?P<phrase>" not in pattern:
                raise ValueError("stub_contact_date patterns need a (?P<phrase>...) group")
        patterns += [p for n in self.shared.notices.values() for p in n.patterns + n.scrub]
        patterns += [r.pattern for r in self.shared.service_type] + [r.pattern for r in self.shared.time_spent]
        patterns += [r.pattern for r in self.stub_rules] + [r.pattern for r in self.stub_case_note]
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"bad regular expression {pattern!r}: {exc}") from exc
        if "(?P<number>" not in self.shared.ssn.full_number:
            raise ValueError("shared.ssn.full_number needs a (?P<number>...) group")
        if "length_of_stay_days" not in self.buckets:
            raise ValueError("buckets.length_of_stay_days is needed by llm_checks.length_of_stay")
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


# users.yaml


class Account(_Strict):
    """A web sign-in account. The password is never here: only the name of its environment variable."""

    username: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")
    role: Literal["worker", "supervisor", "staff"]
    worker: str | None = None  # a worker's address in workers.yaml (required for role worker)
    display_name: str | None = None  # for a supervisor or staff; a worker's comes from workers.yaml
    password_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")


class UsersConfig(_Strict):
    accounts: list[Account]


class AppConfig(_Strict):
    fields: FieldsConfig
    validation: ValidationConfig
    workers: WorkersConfig
    programs: ProgramsConfig
    settings: Settings
    mappings: MappingsConfig
    users: UsersConfig

    @model_validator(mode="after")
    def _check(self) -> AppConfig:
        known = self.fields.fields
        self._check_users()
        self._check_mappings(known)
        bad = [r.value for r in self.mappings.shared.service_type if r.value not in self.fields.option_ids("service_type")]
        if bad:
            raise ValueError(f"shared.service_type: {bad} are not service_type options")
        if set(self.mappings.stub_query.status_types) != set(self.settings.hmis_queries.status_types):
            raise ValueError("mappings.stub_query.status_types and settings.hmis_queries.status_types must name the same types")
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
        for name in m.shared.not_asked.topics:
            if name not in known or "data_not_collected" not in self.fields.option_ids(name):
                raise ValueError(f"shared.not_asked: {name!r} is not a field with a data_not_collected option")
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

    def _check_users(self) -> None:
        accounts = self.users.accounts
        for key in ("username", "password_env"):
            values = [getattr(a, key) for a in accounts]
            if len(values) != len(set(values)):
                raise ValueError(f"users.yaml: each account needs its own {key}")
        for a in accounts:
            if a.role == "worker" and (a.worker is None or self.workers.worker_for(a.worker) is None):
                raise ValueError(f"users.yaml: worker account {a.username!r} must name a worker in workers.yaml")
            if a.role != "worker" and a.worker is not None:
                raise ValueError(f"users.yaml: {a.role} account {a.username!r} cannot be a worker")

    def parsable_fields(self, kind: str = "new_client") -> dict[str, FieldDef]:
        """Fields a parser may fill from the email, for a new-client or an update draft.

        Fixed values and program defaults are not parsed, and generated text (the case
        note) is returned separately.
        """
        return {
            n: f
            for n, f in self.fields.fields_for(kind).items()
            if f.fixed_value is None and f.fallback != "program_default" and f.type != "text"
        }


_FILES = {
    "fields": "fields.yaml",
    "validation": "validation.yaml",
    "workers": "workers.yaml",
    "programs": "programs.yaml",
    "settings": "settings.yaml",
    "mappings": "mappings.yaml",
    "users": "users.yaml",
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


def with_email_channel(config: AppConfig, enabled: bool) -> AppConfig:
    """A copy of `config` with the email channel switched on or off (the email demo and tests turn it on)."""
    channels = config.settings.channels.model_copy(update={"email": EmailChannelSettings(enabled=enabled)})
    settings = config.settings.model_copy(update={"channels": channels})
    return config.model_copy(update={"settings": settings})


def with_draft_content_views(config: AppConfig, enabled: bool) -> AppConfig:
    """A copy of `config` with the demo-only draft content views switched on or off."""
    demo = config.settings.demo.model_copy(update={"draft_content_views": enabled})
    return config.model_copy(update={"settings": config.settings.model_copy(update={"demo": demo})})


def with_web_reset(config: AppConfig, enabled: bool) -> AppConfig:
    """A copy of `config` with the web demo's reset switched on or off."""
    demo = config.settings.demo.model_copy(update={"web_reset": enabled})
    return config.model_copy(update={"settings": config.settings.model_copy(update={"demo": demo})})


def load_config(directory: Path | str | None = None) -> AppConfig:
    """Load every configuration file and check that they agree with each other."""
    base = Path(directory) if directory is not None else config_dir()
    raw = {key: read_yaml(base / name) for key, name in _FILES.items()}
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"configuration in {base} is invalid:\n{exc}") from exc
