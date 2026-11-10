"""The web API, /api/v1 (add-web-application, Stage 2b).

One route per intake core action, plus the worker's drafts and messages and the supervisor
queue. Every rule stays in the core (app/core.py); these routes only:
  - require a signed-in session (401 without one) and the right role, checked here on the
    server (403 for the wrong role), never only in the screens;
  - require the session's CSRF token on every request that changes anything (403 without it);
  - build a channel-neutral Note from the signed-in worker and the text they typed: the author
    and the project always come from the session, never from the request;
  - show a worker only their own drafts, held notes, and messages (someone else's is 404).

Writes to HMIS still happen only through the core's confirm, by the draft's author. Queries
go through the core's ask, with every existing limit (fixed query types, row limit, the 90-day
window, the project visibility flag, minimal replies, and the audit). The model never writes
SQL. Synthetic data only.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import (CSRF_HEADER, SESSION_COOKIE, SIGN_IN_COOKIE, Sessions, SignInGuard, User, UserDirectory, csrf_for,
                   same_token)
from .core import IntakeCore, Outcome
from .note import Note
from .review import receipt_data, review_data, verification_data

PREFIX = "/api/v1"
SIGN_IN_FAILED = "Sign-in failed. Check your username and password."
SIGN_IN_LOCKED = "Too many sign-in attempts. Please wait and try again later."
AUDIT_REF = "AUTH"  # sign-in events: usernames, roles, and times only

# The label a worker sees for a draft. "Entered in HMIS" once HMIS accepted it (Stage 1 decision 8).
STATUS_LABELS = {"draft": "Could not draft", "in_review": "In review", "confirmed": "Entering in HMIS",
                 "submitted": "Entered in HMIS", "failed": "Needs attention", "expired": "With your supervisor"}
# Messages the screens show from the draft itself, so they are not listed again.
SHOWN_ON_SCREEN = ("review", "verification")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")  # an unknown field (an author, a project) is refused


class SignIn(_Body):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class NoteIn(_Body):
    text: str = Field(min_length=1, max_length=20_000)
    title: str | None = Field(default=None, max_length=200)


class QuestionIn(_Body):
    text: str = Field(min_length=1, max_length=2_000)


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

    def note(user: User, text: str, title: str) -> Note:
        return Note(author=user.address, title=title, written_at=service.clock().astimezone(), text=text.strip())

    def last_message_id(user: User) -> int:
        return max((e.id for e in store.emails(recipient=user.address)), default=0)

    def messages(user: User, after: int = 0) -> list[dict]:
        return [{"id": e.id, "ref": e.ref, "kind": e.kind, "subject": e.subject, "body": e.body, "at": e.at.isoformat()}
                for e in store.emails(recipient=user.address)
                if e.direction == "out" and e.id > after and e.kind not in SHOWN_ON_SCREEN]

    def act(user: User, run: Callable[[], Outcome]) -> dict:
        """Run one core action and return its outcome with the messages it produced for this worker."""
        before = last_message_id(user)
        out = run()
        return {"action": out.action, "ref": out.ref, "messages": messages(user, before)}

    def draft_view(draft) -> dict:
        open_check = draft.kind == "new_client" and draft.verification is not None and draft.verification.open
        in_review = draft.state == "in_review"
        return {
            "id": draft.id, "kind": draft.kind, "state": draft.state, "status_label": STATUS_LABELS[draft.state],
            "version": draft.version, "title": draft.subject, "client_label": draft.client_label,
            "review": review_data(draft, config) if in_review and not open_check else None,
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
    def new_client(body: NoteIn, user: User = writes_as_worker) -> dict:
        return act(user, lambda: service.new_client(note(user, body.text, body.title or "New client"), worker_of(user)))

    @router.post("/notes/update")
    def update(body: NoteIn, user: User = writes_as_worker) -> dict:
        return act(user, lambda: service.update(note(user, body.text, body.title or "Update"), worker_of(user)))

    @router.post("/queries")
    def ask(body: QuestionIn, user: User = writes_as_worker) -> dict:
        """A read-only question. The answer is shown once and kept only until the query retention rule deletes it."""
        out = act(user, lambda: service.ask(note(user, body.text, "Query"), worker_of(user)))
        replies = [m for m in out["messages"] if m["kind"] == "query_reply"]
        return {**out, "answer": replies[-1]["body"] if replies else None}

    # ---------------------------------------------------------------- worker: held notes

    @router.post("/held/{ref}/searched")
    def searched(ref: str, body: SearchedIn, user: User = writes_as_worker) -> dict:
        own_pending(user, ref)
        statement = (body.statement or "").strip()
        return act(user, lambda: service.confirm_search(ref, user.address, worker_of(user), statement or "Searched HMIS, no match.",
                                                        explicit=not statement))

    @router.post("/held/{ref}/client")
    def pick_client(ref: str, body: ClientIn, user: User = writes_as_worker) -> dict:
        own_pending(user, ref)
        return act(user, lambda: service.pick_client(ref, user.address, worker_of(user), body.client_id.strip()))

    # ---------------------------------------------------------------- worker: drafts

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
    def confirm(ref: str, body: ConfirmIn, user: User = writes_as_worker) -> dict:
        """The only way anything is written to HMIS: the author confirms the current version."""
        own_draft(user, ref)
        return act(user, lambda: service.confirm(ref, user.address, worker_of(user), body.version))

    @router.post("/drafts/{ref}/retry")
    def retry(ref: str, user: User = writes_as_worker) -> dict:
        own_draft(user, ref)
        return act(user, lambda: service.retry(ref, user.address, worker_of(user)))

    @router.post("/drafts/{ref}/corrections")
    def correct(ref: str, body: CorrectionsIn, user: User = writes_as_worker) -> dict:
        d = own_draft(user, ref)
        return act(user, lambda: service.correct(ref, user.address, worker_of(user), note(user, body.text, d.subject)))

    @router.post("/drafts/{ref}/same-client")
    def same_client(ref: str, body: ClientIn, user: User = writes_as_worker) -> dict:
        own_draft(user, ref)
        return act(user, lambda: service.same_client(ref, user.address, worker_of(user), body.client_id.strip()))

    @router.post("/drafts/{ref}/different-person")
    def different_person(ref: str, body: ReasonIn, user: User = writes_as_worker) -> dict:
        own_draft(user, ref)
        return act(user, lambda: service.different_person(ref, user.address, worker_of(user), body.reason))

    # ---------------------------------------------------------------- supervisor

    @router.get("/supervisor/queue")
    def supervisor_queue(user: User = reads_as_supervisor) -> list[dict]:
        return service.supervisor_queue()

    app.include_router(router)
