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
from .drafts import ORIGIN_LABELS, Candidate, Draft, DraftField
from .messages import phrase

TOKEN = re.compile(r"\[(?P<id>(?:ENC|INT|UPD)-[0-9-]+?)(?: v(?P<version>\d+))?\]")

SECTION_ORDER = ["client", "enrollment", "ce_enrollment", "encounter"]


def draft_sections(draft: Draft, config: AppConfig) -> list[tuple[str, str, list[str]]]:
    """(section id, label, field names) in review order, without the case note, for the draft's kind."""
    if draft.kind == "update":
        names = [n for n in config.fields.update_draft.fields if n != "case_note"]
        return [("service", config.fields.sections["service"].label, names)]
    defs = config.fields.fields_for("new_client")
    out = []
    for section in SECTION_ORDER:
        names = [n for n, f in defs.items() if f.section == section and n != "case_note"]
        if names:
            out.append((section, config.fields.sections[section].label, names))
    return out


def update_intro(draft: Draft) -> list[str]:
    """The first lines of an update review: which client, and which entries a correction changes."""
    if draft.kind != "update":
        return []
    lines = [f"Update for client {draft.client_id} ({draft.client_label}): one visit's case note and service entry."]
    v = draft.verification
    if v is not None and v.decision == "same_client":
        lines.append(phrase(draft.channel, "update_same_client", client_id=v.chosen))
    c = draft.correction
    if c is not None:
        ids = ", ".join(i for i in (c.case_note_id, c.service_id) if i)
        lines.append(phrase(draft.channel, "update_correction", ids=ids))
    return lines + [""]


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


def origin_label(field: DraftField, channel: str = "email") -> str:
    """Where a value came from, in the channel's words ("from your reply" by email, "from your correction" on the web)."""
    if field.origin in ("email_date", "worker"):
        return phrase(channel, f"origin_{field.origin}")
    return ORIGIN_LABELS[field.origin]


def where_from(field: DraftField, channel: str = "email") -> str:
    label = origin_label(field, channel)
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
    lines = lines[:2] + [""] + update_intro(draft) if draft.kind == "update" else lines
    flags = draft.all_flags
    if flags:
        lines.append(f"FLAGGED ({len(flags)}): please check")
        lines += [f"  - {f.message}" for f in flags]
        lines.append("")

    defs = config.fields.fields_for(draft.kind)
    for section, section_label, names in draft_sections(draft, config):
        lines.append(section_label.upper())
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

    if draft.update_in_hmis_yourself:
        lines.append("UPDATE IN HMIS YOURSELF (from your note; never written to an existing client's record)")
        lines += [f"  {row['label']}: {row['value']}" for row in draft.update_in_hmis_yourself]
        lines.append("")
    if (check := same_name_line(draft)) is not None:
        lines.append(f"SAME-NAME CHECK: {check}")
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

    if draft.kind == "new_client":
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
    defs = config.fields.fields_for(draft.kind)
    sections = []
    for section, section_label, names in draft_sections(draft, config):
        shown, collapsed = [], []
        for name in names:
            f = defs[name]
            field = draft.fields.get(name)
            flags = [fl.message for fl in draft.all_flags if fl.field == name]
            row = {
                "name": name,
                "label": f.label,
                "value": None if field is None else display(config, name, field.value),
                "origin": None if field is None else field.origin,
                "origin_label": None if field is None else origin_label(field, draft.channel),
                "source": None if field is None else field.source,
                "confidence": None if field is None else field.confidence,
                "flags": flags,
                "missing": field is None and bool(flags),
            }
            (shown if field is not None or flags else collapsed).append(row)
        if shown or collapsed:
            label, hint = section_label, None
            if draft.channel == "web":
                from .web_wording import WEB_SECTION_LABELS

                label, hint = WEB_SECTION_LABELS.get(section, (section_label, None))
            sections.append({"id": section, "label": label, "hint": hint, "fields": shown, "collapsed": collapsed})

    blocking = draft.blocking_flags
    missing = [defs[f.field].label for f in blocking if f.field in defs]
    note = draft.fields.get("case_note")
    notices = config.mappings.shared.notices
    in_review = draft.state == "in_review"
    subject = compose_review(draft, config)[0] if draft.channel == "email" else draft.subject
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
                                   phrase(draft.channel, "confirm_blocked",
                                          missing="; ".join(missing or [f.message for f in blocking]))),
        "sections": sections,
        "consent": "Client consent and signatures: PENDING. You complete the consent with the neighbor in HMIS.",
        "case_note": None if note is None else note.value,
        "notices": [notices[n].label for n in draft.notices if n in notices],
        "remaining_in_hmis": list(config.fields.remaining_in_hmis) if draft.kind == "new_client" else [],
        "kind": draft.kind,
        "changed_by_worker": list(draft.changed_by_worker),
        "client": {"id": draft.client_id, "label": draft.client_label} if draft.kind == "update" else None,
        "intro": [line for line in update_intro(draft) if line],
        "correction": draft.correction.model_dump() if draft.correction else None,
        "update_in_hmis_yourself": list(draft.update_in_hmis_yourself),
        "same_client": draft.verification is not None and draft.verification.decision == "same_client",
        "same_name_check": same_name_line(draft),
        "footer": (f"Draft v{draft.version}. Nothing has been sent to HMIS. Drafts not confirmed in "
                   f"{config.settings.supervisor_timeout_hours} hours go to your supervisor's queue."),
    }


