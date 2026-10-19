"""Entry rules the mock HMIS enforces, loaded from config/hmis.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "config" / "hmis.yaml"
RULES_PATH_ENV = "HMIS_MOCK_RULES"

Operation = Literal["create_client", "enroll_in_program", "create_ce_enrollment"]
OPERATIONS: tuple[Operation, ...] = ("create_client", "enroll_in_program", "create_ce_enrollment")


class RulesError(Exception):
    """hmis.yaml is missing or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class When(_Strict):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    field: str
    in_: list[str] = Field(alias="in", min_length=1)


class ConditionalRequirement(_Strict):
    field: str
    when: When


class OperationRules(_Strict):
    accepted: list[str]
    required: list[str]
    required_when: list[ConditionalRequirement] = []
    must_equal: dict[str, Any] = {}

    @model_validator(mode="after")
    def _check(self) -> OperationRules:
        named = set(self.required) | {r.field for r in self.required_when} | set(self.must_equal)
        unknown = named - set(self.accepted)
        if unknown:
            raise ValueError(f"rules name fields the operation does not accept: {sorted(unknown)}")
        return self

    def missing(self, fields: dict[str, Any]) -> list[str]:
        """Required fields with no value, including conditional ones that apply."""
        needed = list(self.required)
        needed += [r.field for r in self.required_when if fields.get(r.when.field) in r.when.in_]
        return [name for name in needed if _is_blank(fields.get(name))]

    def wrong_values(self, fields: dict[str, Any]) -> list[str]:
        return [name for name, value in self.must_equal.items() if fields.get(name) != value]


class DuplicateCheck(_Strict):
    enabled: bool
    match_on: list[str] = Field(min_length=1)


class IdPrefixes(_Strict):
    client: str
    enrollment: str
    ce_enrollment: str


class HmisRules(_Strict):
    operations: dict[Operation, OperationRules]
    duplicate_check: DuplicateCheck
    id_prefixes: IdPrefixes

    @model_validator(mode="after")
    def _check(self) -> HmisRules:
        if set(self.operations) != set(OPERATIONS):
            raise ValueError(f"operations must be exactly {list(OPERATIONS)}")
        accepted = set(self.operations["create_client"].accepted)
        if set(self.duplicate_check.match_on) - accepted:
            raise ValueError("duplicate_check.match_on must name create_client fields")
        return self


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == []


def load_rules(path: Path | str | None = None) -> HmisRules:
    target = Path(path or os.environ.get(RULES_PATH_ENV, DEFAULT_RULES_PATH))
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
        return HmisRules.model_validate(raw)
    except FileNotFoundError as exc:
        raise RulesError(f"missing rules file {target}") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise RulesError(f"{target.name} is invalid:\n{exc}") from exc
