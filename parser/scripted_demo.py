"""A demo-only parser that returns a fixed, deliberate error for one exact scenario note.

Scenario B of the demo must always show the worker catching a mistake, and neither the
rule-based stub nor a live model makes that mistake on cue. For a note that matches a
script exactly, this parser runs the stub and then applies the scripted error. Every other
email, including the worker's replies and a scenario note the worker edited, goes to the
configured parser unchanged.

Drafts it produces carry parser name "scripted_demo", so the UI labels them as a scripted
demo example and never as a live model result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.email_message import IntakeEmail

from .interface import EmailParser, ParsedField, ParseResult
from .rule_stub import RuleStubParser

NAME = "scripted_demo"
PROMPT_VERSION = "scripted-demo-1"


@dataclass(frozen=True)
class Script:
    body: str
    fields: dict[str, ParsedField] = field(default_factory=dict)
    case_note: str | None = None


class ScriptedDemoParser:
    name = NAME

    def __init__(self, base: EmailParser, stub: RuleStubParser, scripts: list[Script]) -> None:
        self.base = base
        self.stub = stub
        self.scripts = scripts

    @property
    def model(self) -> str | None:
        return getattr(self.base, "model", None)

    def _script_for(self, email: IntakeEmail) -> Script | None:
        body = email.body.strip()
        return next((s for s in self.scripts if s.body.strip() == body), None)

    def parse(self, email: IntakeEmail) -> ParseResult:
        script = self._script_for(email)
        if script is None:
            return self.base.parse(email)
        result = self.stub.parse(email)
        fields = {**result.fields, **script.fields}
        return result.model_copy(update={
            "parser": NAME,
            "model": None,
            "prompt_version": PROMPT_VERSION,
            "fields": fields,
            "case_note": script.case_note or result.case_note,
        })

    def regenerate_case_note(self, note: str, corrections: str, fields: dict[str, ParsedField]) -> str | None:
        return self.base.regenerate_case_note(note, corrections, fields)
