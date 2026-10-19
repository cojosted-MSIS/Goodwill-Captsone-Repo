"""Failure switches that make the mock HMIS reject entries on purpose."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .rules import Operation

FailureMode = Literal["missing_required_field", "possible_duplicate", "service_unavailable"]


@dataclass
class _Switch:
    mode: FailureMode
    remaining: int | None  # None means until cleared


class FailureSwitches:
    def __init__(self) -> None:
        self._switches: dict[Operation, _Switch] = {}

    def set(self, operation: Operation, mode: FailureMode, times: int | None = 1) -> None:
        """Fail the next `times` calls to `operation` (every call when times is None)."""
        if times is not None and times < 1:
            raise ValueError("times must be at least 1, or None for every call")
        self._switches[operation] = _Switch(mode=mode, remaining=times)

    def clear(self) -> None:
        self._switches.clear()

    def take(self, operation: Operation) -> FailureMode | None:
        """The forced failure for this call, if any, using up one of its remaining calls."""
        switch = self._switches.get(operation)
        if switch is None:
            return None
        if switch.remaining is not None:
            switch.remaining -= 1
            if switch.remaining == 0:
                del self._switches[operation]
        return switch.mode
