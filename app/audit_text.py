"""Audit events in plain words, for the supervisor and staff screens (add-web-application, Stage 3d).

Each description uses only fixed words and safe details: versions, steps, identifiers, field names,
and counts. It never echoes free text (a worker's reason, or the first word of a reply), so a
screen can show `what` without showing neighbor information.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

Event = dict[str, Any]

# Details never sent to staff or supervisor screens: words the worker wrote.
FREE_TEXT_DETAILS = ("reason", "command")

STEP_LABELS = {"client": "the client record", "enrollment": "the program enrollment", "ce_enrollment": "the Coordinated Entry enrollment",
               "case_note": "the case note", "service": "the service entry"}
REFUSED = {"missing_parameters": "details were missing", "no_query_type": "the question was not one of the four kinds",
           "unavailable": "HMIS queries were not available", "read_failed": "HMIS could not be read"}
QUERY_NAMES = {"briefing": "Briefing", "lookup": "Lookup", "status": "Status check", "no_contact": "No-contact watchlist"}
DELETION_NAMES = {"unsubmitted_draft": "Unsubmitted draft", "held_note": "Held note"}
STATUS_NAMES = {"id_document": "ID document", "housing_assessment": "housing assessment"}


def _plural(n: Any, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _step(e: Event) -> str:
    label = STEP_LABELS.get(str(e.get("step")), "an entry")
    if e.get("ok"):
        return f"HMIS accepted {label} ({e.get('identifier')})."
    return f"HMIS did not accept {label}."


def _who(e: Event) -> str:
    if e.get("client_id"):
        return f"by client ID {e['client_id']}"
    return "by name and date of birth (both given)"


def _query(e: Event) -> str:
    kind = e.get("query_type")
    name = QUERY_NAMES.get(str(kind), "Query")
    quadrant = f", {str(e['quadrant']).upper()} quadrant" if e.get("quadrant") else ""
    if kind == "lookup":
        head = f"{name} {_who(e)}"
    elif kind == "status":
        head = f"{name} ({STATUS_NAMES.get(str(e.get('status_type')), 'status')}) {_who(e)}"
    else:
        head = f"{name}{quadrant}"
    return f"{head}. {_plural(e.get('rows', 0), 'row')}."


def _refused(e: Event) -> str:
    return f"Nothing was run: {REFUSED.get(str(e.get('refused')), 'the query could not be read')}."


def _decided(e: Event) -> str:
    if e.get("decision") == "same_client":
        return f"Worker chose Same person ({e.get('chosen')}): the note became a visit for that client."
    flagged = " Flagged for supervisor review: the last four SSN digits matched." if e.get("supervisor_review") else ""
    return f"Worker chose Different person, with a reason.{flagged}"


def _fields(e: Event, key: str) -> str:
    return ", ".join(str(f).replace("_", " ") for f in e.get(key) or []) or "none"


DESCRIPTIONS: dict[str, str | Callable[[Event], str]] = {
    "draft_created": lambda e: f"Draft version {e.get('version', 1)} was made from the worker's note.",
    "parse_failed": "The note could not be drafted.",
    "hmis_search_not_stated": "Note held: it did not say HMIS was searched.",
    "hmis_search_confirmed_by_worker": "Worker confirmed they searched HMIS.",
    "ready_for_review": lambda e: f"Version {e.get('version')} was ready for the worker to check.",
    "verification_requested": lambda e: f"Same-name check asked of the worker for version {e.get('version')}.",
    "verification_answer_refused": "The answer to the same-name check was not accepted.",
    "verification_decided": _decided,
    "same_name_found": lambda e: f"HMIS has {_plural(e.get('candidates', 0), 'client')} with the same name and date of birth.",
    "open_draft_same_name": "Another open draft has the same name and date of birth.",
    "possible_duplicate_pair_in_hmis": "Possible duplicate records noted in HMIS for follow-up.",
    "lookup": lambda e: f"Read-only lookup in HMIS: {_plural(e.get('rows', 0), 'row')}.",
    "corrections_applied": lambda e: f"Worker made a correction ({_fields(e, 'changed_fields')}): version {e.get('to_version')}.",
    "rephrase_requested": "A correction could not be matched to a field.",
    "confirm_blocked": lambda e: f"Confirm refused for version {e.get('version')}: still needed ({_fields(e, 'blocking')}).",
    "confirm_blocked_verification": "Confirm refused: the same-name check was still open.",
    "confirm_of_old_version": lambda e: f"Confirm refused: version {e.get('confirmed')} was not the current version.",
    "confirmed": lambda e: f"Worker confirmed version {e.get('version')}.",
    "confirmed_distinct_override": "Entered with the confirmed-different-person override.",
    "entry_step": _step,
    "retry_requested": "Worker asked to try the entry again.",
    "submitted": "Entered in HMIS.",
    "hmis_idempotent_replay": "HMIS returned the result it had already saved: nothing new was made.",
    "idempotent_replay": "A repeated request got the first result: nothing new was made.",
    "correction_drafted": lambda e: f"A correction to entries already in HMIS was drafted as version {e.get('version')}.",
    "correction_step": lambda e: f"Correction: HMIS {'accepted' if e.get('ok') else 'did not accept'} the change.",
    "correction_entered": "The correction was entered in HMIS.",
    "correction_refused_stubbed": "Correction refused: the details are no longer kept here.",
    "correction_refused_not_our_entry": "Correction refused: that entry was not made by this system.",
    "update_client_candidates": lambda e: f"{_plural(e.get('candidates', 0), 'client')} offered for the worker to pick.",
    "update_client_chosen": lambda e: f"Worker picked client {e.get('client_id')}.",
    "update_client_ids_disagree": "The note gave more than one client ID. Nothing was drafted.",
    "update_client_id_invalid": "The note's client ID was not in the HMIS format. Nothing was drafted.",
    "update_client_id_needed": "The note did not say which client. Nothing was drafted.",
    "update_client_not_found": "The client was not found. Nothing was drafted.",
    "update_client_check_failed": "HMIS could not be read to check the client. Nothing was drafted.",
    "action_ignored": "An action from someone other than the author was ignored.",
    "action_ignored_not_author": "An action from someone other than the author was ignored.",
    "action_after_expiry": "An action arrived after the draft went to the supervisor queue.",
    "web_refused_not_owner": "Someone other than the author tried to open this and was refused.",
    "sealed_note_refused": "A note saved on a device was refused when it arrived. Nothing was drafted.",
    "expired_to_supervisor_queue": "Not confirmed in time: moved to the supervisor queue.",
    "copies_deleted": lambda e: f"{e.get('count', 0)} stored {'copy' if e.get('count') == 1 else 'copies'} deleted under the retention rule.",
    "deleted_after_retention": lambda e: f"{DELETION_NAMES.get(str(e.get('deletion_type')), 'Record')} deleted under the retention rule.",
    "query": _query,
    "query_refused": _refused,
}


def describe(event: Event) -> str:
    text = DESCRIPTIONS.get(str(event.get("event")), "Recorded event.")
    return text(event) if callable(text) else text


def hide_numbers(text: str) -> str:
    """A worker's written reason for a supervisor: never SSN digits or a date, even if the worker wrote them."""
    text = re.sub(r"\*{3}-\*{2}-\d{4}", "[number hidden]", text)
    text = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", "[date hidden]", text)
    return re.sub(r"\d{4,}", "[number hidden]", text)
