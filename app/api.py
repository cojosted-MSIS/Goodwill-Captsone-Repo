"""Intake API: the web API (/api/v1) and, when the email channel is on, the email demo's routes.

/api/v1 (app/web_api.py) is always served: sign-in, sessions, CSRF, roles, and one route per
intake core action. The email demo's routes (a simulated inbox and outbox, the phone screens'
/mail routes, the staged-record and staff views, housekeeping, and the demo reset) have no
sign-in, so they are served only when settings.yaml channels.email.enabled is on (python -m app
--email-channel, which the email demo uses). The email channel is off by default.

These routes read the intake system's own staging store, never HMIS.
Run with: python -m app  (the mock HMIS must be running: python -m mock_hmis)
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

import httpx

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from parser.factory import build_parser, load_env
from parser.interface import EmailParser
from parser.rule_stub import RuleStubParser
from parser.scripted_demo import ScriptedDemoParser

from .auth import UserDirectory
from .config_loader import AppConfig, load_config, with_draft_content_views, with_email_channel
from .demo import load_scenarios
from .demo_reset import CONFIRM_PHRASE, DemoResetRefused, reset_demo
from .email_message import EmailFormatError, IntakeEmail, parse_email_text
from .hmis_gateway import HmisGateway
from .hmis_reader import HmisReader
from .match_key import load_match_key
from .review import parse_token, receipt_data, review_data, verification_data
from .sealing import Sealer
from .staff import run_data
from .storage import Store
from .web_api import install as install_web_api
from .workflow import IntakeService

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "intake.db"
UI_DIR = Path(__file__).resolve().parent.parent / "ui" / "static"  # the email demo's phone and staff screens
WEB_DIR = Path(__file__).resolve().parent.parent / "ui" / "web"  # the web app (add-web-application)
PARSER_ENV = "INTAKE_PARSER"  # rule_stub (default) or reallms
logger = logging.getLogger(__name__)


class InboundEmail(BaseModel):
    raw: str  # the whole email: headers, a blank line, then the body


class DemoReset(BaseModel):
    confirm: str  # must be the phrase "reset demo", so nothing resets by accident


class PhoneEmail(BaseModel):
    """An email sent from the phone screens. The system stamps the time and the intake address."""

    sender: str = Field(min_length=3)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)


def build_service(config: AppConfig | None = None, db_path: Path | str = DEFAULT_DB, *,
                  parser: str | None = None, model: str | None = None, email_channel: bool | None = None,
                  draft_content_views: bool | None = None) -> IntakeService:
    """`parser` overrides config/settings.yaml (default: INTAKE_PARSER, else settings), and
    `email_channel` switches the email channel on or off (default: settings, which is off).

    The parser is wrapped by the scripted demo parser, which only acts on the exact
    scripted scenario note (sample-data/scenarios) and labels those drafts as scripted."""
    config = config or load_config()
    if email_channel is not None:
        config = with_email_channel(config, email_channel)
    if draft_content_views is not None:  # demo only: the parser run, mapped draft, and staged record
        config = with_draft_content_views(config, draft_content_views)
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    s = config.settings
    base = build_parser(config, model=model, parser=parser or os.environ.get(PARSER_ENV) or None)
    q = s.hmis_queries
    reader = HmisReader(REPO_ROOT / q.database, q.row_limit)  # read-only; reads only the allowlisted views
    load_env()
    key = load_match_key(s)  # the open-draft hash key: required in production mode, never printed
    return IntakeService(config, Store(str(db_path)), demo_parser(config, base),
                         HmisGateway.from_base_url(s.hmis_base_url, s.hmis_timeout_seconds), reader=reader,
                         match_key=key)


def _waiting(draft, kind: str) -> bool:
    """A verification email is waiting while the same-name check is open; a review once it is not."""
    is_open = draft.verification is not None and draft.verification.open
    return is_open if kind == "verification" else not is_open


def demo_parser(config: AppConfig, base: EmailParser) -> ScriptedDemoParser:
    scripts = [sc.script for sc in load_scenarios(config).values() if sc.script is not None]
    return ScriptedDemoParser(base, RuleStubParser(config), scripts)


# The web app loads nothing from elsewhere and has no inline script or style.
CONTENT_SECURITY_POLICY = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
                           "connect-src 'self'; manifest-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; "
                           "form-action 'self'; frame-ancestors 'none'")
SHELL_SALT_ENV = "INTAKE_SHELL_SALT"  # lets a test act as a new build; it changes only the service worker's version


class WebHeaders:
    """Every /api response says no-store, errors included, so no browser or proxy keeps one. The web
    app's files get a strict Content-Security-Policy."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]

        async def with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if not (path.startswith("/api/") and k.lower() == b"cache-control")]
                if path.startswith("/api/"):
                    headers.append((b"cache-control", b"no-store"))
                elif path.startswith("/app"):
                    headers += [(b"content-security-policy", CONTENT_SECURITY_POLICY.encode()), (b"x-content-type-options", b"nosniff"),
                                (b"referrer-policy", b"no-referrer")]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, with_headers)


