"""Evaluate the intake parser on synthetic notes, by model.

Adapted from docs/reference/reallms/eval_notes.py for our schema and fields. Runs every case
through the real ReallmsParser (same prompt, schema, checks, and retry as the app) for each
model, and optionally through the rule-based stub as a baseline.

Cases: the sample emails in sample-data/emails/ (scored against expected_parse.yaml) and the
hard notes in sample-data/eval_notes.yaml (scored on their listed fields). ALL SYNTHETIC.

    python scripts/eval_parser.py                      # all three models
    python scripts/eval_parser.py --models gemma-4-31B-it --parser-stub
    python scripts/eval_parser.py --stub-only          # no network, no key

Needs LLM_API_KEY (from .env) unless --stub-only. Writes every result, including the first
reply of each case, to eval_results.json (git-ignored). The key is never printed.

Columns: valid = passed every check (at most one retry); correct = valid and every scored
field right; flagged = failed checks after the retry, so sent to human review.
caught = first reply was wrong and the checks flagged it; false alarm = first reply was right
but flagged; missed = a wrong answer that passed every check (the dangerous case).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config_loader import AppConfig, load_config  # noqa: E402
from app.email_message import IntakeEmail, load_email_file  # noqa: E402
from parser.evaluation import evaluate, load_expected  # noqa: E402
from parser.factory import API_KEY_ENV, ParserStartupError, build_reallms_parser, load_env  # noqa: E402
from parser.interface import ParseResult  # noqa: E402
from parser.llm_checks import to_result  # noqa: E402
from parser.llm_v2 import PROMPT_VERSION  # noqa: E402
from parser.rule_stub import RuleStubParser  # noqa: E402
from parser.shared import finalize  # noqa: E402

MODELS = ["gemma-4-31B-it", "gpt-oss-120b", "qwen3.8-27b"]
EVAL_NOTES = ROOT / "sample-data" / "eval_notes.yaml"
INTAKE = "outreach-intake@goodwill-secure.example"
SENDER = "j.alvarez@goodwill-outreach.example"


@dataclass
class Case:
    id: str
    tests: str
    written_by: str
    email: IntakeEmail
    score: Callable[[ParseResult], list[str]]


def _same(want: Any, got: Any) -> bool:
    if isinstance(want, list) and isinstance(got, list):
        return sorted(map(str, want)) == sorted(map(str, got))
    return str(want) == str(got)


def score_listed(result: ParseResult, note: dict) -> list[str]:
    problems = []
    for field, want in note.get("expect", {}).items():
        got = result.fields.get(field)
        if want == "unknown":
            if got is not None:
                problems.append(f"{field}: expected blank, got {got.value!r}")
        elif got is None:
            problems.append(f"{field}: expected {want!r}, got blank")
        elif not _same(want, got.value):
            problems.append(f"{field}: expected {want!r}, got {got.value!r}")
    if "hmis_search_stated" in note:
        stated = bool(result.hmis_search_stated)
        if stated != note["hmis_search_stated"]:
            problems.append(f"hmis_search_stated: expected {note['hmis_search_stated']}, got {stated}")
    case_note = (result.case_note or "").lower()
    for text in note.get("case_note_must_not_include", []):
        if text in case_note:
            problems.append(f"case note mentions {text!r}")
    return problems


def load_cases(config: AppConfig, only: set[str] | None) -> list[Case]:
    cases = []
    expected = load_expected()
    for stem, want in expected.items():
        email = load_email_file(ROOT / "sample-data" / "emails" / f"{stem}.txt")
        cases.append(Case(stem, "sample email", "team" if stem != "01b_clean_new_client_complete" else "claude-code",
                          email, lambda r, w=want: evaluate(r, w, config, check_confidence=False).problems))
    for note in yaml.safe_load(EVAL_NOTES.read_text(encoding="utf-8")):
        sent = datetime.fromisoformat(str(note["sent"]))
        email = IntakeEmail(sender=SENDER, recipient=INTAKE, subject=f"New client {note['id']}", sent_at=sent,
                            body=note["body"].strip())
        cases.append(Case(note["id"], note["tests"], note["written_by"], email, lambda r, n=note: score_listed(r, n)))
    return [c for c in cases if not only or c.id in only]


def run_parser(label: str, parser, cases: list[Case], config: AppConfig) -> list[dict]:
    rows = []
    for n, case in enumerate(cases, 1):
        replies: list[tuple[int, dict | None, list[str]]] = []
        if hasattr(parser, "_on_reply"):
            parser._on_reply = lambda a, o, p: replies.append((a, o, p))
        started = time.perf_counter()
        result = parser.parse(case.email)
        seconds = time.perf_counter() - started
        problems = case.score(result) if result.ok else []
        row: dict[str, Any] = {
            "parser": label, "case": case.id, "tests": case.tests, "written_by": case.written_by,
            "seconds": round(seconds, 2), "valid": result.ok, "correct": result.ok and not problems,
            "flagged": not result.ok, "failure": result.failure.code if result.failure else None,
            "attempts": result.attempts, "check_problems_first_reply": result.retry_reasons,
            "wrong_after_checks": problems, "result": json.loads(result.model_dump_json()),
        }
        first = next((r for r in replies if r[0] == 1), None)
        if first is not None:
            obj, first_problems = first[1], first[2]
            row["first_reply"] = obj
            first_correct = False
            if obj is not None:
                try:
                    first_result = finalize(to_result(obj, case.email, config, parser=label, model=label,
                                                      prompt_version=PROMPT_VERSION), case.email, config)
                    row["first_reply_wrong"] = case.score(first_result)
                    first_correct = not row["first_reply_wrong"]
                except Exception as exc:  # a reply too broken to convert counts as wrong
                    row["first_reply_wrong"] = [f"could not convert: {type(exc).__name__}"]
            row["caught"] = bool(first_problems) and not first_correct
            row["false_alarm"] = bool(first_problems) and first_correct
        row["missed"] = bool(result.ok and problems)
        status = "ok" if row["correct"] else ("FLAGGED " + str(row["failure"]) if row["flagged"] else "WRONG")
        print(f"[{n}/{len(cases)}] {case.id:32s} {status:24s} {seconds:5.1f}s attempts={result.attempts}")
        for p in problems:
            print(f"      wrong after checks: {p}")
        for p in result.retry_reasons:
            print(f"      check on first reply: {p}")
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "cases": n,
        "valid": sum(r["valid"] for r in rows),
        "correct": sum(r["correct"] for r in rows),
        "flagged": sum(r["flagged"] for r in rows),
        "caught": sum(r.get("caught", False) for r in rows),
        "false_alarm": sum(r.get("false_alarm", False) for r in rows),
        "missed": sum(r["missed"] for r in rows),
        "avg_seconds": round(sum(r["seconds"] for r in rows) / n, 2) if n else 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate the intake parser on synthetic notes")
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--cases", nargs="+", help="case ids to run (default: all)")
    ap.add_argument("--parser-stub", action="store_true", help="also run the rule-based stub as a baseline")
    ap.add_argument("--stub-only", action="store_true", help="run only the stub (no network, no key)")
    ap.add_argument("--out", default=str(ROOT / "eval_results.json"))
    args = ap.parse_args()

    config = load_config()
    cases = load_cases(config, set(args.cases) if args.cases else None)
    load_env()
    import os

    runs: dict[str, list[dict]] = {}
    if args.parser_stub or args.stub_only:
        print("\n=== rule_stub (baseline) ===")
        runs["rule_stub"] = run_parser("rule_stub", RuleStubParser(config), cases, config)
    if not args.stub_only:
        if not os.environ.get(API_KEY_ENV):
            print(f"\n{API_KEY_ENV} is not set. Copy .env.example to .env and add your key, or use --stub-only.")
            return 2
        for model in args.models:
            print(f"\n=== {model} / prompt {PROMPT_VERSION} ===")
            try:
                # The comparison measures not-recommended models on purpose, so it overrides the refusal.
                parser = build_reallms_parser(config, model=model, allow_not_recommended=True)  # GET /models at startup
            except ParserStartupError as exc:
                print(f"skipped: {exc}")
                continue
            runs[model] = run_parser(model, parser, cases, config)

    summaries = {label: summarize(rows) for label, rows in runs.items()}
    print(f"\n=== Summary ({len(cases)} cases, prompt {PROMPT_VERSION}) ===")
    print(f"{'parser':<18}{'valid':>7}{'correct':>9}{'flagged':>9}{'caught':>8}{'false alarm':>13}{'missed':>8}{'avg s':>7}")
    for label, s in summaries.items():
        print(f"{label:<18}{s['valid']:>7}{s['correct']:>9}{s['flagged']:>9}{s['caught']:>8}{s['false_alarm']:>13}"
              f"{s['missed']:>8}{s['avg_seconds']:>7.1f}")
    print("\ncaught/false alarm are about the first reply; missed = wrong answers that passed every check.")
    written = sorted({c.written_by for c in cases})
    print(f"Cases written by: {', '.join(written)}. Notes written with the prompt are not proof of accuracy.")

    out = Path(args.out)
    out.write_text(json.dumps({"prompt_version": PROMPT_VERSION, "run_at": datetime.now().isoformat(timespec="seconds"),
                               "summaries": summaries, "rows": [r for rows in runs.values() for r in rows]},
                              indent=1, default=str), encoding="utf-8")
    print(f"Full results written to {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
