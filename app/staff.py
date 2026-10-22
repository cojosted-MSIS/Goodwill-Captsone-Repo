"""Data for the staff screens (task 5.2): the parser run (mockups A2, B2).

The mapped draft (A3, B3) uses review_data, the staged record (A4, B4) uses staged_view, and
the submitted record (B8) uses staged_view with the audit record. Everything here comes from
the staging store. The parser output shown is the verified output kept with the draft; the raw
model reply is never stored.
"""

from __future__ import annotations

from typing import Any

from parser.llm_v2 import build_prompt
from parser.scripted_demo import NAME as SCRIPTED
from parser.shared import clean_source, split_sentences

from .config_loader import AppConfig
from .drafts import Draft
from .review import display
from .storage import Store

STUB_RULES = [
    "Use only what the note states. A field the note does not state stays blank and is flagged.",
    "Never choose \"client doesn't know\", \"client refused\" or \"data not collected\" unless the note says so.",
    "Keep location at quadrant level. Do not record camp locations or intersections.",
    "Do not record anything about people other than the neighbor.",
    "Keep only the last four digits of a Social Security number.",
    "Hedged or second-hand statements are not answers.",
    "Keep each value with the sentence it came from and a confidence level.",
]


def cleaned_note(note: str, config: AppConfig) -> str:
    """The note sentence by sentence through the shared privacy cleaning: SSN masked, precise
    locations and other people's details removed, and a sentence that still matches withheld."""
    return " ".join(clean_source(s, config) for s in split_sentences(note, config))


def instructions(draft: Draft, config: AppConfig) -> dict[str, Any]:
    """The fixed instructions behind the parser that produced this draft."""
    stub = {
        "title": "Rule-based stub (no model)",
        "text": (f"Phrase rules from config/mappings.yaml ({len(config.mappings.stub_rules)} rules), "
                 "plus the rules every parser shares:\n" + "\n".join(f"- {r}" for r in STUB_RULES)),
    }
    if draft.parser == SCRIPTED:
        return {
            "title": "Scripted demo parser (not a live model)",
            "text": ("The rule-based stub's output with the scripted error from "
                     "sample-data/scenarios/scenarios.yaml applied, so the demo always shows the worker "
                     "catching a mistake. This is not a live model result.\n\n" + stub["text"]),
        }
    if draft.parser.startswith("reallms"):
        prompt = build_prompt(config).replace("{note}", "[the worker's note is inserted here, unchanged]")
        return {"title": f"REALLMS prompt {draft.prompt_version}", "text": prompt}
    return stub


def run_data(draft: Draft, config: AppConfig, store: Store, *, scripted_fields: set[str]) -> dict[str, Any]:
    """The parser run for a draft: the note as received, the instructions, and the verified output."""
    intake = store.emails(ref=draft.id, kind="intake")
    output = draft.parse_output or {"fields": {}, "case_note": None, "flags": [], "notices": [], "attempts": 1,
                                    "retry_reasons": [], "elapsed_seconds": None}
    defs = config.fields.fields
    rows = []
    for name, f in output["fields"].items():
        rows.append({
            "name": name,
            "label": defs[name].label if name in defs else name,
            "value": display(config, name, f["value"]),
            "source": f["source"],
            "confidence": f["confidence"],
            "scripted": draft.parser == SCRIPTED and name in scripted_fields,
        })
    return {
        "draft_id": draft.id,
        "subject": draft.subject,
        "state": draft.state,
        "parser": draft.parser,
        "model": draft.model,
        "prompt_version": draft.prompt_version,
        "parsed_at": draft.parsed_at.isoformat(),
        "received_at": draft.email_sent_at.isoformat(),
        "elapsed_seconds": output.get("elapsed_seconds"),
        "attempts": output.get("attempts", 1),
        "retry_reasons": output.get("retry_reasons", []),
        "scripted": draft.parser == SCRIPTED,
        "note": cleaned_note(intake[0].body, config) if intake else None,
        "note_status": ("Shown as received, with the Social Security number masked and precise locations and "
                        "other people's details removed." if intake else
                        "The email copies were deleted under the retention rule after submission."),
        "instructions": instructions(draft, config),
        "output": rows,
        "case_note": output.get("case_note"),
        "flags": output.get("flags", []),
        "notices": [config.mappings.shared.notices[n].label for n in output.get("notices", [])
                    if n in config.mappings.shared.notices],
    }