GRADE_TEXT = {
    "likely_same": "Likely the same person: the last four SSN digits match.",
    "hard_stop": ("Hard stop: the last four SSN digits are missing in your note or in HMIS, so the system cannot "
                  "tell. Please get the digits from the neighbor if you can and reply with them."),
    "warning": "Warning: the last four SSN digits are different. This may be someone else; check before you decide.",
}


def grade_text(grade: str, channel: str = "email") -> str:
    return phrase(channel, "grade_hard_stop") if grade == "hard_stop" else GRADE_TEXT[grade]


def same_name_line(draft: Draft) -> str | None:
    """One line on the same-name check for a new-client review, or None when there is nothing to say."""
    v = draft.verification
    if draft.kind != "new_client" or v is None:
        return None
    if not v.checked:
        return v.not_checked_reason
    if v.decision == "different_person":
        ids = ", ".join(c.client_id for c in v.candidates)
        flagged = " The decision is flagged for supervisor review afterward." if v.supervisor_review else ""
        return phrase(draft.channel, "different_person_line", ids=ids, flagged=flagged)
    if not v.candidates:
        return "no client in HMIS that your project can see has this name and date of birth."
    return None


def verification_subject(draft: Draft) -> str:
    return f"Same name in HMIS: {draft.subject} [{draft.id} v{draft.version}]"


def _last_contact(c: Candidate) -> str:
    when = f"last contact {date.fromisoformat(c.last_contact):%m/%d/%Y}" if c.last_contact else "no contact recorded"
    return when + (f" in the {c.quadrant.upper()} quadrant" if c.quadrant else "")


def _record(c: Candidate) -> str:
    """Entered date, enrollment status, and last service type. Never SSN digits, a date of birth, or note text."""
    entered = f"entered {date.fromisoformat(c.entered):%m/%d/%Y}" if c.entered else "entry date not recorded"
    enrollment = f"enrollment {c.enrollment}" if c.enrollment else "no enrollment recorded"
    service = f"last service: {c.last_service}" if c.last_service else "no service recorded"
    return f"{entered}; {enrollment}; {service}"


def recommended(draft: Draft) -> str | None:
    """The one strong match, or None when there is none or more than one (possible duplicates)."""
    strong = [c.client_id for c in draft.verification.candidates if c.grade == "likely_same"]
    return strong[0] if len(strong) == 1 else None


def duplicates_notice(draft: Draft) -> str | None:
    ids = draft.verification.possible_duplicates
    if len(ids) < 2:
        return None
    named, both = (" and ".join(ids), "both") if len(ids) == 2 else (", ".join(ids[:-1]) + ", and " + ids[-1], "all")
    return (f"{named} {both} match on name, date of birth, and SSN digits. They may be duplicates of each other in "
            "HMIS. Check HMIS and pick the current record; no candidate is recommended. The possible duplicate is "
            "recorded for follow-up.")


def _min_reason(draft: Draft, config: AppConfig) -> int:
    likely = any(c.grade == "likely_same" for c in draft.verification.candidates)
    return config.settings.verification.min_reason_length_matching_digits if likely else 1


