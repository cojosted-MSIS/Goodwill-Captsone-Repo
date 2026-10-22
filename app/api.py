"""Intake API: a simulated inbox and outbox, the staged-record view, and housekeeping.

These routes read the intake system's own staging store, never HMIS. The phone-style UI
(task 5, ui/static) uses them and is served at /ui. Every worker action in the UI is sent
as a simulated email through the same workflow as /inbox.
Run with: python -m app  (the mock HMIS must be running: python -m mock_hmis)
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from parser.factory import build_parser
from parser.interface import EmailParser
from parser.rule_stub import RuleStubParser
from parser.scripted_demo import ScriptedDemoParser

from .config_loader import AppConfig, load_config
from .demo import load_scenarios
from .email_message import EmailFormatError, IntakeEmail, parse_email_text
from .hmis_gateway import HmisGateway
from .review import parse_token, receipt_data, review_data
from .staff import run_data
from .storage import Store
from .workflow import IntakeService

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "intake.db"
UI_DIR = Path(__file__).resolve().parent.parent / "ui" / "static"
PARSER_ENV = "INTAKE_PARSER"  # rule_stub (default) or reallms


class InboundEmail(BaseModel):
    raw: str  # the whole email: headers, a blank line, then the body


class PhoneEmail(BaseModel):
    """An email sent from the phone screens. The system stamps the time and the intake address."""

    sender: str = Field(min_length=3)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)


def build_service(config: AppConfig | None = None, db_path: Path | str = DEFAULT_DB, *,
                  parser: str | None = None, model: str | None = None) -> IntakeService:
    """`parser` overrides config/settings.yaml (default: INTAKE_PARSER, else settings).

    The parser is wrapped by the scripted demo parser, which only acts on the exact
    scripted scenario note (sample-data/scenarios) and labels those drafts as scripted."""
    config = config or load_config()
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    s = config.settings
    base = build_parser(config, model=model, parser=parser or os.environ.get(PARSER_ENV) or None)
    return IntakeService(config, Store(str(db_path)), demo_parser(config, base),
                         HmisGateway.from_base_url(s.hmis_base_url, s.hmis_timeout_seconds))


def demo_parser(config: AppConfig, base: EmailParser) -> ScriptedDemoParser:
    scripts = [sc.script for sc in load_scenarios(config).values() if sc.script is not None]
    return ScriptedDemoParser(base, RuleStubParser(config), scripts)


def create_app(service: IntakeService) -> FastAPI:
    app = FastAPI(title="Outreach intake (demo, synthetic data only)")

    @app.post("/inbox")
    def receive(email: InboundEmail) -> dict:
        try:
            parsed = parse_email_text(email.raw)
        except EmailFormatError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        outcome = service.receive(parsed)
        return {"action": outcome.action, "ref": outcome.ref}

    @app.get("/outbox/{address}")
    def outbox(address: str) -> list[dict]:
        """The simulated phone: emails the system sent to this address."""
        return [{"id": e.id, "ref": e.ref, "kind": e.kind, "subject": e.subject, "body": e.body, "at": e.at.isoformat()}
                for e in service.store.emails(recipient=address.lower()) if e.direction == "out"]

    @app.get("/drafts/{draft_id}")
    def staged(draft_id: str) -> dict:
        view = service.staged_view(draft_id)
        if view is None:
            raise HTTPException(status_code=404, detail="No such draft")
        return view

    @app.get("/drafts/{draft_id}/audit")
    def audit(draft_id: str) -> dict:
        if service.store.get_draft(draft_id) is None:
            raise HTTPException(status_code=404, detail="No such draft")
        return service.audit_record(draft_id)

    @app.get("/supervisor-queue")
    def supervisor_queue() -> list[dict]:
        return service.supervisor_queue()

    @app.post("/maintenance/expire")
    def expire() -> dict:
        return {"expired": service.expire_stale()}

    @app.post("/maintenance/purge-emails")
    def purge() -> dict:
        return {"deleted_for": service.purge_emails()}

    # Phone screens (task 5): scenarios, the worker's inbox, review data, receipt

    scenarios = load_scenarios(service.config)
    scripted_label = next((s.scripted_label for s in scenarios.values() if s.scripted_label), None)

    def draft_or_404(draft_id: str):
        draft = service.store.get_draft(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="No such draft")
        return draft

    def outgoing(address: str | None = None):
        return [e for e in service.store.emails(recipient=address.lower() if address else None) if e.direction == "out"]

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/ui/")

    @app.get("/demo/scenarios")
    def demo_scenarios() -> list[dict]:
        today = service.clock().astimezone().date()  # the date the phone will send on
        return [s.public(today) for s in scenarios.values()]

    @app.get("/demo/drafts")
    def demo_drafts() -> list[dict]:
        return [{"id": d.id, "subject": d.subject, "state": d.state, "version": d.version, "author": d.author,
                 "parser": d.parser, "model": d.model} for d in reversed(service.store.drafts())]

    @app.post("/mail/send")
    def send(email: PhoneEmail) -> dict:
        outcome = service.receive(IntakeEmail(
            sender=email.sender.strip().lower(), recipient=service.config.workers.intake_address.lower(),
            subject=email.subject.strip(), sent_at=service.clock().astimezone(), body=email.body.strip()))
        return {"action": outcome.action, "ref": outcome.ref}

    @app.get("/mail/inbox/{address}")
    def inbox(address: str) -> list[dict]:
        """The worker's phone inbox, newest first. Bodies are fetched one email at a time."""
        rows = []
        for e in reversed(outgoing(address)):
            token = parse_token(e.subject)
            version = token[1] if token else None
            draft = service.store.get_draft(e.ref) if e.ref else None
            current = (e.kind == "review" and draft is not None and draft.state == "in_review"
                       and version == draft.version)
            rows.append({"id": e.id, "ref": e.ref, "kind": e.kind, "subject": e.subject, "at": e.at.isoformat(),
                         "version": version, "current": current})
        return rows

    @app.get("/mail/message/{email_id}")
    def message(email_id: int) -> dict:
        e = next((m for m in outgoing() if m.id == email_id), None)
        if e is None:
            raise HTTPException(status_code=404, detail="No such email")
        token = parse_token(e.subject)
        draft = service.store.get_draft(e.ref) if e.ref else None
        out = {"id": e.id, "ref": e.ref, "kind": e.kind, "subject": e.subject, "at": e.at.isoformat(),
               "sender": e.sender, "recipient": e.recipient, "body": e.body,
               "version": token[1] if token else None, "review": None, "current": False,
               "draft_state": draft.state if draft else None, "draft_version": draft.version if draft else None}
        if e.kind == "review" and draft is not None:
            out["current"] = draft.state == "in_review" and out["version"] == draft.version
            if out["current"]:
                out["review"] = review_data(draft, service.config, scripted_label=scripted_label)
        return out

    @app.get("/drafts/{draft_id}/review")
    def review(draft_id: str) -> dict:
        return review_data(draft_or_404(draft_id), service.config, scripted_label=scripted_label)

    @app.get("/drafts/{draft_id}/receipt")
    def receipt(draft_id: str) -> dict:
        draft = draft_or_404(draft_id)
        if draft.state not in ("submitted", "failed"):
            raise HTTPException(status_code=409, detail="This draft has not been sent to HMIS yet.")
        return receipt_data(draft, service.config)

    # Staff screens (task 5.2): parser run. The mapped draft, staged record and audit use the routes above.

    scripted_fields = {n for s in scenarios.values() if s.script for n in s.script.fields}

    @app.get("/staff/drafts/{draft_id}/run")
    def parser_run(draft_id: str) -> dict:
        return run_data(draft_or_404(draft_id), service.config, service.store, scripted_fields=scripted_fields)

    app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")
    return app
