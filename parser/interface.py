"""The parser interface. Every implementation returns a ParseResult.

A field appears in `fields` only when the email states it. Missing fields are simply
absent; the workflow flags them. A failed parse sets `failure` and is never an empty
draft that looks complete.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from app.email_message import IntakeEmail

Confidence = Literal["high", "medium", "low"]

FailureCode = Literal[
    "not_configured",
    "timeout",
    "unreachable",
    "unauthorized",
    "rate_limited",
    "service_error",
    "malformed_response",
    "invalid_output",
]


class ParsedField(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: Any
    source: str  # the sentence from the email the value came from
    confidence: Confidence


class ParserFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: FailureCode
    message: str  # shown to the worker; never contains the API key or email text


class ParseResult(BaseModel):
    parser: str
    fields: dict[str, ParsedField] = {}
    hmis_search_stated: ParsedField | None = None
    case_note: str | None = None
    notices: list[str] = []
    flags: list[str] = []
    failure: ParserFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None


class EmailParser(Protocol):
    name: str

    def parse(self, email: IntakeEmail) -> ParseResult: ...
