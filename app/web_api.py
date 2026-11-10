"""The web API, /api/v1 (add-web-application, Stage 2b).

One route per intake core action, plus the worker's drafts and messages, the supervisor queue,
and the staff audit views. Every rule stays in the core (app/core.py); these routes only:
  - require a signed-in session (401 without one) and the right role, checked here on the
    server (403 for the wrong role), never only in the screens;
  - require the session's CSRF token on every request that changes anything (403 without it);
  - build a channel-neutral Note from the signed-in worker and the text they typed: the author
    and the project always come from the session, never from the request;
  - show a worker only their own drafts, held notes, and messages (someone else's is 404);
  - show staff the audit (who, when, versions, query types and row counts), never note text or
    draft contents;
  - honor an Idempotency-Key header on every worker write: the same key and request from the
    same user returns the first result and does nothing again, a different request with that
    key is refused (409), and keys expire after settings.yaml web.idempotency_key_hours. Only a
    hash of the key is stored, with the result as action, ref, and message IDs (no note text).

Writes to HMIS still happen only through the core's confirm, by the draft's author. Queries
go through the core's ask, with every existing limit (fixed query types, row limit, the 90-day
window, the project visibility flag, minimal replies, and the audit). The model never writes
SQL. Synthetic data only.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import (CSRF_HEADER, SESSION_COOKIE, SIGN_IN_COOKIE, Sessions, SignInGuard, User, UserDirectory, csrf_for,
                   same_token)
from parser.interface import QueryRequest

from .core import IntakeCore, Outcome
from .note import Note
from .review import entry_summary, receipt_data, review_data, verification_data
from .ssn_guard import REFUSED_MESSAGE, guard as ssn_guard

PREFIX = "/api/v1"
SIGN_IN_FAILED = "Sign-in failed. Check your username and password."
SIGN_IN_LOCKED = "Too many sign-in attempts. Please wait and try again later."
AUDIT_REF = "AUTH"  # sign-in events: usernames, roles, and times only

# The label a worker sees for a draft. "Entered in HMIS" once HMIS accepted it (Stage 1 decision 8).
STATUS_LABELS = {"draft": "Could not draft", "in_review": "In review", "confirmed": "Entering in HMIS",
                 "submitted": "Entered in HMIS", "failed": "Needs attention", "expired": "With your supervisor"}
# Messages the screens show from the draft itself, so they are not listed again.
SHOWN_ON_SCREEN = ("review", "verification")
IDEMPOTENCY_HEADER = "Idempotency-Key"
KEY_FORMAT = re.compile(r"[A-Za-z0-9._:-]{8,200}")  # a UUID fits; spaces and very long keys do not


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")  # an unknown field (an author, a project) is refused


class SignIn(_Body):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class NoteIn(_Body):
    text: str = Field(min_length=1, max_length=20_000)
    title: str | None = Field(default=None, max_length=200)


Quadrant = Literal["NW", "NE", "SW", "SE"]


class Who(_Body):
    """A client by HMIS client ID, or by first and last name with the full date of birth. Never by name alone."""

    client_id: str | None = Field(default=None, max_length=40)
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    date_of_birth: date | None = None


class BriefingIn(_Body):
    quadrant: Quadrant


class StatusIn(Who):
    status_type: Literal["id_document", "housing_assessment"]


class NoContactIn(_Body):
    quadrant: Quadrant | None = None


class SearchedIn(_Body):
    statement: str | None = Field(default=None, max_length=2_000)  # empty: the "I searched HMIS, no match" button


class ClientIn(_Body):
    client_id: str = Field(min_length=1, max_length=40)


class ConfirmIn(_Body):
    version: int = Field(ge=1)


class CorrectionsIn(_Body):
    text: str = Field(min_length=1, max_length=20_000)


class ReasonIn(_Body):
    reason: str = Field(max_length=2_000)


class EmptyIn(_Body):
    """No fields: anything sent (an HMIS key, for example) is refused."""


def install(app: FastAPI, service: IntakeCore, users: UserDirectory) -> None:
    """Add the /api/v1 routes to `app`."""
    store, config = service.store, service.config
    app.state.users = users  # for the startup message: which password variables are not set (names only)
    web = config.settings.web
    sessions = Sessions(store, web, service.clock)
    guard = SignInGuard(web.sign_in, service.clock)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        """Never echo what was sent (it may hold a password): only where and what was wrong."""
        if not request.url.path.startswith(PREFIX):
            return await request_validation_exception_handler(request, exc)
        detail = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": detail})

    def audit(event: str, actor: str | None, **details) -> None:
        store.audit(AUDIT_REF, event, service.clock(), actor, **details)

    def secure(request: Request) -> bool:
        return request.url.scheme == "https" if web.cookie_secure == "auto" else bool(web.cookie_secure)

    # ---------------------------------------------------------------- dependencies

    def signed_in(request: Request) -> User:
        token = request.cookies.get(SESSION_COOKIE)
        username, expired = sessions.resolve(token) if token else (None, None)
        if expired:
            audit("session_expired", username, reason=expired)
        user = None if expired else users.get(username)
        if user is None:
            raise HTTPException(status_code=401, detail="Please sign in.")
        request.state.session_token = token
        return user

    def with_csrf(request: Request, user: User = Depends(signed_in)) -> User:
        if not same_token(request.headers.get(CSRF_HEADER), csrf_for(request.state.session_token)):
            raise HTTPException(status_code=403, detail="Missing or invalid CSRF token. Reload the page and try again.")
        return user

    def role(name: str, *, writes: bool) -> Callable[..., User]:
        base = with_csrf if writes else signed_in

        def check(user: User = Depends(base)) -> User:
            if user.role != name:
                raise HTTPException(status_code=403, detail="Your role cannot do this.")
            return user

        return check

    reads_as_worker = Depends(role("worker", writes=False))
    writes_as_worker = Depends(role("worker", writes=True))
    reads_as_supervisor = Depends(role("supervisor", writes=False))
    reads_as_staff = Depends(role("staff", writes=False))

    # ---------------------------------------------------------------- helpers

    def worker_of(user: User):
        return user.worker

    def own_draft(user: User, ref: str):
        draft = store.get_draft(ref)
        if draft is None or draft.author != user.address:
            if draft is not None:
                audit_refusal(user, ref)
            raise HTTPException(status_code=404, detail="No such draft.")
        return draft

    def own_pending(user: User, ref: str):
        pending = store.get_pending(ref)
        if pending is None or pending.author != user.address:
            if pending is not None:
                audit_refusal(user, ref)
            raise HTTPException(status_code=404, detail="No such note.")
        return pending

    def audit_refusal(user: User, ref: str) -> None:
        store.audit(ref, "web_refused_not_owner", service.clock(), user.worker.worker_id)

    def guarded(text: str):
        """Mask full SSNs before anything is kept; refuse an SSN in another form (app/ssn_guard.py)."""
        g = ssn_guard(text, config)
        if g.refused:
            raise HTTPException(status_code=422, detail={"code": "ssn_possible_full_number", "message": REFUSED_MESSAGE})
        return g

    def note(user: User, text: str, title: str) -> Note:
        g = guarded(text.strip())
        return Note(author=user.address, title=title, written_at=service.clock().astimezone(), text=g.text,
                    ssn_invalid_label=g.invalid_label)

    def with_ssn(out: dict, text: str) -> dict:
        """Tell the screen how many full SSNs were masked, so it can say so."""
        return {**out, "ssn": {"masked": ssn_guard(text, config).masked}}

    def last_message_id(user: User) -> int:
        return max((e.id for e in store.emails(recipient=user.address)), default=0)

    def messages(user: User, after: int = 0) -> list[dict]:
        return [{"id": e.id, "ref": e.ref, "kind": e.kind, "key": e.message_key, "subject": e.subject, "body": e.body,
                 "at": e.at.isoformat()}
                for e in store.emails(recipient=user.address)
                if e.direction == "out" and e.id > after and e.kind not in SHOWN_ON_SCREEN]

    def outcome_of(user: User, run: Callable[[], Outcome]) -> dict:
        """Run one core action. The record is what a replay needs: action, ref, and message IDs only."""
        before = last_message_id(user)
        out = run()
        return {"action": out.action, "ref": out.ref, "message_ids": [m["id"] for m in messages(user, before)]}

    def respond(user: User, record: dict) -> dict:
        wanted = set(record["message_ids"])
        return {"action": record["action"], "ref": record["ref"],
                "messages": [m for m in messages(user) if m["id"] in wanted]}

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def act(request: Request, user: User, kind: str, body: dict, run: Callable[[], Outcome]) -> dict:
        """Run one core action once per Idempotency-Key (when one is sent) and return its outcome with the
        messages it produced for this worker. A replay shows the messages that are still kept."""
        key = request.headers.get(IDEMPOTENCY_HEADER)
        if key is None:
            return respond(user, outcome_of(user, run))
        if not KEY_FORMAT.fullmatch(key):
            raise HTTPException(status_code=400, detail="Idempotency-Key must be 8 to 200 letters, digits, or . _ : -")
        key_hash = digest(key)
        request_hash = digest(json.dumps([kind, request.url.path, body], sort_keys=True, default=str))
        deadline = time.monotonic() + web.idempotency_wait_seconds
        while True:
            now = service.clock()
            state, record = store.claim_idempotency(user.username, key_hash, request_hash, now,
                                                    now - timedelta(hours=web.idempotency_key_hours))
            if state == "new":
                break
            if state == "conflict":
                raise HTTPException(status_code=409, detail="This Idempotency-Key was already used for a different request.")
            if state == "replay":
                store.audit(record["ref"] or "web", "idempotent_replay", now, type=kind)  # no key, no personal data
                return respond(user, record)
            if time.monotonic() > deadline:
                raise HTTPException(status_code=409, detail="A request with this Idempotency-Key is still running. Try again shortly.")
            time.sleep(0.05)  # the first request with this key is still running: wait for its result
        try:
            record = outcome_of(user, run)
        except BaseException:
            store.release_idempotency(user.username, key_hash)
            raise
        store.finish_idempotency(user.username, key_hash, record)
        return respond(user, record)

    def draft_view(draft) -> dict:
        open_check = draft.kind == "new_client" and draft.verification is not None and draft.verification.open
        in_review = draft.state == "in_review"
        review = review_data(draft, config) if in_review and not open_check else None
        return {
            "id": draft.id, "kind": draft.kind, "state": draft.state, "status_label": STATUS_LABELS[draft.state],
            "version": draft.version, "title": draft.subject, "client_label": draft.client_label,
            "review": review,
            "confirm_allowed": bool(review and review["confirm_allowed"]),  # never while a verification is open
            "entry_summary": entry_summary(draft, config) if in_review else None,
            "verification": verification_data(draft, config) if in_review and open_check else None,
            "receipt": receipt_data(draft, config) if draft.state in ("submitted", "failed") else None,
        }

    router = APIRouter(prefix=PREFIX)

    # ---------------------------------------------------------------- sign-in and sessions

    @router.get("/auth/csrf")
    def sign_in_token(request: Request, response: Response) -> dict:
        """The token the sign-in form sends back (double submit: it must match this cookie)."""
        token = secrets.token_urlsafe(32)
        response.set_cookie(SIGN_IN_COOKIE, token, max_age=3600, path=f"{PREFIX}/auth", httponly=True,
                            samesite="strict", secure=secure(request))
        return {"csrf_token": token}

    @router.post("/auth/sign-in")
    def sign_in(body: SignIn, request: Request, response: Response) -> dict:
        if not same_token(request.headers.get(CSRF_HEADER), request.cookies.get(SIGN_IN_COOKIE)):
            raise HTTPException(status_code=403, detail="Missing or invalid CSRF token. Reload the page and try again.")
        username = body.username.strip().lower()
        known = users.get(username)
        actor = known.username if known else None  # an unknown username is never recorded
        refused = guard.refused(username, request.client.host if request.client else "unknown")
        if refused:
            audit("sign_in_rate_limited" if refused == "rate_limited" else "sign_in_refused_locked", actor)
            raise HTTPException(status_code=429, detail=SIGN_IN_LOCKED)
        user = users.check(username, body.password)
        if user is None:
            locked = guard.failed(username)
            audit("sign_in_failed", actor)
            if locked:
                audit("sign_in_locked", actor, minutes=web.sign_in.lockout_minutes)
            raise HTTPException(status_code=401, detail=SIGN_IN_FAILED)
        guard.succeeded(username)
        old = request.cookies.get(SESSION_COOKIE)
        if old:
            sessions.end(old)  # one session per browser; a token the browser offered is never reused
        token = sessions.start(user)
        response.set_cookie(SESSION_COOKIE, token, path="/", httponly=True, samesite="strict", secure=secure(request))
        response.delete_cookie(SIGN_IN_COOKIE, path=f"{PREFIX}/auth", httponly=True, samesite="strict", secure=secure(request))
        audit("sign_in", user.username, role=user.role)
        return {**user.public(), "csrf_token": csrf_for(token)}

    @router.post("/auth/sign-out")
    def sign_out(request: Request, response: Response, user: User = Depends(with_csrf)) -> dict:
        sessions.end(request.state.session_token)
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict", secure=secure(request))
        audit("sign_out", user.username)
        return {"signed_out": True}

    @router.get("/session")
    def session(request: Request, user: User = Depends(signed_in)) -> dict:
        return {**user.public(), "csrf_token": csrf_for(request.state.session_token)}

    # ---------------------------------------------------------------- worker: notes and questions

    @router.post("/notes/new-client")
    def new_client(request: Request, body: NoteIn, user: User = writes_as_worker) -> dict:
        n = note(user, body.text, body.title or "New client")
        return with_ssn(act(request, user, "new_client", body.model_dump(), lambda: service.new_client(n, worker_of(user))),
                        body.text)

    @router.post("/notes/update")
    def update(request: Request, body: NoteIn, user: User = writes_as_worker) -> dict:
        n = note(user, body.text, body.title or "Update")
        return with_ssn(act(request, user, "update", body.model_dump(), lambda: service.update(n, worker_of(user))),
                        body.text)

    # Read-only queries: four fixed forms. The fields are the request: no parser and no free text, and the
    # model never writes SQL. The same checks, limits, and audit as an email query. Nothing is kept but the
    # audit; the answer is shown once.

    def fixed(user: User, query_type: str, quadrant: str | None = None, who: Who | None = None,
              status_type: str | None = None) -> dict:
        dob = who.date_of_birth if who else None
        request = QueryRequest(query_type=query_type, quadrant=quadrant.lower() if quadrant else None,
                               first_name=(who.first_name or "").strip() or None if who else None,
                               last_name=(who.last_name or "").strip() or None if who else None,
                               date_of_birth_as_written=f"{dob.month}/{dob.day}/{dob.year}" if dob else None,
                               client_id=(who.client_id or "").strip() or None if who else None, status_type=status_type)
        return service.ask_fixed(request, worker_of(user))

    @router.get("/queries/options")
    def query_options(user: User = reads_as_worker) -> dict:
        q = config.settings.hmis_queries
        return {"quadrants": ["NW", "NE", "SW", "SE"], "status_types": dict(q.status_types),
                "no_contact_days": q.no_contact_days, "no_contact_warning_days": q.no_contact_warning_days,
                "briefing_window_days": q.briefing_window_days, "row_limit": q.row_limit}

    @router.post("/queries/briefing")
    def briefing(body: BriefingIn, user: User = writes_as_worker) -> dict:
        return fixed(user, "briefing", quadrant=body.quadrant)

    @router.post("/queries/lookup")
    def lookup(body: Who, user: User = writes_as_worker) -> dict:
        return fixed(user, "lookup", who=body)

    @router.post("/queries/status")
    def status(body: StatusIn, user: User = writes_as_worker) -> dict:
        return fixed(user, "status", who=body, status_type=body.status_type)

    @router.post("/queries/no-contact")
    def no_contact(body: NoContactIn, user: User = writes_as_worker) -> dict:
        return fixed(user, "no_contact", quadrant=body.quadrant)

    # ---------------------------------------------------------------- worker: held notes

    @router.post("/held/{ref}/searched")
    def searched(request: Request, ref: str, body: SearchedIn, user: User = writes_as_worker) -> dict:
        own_pending(user, ref)
        statement = guarded((body.statement or "").strip()).text
        return act(request, user, "confirm_search", body.model_dump(), lambda: service.confirm_search(ref, user.address, worker_of(user), statement or "Searched HMIS, no match.",
                                                        explicit=not statement))

    @router.post("/held/{ref}/client")
    def pick_client(request: Request, ref: str, body: ClientIn, user: User = writes_as_worker) -> dict:
        own_pending(user, ref)
        return act(request, user, "pick_client", body.model_dump(), lambda: service.pick_client(ref, user.address, worker_of(user), body.client_id.strip()))

    # ---------------------------------------------------------------- worker: drafts

    @router.get("/held")
    def held_notes(user: User = reads_as_worker) -> list[dict]:
        """The worker's notes waiting for them: an HMIS search to confirm, or a client to pick."""
        mine = [p for p in store.all_pending() if p.author == user.address]
        return [{"id": p.id, "kind": p.kind, "title": p.subject, "created_at": p.created_at.isoformat()}
                for p in sorted(mine, key=lambda p: p.created_at, reverse=True)]

    @router.get("/held/{ref}")
    def held_note(ref: str, user: User = reads_as_worker) -> dict:
        p = own_pending(user, ref)
        return {"id": p.id, "kind": p.kind, "title": p.subject, "created_at": p.created_at.isoformat(),
                "candidates": [{k: c.get(k) for k in ("client_id", "label", "last_contact", "quadrant")}
                               for c in p.candidate_details]}

    @router.get("/drafts")
    def drafts(user: User = reads_as_worker) -> list[dict]:
        mine = [d for d in reversed(store.drafts()) if d.author == user.address]
        return [{"id": d.id, "kind": d.kind, "state": d.state, "status_label": STATUS_LABELS[d.state],
                 "version": d.version, "title": d.subject} for d in mine]

    @router.get("/drafts/{ref}")
    def draft(ref: str, user: User = reads_as_worker) -> dict:
        return draft_view(own_draft(user, ref))

    @router.get("/messages")
    def inbox(user: User = reads_as_worker) -> list[dict]:
        return list(reversed(messages(user)))

    @router.post("/drafts/{ref}/confirm")
    def confirm(request: Request, ref: str, body: ConfirmIn, user: User = writes_as_worker) -> dict:
        """The only way anything is written to HMIS: the author confirms the current version. The HMIS
        idempotency key is made by the core at this point and is never taken from the request."""
        own_draft(user, ref)
        return act(request, user, "confirm", body.model_dump(), lambda: service.confirm(ref, user.address, worker_of(user), body.version))

    @router.post("/drafts/{ref}/retry")
    def retry(request: Request, ref: str, body: EmptyIn | None = None, user: User = writes_as_worker) -> dict:
        """Retry a failed entry. It reuses the HMIS key stored with the draft; no request can change it."""
        own_draft(user, ref)
        return act(request, user, "retry", {}, lambda: service.retry(ref, user.address, worker_of(user)))

    @router.post("/drafts/{ref}/corrections")
    def correct(request: Request, ref: str, body: CorrectionsIn, user: User = writes_as_worker) -> dict:
        d = own_draft(user, ref)
        n = note(user, body.text, d.subject)
        return with_ssn(act(request, user, "correct", body.model_dump(),
                            lambda: service.correct(ref, user.address, worker_of(user), n)), body.text)

    @router.post("/drafts/{ref}/same-client")
    def same_client(request: Request, ref: str, body: ClientIn, user: User = writes_as_worker) -> dict:
        own_draft(user, ref)
        return act(request, user, "same_client", body.model_dump(), lambda: service.same_client(ref, user.address, worker_of(user), body.client_id.strip()))

    @router.post("/drafts/{ref}/different-person")
    def different_person(request: Request, ref: str, body: ReasonIn, user: User = writes_as_worker) -> dict:
        own_draft(user, ref)
        reason = guarded(body.reason).text
        return act(request, user, "different_person", body.model_dump(), lambda: service.different_person(ref, user.address, worker_of(user), reason))

    # ---------------------------------------------------------------- supervisor

    @router.get("/supervisor/queue")
    def supervisor_queue(user: User = reads_as_supervisor) -> list[dict]:
        return service.supervisor_queue()

    # ---------------------------------------------------------------- staff: read-only audit, no neighbor information

    @router.get("/staff/queries")
    def staff_queries(user: User = reads_as_staff) -> list[dict]:
        """Every read-only query: who, when, type, parameters as audited (a name or date of birth only as
        "given"), and row counts. Never the returned values."""
        return service.query_log()

    @router.get("/staff/drafts")
    def staff_drafts(user: User = reads_as_staff) -> list[dict]:
        """Draft IDs, kinds, states, workers, versions, and times. No title (it can hold a name), no fields."""
        return [{"id": d.id, "kind": d.kind, "state": d.state, "worker_id": d.worker_id, "version": d.version,
                 "created_at": d.created_at.isoformat(),
                 "submitted_at": d.submitted_at.isoformat() if d.submitted_at else None}
                for d in store.drafts()]

    @router.get("/staff/drafts/{ref}/audit")
    def staff_audit(ref: str, user: User = reads_as_staff) -> dict:
        """The audit record without the worker's free-text reason (it describes the neighbor)."""
        if store.get_draft(ref) is None:
            raise HTTPException(status_code=404, detail="No such draft.")
        record = service.audit_record(ref)
        if record.get("verification"):
            record["verification"] = {k: v for k, v in record["verification"].items() if k != "reason"}
        record["events"] = [{k: v for k, v in e.items() if k != "reason"} for e in record["events"]]
        return record

    app.include_router(router)
