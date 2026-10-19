"""HTTP service for the mock HMIS. Every route is a POST.

Entry routes return 201 with the assigned identifier, or a rejection with a code and
a reason. Rejections name fields but never echo submitted values or stored records.
The interactive docs and the OpenAPI schema are turned off so the service exposes
no GET route at all.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .failures import FailureMode, FailureSwitches
from .rules import HmisRules, Operation, load_rules
from .store import MockHmisStore

_FORCED: dict[FailureMode, tuple[int, str]] = {
    "missing_required_field": (422, "A required field is missing (forced failure)"),
    "possible_duplicate": (409, "Possible duplicate client (forced failure)"),
    "service_unavailable": (503, "HMIS is unavailable (forced failure)"),
}


class EntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Any]


class FailureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Operation
    mode: FailureMode
    times: int | None = Field(default=1, ge=1)


def _rejected(status: int, code: str, reason: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "rejected", "code": code, "reason": reason})


def _accepted(id_key: str, identifier: str) -> JSONResponse:
    return JSONResponse(status_code=201, content={"status": "accepted", id_key: identifier})


def create_app(rules: HmisRules | None = None, *, enable_admin: bool = True) -> FastAPI:
    rules = rules or load_rules()
    store = MockHmisStore(rules.id_prefixes)
    switches = FailureSwitches()

    app = FastAPI(title="Mock HMIS (entry only)", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.failures = switches

    def forced_failure(operation: Operation) -> JSONResponse | None:
        mode = switches.take(operation)
        if mode is None:
            return None
        status, reason = _FORCED[mode]
        return _rejected(status, mode, reason)

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
        return _rejected(404, "unknown_client", "No client with that ID was created through this interface")

    @app.post("/clients")
    def create_client(request: EntryRequest) -> JSONResponse:
        if (forced := forced_failure("create_client")) is not None:
            return forced
        if (problem := check("create_client", request.fields)) is not None:
            return problem
        dup = rules.duplicate_check
        if dup.enabled and store.possible_duplicate(dup.match_on, request.fields):
            return _rejected(409, "possible_duplicate", "Possible duplicate client. Search HMIS and resolve it there")
        return _accepted("client_id", store.add_client(request.fields))

    @app.post("/clients/{client_id}/enrollments")
    def enroll_in_program(client_id: str, request: EntryRequest) -> JSONResponse:
        if (forced := forced_failure("enroll_in_program")) is not None:
            return forced
        if not store.has_client(client_id):
            return unknown_client()
        if (problem := check("enroll_in_program", request.fields)) is not None:
            return problem
        return _accepted("enrollment_id", store.add_enrollment(client_id, request.fields))

    @app.post("/clients/{client_id}/ce-enrollments")
    def create_ce_enrollment(client_id: str, request: EntryRequest) -> JSONResponse:
        if (forced := forced_failure("create_ce_enrollment")) is not None:
            return forced
        if not store.has_client(client_id):
            return unknown_client()
        if not store.has_program_enrollment(client_id):
            return _rejected(409, "out_of_order", "Enroll the client in a program before the Coordinated Entry enrollment")
        if (problem := check("create_ce_enrollment", request.fields)) is not None:
            return problem
        return _accepted("ce_enrollment_id", store.add_ce_enrollment(client_id, request.fields))

    if enable_admin:

        @app.post("/_admin/failures", status_code=204)
        def set_failure(request: FailureRequest) -> None:
            switches.set(request.operation, request.mode, request.times)

        @app.post("/_admin/reset", status_code=204)
        def reset() -> None:
            store.reset()
            switches.clear()

    return app
