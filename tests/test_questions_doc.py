"""docs/QUESTIONS.md holds every [TBC] in the repository, grouped by who can answer it."""

from __future__ import annotations

import importlib.util
import re
import sys

from .conftest import REPO_ROOT

DOC = (REPO_ROOT / "docs" / "QUESTIONS.md").read_text(encoding="utf-8")
OWNERS = ["CHIP", "Goodwill", "Goodwill IT", "Horizon House", "DeveloperTown"]

spec = importlib.util.spec_from_file_location("update_questions_doc", REPO_ROOT / "scripts" / "update_questions_doc.py")
updater = importlib.util.module_from_spec(spec)
sys.modules["update_questions_doc"] = updater
spec.loader.exec_module(updater)


def rows() -> list[list[str]]:
    return [[c.strip() for c in line.strip("|").split(" | ")] for line in DOC.splitlines() if re.match(r"\| (CHIP|GW|IT|HH|DT)-\d+ \|", line)]


def test_the_appendix_is_current():
    assert updater.updated(DOC) == DOC, "run: python scripts/update_questions_doc.py"


def test_every_tbc_has_a_question():
    unmatched = [(name, text) for name, text in updater.occurrences() if updater.classify(f"{name}: {text}") is None]
    assert unmatched == []


def test_every_id_the_rules_use_is_a_question():
    ids = {row[0] for row in rows()}
    for _, qid in updater.RULES:
        if qid != updater.POINTER:
            for one in qid.split("/"):
                assert one in ids, one


def test_every_owner_has_a_section():
    for owner in OWNERS:
        assert f"\n## {owner}\n" in DOC, owner


def test_each_question_says_what_why_and_what_the_demo_assumes():
    assert len(rows()) >= 45
    for row in rows():
        assert len(row) == 4 and all(row), row


def test_ids_are_unique():
    ids = [row[0] for row in rows()]
    assert len(ids) == len(set(ids))


def test_the_top_section_has_ten_real_questions():
    top = DOC[DOC.index("## The 10 most important"):DOC.index("\n## CHIP\n")]
    named = re.findall(r"^\d+\. \*\*\[([A-Z]+-\d+)\]", top, re.M)
    assert len(named) == 10 and len(set(named)) == 10 and set(named) <= {row[0] for row in rows()}


def test_no_em_dashes():
    assert chr(0x2014) not in DOC
