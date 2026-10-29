"""Refresh the generated appendix of docs/PROMPTS.md from the code: python scripts/update_prompt_doc.py

The appendix holds the exact prompt template, response schema, and case note prompt and
schema the live parser sends, built from parser/llm_v2.py and config/. Run this after any
change to them. With --check it changes nothing and exits 1 if the appendix is out of date
(the test suite runs the same check).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config_loader import load_config  # noqa: E402
from parser.llm_v2 import (  # noqa: E402
    CASE_NOTE_PROMPT,
    CASE_NOTE_SCHEMA,
    PROMPT_VERSION,
    build_prompt,
    build_schema,
)

DOC = ROOT / "docs" / "PROMPTS.md"
BEGIN = "<!-- BEGIN GENERATED: scripts/update_prompt_doc.py -->"
END = "<!-- END GENERATED -->"


def _schema_text(schema: dict) -> str:
    """The schema with one property per line, so it is readable and still exact JSON."""
    props = ",\n".join(f"    {json.dumps(k)}: {json.dumps(v)}" for k, v in schema["properties"].items())
    return ("{\n"
            f'  "type": {json.dumps(schema["type"])},\n'
            f'  "properties": {{\n{props}\n  }},\n'
            f'  "required": {json.dumps(schema["required"])},\n'
            f'  "additionalProperties": {json.dumps(schema["additionalProperties"])}\n'
            "}")


def render() -> str:
    config = load_config()
    schema = build_schema(config)
    return "\n".join([
        BEGIN,
        "",
        f"Prompt version: `{PROMPT_VERSION}`. Response schema: {len(schema['properties'])} properties, all required.",
        "",
        "### Prompt template",
        "",
        "The note replaces `{note}` exactly as written.",
        "",
        "```text",
        build_prompt(config),
        "```",
        "",
        "### Response schema",
        "",
        "Sent as `response_format: {\"type\": \"json_schema\", \"json_schema\": {\"name\": \"intake\", \"schema\": <this>, \"strict\": true}}`.",
        "",
        "```json",
        _schema_text(schema),
        "```",
        "",
        "### Case note rewrite prompt",
        "",
        "Used after the worker's corrections. `{note}` and `{corrections}` are filled in one pass.",
        "",
        "```text",
        CASE_NOTE_PROMPT,
        "```",
        "",
        "### Case note rewrite schema",
        "",
        "```json",
        json.dumps(CASE_NOTE_SCHEMA, indent=2),
        "```",
        "",
        END,
    ])


def updated(text: str) -> str:
    start, end = text.index(BEGIN), text.index(END) + len(END)
    return text[:start] + render() + text[end:]


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh the generated appendix of docs/PROMPTS.md")
    ap.add_argument("--check", action="store_true", help="exit 1 if the appendix is out of date, change nothing")
    args = ap.parse_args()
    text = DOC.read_text(encoding="utf-8")
    new = updated(text)
    if args.check:
        sys.exit(0 if new == text else "docs/PROMPTS.md is out of date. Run: python scripts/update_prompt_doc.py")
    DOC.write_text(new, encoding="utf-8")
    print(f"Updated {DOC.relative_to(ROOT)} (prompt version {PROMPT_VERSION}).")


if __name__ == "__main__":
    main()
