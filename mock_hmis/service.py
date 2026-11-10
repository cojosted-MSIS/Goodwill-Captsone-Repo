"""HTTP service for the mock HMIS. Every route is a POST.

Entry routes return 201 with the assigned identifier, or a rejection with a code and
a reason. An Idempotency-Key header makes a route safe to repeat: the same key with the same
request gets the first 201 again (header Idempotent-Replay: true) and creates nothing; the same
key with a different request is refused. Only accepted results are remembered, so a retry after
a rejection runs again. Whether the real HMIS supports this is [TBC with CHIP]. Rejections name fields but never echo submitted values or stored records.
The interactive docs and the OpenAPI schema are turned off so the service exposes
no GET route at all. Reads happen only through the read-only SQL layer in store.py.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .failures import FailureMode, FailureSwitches
from .rules import HmisRules, Operation, load_rules
from .store import MockHmisStore

# The mock's answer to /_admin/reset carries this header (see the reset route).
MOCK_RESET_HEADER = "X-Mock-HMIS"
MOCK_RESET_VALUE = "reset"

_FORCED: dict[FailureMode, tuple[int, str]] = {
    "missing_required_field": (422, "A required field is missing (forced failure)"),
    "possible_duplicate": (409, "Possible duplicate client (forced failure)"),
    "service_unavailable": (503, "HMIS is unavailable (forced failure)"),
    "timeout": (504, "No answer from HMIS in time (forced failure)"),
}
# lost_response saves the entry, then answers exactly as a timeout does.
_LOST = "lost_response"


class ConfirmedDistinct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class EntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Any]
    # create_client only: the worker confirmed this is a different person from a possible duplicate
    # [TBC with CHIP: whether the real HMIS allows such an override].
    confirmed_distinct: ConfirmedDistinct | None = None


class FailureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Operation
    mode: FailureMode
    times: int | None = Field(default=1, ge=1)


def _rejected(status: int, code: str, reason: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "rejected", "code": code, "reason": reason})


def _accepted(id_key: str, identifier: str) -> JSONResponse:
    return JSONResponse(status_code=201, content={"status": "accepted", id_key: identifier})


def create_app(rules: HmisRules | None = None, *, enable_admin: bool = True,
               db_path: str | Path | None = None, today: date | None = None) -> FastAPI:
    """`db_path` is the SQLite file the read-only queries also read (default: a private temporary file).
    `today` anchors the seed data's "days ago" dates (default: the real date)."""
    rules = rules or load_rules()
    store = MockHmisStore(rules.id_prefixes, db_path=db_path, today=today)
    switches = FailureSwitches()

    app = FastAPI(title="Mock HMIS (entry routes, POST only)", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.failures = switches
    remembered: dict[tuple[str, str], tuple[str, dict]] = {}  # (operation, key) -> (request hash, accepted body)
    lock = threading.Lock()  # one keyed request at a time, so two repeats at once still make one record

    def entry(operation: Operation, key: str | None, request: EntryRequest, target: str,
              run: Callable[[], JSONResponse]) -> JSONResponse:
        """Idempotency, forced failures, then the operation itself."""
        with lock:
            digest = hashlib.sha256(json.dumps([target, request.model_dump()], sort_keys=True, default=str).encode()).hexdigest()
            if key:
                seen = remembered.get((operation, key))
                if seen is not None:
                    if seen[0] != digest:
                        return _rejected(422, "idempotency_key_reused",
                                         "This Idempotency-Key was already used for a different request")
                    return JSONResponse(status_code=201, content=seen[1], headers={"Idempotent-Replay": "true"})
            mode = switches.take(operation)
            if mode is not None and mode != _LOST:
                status, reason = _FORCED[mode]
                return _rejected(status, mode, reason)
            response = run()
            if key and response.status_code == 201:
                remembered[(operation, key)] = (digest, json.loads(response.body))
            if mode == _LOST and response.status_code == 201:
                status, reason = _FORCED["timeout"]
                return _rejected(status, "timeout", reason)  # saved, but the caller never hears so
            return response

    def check(operation: Operation, fields: dict[str, Any]) -> JSONResponse | None:
        op = rules.operations[operation]
        unknown = sorted(set(fields) - set(op.accepted))
        if unknown:
            return _rejected(422, "unknown_field", f"Field(s) not accepted: {', '.join(unknown)}")
        missing = op.missing(fields)
        if missing:
            return _rejected(422, "missing_required_field", f"Missing required field(s): {', '.join(missing)}")
        wrong = op.wrong_values(fields)
        if wrong:
            return _rejected(422, "invalid_value", f"Field(s) with a value HMIS does not accept: {', '.join(wrong)}")
        return None

    def unknown_client() -> JSONResponse:
        return _rejected(404, "unknown_client", "No client with that ID exists")

    def updates_refused() -> JSONResponse | None:
        if rules.entry_updates_allowed:
            return None
        return _rejected(409, "edit_not_allowed", "HMIS does not allow this entry to be changed after it is saved")

    @app.post("/clients")
    def create_client(request: EntryRequest, key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
        return entry("create_client", key, request, "/clients", lambda: _create_client(request))

    def _create_client(request: EntryRequest) -> JSONResponse:
        if (problem := check("create_client", request.fields)) is not None:
            return problem
        dup = rules.duplicate_check
        override = request.confirmed_distinct
        if override is not None and not override.reason.strip():
            return _rejected(422, "override_needs_reason", "A confirmed-distinct override needs a reason")
        if dup.enabled and override is None and store.possible_duplicate(dup.match_on, request.fields):
            # A backstop: it never says anything about the matching record.
            return _rejected(409, "possible_duplicate", "Possible duplicate client. Search HMIS and resolve it there")
        return _accepted("client_id", store.add_client(request.fields))

    @app.post("/clients/{client_id}/enrollments")
    def enroll_in_program(client_id: str, request: EntryRequest,
                          key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
        return entry("enroll_in_program", key, request, client_id, lambda: _enroll_in_program(client_id, request))

    def _enroll_in_program(client_id: str, request: EntryRequest) -> JSONResponse:
        if not store.has_client(client_id):
            return unknown_client()
        if (problem := check("enroll_in_program", request.fields)) is not None:
            return problem
        return _accepted("enrollment_id", store.add_enrollment(client_id, request.fields))

    @app.post("/clients/{client_id}/ce-enrollments")
    def create_ce_enrollment(client_id: str, request: EntryRequest,
                             key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
        return entry("create_ce_enrollment", key, request, client_id, lambda: _create_ce_enrollment(client_id, request))

    def _create_ce_enrollment(client_id: str, request: EntryRequest) -> JSONResponse:
        if not store.has_client(client_id):
            return unknown_client()
        if not store.has_program_enrollment(client_id):
            return _rejected(409, "out_of_order", "Enroll the client in a program before the Coordinated Entry enrollment")
        if (problem := check("create_ce_enrollment", request.fields)) is not None:
            return problem
        return _accepted("ce_enrollment_id", store.add_ce_enrollment(client_id, request.fields))

    # Case notes and services for a client already in HMIS (add-existing-client-updates)

    @app.post("/clients/{client_id}/case-notes")
    def add_case_note(client_id: str, request: EntryRequest,
                      key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
        return entry("add_case_note", key, request, client_id, lambda: _add_case_note(client_id, request))

    def _add_case_note(client_id: str, request: EntryRequest) -> JSONResponse:
        if not store.has_client(client_id):
            return unknown_client()
        if (problem := check("add_case_note", request.fields)) is not None:
            return problem
        return _accepted("case_note_id", store.add_case_note(client_id, request.fields))

    @app.post("/clients/{client_id}/services")
    def add_service(client_id: str, request: EntryRequest,
                    key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
        return entry("add_service", key, request, client_id, lambda: _add_service(client_id, request))

    def _add_service(client_id: str, request: EntryRequest) -> JSONResponse:
        if not store.has_client(client_id):
            return unknown_client()
        if (problem := check("add_service", request.fields)) is not None:
            return problem
        return _accepted("service_id", store.add_service(client_id, request.fields))

    @app.post("/case-notes/{case_note_id}/updates")
    def update_case_note(case_note_id: str, request: EntryRequest,
                         key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
        return entry("update_case_note", key, request, case_note_id, lambda: _update_case_note(case_note_id, request))

    def _update_case_note(case_note_id: str, request: EntryRequest) -> JSONResponse:
        if not store.has_case_note(case_note_id):
            return _rejected(404, "unknown_entry", "No entry with that ID exists")
        if (refused := updates_refused()) is not None:
            return refused
        if (problem := check("update_case_note", request.fields)) is not None:
            return problem
        return _accepted("case_note_id", store.update_case_note(case_note_id, request.fields))

    @app.post("/services/{service_id}/updates")
    def update_service(service_id: str, request: EntryRequest,
                       key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
        return entry("update_service", key, request, service_id, lambda: _update_service(service_id, request))

    def _update_service(service_id: str, request: EntryRequest) -> JSONResponse:
        if not store.has_service(service_id):
            return _rejected(404, "unknown_entry", "No entry with that ID exists")
        if (refused := updates_refused()) is not None:
            return refused
        if (problem := check("update_service", request.fields)) is not None:
            return problem
        return _accepted("service_id", store.update_service(service_id, request.fields))

    if enable_admin:

        @app.post("/_admin/failures", status_code=204)
        def set_failure(request: FailureRequest) -> None:
            switches.set(request.operation, request.mode, request.times)

        @app.post("/_admin/reset", status_code=204)
        def reset(response: Response) -> None:
            store.reset()  # records, the ID counter, and the seed data: the next client is HMIS-C-000001 again
            switches.clear()
            remembered.clear()
            # Identifies the answer as the mock's. The intake app's demo reset clears its own
            # store only when it sees this, so it can never act on a real HMIS.
            response.headers[MOCK_RESET_HEADER] = MOCK_RESET_VALUE

    return app
