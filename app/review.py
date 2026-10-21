"""The review email (task 4.3) and the staged-record view.

Every field is shown beside where it came from, flags come first, and the email always
says that nothing has been sent to HMIS. The Social Security digits are masked.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .config_loader import AppConfig
from .drafts import ORIGIN_LABELS, Draft, DraftField

TOKEN = re.compile(r"\[(?P<id>(?:ENC|INT)-[0-9-]+?)(?: v(?P<version>\d+))?\]")

SECTION_ORDER = ["client", "enrollment", "ce_enrollment", "encounter"]


def review_subject(draft: Draft) -> str:
    return f"Please confirm: {draft.subject} [{draft.id} v{draft.version}]"


def parse_token(subject: str) -> tuple[str, int | None] | None:
    match = TOKEN.search(subject)
    if not match:
        return None
    version = match.group("version")
    return match.group("id"), int(version) if version else None


def display(config: AppConfig, name: str, value: Any) -> str:
    f = config.fields.fields.get(name)
    if value is None or value == [] or value == "":
        return "(blank)"
    if f is not None and f.type == "ssn_last4":
        return f"***-**-{value}"
    if f is not None and f.enum:
        labels = {o.id: o.label for o in config.fields.enums[f.enum]}
        values = value if isinstance(value, list) else [value]
        return "; ".join(labels.get(v, str(v)) for v in values)
    if name == "project_id":
        return next((p.label for p in config.programs.projects.values() if p.project_id == value), str(value))
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return "; ".join(map(str, value))
    if f is not None and f.type == "date":
        try:
            return date.fromisoformat(str(value)).strftime("%m/%d/%Y")
        except ValueError:
            return str(value)
    return str(value)


def where_from(field: DraftField) -> str:
    label = ORIGIN_LABELS[field.origin]
    if field.origin in ("email", "worker") and field.source:
        return f'{label}: "{field.source}"'
    if field.origin == "email_date" and field.source:
        return f'{label} ("{field.source}")'
    return label


def compose_review(draft: Draft, config: AppConfig) -> tuple[str, str]:
    lines = [
        f"Here is your draft, version {draft.version}. Nothing has been sent to HMIS.",
        "Reply CONFIRM if it is correct, or reply with changes in plain words.",
        "",
    ]
    flags = draft.all_flags
    if flags:
        lines.append(f"FLAGGED ({len(flags)}): please check")
        lines += [f"  - {f.message}" for f in flags]
        lines.append("")

    defs = config.fields.fields
    for section in SECTION_ORDER:
        names = [n for n, f in defs.items() if f.section == section and n != "case_note"]
        if not names:
            continue
        lines.append(config.fields.sections[section].label.upper())
        for name in names:
            field = draft.fields.get(name)
            label = defs[name].label
            if field is None:
                lines.append(f"  {label}: NOT STATED, please reply with it" if _flagged(draft, name) else f"  {label}: (blank)")
            else:
                lines.append(f"  {label}: {display(config, name, field.value)}  [{where_from(field)}]")
        if section == "ce_enrollment":
            lines.append("  Client consent and signatures: PENDING. You complete the consent with the neighbor in HMIS.")
        lines.append("")

    note = draft.fields.get("case_note")
    lines.append("CASE NOTE (generated from your note: read it for wording, not just accuracy)")
    lines.append(f"  {note.value if note else '(none)'}")
    lines.append("")

    notices = config.mappings.shared.notices
    if draft.notices:
        lines.append("NOTES")
        lines += [f"  - {notices[n].label}" for n in draft.notices if n in notices]
        lines.append("")

    lines.append("REMAINING IN HMIS (complete these yourself)")
    lines += [f"  - {item}" for item in config.fields.remaining_in_hmis]
    lines.append("")
    hours = config.settings.supervisor_timeout_hours
    lines.append(f"Draft v{draft.version}. Nothing has been sent to HMIS. "
                 f"Drafts not confirmed in {hours} hours go to your supervisor's queue.")
    return review_subject(draft), "\n".join(lines)


def _flagged(draft: Draft, name: str) -> bool:
    return any(f.field == name for f in draft.all_flags)


def staged_view(draft: Draft, config: AppConfig) -> dict[str, Any]:
    """The record as the API sees it: one row per field with value, type, source, and confidence."""
    defs = config.fields.fields
    rows = [{"column": "encounter_id", "value": draft.id, "type": "string", "source": "System", "confidence": "n/a"}]
    for name, f in defs.items():
        field = draft.fields.get(name)
        rows.append({
            "column": name,
            "label": f.label,
            "value": None if field is None else field.value,
            "type": f.type,
            "source": "not stated" if field is None else where_from(field),
            "confidence": ("worker" if field and field.origin == "worker" else
                           "review" if field and field.origin == "generated" else
                           field.confidence if field and field.confidence else "n/a"),
        })
    rows.append({"column": "worker_id", "value": draft.worker_id, "type": "string", "source": "Sender", "confidence": "n/a"})
    blocked = draft.state in ("draft", "in_review")
    return {
        "encounter_id": draft.id,
        "state": draft.state,
        "version": draft.version,
        "status": ("STAGED: not sent to HMIS. Submission is blocked until the worker replies CONFIRM."
                   if blocked else f"{draft.state.upper()}"),
        "parser": draft.parser,
        "model": draft.model,
        "prompt_version": draft.prompt_version,
        "parsed_at": draft.parsed_at.isoformat(),
        "flags": [f.model_dump() for f in draft.all_flags],
        "hmis_ids": draft.entry.model_dump(),
        "rows": rows,
    }
