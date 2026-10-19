"""The intake app's only path into HMIS.

Three entry operations and nothing that reads. Each returns success with the
identifier HMIS assigned, or failure with a code and reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx


@dataclass(frozen=True)
class EntryResult:
    ok: bool
    identifier: str | None = None
    code: str | None = None
    reason: str | None = None


class HmisGateway:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    @classmethod
    def from_base_url(cls, base_url: str, timeout_seconds: float) -> HmisGateway:
        return cls(httpx.Client(base_url=base_url, timeout=timeout_seconds))

    def create_client(self, fields: Mapping[str, Any]) -> EntryResult:
        return self._post("/clients", fields, "client_id")

    def enroll_in_program(self, client_id: str, fields: Mapping[str, Any]) -> EntryResult:
        return self._post(f"/clients/{client_id}/enrollments", fields, "enrollment_id")

    def create_ce_enrollment(self, client_id: str, fields: Mapping[str, Any]) -> EntryResult:
        return self._post(f"/clients/{client_id}/ce-enrollments", fields, "ce_enrollment_id")

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, fields: Mapping[str, Any], id_key: str) -> EntryResult:
        payload = {"fields": {name: _to_json(value) for name, value in fields.items()}}
        try:
            response = self._http.post(path, json=payload)
        except httpx.TransportError:
            return EntryResult(ok=False, code="service_unavailable", reason="HMIS could not be reached")
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 201 and body.get(id_key):
            return EntryResult(ok=True, identifier=body[id_key])
        return EntryResult(
            ok=False,
            code=body.get("code", "unexpected_response"),
            reason=body.get("reason", f"HMIS returned status {response.status_code}"),
        )


def _to_json(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
