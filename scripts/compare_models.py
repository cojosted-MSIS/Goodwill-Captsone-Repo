"""Run every synthetic sample email through several REALLMS models and score how well each follows the intake rules.

Usage (from the repo root, with REALLMS_API_KEY in .env):
    python scripts/compare_models.py
    python scripts/compare_models.py --models gpt-oss-120b glm-5.2
    python scripts/compare_models.py --list-models

Only the synthetic emails in sample-data/emails/ are sent. Detailed results are written
to scripts/output/ (git-ignored). The API key is never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config_loader import load_config  # noqa: E402
from app.email_message import load_email_file  # noqa: E402
from parser.evaluation import evaluate, load_expected  # noqa: E402
from parser.factory import API_KEY_ENV, build_reallms_parser, load_env  # noqa: E402

DEFAULT_MODELS = ["gpt-oss-120b", "glm-5.2", "gemma-4-31B-it"]


def list_models(config, key: str) -> None:
    s = config.settings.reallms
    response = httpx.get(f"{s.base_url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=s.timeout_seconds)
    print(f"GET /models -> {response.status_code}")
    if response.status_code == 200:
        for item in response.json().get("data", []):
            print(" ", item.get("id"))


def run_model(model: str, config, emails: dict, expected: dict) -> dict:
    calls = {"n": 0}
    http = httpx.Client(
        base_url=config.settings.reallms.base_url,
        timeout=config.settings.reallms.timeout_seconds,
        event_hooks={"request": [lambda request: calls.__setitem__("n", calls["n"] + 1)]},
    )
    parser = build_reallms_parser(config, model=model, http=http)
    rows = []
    for stem, email in emails.items():
        before = calls["n"]
        started = time.perf_counter()
        result = parser.parse(email)
        seconds = time.perf_counter() - started
        ev = evaluate(result, expected[stem], config)
        rows.append({
            "email": stem,
            "ok": result.ok,
            "failure": result.failure.code if result.failure else None,
            "calls": calls["n"] - before,
            "seconds": round(seconds, 1),
            "correct": len(ev.correct),
            "wrong": ev.wrong,
            "missed": ev.missed,
            "inferred": ev.inferred,
            "rule_breaks": ev.rule_breaks,
            "case_note": result.case_note,
        })
        status = "ok" if result.ok else f"FAILED ({result.failure.code})"
        print(f"  {stem:34s} {status:24s} calls={rows[-1]['calls']} {seconds:5.1f}s problems={len(ev.problems)}")
        for problem in ev.problems:
            print(f"      - {problem}")
    return {"model": model, "rows": rows}


def summarize(run: dict) -> dict:
    rows = run["rows"]
    return {
        "model": run["model"],
        "parsed": sum(r["ok"] for r in rows),
        "emails": len(rows),
        "first_try": sum(r["ok"] and r["calls"] == 1 for r in rows),
        "correct": sum(r["correct"] for r in rows),
        "wrong": sum(len(r["wrong"]) for r in rows),
        "missed": sum(len(r["missed"]) for r in rows),
        "inferred": sum(len(r["inferred"]) for r in rows),
        "rule_breaks": sum(len(r["rule_breaks"]) for r in rows),
        "seconds": round(sum(r["seconds"] for r in rows), 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--emails", nargs="+", help="sample email stems (default: all)")
    ap.add_argument("--list-models", action="store_true")
    args = ap.parse_args()

    load_env()
    key = os.environ.get(API_KEY_ENV)
    if not key:
        print(f"{API_KEY_ENV} is not set. Copy .env.example to .env and add your key.")
        return 2
    config = load_config()
    if args.list_models:
        list_models(config, key)
        return 0

    expected = load_expected()
    stems = args.emails or sorted(expected)
    emails = {s: load_email_file(ROOT / "sample-data" / "emails" / f"{s}.txt") for s in stems}

    runs = []
    for model in args.models:
        print(f"\n== {model}")
        runs.append(run_model(model, config, emails, expected))

    print("\nSummary (fewer inferred values and rule breaks is better; inferred values matter most)")
    header = f"{'model':18s} {'parsed':>7s} {'1st try':>7s} {'correct':>7s} {'wrong':>5s} {'missed':>6s} {'inferred':>8s} {'rules':>5s} {'secs':>6s}"
    print(header)
    summaries = [summarize(r) for r in runs]
    for s in summaries:
        print(f"{s['model']:18s} {s['parsed']:>3d}/{s['emails']:<3d} {s['first_try']:>7d} {s['correct']:>7d} {s['wrong']:>5d} "
              f"{s['missed']:>6d} {s['inferred']:>8d} {s['rule_breaks']:>5d} {s['seconds']:>6.1f}")

    out_dir = ROOT / "scripts" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"compare_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"summaries": summaries, "runs": runs}, indent=2), encoding="utf-8")
    print(f"\nDetails written to {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
