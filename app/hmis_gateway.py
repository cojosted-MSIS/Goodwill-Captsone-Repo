"""The intake app's only path for writes to HMIS.

Entry operations only (POST), and nothing that reads: the new-client operations, case
notes and services for an existing client, and updates to entries this system made. Each
returns success with the identifier HMIS assigned or updated, or failure with a code and
reason. Reads go only through app/hmis_reader.py.

Every call carries the Idempotency-Key the core made when the worker confirmed (one per step),
so a retry after a lost answer gets the first result back instead of a second record. The mock
HMIS honors it; whether the real HMIS does is [TBC with CHIP].
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
    reason: str | None = None  # on success, code is None, or "idempotent_replay" when HMIS returned the result
    # it gave this key before (nothing new was made)


class HmisGateway:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    @classmethod
    def from_base_url(cls, base_url: str, timeout_seconds: float) -> HmisGateway:
        return cls(httpx.Client(base_url=base_url, timeout=timeout_seconds))

    def create_client(self, fields: Mapping[str, Any], confirmed_distinct_reason: str | None = None, *,
                      idempotency_key: str | None = None) -> EntryResult:
        # The reason is sent only when the worker replied DIFFERENT PERSON to a same-name verification.
        extra = {"confirmed_distinct": {"reason": confirmed_distinct_reason}} if confirmed_distinct_reason else {}
        return self._post("/clients", fields, "client_id", idempotency_key=idempotency_key, **extra)

    def enroll_in_program(self, client_id: str, fields: Mapping[str, Any], *, idempotency_key: str | None = None) -> EntryResult:
        return self._post(f"/clients/{client_id}/enrollments", fields, "enrollment_id", idempotency_key=idempotency_key)

    def create_ce_enrollment(self, client_id: str, fields: Mapping[str, Any], *, idempotency_key: str | None = None) -> EntryResult:
        return self._post(f"/clients/{client_id}/ce-enrollments", fields, "ce_enrollment_id", idempotency_key=idempotency_key)

    def add_case_note(self, client_id: str, fields: Mapping[str, Any], *, idempotency_key: str | None = None) -> EntryResult:
        return self._post(f"/clients/{client_id}/case-notes", fields, "case_note_id", idempotency_key=idempotency_key)

    def add_service(self, client_id: str, fields: Mapping[str, Any], *, idempotency_key: str | None = None) -> EntryResult:
        return self._post(f"/clients/{client_id}/services", fields, "service_id", idempotency_key=idempotency_key)

    def update_case_note(self, case_note_id: str, fields: Mapping[str, Any], *, idempotency_key: str | None = None) -> EntryResult:
        return self._post(f"/case-notes/{case_note_id}/updates", fields, "case_note_id", idempotency_key=idempotency_key)

    def update_service(self, service_id: str, fields: Mapping[str, Any], *, idempotency_key: str | None = None) -> EntryResult:
        return self._post(f"/services/{service_id}/updates", fields, "service_id", idempotency_key=idempotency_key)

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, fields: Mapping[str, Any], id_key: str, *, idempotency_key: str | None = None,
              **extra: Any) -> EntryResult:
        payload = {"fields": {name: _to_json(value) for name, value in fields.items()}, **extra}
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        try:
            response = self._http.post(path, json=payload, headers=headers)
        except httpx.TimeoutException:
            # HMIS may or may not have saved the entry. A retry with the same key is safe either way.
            return EntryResult(ok=False, code="timeout", reason="HMIS did not answer in time")
        except httpx.TransportError:
            return EntryResult(ok=False, code="service_unavailable", reason="HMIS could not be reached")
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 201 and body.get(id_key):
            replayed = response.headers.get("Idempotent-Replay", "").lower() == "true"
            return EntryResult(ok=True, identifier=body[id_key], code="idempotent_replay" if replayed else None)
        return EntryResult(
            ok=False,
            code=body.get("code", "unexpected_response"),
            reason=body.get("reason", f"HMIS returned status {response.status_code}"),
        )


def _to_json(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
