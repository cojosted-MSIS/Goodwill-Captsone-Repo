"""The parser interface. Every implementation returns a ParseResult.

A field appears in `fields` only when the email states it. Missing fields are simply
absent; the workflow flags them. A failed parse sets `failure` and is never an empty
draft that looks complete. `model`, `prompt_version`, and `parsed_at` are stored with the
draft and in the audit record.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

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


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ParseResult(BaseModel):
    parser: str
    model: str | None = None
    prompt_version: str
    parsed_at: datetime = Field(default_factory=_now)
    fields: dict[str, ParsedField] = {}
    hmis_search_stated: ParsedField | None = None
    contact_date_phrase: ParsedField | None = None  # the words, resolved later in code
    case_note: str | None = None
    notices: list[str] = []
    flags: list[str] = []
    attempts: int = 1
    retry_reasons: list[str] = []  # checks the first reply failed, if it was retried
    elapsed_seconds: float | None = None  # how long parsing took, set by the workflow
    failure: ParserFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None


QueryType = Literal["briefing", "lookup", "status", "no_contact"]


class QueryRequest(BaseModel):
    """What a parser read from a "Query:" email: one fixed query type and its parameters.

    A parser never returns query text. Code validates every parameter before any query
    runs (app/queries.py) and runs only its own fixed queries (app/hmis_reader.py).
    """

    query_type: QueryType | None = None  # None: the question matches no query type
    quadrant: str | None = None  # nw, ne, sw, se
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth_as_written: str | None = None  # copied as written; read in code
    client_id: str | None = None
    status_type: str | None = None  # an id in settings hmis_queries.status_types
    failure: ParserFailure | None = None


class EmailParser(Protocol):
    name: str

    def parse(self, email: IntakeEmail) -> ParseResult: ...

    def parse_query(self, email: IntakeEmail) -> QueryRequest:
        """The query type and parameters of a "Query:" email. Never SQL."""
        ...

    def regenerate_case_note(self, note: str, corrections: str, fields: dict[str, ParsedField]) -> str | None:
        """A case note that reflects the worker's corrections, or None if it could not be written."""
        ...
