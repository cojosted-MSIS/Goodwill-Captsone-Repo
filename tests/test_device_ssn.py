"""add-web-application, Stage 4c: the device and the server apply the same SSN rules.

One table of cases (tests/ssn_cases.json) runs through the server's guard (app/ssn_guard.py) and the
device's guard (ui/web/ssn.js, in Node, compiled from the rules the server sends at sign-in). Specs:
openspec/changes/add-web-application/specs/offline-sync/spec.md ("Keep full SSNs out of the device
queue"). Synthetic data only.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from app.config_loader import load_config
from app.ssn_guard import guard

from .conftest import REPO_ROOT
from .test_web_screens import node

CASES = json.loads((REPO_ROOT / "tests" / "ssn_cases.json").read_text(encoding="utf-8"))
CONFIG = load_config()


def rules() -> dict:
    ssn = CONFIG.mappings.shared.ssn
    return {"any_full_number": ssn.any_full_number, "possible_full_number": ssn.possible_full_number,
            "invalid_full_number_patterns": [{"pattern": r.pattern, "label": r.label} for r in CONFIG.validation.ssn.invalid_full_number_patterns]}


def on_device(texts: list[str]) -> list[dict]:
    plan = {"module": str(REPO_ROOT / "ui" / "web" / "ssn.js"), "rules": rules(), "texts": texts}
    run = subprocess.run([node(), str(REPO_ROOT / "tests" / "ssn_check.mjs")], input=json.dumps(plan), text=True, encoding="utf-8",
                         capture_output=True, check=False, timeout=60)
    assert run.returncode == 0, run.stderr[-2000:]
    return json.loads(run.stdout)


@pytest.fixture(scope="module")
def device_results() -> list[dict]:
    return on_device([c["text"] for c in CASES])


@pytest.mark.parametrize("case", [c for c in CASES if not c.get("only_compare")], ids=lambda c: repr(c["text"])[:40])
def test_the_server_matches_the_table(case):
    g = guard(case["text"], CONFIG)
    assert (g.text, g.masked, g.invalid_label, g.refused) == (case["masked_text"], case["masked"], case["label"], case["refused"])


@pytest.mark.parametrize("index", range(len(CASES)), ids=lambda i: repr(CASES[i]["text"])[:40])
def test_the_device_agrees_with_the_server(device_results, index):
    g = guard(CASES[index]["text"], CONFIG)
    d = device_results[index]
    assert (d["text"], d["masked"], d["invalidLabel"], d["refused"]) == (g.text, g.masked, g.invalid_label, g.refused)


def test_masking_twice_changes_nothing(device_results):
    masked = [r["text"] for r in device_results if not r["refused"]]
    again = on_device(masked)
    assert [r["text"] for r in again] == masked and all(r["masked"] == 0 for r in again)