def compose_verification(draft: Draft, config: AppConfig, lead: str | None = None) -> tuple[str, str]:
    """The same-name verification email, sent instead of the review while the check is open.

    It names each candidate by client ID, first name and last initial, quadrant, and last
    contact date, never a date of birth or SSN digits."""
    v = draft.verification
    n = len(v.candidates)
    lines = [lead, ""] if lead else []
    lines += [f"HMIS already has {n} client{'s' if n != 1 else ''} with the same name and date of birth as your "
              "new-client note. Nothing has been sent to HMIS.", ""]
    if (notice := duplicates_notice(draft)) is not None:
        lines += [f"POSSIBLE DUPLICATES IN HMIS: {notice}", ""]
    lines.append("CANDIDATES")
    best = recommended(draft)
    for c in v.candidates:
        lines.append(f"  - {c.client_id}  {c.label}  {_last_contact(c)}")
        lines.append(f"    {_record(c)}")
        lines.append(f"    {GRADE_TEXT[c.grade]}" + (" We recommend SAME CLIENT." if c.client_id == best else ""))
    lines += ["", "REPLY WITH ONE OF",
              "  - SAME CLIENT <ID>: this neighbor is already in HMIS. Your note becomes an update (a case note and "
              "a service entry) for that client, and no new client is created.",
              "  - DIFFERENT PERSON: <reason>: this is someone else. Say why, for example an age or appearance "
              "difference. The note is then entered as a new client marked confirmed distinct."]
    minimum = _min_reason(draft, config)
    if minimum > 1:
        lines.append(f"    Because the SSN digits match, the reason must be at least {minimum} characters, and the "
                     "decision is flagged for supervisor review afterward.")
    lines += ["", "CONFIRM is not accepted until you reply SAME CLIENT <ID> or DIFFERENT PERSON with a reason.",
              f"Draft v{draft.version}. Nothing has been sent to HMIS."]
    return verification_subject(draft), "\n".join(lines)


def verification_data(draft: Draft, config: AppConfig) -> dict[str, Any]:
    """The verification email as structured data for the phone screen. No CONFIRM is offered."""
    v = draft.verification
    return {
        "draft_id": draft.id,
        "version": draft.version,
        "open": v.open,
        "candidates": [{"client_id": c.client_id, "label": c.label, "last_contact": _last_contact(c),
                        "record": _record(c), "grade": c.grade, "grade_text": grade_text(c.grade, draft.channel),
                        "recommended": c.client_id == recommended(draft)} for c in v.candidates],
        "recommend": recommended(draft),
        "duplicates_notice": duplicates_notice(draft),
        "min_reason_length": _min_reason(draft, config),
        "confirm_allowed": False,
    }


# Plain-words explanations of an entry failure, by the code the HMIS gateway returns.
# They never include note text, field values, or keys.
ENTRY_FAILURES: dict[str, str] = {
    "service_unavailable": "The mock HMIS did not answer. It may not be running (start it with python -m mock_hmis, demo only).",
    "possible_duplicate": ("HMIS reported a possible duplicate: a client with the same details was already entered. "
                           "In the demo this happens when the mock HMIS still holds clients from an earlier run. "
                           "In real use, search HMIS and resolve it there."),
    "missing_required_field": "HMIS said a required field was missing.",
    "invalid_value": "HMIS did not accept one of the values.",
    "unknown_field": "HMIS did not accept one of the fields.",
    "unknown_client": "HMIS did not recognize the client ID from the earlier step.",
    "out_of_order": "HMIS needs the program enrollment before the Coordinated Entry enrollment.",
    "unknown_entry": "HMIS did not recognize the entry ID being corrected.",
    "edit_not_allowed": "HMIS does not allow this entry to be changed after it is saved.",
    "override_needs_reason": "HMIS needs a reason with a confirmed-distinct override.",
    "unexpected_response": "HMIS sent an answer the system did not understand.",
    "timeout": ("HMIS did not answer in time, so the entry may or may not have been saved. Retrying is safe: "
                "it sends the same key, so HMIS returns the saved entry instead of making a second one."),
}
def failure_meaning(code: str | None, channel: str = "email") -> str:
    """What an entry failure means, in the channel's words."""
    from .web_wording import WEB_ENTRY_FAILURES

    if channel == "web" and code in WEB_ENTRY_FAILURES:
        return WEB_ENTRY_FAILURES[code]
    return ENTRY_FAILURES.get(code or "", ENTRY_FAILURES["unexpected_response"])


ENTRY_STEP_LABELS = [("client_id", "the client record"), ("enrollment_id", "the program enrollment"),
                     ("ce_enrollment_id", "the Coordinated Entry enrollment")]
UPDATE_STEP_LABELS = [("case_note_id", "the case note"), ("service_id", "the service entry")]


def step_labels(draft: Draft) -> list[tuple[str, str]]:
    return UPDATE_STEP_LABELS if draft.kind == "update" else ENTRY_STEP_LABELS


