"""LLM parser using REALLMS, the IU-hosted service, as REALLMS_GUIDE.md specifies.

- response_format json_schema with strict: true (guided_json is ignored by IU's API and
  prompt-only JSON fails), temperature 0, one note per request, the note sent unmodified.
- The answer is read only from choices[0].message.content, and finish_reason must be "stop".
- Every reply goes through parser/llm_checks.py. A failing reply is retried once with the
  problems listed; a second failure is flagged for the worker and nothing is saved.
- HTTP 429 and 5xx are retried with exponential backoff. Timeout is 180 seconds.
- At startup, check_model() calls GET /models and fails clearly if the model is not listed.

The API key goes only in the Authorization header. It is never logged, stored, or put in a
message, and note text is never logged. Only synthetic data may be sent.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable

import httpx
import jsonschema

from app.config_loader import AppConfig
from app.email_message import IntakeEmail

from .interface import FailureCode, ParsedField, ParseResult, ParserFailure
from .llm_checks import check_reply, to_result
from .llm_v2 import CASE_NOTE_PROMPT, CASE_NOTE_SCHEMA, PROMPT_STYLE, PROMPT_VERSION, build_prompt, build_schema
from .shared import finalize

logger = logging.getLogger(__name__)

NOTHING_ENTERED = "Nothing was drafted or entered into HMIS."
KEY_PROBLEM = (
    "REALLMS rejected the API key (401 token_not_found_in_db). This is a key problem, not a code bug: "
    "check LLM_API_KEY for a typo or a stray line break, and that the key is from the RT Projects "
    "allocation page and approved (keys from the REALLMS Chat website do not work on the API)."
)

WORKER_MESSAGES: dict[FailureCode, str] = {
    "not_configured": f"The AI parser is not set up (no LLM_API_KEY). {NOTHING_ENTERED} Ask the demo admin.",
    "timeout": f"The AI parser did not answer in time. {NOTHING_ENTERED} Please resend your note.",
    "unreachable": f"The AI parser could not be reached. {NOTHING_ENTERED} Please resend your note.",
    "unauthorized": f"The AI parser rejected the demo's API key. {NOTHING_ENTERED} Ask the demo admin to check the key.",
    "rate_limited": f"The AI parser is busy. {NOTHING_ENTERED} Please resend your note in a few minutes.",
    "service_error": f"The AI parser returned an error. {NOTHING_ENTERED} Please resend your note.",
    "malformed_response": f"The AI parser sent a response the system could not read. {NOTHING_ENTERED} Please resend your note.",
    "invalid_output": (
        f"The AI parser's draft did not pass the intake checks, even after a retry. {NOTHING_ENTERED} "
        "The note is waiting for human review. Please resend it or enter the record in HMIS yourself."
    ),
}


class ParserStartupError(RuntimeError):
    """The REALLMS parser cannot start (no key, bad key, unreachable, or the model is not listed)."""


class _CallFailed(Exception):
    def __init__(self, code: FailureCode, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _fill(template: str, **values: str) -> str:
    """Insert values in one pass, so text inside a note is never treated as a placeholder."""
    return re.sub(r"\{(" + "|".join(values) + r")\}", lambda m: values[m.group(1)], template)


class ReallmsParser:
    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        config: AppConfig,
        *,
        api_key: str | None,
        base_url: str | None = None,
        model: str | None = None,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_reply: Callable[[int, dict | None, list[str]], None] | None = None,
    ) -> None:
        settings = config.settings.reallms
        self._config = config
        self._settings = settings
        self._api_key = (api_key or "").strip() or None
        self.model = model or settings.model
        if self.model not in settings.allowed_models:
            raise ParserStartupError(
                f"Model {self.model!r} is not allowed. Use {settings.model!r} or a fallback: {settings.fallback_models}."
            )
        if self.model != settings.model and PROMPT_STYLE != settings.fallback_requires_prompt_style:
            raise ParserStartupError(f"Fallback model {self.model!r} needs a {settings.fallback_requires_prompt_style} prompt.")
        self.base_url = (base_url or settings.base_url).rstrip("/")
        self.name = f"reallms:{self.model}"
        self._http = http or httpx.Client(base_url=self.base_url, timeout=settings.timeout_seconds)
        self._sleep = sleep
        self._on_reply = on_reply  # evaluation hook: (attempt, reply, problems); synthetic data only
        self._schema = build_schema(config)
        self._prompt = build_prompt(config)

    def __repr__(self) -> str:
        return f"ReallmsParser(model={self.model!r}, key={'set' if self._api_key else 'missing'})"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    # Startup

    def check_model(self) -> None:
        """GET /models and fail clearly if the key is bad or the configured model is not listed."""
        if not self._api_key:
            raise ParserStartupError("LLM_API_KEY is not set. Copy .env.example to .env and add your REALLMS key.")
        try:
            response = self._http.get("models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise ParserStartupError(f"REALLMS could not be reached at {self.base_url} ({type(exc).__name__}).") from exc
        if response.status_code in (401, 403):
            raise ParserStartupError(KEY_PROBLEM if "token_not_found_in_db" in response.text else
                                     f"REALLMS refused the API key (HTTP {response.status_code}). Check LLM_API_KEY.")
        if response.status_code != 200:
            raise ParserStartupError(f"GET /models returned HTTP {response.status_code}.")
        try:
            ids = [m.get("id") for m in response.json().get("data", [])]
        except (ValueError, AttributeError) as exc:
            raise ParserStartupError("GET /models returned a response that could not be read.") from exc
        if self.model not in ids:
            raise ParserStartupError(f"Model {self.model!r} is not listed by REALLMS. Listed: {', '.join(map(str, ids)) or 'none'}.")

    # Parsing

    def parse(self, email: IntakeEmail) -> ParseResult:
        if not self._api_key:
            return self._failed("not_configured")
        note = email.body  # sent exactly as written
        messages = [{"role": "user", "content": _fill(self._prompt, note=note)}]
        try:
            content, finish = self._chat(messages, self._schema, "intake")
            obj, problems = check_reply(content, finish, note, self._schema, self._config, email.sent_at.date())
            self._report(1, obj, problems)
            first_problems = problems
            attempts = 1
            if problems:
                logger.info("REALLMS reply failed %d checks; retrying once", len(problems))
                messages += [
                    {"role": "assistant", "content": content or ""},
                    {"role": "user", "content": "Your reply failed these checks:\n"
                     + "\n".join(f"- {p}" for p in problems)
                     + "\nReply again for the same note, following every rule."},
                ]
                content, finish = self._chat(messages, self._schema, "intake")
                obj, problems = check_reply(content, finish, note, self._schema, self._config, email.sent_at.date())
                self._report(2, obj, problems)
                attempts = 2
        except _CallFailed as failed:
            logger.warning("REALLMS call failed: %s %s", failed.code, failed.detail)
            return self._failed(failed.code)
        if problems:
            logger.warning("REALLMS reply failed checks after retry (%d problems); sent to human review", len(problems))
            return self._failed("invalid_output", attempts=attempts, retry_reasons=first_problems,
                                flags=[f"parser_check: {p}" for p in problems])
        result = to_result(obj, email, self._config, parser=self.name, model=self.model, prompt_version=self.prompt_version)
        result = result.model_copy(update={"attempts": attempts, "retry_reasons": first_problems})
        return finalize(result, email, self._config)

    def _report(self, attempt: int, obj: dict | None, problems: list[str]) -> None:
        if self._on_reply is not None:
            self._on_reply(attempt, obj, problems)

    def regenerate_case_note(self, note: str, corrections: str, fields: dict[str, ParsedField]) -> str | None:
        if not self._api_key:
            return None
        prompt = _fill(CASE_NOTE_PROMPT, note=note, corrections=corrections)
        try:
            content, finish = self._chat([{"role": "user", "content": prompt}], CASE_NOTE_SCHEMA, "case_note")
        except _CallFailed as failed:
            logger.warning("REALLMS case note call failed: %s", failed.code)
            return None
        obj, problems = check_case_note(content, finish)
        return None if problems else obj["case_note"].strip()

    def _failed(self, code: FailureCode, **extra) -> ParseResult:
        return ParseResult(
            parser=self.name,
            model=self.model,
            prompt_version=self.prompt_version,
            failure=ParserFailure(code=code, message=WORKER_MESSAGES[code]),
            **extra,
        )

    def _chat(self, messages: list[dict[str, str]], schema: dict, name: str) -> tuple[str | None, str | None]:
        s = self._settings
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
            "temperature": s.temperature,
        }
        if s.max_tokens:
            payload["max_tokens"] = s.max_tokens
        for attempt in range(s.http_retries + 1):
            try:
                response = self._http.post("chat/completions", json=payload, headers=self._headers())
            except httpx.TimeoutException as exc:
                raise _CallFailed("timeout") from exc
            except httpx.TransportError as exc:
                raise _CallFailed("unreachable", type(exc).__name__) from exc
            status = response.status_code
            if status == 429 or status >= 500:
                if attempt < s.http_retries:
                    delay = s.backoff_seconds * (2 ** attempt)
                    logger.info("REALLMS HTTP %d; retrying in %.0f s", status, delay)
                    self._sleep(delay)
                    continue
                raise _CallFailed("rate_limited" if status == 429 else "service_error", f"HTTP {status}")
            if status in (401, 403):
                raise _CallFailed("unauthorized", KEY_PROBLEM if "token_not_found_in_db" in response.text else f"HTTP {status}")
            if status >= 400:
                raise _CallFailed("service_error", f"HTTP {status}")
            try:
                choice = response.json()["choices"][0]
                content = choice["message"].get("content")  # never reasoning_content
                return content, choice.get("finish_reason")
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                raise _CallFailed("malformed_response", "unexpected response shape") from exc
        raise _CallFailed("service_error", "retries exhausted")  # not reached


def check_case_note(content: str | None, finish: str | None) -> tuple[dict | None, list[str]]:
    if finish != "stop":
        return None, ["cut off"]
    try:
        obj = json.loads(content or "")
        jsonschema.validate(obj, CASE_NOTE_SCHEMA)
    except (json.JSONDecodeError, jsonschema.ValidationError):
        return None, ["invalid"]
    return (obj, []) if obj["case_note"].strip() else (None, ["empty"])