def shell_version() -> str:
    """A hash of the web app's files: a new build gets a new service worker."""
    digest = hashlib.sha256(os.environ.get(SHELL_SALT_ENV, "").encode())
    for path in sorted(p for p in WEB_DIR.rglob("*") if p.is_file()):
        digest.update(path.relative_to(WEB_DIR).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def run_housekeeping_every(service: IntakeService, seconds: float) -> threading.Event:
    """Run the time-based rules on a timer, so retention holds with nobody signed in. Set the returned
    event to stop. A failed run is logged by its type only (never content) and the timer goes on."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(seconds):
            try:
                service.housekeeping()
            except Exception as exc:  # noqa: BLE001
                logger.error("housekeeping failed: %s", type(exc).__name__)

    threading.Thread(target=loop, name="housekeeping", daemon=True).start()
    return stop


def create_app(service: IntakeService, hmis_admin: httpx.Client | None = None,
               users: UserDirectory | None = None, sealer: Sealer | None = None) -> FastAPI:
    """`hmis_admin` reaches the mock HMIS for the demo reset only (default: the configured address).
    `users` holds the sign-in accounts (default: the demo accounts, with passwords from the environment).
    `sealer` holds the keys that open notes sealed on a device (default: from the environment)."""
    app = FastAPI(title="Outreach intake (demo, synthetic data only)")
    app.add_middleware(WebHeaders)
    if users is None:
        load_env()
        users = UserDirectory.from_environment(service.config)
    if sealer is None:
        load_env()
        sealer = Sealer.from_environment(service.config.settings)
    install_web_api(app, service, users, sealer)

    email = service.config.settings.channels.email.enabled

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/ui/" if email else "/app/")

    if email:
        _email_demo_routes(app, service, hmis_admin)

    version = shell_version()

    @app.get("/app/sw.js", include_in_schema=False)
    def service_worker() -> Response:
        """The service worker, stamped with the build's version, and never kept in the HTTP cache."""
        source = (WEB_DIR / "sw.js").read_text(encoding="utf-8").replace("__SHELL_VERSION__", version)
        return Response(source, media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="web")
    app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")
    return app


def _email_demo_routes(app: FastAPI, service: IntakeService, hmis_admin: httpx.Client | None) -> None:
    """The email demo's routes. They have no sign-in, so they exist only while the email channel is on."""

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

    content_views = service.config.settings.demo.draft_content_views

    def content_view_or_404() -> None:
        """The staged record, mapped draft, and parser run show draft contents: demo only."""
        if not content_views:
            raise HTTPException(status_code=404, detail="Not found")

    @app.get("/drafts/{draft_id}")
    def staged(draft_id: str) -> dict:
        content_view_or_404()
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

    @app.post("/maintenance/delete-unsubmitted")
    def delete_unsubmitted() -> dict:
        """Held notes and drafts never submitted, with their emails, after the configured days."""
        return {"deleted": service.delete_unsubmitted()}

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

    def entered_client(sid: str) -> str | None:
        """The client ID from the newest receipt of scenario `sid` (a submitted new-client draft), if any."""
        source = scenarios[sid]
        done = [d for d in service.store.drafts("submitted")
                if d.kind == "new_client" and d.entry.client_id and source.matches_subject(d.subject)]
        return max(done, key=lambda d: d.submitted_at).entry.client_id if done else None

    @app.get("/demo/scenarios")
    def demo_scenarios() -> list[dict]:
        today = service.clock().astimezone().date()  # the date the phone will send on
        return [s.public(today, entered_client(s.client_from) if s.client_from else None) for s in scenarios.values()]

    @app.post("/demo/reset")
    def demo_reset(request: DemoReset) -> dict:
        """Demo only: clear the mock HMIS and the staging store. Never reachable by email."""
        if request.confirm.strip().lower() != CONFIRM_PHRASE:
            raise HTTPException(status_code=422, detail=f'Type "{CONFIRM_PHRASE}" to reset the demo.')
        try:
            if hmis_admin is not None:
                return reset_demo(service, hmis_admin)
            with httpx.Client(base_url=service.config.settings.hmis_base_url, timeout=5) as admin:
                return reset_demo(service, admin)
        except DemoResetRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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
            current = (e.kind in ("review", "verification") and draft is not None and draft.state == "in_review"
                       and version == draft.version and _waiting(draft, e.kind))
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
               "draft_state": draft.state if draft else None, "draft_version": draft.version if draft else None,
               "draft_kind": draft.kind if draft else None}
        if e.kind in ("review", "verification") and draft is not None:
            out["current"] = (draft.state == "in_review" and out["version"] == draft.version
                              and _waiting(draft, e.kind))
            if out["current"] and e.kind == "review":
                out["review"] = review_data(draft, service.config, scripted_label=scripted_label)
            if out["current"] and e.kind == "verification":
                out["verification"] = verification_data(draft, service.config)
        return out

    @app.get("/drafts/{draft_id}/review")
    def review(draft_id: str) -> dict:
        content_view_or_404()
        return review_data(draft_or_404(draft_id), service.config, scripted_label=scripted_label)

    @app.get("/drafts/{draft_id}/receipt")
    def receipt(draft_id: str) -> dict:
        draft = draft_or_404(draft_id)
        if draft.state not in ("submitted", "failed"):
            raise HTTPException(status_code=409, detail="This draft has not been sent to HMIS yet.")
        return receipt_data(draft, service.config)

    # Staff screens (task 5.2): parser run. The mapped draft, staged record and audit use the routes above.

    scripted_fields = {n for s in scenarios.values() if s.script for n in s.script.fields}

    @app.get("/staff/queries")
    def staff_queries() -> list[dict]:
        """Every read-only query: who, when, type, parameters as audited, and row counts. No returned values."""
        return service.query_log()

    @app.get("/staff/drafts/{draft_id}/run")
    def parser_run(draft_id: str) -> dict:
        content_view_or_404()
        return run_data(draft_or_404(draft_id), service.config, service.store, scripted_fields=scripted_fields)