def entry_ids(draft: Draft) -> list[dict[str, Any]]:
    """The identifiers HMIS assigned for this draft, labelled, in entry order."""
    labels = {"client_id": "Client ID", "enrollment_id": "Program enrollment ID",
              "ce_enrollment_id": "Coordinated Entry enrollment ID", "case_note_id": "Case note ID",
              "service_id": "Service ID"}
    return [{"label": labels[attr], "value": getattr(draft.entry, attr)} for attr, _ in step_labels(draft)]


def entry_failure(draft: Draft) -> dict[str, Any] | None:
    """What failed on entry, in plain words, or None if the draft has not failed."""
    if draft.state != "failed":
        return None
    if draft.correction is not None:
        done = draft.correction.done
        step = next((label for attr, label in UPDATE_STEP_LABELS if attr not in done), "an entry")
    else:
        step = next((label for attr, label in step_labels(draft) if not getattr(draft.entry, attr)), "an entry")
    code = draft.last_failure or "unexpected_response"
    return {"code": code, "step": step,
            "explanation": failure_meaning(code, draft.channel),
            "next": phrase(draft.channel, "entry_next")}


def entry_summary(draft: Draft, config: AppConfig) -> list[dict[str, str]]:
    """What Confirm will enter in HMIS, in entry order, shown above the Confirm button."""
    def shown(name: str) -> str | None:
        value = draft.value(name)
        return None if value in (None, "", []) else display(config, name, value)

    def join(*parts: str | None) -> str:
        return ", ".join(p for p in parts if p)

    if draft.correction is not None:
        ids = ", ".join(i for i in (draft.correction.case_note_id, draft.correction.service_id) if i)
        return [{"what": "A correction", "detail": f"Updates the entries already in HMIS ({ids})"}]
    if draft.kind == "update":
        minutes = shown("time_spent_minutes")
        return [
            {"what": "A case note", "detail": join(f"for client {draft.client_id} ({draft.client_label})",
                                                    f"dated {shown('service_date')}" if shown("service_date") else None)},
            {"what": "A service entry", "detail": join(shown("service_type"), f"{minutes} minutes" if minutes else None)},
        ]
    name = " ".join(p for p in (shown("first_name"), shown("last_name")) if p) or "name not stated"
    return [
        {"what": "A new client record", "detail": join(name, f"born {shown('date_of_birth')}" if shown("date_of_birth") else None)},
        {"what": "A program enrollment", "detail": join(shown("project_id"), f"starting {shown('enrollment_date')}"
                                                         if shown("enrollment_date") else None)},
        {"what": "A Coordinated Entry enrollment", "detail": join(f"region {shown('ce_region')}" if shown("ce_region") else None,
                                                                  shown("household_type"))},
    ]


def receipt_data(draft: Draft, config: AppConfig) -> dict[str, Any]:
    """What HMIS accepted, for the receipt screen. Only identifiers HMIS returned on entry.

    For a failed entry it also says, in plain words, which step failed and why."""
    update = draft.kind == "update"
    return {
        "failure": entry_failure(draft),
        "kind": draft.kind,
        "client": {"id": draft.client_id, "label": draft.client_label} if update else None,
        "draft_id": draft.id,
        "subject": draft.subject,
        "state": draft.state,
        "version": draft.version,
        "submitted_at": draft.submitted_at.isoformat() if draft.submitted_at else None,
        "confirmed_at": draft.confirmed_at.isoformat() if draft.confirmed_at else None,
        "hmis_ids": entry_ids(draft),
        "changed_by_worker": [config.fields.fields[n].label for n in draft.changed_by_worker if n in config.fields.fields],
        "search_note": phrase(draft.channel, "receipt_update" if update else "receipt_new_client"),
        "remaining_in_hmis": [] if update else list(config.fields.remaining_in_hmis),
        "corrected_entries": [i for i in ((draft.correction.case_note_id, draft.correction.service_id) if draft.correction else ()) if i],
        "last_failure": draft.last_failure,
    }


def _flagged(draft: Draft, name: str) -> bool:
    return any(f.field == name for f in draft.all_flags)


def staged_view(draft: Draft, config: AppConfig) -> dict[str, Any]:
    """The record as the API sees it: one row per field with value, type, source, and confidence."""
    defs = config.fields.fields_for(draft.kind)
    rows = [{"column": "encounter_id", "value": draft.id, "type": "string", "source": "System", "confidence": "n/a"}]
    if draft.kind == "update":
        rows.append({"column": "hmis_client_id", "value": draft.client_id, "type": "string",
                     "source": "Checked by the read-only lookup", "confidence": "n/a"})
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
        "hmis_id_list": entry_ids(draft),
        "kind": draft.kind,
        "rows": rows,
    }
