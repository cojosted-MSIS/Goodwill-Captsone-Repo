"""In-memory records held by the mock HMIS.

This stands in for HMIS's own database. The service writes to it and checks it for
ordering and possible duplicates, but no endpoint returns anything from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .rules import IdPrefixes


@dataclass
class _Client:
    fields: dict[str, Any]
    enrollment_ids: list[str] = field(default_factory=list)
    ce_enrollment_ids: list[str] = field(default_factory=list)


class MockHmisStore:
    def __init__(self, prefixes: IdPrefixes) -> None:
        self._prefixes = prefixes
        self.reset()

    def reset(self) -> None:
        self._clients: dict[str, _Client] = {}
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:06d}"

    def add_client(self, fields: dict[str, Any]) -> str:
        client_id = self._next_id(self._prefixes.client)
        self._clients[client_id] = _Client(fields=dict(fields))
        return client_id

    def has_client(self, client_id: str) -> bool:
        return client_id in self._clients

    def has_program_enrollment(self, client_id: str) -> bool:
        return bool(self._clients[client_id].enrollment_ids)

    def add_enrollment(self, client_id: str, fields: dict[str, Any]) -> str:
        enrollment_id = self._next_id(self._prefixes.enrollment)
        self._clients[client_id].enrollment_ids.append(enrollment_id)
        return enrollment_id

    def add_ce_enrollment(self, client_id: str, fields: dict[str, Any]) -> str:
        ce_id = self._next_id(self._prefixes.ce_enrollment)
        self._clients[client_id].ce_enrollment_ids.append(ce_id)
        return ce_id

    def possible_duplicate(self, match_on: list[str], fields: dict[str, Any]) -> bool:
        """True when an existing client matches on every match field. Blank values never match."""
        wanted = [_normalize(fields.get(name)) for name in match_on]
        if any(v is None for v in wanted):
            return False
        return any(
            [_normalize(c.fields.get(name)) for name in match_on] == wanted for c in self._clients.values()
        )

    def counts(self) -> dict[str, int]:
        """Totals for in-process tests. Not exposed by any endpoint."""
        return {
            "clients": len(self._clients),
            "enrollments": sum(len(c.enrollment_ids) for c in self._clients.values()),
            "ce_enrollments": sum(len(c.ce_enrollment_ids) for c in self._clients.values()),
        }


def _normalize(value: Any) -> Any:
    if value is None or value == "":
        return None
    return value.strip().lower() if isinstance(value, str) else value
