"""Score a ParseResult against sample-data/expected_parse.yaml.

Used by the stub parser tests and by scripts/eval_parser.py to compare LLMs on how
well they follow the intake rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config_loader import AppConfig

from .interface import ParseResult

EXPECTED_FILE = Path(__file__).resolve().parent.parent / "sample-data" / "expected_parse.yaml"


def load_expected(path: Path = EXPECTED_FILE) -> dict[str, dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@dataclass
class Evaluation:
    correct: list[str] = field(default_factory=list)
    wrong: list[str] = field(default_factory=list)  # filled with the wrong value
    missed: list[str] = field(default_factory=list)  # stated in the email, left blank
    inferred: list[str] = field(default_factory=list)  # filled although the email does not state it
    rule_breaks: list[str] = field(default_factory=list)  # privacy, case note, search, notices, confidence
    failed: str | None = None

    @property
    def problems(self) -> list[str]:
        if self.failed:
            return [f"parse failed: {self.failed}"]
        return self.wrong + [f"missed {m}" for m in self.missed] + [f"inferred {i}" for i in self.inferred] + self.rule_breaks


def _same(expected: Any, got: Any) -> bool:
    if isinstance(expected, list) and isinstance(got, list):
        return sorted(map(str, expected)) == sorted(map(str, got))
    return str(expected) == str(got)


def evaluate(result: ParseResult, expected: dict[str, Any], config: AppConfig, *, check_confidence: bool = True) -> Evaluation:
    ev = Evaluation()
    if not result.ok:
        ev.failed = result.failure.code
        return ev

    want = expected.get("fields", {})
    any_value = set(expected.get("any_value", []))
    for name in config.parsable_fields():
        got = result.fields.get(name)
        if name in want:
            if got is None:
                ev.missed.append(name)
            elif _same(want[name], got.value):
                ev.correct.append(name)
            else:
                ev.wrong.append(f"{name}: expected {want[name]!r}, got {got.value!r}")
        elif name in any_value:
            (ev.correct if got is not None else ev.missed).append(name)
        elif got is not None:
            ev.inferred.append(f"{name}={got.value!r}")

    if check_confidence:
        for name in expected.get("medium", []):
            if name in result.fields and result.fields[name].confidence == "high":
                ev.rule_breaks.append(f"{name}: hedged wording should not be high confidence")

    stated = bool(result.hmis_search_stated and result.hmis_search_stated.value)
    if stated != expected["hmis_search_stated"]:
        ev.rule_breaks.append(f"hmis_search_stated: expected {expected['hmis_search_stated']}, got {stated}")

    missing_notices = set(expected.get("notices", [])) - set(result.notices)
    if missing_notices:
        ev.rule_breaks.append(f"missing notices: {sorted(missing_notices)}")
    for prefix in expected.get("flags_starting_with", []):
        if not any(f.startswith(prefix) for f in result.flags):
            ev.rule_breaks.append(f"missing flag {prefix}")

    note = (result.case_note or "").lower()
    if not note:
        ev.rule_breaks.append("case note is empty")
    for text in expected.get("case_note_must_include", []):
        if text not in note:
            ev.rule_breaks.append(f"case note should mention {text!r}")
    for text in expected.get("case_note_must_not_include", []):
        if text in note:
            ev.rule_breaks.append(f"case note must not mention {text!r}")

    everything = " ".join(
        [result.case_note or ""]
        + [f"{f.value} {f.source}" for f in result.fields.values()]
        + ([result.hmis_search_stated.source] if result.hmis_search_stated else [])
    ).lower()
    for text in expected.get("never_anywhere", []):
        if text.lower() in everything:
            ev.rule_breaks.append(f"leaked {text!r}")
    return ev
