"""Demo scenarios for the review UI and the demo script (task 5). Synthetic data only.

Scenarios live in sample-data/scenarios/scenarios.yaml. Loading checks that a scripted
error quotes the note exactly and uses an allowed answer, so a bad script fails at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from parser.interface import ParsedField
from parser.scripted_demo import Script

from .config_loader import AppConfig, ConfigError
from .email_message import load_email_file

SCENARIO_FILE = Path(__file__).resolve().parent.parent / "sample-data" / "scenarios" / "scenarios.yaml"


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    summary: str
    sender: str
    subject: str
    body: str
    suggested_reply: str | None
    scripted_label: str | None
    script: Script | None

    def subject_on(self, day: date) -> str:
        """The subject with {date} filled in as M/D, so it matches the encounter date the draft shows."""
        return self.subject.replace("{date}", f"{day.month}/{day.day}")

    def public(self, today: date) -> dict:
        return {"id": self.id, "title": self.title, "summary": self.summary, "sender": self.sender,
                "subject": self.subject_on(today), "body": self.body, "suggested_reply": self.suggested_reply,
                "scripted": self.script is not None, "scripted_label": self.scripted_label}


def load_scenarios(config: AppConfig, path: Path = SCENARIO_FILE) -> dict[str, Scenario]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenarios = {}
    for sid, spec in data.items():
        email = load_email_file(path.parent / spec["email"])
        script, label = None, None
        if "scripted" in spec:
            scripted = spec["scripted"]
            fields = {}
            for name, f in scripted.get("fields", {}).items():
                if name not in config.fields.fields:
                    raise ConfigError(f"scenario {sid}: unknown field {name!r}")
                if config.fields.fields[name].enum and f["value"] not in config.fields.option_ids(name):
                    raise ConfigError(f"scenario {sid}: {f['value']!r} is not an option for {name!r}")
                if f["source"] not in email.body:
                    raise ConfigError(f"scenario {sid}: the source for {name!r} is not in the note")
                fields[name] = ParsedField(value=f["value"], source=f["source"], confidence=f["confidence"])
            script = Script(body=email.body, fields=fields, case_note=scripted.get("case_note"))
            label = " ".join(scripted["label"].split())
        scenarios[sid] = Scenario(id=sid, title=spec["title"], summary=" ".join(spec["summary"].split()),
                                  sender=email.sender, subject=spec.get("subject", email.subject), body=email.body,
                                  suggested_reply=spec.get("suggested_reply"), scripted_label=label, script=script)
    return scenarios
