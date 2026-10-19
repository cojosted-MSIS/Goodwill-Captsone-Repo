"""Draft validation (task 4.2). Rules come from config/fields.yaml and config/validation.yaml.

Validation only flags. It never changes, completes, or corrects a value.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .config_loader import AppConfig
from .drafts import Draft, Flag

QUESTIONS: dict[str, str] = {
    "project_id": "Which project should the neighbor be enrolled in? Reply with the project name.",
    "ce_region": "Which Coordinated Entry region? Reply with the region number, for example \"CE region 7\".",
}


def _blank(value: Any) -> bool:
    return value is None or value == "" or value == []


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def validate(draft: Draft, config: AppConfig) -> list[Flag]:
    flags: list[Flag] = []
    defs = config.fields.fields

    # Required and conditionally required fields
    for name, f in defs.items():
        rule = f.required_when
        needed = f.required or (rule is not None and draft.value(rule.field) in rule.in_)
        if needed and _blank(draft.value(name)):
            reason = ""
            if rule is not None:
                reason = f" It is needed because {defs[rule.field].label.lower()} is \"{_label(config, rule.field, draft.value(rule.field))}\"."
            message = QUESTIONS.get(name, f"{f.label} is missing. Please reply with it.{reason}")
            flags.append(Flag(code="missing", field=name, message=message, blocking=True))

    reference = {"encounter_date": draft.encounter_date, "email_date": draft.email_sent_at.date()}
    for name, df in draft.fields.items():
        f = defs.get(name)
        if f is None or _blank(df.value):
            continue
        options = config.fields.option_ids(name)
        if f.type == "enum" and options and df.value not in options:
            flags.append(Flag(code="invalid", field=name, blocking=True, message=f"{f.label}: {df.value!r} is not an allowed answer."))
        if f.type == "multi_enum":
            values = df.value if isinstance(df.value, list) else [df.value]
            if any(v not in options for v in values) or (f.max_items and len(values) > f.max_items):
                flags.append(Flag(code="invalid", field=name, blocking=True, message=f"{f.label}: check the answers."))
        pattern = config.validation.formats.get(name)
        if pattern and not re.search(pattern, str(df.value)):
            flags.append(Flag(code="format", field=name, blocking=True, message=f"{f.label} is not in the expected format."))
        rule = config.validation.dates.get(name)
        if rule:
            value = _as_date(df.value)
            if value is None:
                flags.append(Flag(code="date", field=name, blocking=True, message=f"{f.label} is not a valid date."))
                continue
            if rule.not_before and value < rule.not_before:
                flags.append(Flag(code="date", field=name, blocking=True,
                                  message=f"{f.label} {value:%m/%d/%Y} is before {rule.not_before:%m/%d/%Y}. Check it."))
            if rule.not_after and value > reference[rule.not_after]:
                anchor = "the encounter date" if rule.not_after == "encounter_date" else "the date of your email"
                flags.append(Flag(code="date", field=name, blocking=True,
                                  message=f"{f.label} {value:%m/%d/%Y} is after {anchor}. Check it."))
        if df.confidence in config.validation.confidence.flag:
            flags.append(Flag(code="low_confidence", field=name, message=f"{f.label}: the parser was not sure. Check it."))
    return flags


def _label(config: AppConfig, field: str, option: Any) -> str:
    enum = config.fields.fields[field].enum
    if not enum:
        return str(option)
    return next((o.label for o in config.fields.enums[enum] if o.id == option), str(option))
