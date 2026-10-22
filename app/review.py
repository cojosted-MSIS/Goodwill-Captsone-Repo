"""The review email (task 4.3) and the staged-record view.

Every filled or flagged field is shown beside where it came from, flags come first, and the
email always says that nothing has been sent to HMIS. A blank field with no flag is not
needed for this neighbor, so it is named on one "not needed" line per section (the phone
screen collapses the same fields). The Social Security digits are masked.
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
        not_needed = []
        for name in names:
            field = draft.fields.get(name)
            label = defs[name].label
            if field is None and _flagged(draft, name):
                lines.append(f"  {label}: NOT STATED, please reply with it")
            elif field is None:
                not_needed.append(label)  # blank and not flagged: not needed for this neighbor
            else:
                lines.append(f"  {label}: {display(config, name, field.value)}  [{where_from(field)}]")
        if not_needed:
            lines.append(f"  {len(not_needed)} more field{'s' if len(not_needed) > 1 else ''} not needed for this "
                         f"neighbor, left blank: {', '.join(not_needed)}")
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


def review_data(draft: Draft, config: AppConfig, *, scripted_label: str | None = None) -> dict[str, Any]:
    """The review email as structured data for the phone screen (mockups A5, B5, B7).

    Same content as compose_review. Filled and flagged fields are shown. A blank field with
    no flag is not needed for this neighbor and is counted in `collapsed`. CONFIRM is
    allowed only while the draft is in review and has no blocking flag."""
    defs = config.fields.fields
    sections = []
    for section in SECTION_ORDER:
        shown, collapsed = [], []
        for name, f in defs.items():
            if f.section != section or name == "case_note":
                continue
            field = draft.fields.get(name)
            flags = [fl.message for fl in draft.all_flags if fl.field == name]
            row = {
                "name": name,
                "label": f.label,
                "value": None if field is None else display(config, name, field.value),
                "origin": None if field is None else field.origin,
                "origin_label": None if field is None else ORIGIN_LABELS[field.origin],
                "source": None if field is None else field.source,
                "confidence": None if field is None else field.confidence,
                "flags": flags,
                "missing": field is None and bool(flags),
            }
            (shown if field is not None or flags else collapsed).append(row)
        if shown or collapsed:
            sections.append({"id": section, "label": config.fields.sections[section].label,
                             "fields": shown, "collapsed": collapsed})

    blocking = draft.blocking_flags
    missing = [defs[f.field].label for f in blocking if f.field in defs]
    note = draft.fields.get("case_note")
    notices = config.mappings.shared.notices
    in_review = draft.state == "in_review"
    subject, _ = compose_review(draft, config)
    return {
        "draft_id": draft.id,
        "subject": subject,
        "revised": draft.version > 1,
        "version": draft.version,
        "state": draft.state,
        "parser": draft.parser,
        "model": draft.model,
        "scripted_label": scripted_label if draft.parser == "scripted_demo" else None,
        "flags": [{"field": f.field, "label": defs[f.field].label if f.field in defs else None,
                   "message": f.message, "blocking": f.blocking} for f in draft.all_flags],
        "missing": missing,
        "confirm_allowed": in_review and not blocking,
        "confirm_blocked_reason": (None if not in_review or not blocking else
                                   "CONFIRM is blocked until you reply with: " + "; ".join(missing or [f.message for f in blocking])),
        "sections": sections,
        "consent": "Client consent and signatures: PENDING. You complete the consent with the neighbor in HMIS.",
        "case_note": None if note is None else note.value,
        "notices": [notices[n].label for n in draft.notices if n in notices],
        "remaining_in_hmis": list(config.fields.remaining_in_hmis),
        "footer": (f"Draft v{draft.version}. Nothing has been sent to HMIS. Drafts not confirmed in "
                   f"{config.settings.supervisor_timeout_hours} hours go to your supervisor's queue."),
    }


# Plain-words explanations of an entry failure, by the code the HMIS gateway returns.
# They never include note text, field values, or keys.
ENTRY_FAILURES: dict[str, str] = {
    "service_unavailable": "The mock HMIS did not answer. It may not be running (start it with python -m mock_hmis).",
    "possible_duplicate": ("HMIS reported a possible duplicate: a client with the same details was already entered. "
                           "In the demo this happens when the mock HMIS still holds clients from an earlier run. "
                           "In real use, search HMIS and resolve it there."),
    "missing_required_field": "HMIS said a required field was missing.",
    "invalid_value": "HMIS did not accept one of the values.",
    "unknown_field": "HMIS did not accept one of the fields.",
    "unknown_client": "HMIS did not recognize the client ID from the earlier step.",
    "out_of_order": "HMIS needs the program enrollment before the Coordinated Entry enrollment.",
    "unexpected_response": "HMIS sent an answer the system did not understand.",
}
ENTRY_STEP_LABELS = [("client_id", "the client record"), ("enrollment_id", "the program enrollment"),
                     ("ce_enrollment_id", "the Coordinated Entry enrollment")]


def entry_failure(draft: Draft) -> dict[str, Any] | None:
    """What failed on entry, in plain words, or None if the draft has not failed."""
    if draft.state != "failed":
        return None
    step = next((label for attr, label in ENTRY_STEP_LABELS if not getattr(draft.entry, attr)), "an entry")
    code = draft.last_failure or "unexpected_response"
    return {"code": code, "step": step,
            "explanation": ENTRY_FAILURES.get(code, ENTRY_FAILURES["unexpected_response"]),
            "next": "Your confirmed draft is kept. Reply RETRY to try again; steps HMIS already accepted are not repeated."}


def receipt_data(draft: Draft, config: AppConfig) -> dict[str, Any]:
    """What HMIS accepted, for the receipt screen. Only identifiers HMIS returned on entry.

    For a failed entry it also says, in plain words, which step failed and why."""
    ids = draft.entry
    return {
        "failure": entry_failure(draft),
        "draft_id": draft.id,
        "subject": draft.subject,
        "state": draft.state,
        "version": draft.version,
        "submitted_at": draft.submitted_at.isoformat() if draft.submitted_at else None,
        "confirmed_at": draft.confirmed_at.isoformat() if draft.confirmed_at else None,
        "hmis_ids": [
            {"label": "Client ID", "value": ids.client_id},
            {"label": "Program enrollment ID", "value": ids.enrollment_id},
            {"label": "Coordinated Entry enrollment ID", "value": ids.ce_enrollment_id},
        ],
        "changed_by_worker": [config.fields.fields[n].label for n in draft.changed_by_worker if n in config.fields.fields],
        "search_note": "You searched HMIS and found no match. The system only entered data and never searched HMIS.",
        "remaining_in_hmis": list(config.fields.remaining_in_hmis),
        "last_failure": draft.last_failure,
    }


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
