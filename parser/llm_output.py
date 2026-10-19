"""Read and check the LLM's reply. Nothing here trusts the model.

The reply must be one JSON object of the expected shape. Every filled value must be a
valid value for its field, cite a source sentence that appears in the email, and, for
dates, cite a sentence that actually contains the day.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.config_loader import AppConfig, FieldDef
from app.email_message import IntakeEmail

from .interface import ParsedField, ParseResult


class LlmOutputError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class _FieldOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: Any = None
    source: str | None = None
    confidence: Literal["high", "medium", "low"] | None = None


class _Output(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hmis_search_stated: _FieldOut
    fields: dict[str, _FieldOut]
    case_note: str
    notices: list[str] = []


def extract_json(content: str) -> Any:
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LlmOutputError(["The reply did not contain a JSON object."])
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LlmOutputError([f"The reply was not valid JSON ({exc.msg} at character {exc.pos})."]) from exc


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().strip("\"'").rstrip(".").lower()


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == []


def _check_value(name: str, f: FieldDef, value: Any, source: str, config: AppConfig) -> str | None:
    options = config.fields.option_ids(name)
    if name == "project_id":
        ids = [p.project_id for p in config.programs.projects.values()]
        return None if value in ids else f"{name}: {value!r} is not one of {ids}."
    if name == "ce_region":
        return None if isinstance(value, str) and value.isdigit() else f"{name}: give the region number as a string."
    if f.type == "enum":
        return None if value in options else f"{name}: {value!r} is not an allowed value."
    if f.type == "multi_enum":
        if not isinstance(value, list) or not all(v in options for v in value):
            return f"{name}: give a list of allowed values."
        if f.max_items and len(value) > f.max_items:
            return f"{name}: at most {f.max_items} values."
        return None
    if f.type == "date":
        try:
            day = date.fromisoformat(value).day
        except (TypeError, ValueError):
            return f"{name}: give a date as YYYY-MM-DD, or null."
        if not re.search(rf"(?<!\d)0?{day}(?!\d)", source):
            return f"{name}: the source does not state the day. Use null when the note gives only a month or year."
        return None
    if f.type == "ssn_last4":
        return None if isinstance(value, str) and re.fullmatch(r"\d{4}", value) else f"{name}: exactly four digits."
    if f.type == "list":
        ok = isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
        return None if ok else f"{name}: give a list of strings."
    if f.type == "boolean":
        return None if isinstance(value, bool) else f"{name}: give true or false."
    return None if isinstance(value, str) and value.strip() else f"{name}: give text."


def validate_output(data: Any, email: IntakeEmail, config: AppConfig, parser_name: str) -> ParseResult:
    try:
        out = _Output.model_validate(data)
    except ValidationError as exc:
        raise LlmOutputError(
            [f"{'.'.join(str(p) for p in e['loc']) or 'reply'}: {e['msg']}" for e in exc.errors()]
        ) from exc

    body = _norm(email.body)
    all_fields = config.fields.fields
    parsable = config.parsable_fields()
    problems: list[str] = []
    fields: dict[str, ParsedField] = {}

    unknown = sorted(set(out.fields) - set(all_fields))
    if unknown:
        problems.append(f"Unknown field names: {', '.join(unknown)}. Use only the names in the field list.")

    for name, f in out.fields.items():
        if name not in parsable or _is_blank(f.value):
            continue  # fixed values and program defaults are never taken from the model
        if not f.source or not f.confidence:
            problems.append(f"{name}: a value needs a source sentence and a confidence.")
            continue
        if _norm(f.source) not in body:
            problems.append(f"{name}: the source must be copied exactly from the note.")
            continue
        if (problem := _check_value(name, parsable[name], f.value, f.source, config)) is not None:
            problems.append(problem)
            continue
        fields[name] = ParsedField(value=f.value, source=f.source.strip(), confidence=f.confidence)

    search = out.hmis_search_stated
    hmis_search = None
    if not isinstance(search.value, bool):
        problems.append("hmis_search_stated.value must be true or false.")
    elif search.value:
        if not search.source or _norm(search.source) not in body:
            problems.append("hmis_search_stated: the source must be copied exactly from the note.")
        else:
            hmis_search = ParsedField(value=True, source=search.source.strip(), confidence=search.confidence or "high")

    known_notices = set(config.mappings.shared.notices)
    bad_notices = sorted(set(out.notices) - known_notices)
    if bad_notices:
        problems.append(f"Unknown notice ids: {', '.join(bad_notices)}.")
    if not out.case_note.strip():
        problems.append("case_note must not be empty.")

    if problems:
        raise LlmOutputError(problems)
    return ParseResult(
        parser=parser_name,
        fields=fields,
        hmis_search_stated=hmis_search,
        case_note=out.case_note.strip(),
        notices=[n for n in out.notices if n in known_notices],
    )
