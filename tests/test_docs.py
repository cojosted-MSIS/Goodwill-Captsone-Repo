"""The handoff docs stay true to the code: exact prompt and schema, settings, word lists, paths."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from app.config_loader import load_config
from parser import rule_stub
from parser.llm_checks import HEDGE_EXEMPT
from parser.llm_v2 import PROMPT_VERSION, build_prompt, build_schema

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CONFIG = load_config()

spec = importlib.util.spec_from_file_location("update_prompt_doc", ROOT / "scripts" / "update_prompt_doc.py")
update_prompt_doc = importlib.util.module_from_spec(spec)
sys.modules["update_prompt_doc"] = update_prompt_doc
spec.loader.exec_module(update_prompt_doc)


def read(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def test_prompt_appendix_is_current():
    text = read("PROMPTS.md")
    assert update_prompt_doc.updated(text) == text, "run: python scripts/update_prompt_doc.py"


def test_prompt_doc_holds_the_exact_prompt_and_schema():
    text = read("PROMPTS.md")
    assert build_prompt(CONFIG) in text
    schema_block = re.search(r"### Response schema.*?```json\n(.*?)\n```", text, re.S).group(1)
    assert json.loads(schema_block) == build_schema(CONFIG)


def test_prompt_doc_settings_match_the_config():
    text = read("PROMPTS.md")
    s = CONFIG.settings.reallms
    assert f"`{PROMPT_VERSION}`" in text and f"`{s.model}`" in text and s.base_url in text
    for model in s.fallback_models:
        assert f"`{model}`" in text
    assert f"| `temperature` | `{s.temperature:g}` |" in text
    assert f"| `max_tokens` | `{s.max_tokens}` |" in text
    assert f"{s.timeout_seconds:g} seconds per request" in text
    assert f"Up to {s.http_retries} retries" in text and f"waiting {s.backoff_seconds:g}, " in text
    assert f"schema: {len(build_schema(CONFIG)['properties'])} properties" in text


def _quoted_list(text: str, after: str, until: str = ")") -> list[str]:
    """Backtick-quoted words between `after` and the next `until`."""
    tail = text[text.index(after) + len(after):]
    return re.findall(r"`([^`]+)`", tail[: tail.index(until)])


def test_word_lists_in_the_docs_match_the_config():
    m = CONFIG.mappings
    conf, prompts = read("CONFIDENCE.md"), read("PROMPTS.md")
    assert "> " + ", ".join(m.hedge_words) in conf
    assert _quoted_list(conf, "the full sentence a quote comes from contains ", ", a definite answer") == m.llm_checks.hedges
    assert _quoted_list(prompts, "has no hedge or hearsay word (") == m.llm_checks.hedges
    assert _quoted_list(conf, "containing a hearsay word (") == m.stub_hearsay_words
    assert _quoted_list(prompts, "Sentences with hearsay words (") == m.stub_hearsay_words
    assert f"{rule_stub.HEDGE_WINDOW} characters before" in conf
    assert HEDGE_EXEMPT == {"client_doesnt_know", "approximate_or_partial_dob_reported"}  # named in both docs


def test_the_model_is_never_asked_for_confidence():
    """CONFIDENCE.md says the schema has no confidence field. Keep it true."""
    assert not any("confiden" in key for key in build_schema(CONFIG)["properties"])
    assert "confiden" not in build_prompt(CONFIG).lower()


@pytest.mark.parametrize("name", ["PROMPTS.md", "CONFIDENCE.md", "FUTURE.md", "HANDOFF.md"])
def test_docs_have_no_em_dashes(name):
    assert chr(0x2014) not in read(name)


def test_design_has_no_em_dashes():
    assert chr(0x2014) not in (ROOT / "openspec/changes/add-new-client-enrollment-demo/design.md").read_text(encoding="utf-8")


def test_paths_named_in_the_handoff_exist():
    text = read("HANDOFF.md")
    paths = {p for p in re.findall(r"`([A-Za-z_./-]+/[A-Za-z_./-]*|[A-Za-z_]+\.(?:py|md|yaml|js|html|css))`", text)}
    missing = []
    for p in paths:
        candidates = [ROOT / p, ROOT / "app" / p, ROOT / "ui" / "static" / p, DOCS / p,
                      ROOT / "openspec/changes/add-new-client-enrollment-demo" / p]
        if not any(c.exists() for c in candidates):
            missing.append(p)
    assert missing == [], missing
