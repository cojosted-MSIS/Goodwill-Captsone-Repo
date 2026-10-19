"""LLM parser using REALLMS, the IU-hosted chat completions service.

The service is not assumed to support a JSON output mode. JSON is asked for in the
prompt, read, and checked; one retry is made with the problems listed. Every failure
returns a ParseResult with `failure` set and a message for the worker. The API key is
sent only in the Authorization header and never logged or included in a message.
Only synthetic data may be sent.
"""

from __future__ import annotations

import logging

import httpx

from app.config_loader import AppConfig
from app.email_message import IntakeEmail

from .interface import FailureCode, ParseResult, ParserFailure
from .llm_output import LlmOutputError, extract_json, validate_output
from .prompt import build_messages, retry_message
from .shared import finalize

logger = logging.getLogger(__name__)

NOTHING_ENTERED = "Nothing was drafted or entered into HMIS."

WORKER_MESSAGES: dict[FailureCode, str] = {
    "not_configured": f"The AI parser is not set up (no REALLMS key). {NOTHING_ENTERED} Ask the demo admin.",
    "timeout": f"The AI parser did not answer in time. {NOTHING_ENTERED} Please resend your note.",
    "unreachable": f"The AI parser could not be reached. {NOTHING_ENTERED} Please resend your note.",
    "unauthorized": f"The AI parser rejected the demo's credentials. {NOTHING_ENTERED} Ask the demo admin to check the REALLMS key.",
    "rate_limited": f"The AI parser is busy. {NOTHING_ENTERED} Please resend your note in a few minutes.",
    "service_error": f"The AI parser returned an error. {NOTHING_ENTERED} Please resend your note.",
    "malformed_response": f"The AI parser sent a response the system could not read. {NOTHING_ENTERED} Please resend your note.",
    "invalid_output": (
        f"The AI parser could not produce a draft that follows the intake rules, even after a retry. "
        f"{NOTHING_ENTERED} Please resend your note or enter the record in HMIS yourself."
    ),
}


class _CallFailed(Exception):
    def __init__(self, code: FailureCode, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


class ReallmsParser:
    def __init__(
        self,
        config: AppConfig,
        *,
        api_key: str | None,
        model: str | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        settings = config.settings.reallms
        self._config = config
        self._settings = settings
        self._api_key = api_key or None
        self.model = model or settings.model
        self.name = f"reallms:{self.model}"
        self._http = http or httpx.Client(base_url=settings.base_url, timeout=settings.timeout_seconds)

    def __repr__(self) -> str:
        return f"ReallmsParser(model={self.model!r}, key={'set' if self._api_key else 'missing'})"

    def parse(self, email: IntakeEmail) -> ParseResult:
        if not self._api_key:
            return self._failed("not_configured")
        messages = build_messages(email, self._config)
        try:
            content = self._chat(messages)
            try:
                return self._read(content, email)
            except LlmOutputError as first:
                logger.info("REALLMS reply failed checks (%d problems), retrying once", len(first.problems))
                messages += [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": retry_message(first.problems)},
                ]
            content = self._chat(messages)
            try:
                return self._read(content, email)
            except LlmOutputError as second:
                logger.warning("REALLMS reply failed checks after retry (%d problems)", len(second.problems))
                return self._failed("invalid_output", flags=[f"parser_problem: {p}" for p in second.problems])
        except _CallFailed as failed:
            logger.warning("REALLMS call failed: %s %s", failed.code, failed.detail)
            return self._failed(failed.code)

    def _read(self, content: str, email: IntakeEmail) -> ParseResult:
        result = validate_output(extract_json(content), email, self._config, self.name)
        return finalize(result, email, self._config)

    def _failed(self, code: FailureCode, flags: list[str] | None = None) -> ParseResult:
        return ParseResult(
            parser=self.name,
            failure=ParserFailure(code=code, message=WORKER_MESSAGES[code]),
            flags=flags or [],
        )

    def _chat(self, messages: list[dict[str, str]]) -> str:
        payload: dict = {"model": self.model, "messages": messages, "temperature": self._settings.temperature}
        if self._settings.max_tokens:
            payload["max_tokens"] = self._settings.max_tokens
        try:
            response = self._http.post(
                "chat/completions", json=payload, headers={"Authorization": f"Bearer {self._api_key}"}
            )
        except httpx.TimeoutException as exc:
            raise _CallFailed("timeout") from exc
        except httpx.TransportError as exc:
            raise _CallFailed("unreachable", type(exc).__name__) from exc
        status = response.status_code
        if status in (401, 403):
            raise _CallFailed("unauthorized", f"status {status}")
        if status == 429:
            raise _CallFailed("rate_limited", "status 429")
        if status >= 400:
            raise _CallFailed("service_error", f"status {status}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise _CallFailed("malformed_response", "unexpected response shape") from exc
        if not isinstance(content, str) or not content.strip():
            raise _CallFailed("malformed_response", "empty message content")
        return content
