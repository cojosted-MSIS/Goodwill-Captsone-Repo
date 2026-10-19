"""scripts/eval_parser.py runs offline with the stub and scores cases correctly."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

from app.config_loader import load_config
from parser.interface import ParsedField, ParseResult

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("eval_parser", ROOT / "scripts" / "eval_parser.py")
eval_parser = importlib.util.module_from_spec(spec)
sys.modules["eval_parser"] = eval_parser  # dataclasses look the module up here
spec.loader.exec_module(eval_parser)


def test_every_eval_note_has_expected_answers_and_an_author():
    notes = yaml.safe_load((ROOT / "sample-data" / "eval_notes.yaml").read_text(encoding="utf-8"))
    assert len(notes) >= 15
    for note in notes:
        assert note["expect"] and note["written_by"] and note["tests"]
        assert "hmis_search_stated" in note


def test_eval_notes_cover_the_hard_cases_from_the_guide():
    tests = " ".join(n["tests"] for n in yaml.safe_load((ROOT / "sample-data" / "eval_notes.yaml").read_text(encoding="utf-8")))
    for case in ("hearsay", "past vs current", "didn't sleep outside", "two people", "DOB", "typos", "injected"):
        assert case in tests, case


def test_score_listed_treats_unknown_as_must_be_blank():
    result = ParseResult(parser="x", prompt_version="x",
                         fields={"veteran_status": ParsedField(value="yes", source="s", confidence="high")})
    problems = eval_parser.score_listed(result, {"expect": {"veteran_status": "unknown"}})
    assert problems == ["veteran_status: expected blank, got 'yes'"]


def test_stub_only_run_writes_results(tmp_path, monkeypatch):
    out = tmp_path / "eval_results.json"
    monkeypatch.setattr(sys, "argv", ["eval_parser.py", "--stub-only", "--out", str(out)])
    assert eval_parser.main() == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summaries"]["rule_stub"]["cases"] == len(eval_parser.load_cases(load_config(), None))
