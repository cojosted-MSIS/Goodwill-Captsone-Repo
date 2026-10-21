"""Intake API: a simulated inbox and outbox, the staged-record view, and housekeeping.

These routes read the intake system's own staging store, never HMIS. The UI (task 5) will
use them. Run with: python -m app  (the mock HMIS must be running: python -m mock_hmis)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from parser.factory import build_parser

from .config_loader import AppConfig, load_config
from .email_message import EmailFormatError, parse_email_text
from .hmis_gateway import HmisGateway
from .storage import Store
from .workflow import IntakeService

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "intake.db"


class InboundEmail(BaseModel):
    raw: str  # the whole email: headers, a blank line, then the body


def build_service(config: AppConfig | None = None, db_path: Path | str = DEFAULT_DB) -> IntakeService:
    config = config or load_config()
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    s = config.settings
    return IntakeService(config, Store(str(db_path)), build_parser(config),
                         HmisGateway.from_base_url(s.hmis_base_url, s.hmis_timeout_seconds))


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

    return app
