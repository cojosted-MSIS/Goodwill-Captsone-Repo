"""Choose the parser from config/settings.yaml (`parser: rule_stub` or `parser: reallms`).

REALLMS settings come from the environment (or .env, git-ignored) using the names in
docs/reference/reallms/REALLMS_GUIDE.md: LLM_API_KEY, LLM_BASE_URL, LLM_MODEL.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.config_loader import AppConfig

from .interface import EmailParser
from .llm import ALLOW_NOT_RECOMMENDED_ENV, ParserStartupError, ReallmsParser
from .rule_stub import RuleStubParser

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
API_KEY_ENV = "LLM_API_KEY"
BASE_URL_ENV = "LLM_BASE_URL"
MODEL_ENV = "LLM_MODEL"

__all__ = ["ALLOW_NOT_RECOMMENDED_ENV", "API_KEY_ENV", "BASE_URL_ENV", "MODEL_ENV", "ParserStartupError", "build_parser", "build_reallms_parser", "load_env"]


def load_env() -> None:
    """Load .env without overriding variables already set in the environment."""
    load_dotenv(ENV_FILE, override=False)


def build_parser(config: AppConfig, *, model: str | None = None, http: httpx.Client | None = None,
                 check: bool = True, parser: str | None = None) -> EmailParser:
    """`parser` ("rule_stub" or "reallms") overrides config/settings.yaml for one run."""
    if parser not in (None, "rule_stub", "reallms"):
        raise ValueError(f"unknown parser {parser!r}: use rule_stub or reallms")
    if (parser or config.settings.parser) == "rule_stub":
        return RuleStubParser(config)
    return build_reallms_parser(config, model=model, http=http, check=check)


def build_reallms_parser(config: AppConfig, *, model: str | None = None, http: httpx.Client | None = None,
                         check: bool = True, allow_not_recommended: bool | None = None) -> ReallmsParser:
    """Build the REALLMS parser. With check=True (startup), GET /models must list the model.

    A model listed as not recommended in config/settings.yaml is refused unless
    allow_not_recommended is True, or LLM_ALLOW_NOT_RECOMMENDED=1 when it is not given."""
    load_env()
    if allow_not_recommended is None:
        allow_not_recommended = os.environ.get(ALLOW_NOT_RECOMMENDED_ENV, "").strip().lower() in ("1", "true", "yes")
    parser = ReallmsParser(
        config,
        api_key=os.environ.get(API_KEY_ENV),
        base_url=os.environ.get(BASE_URL_ENV) or None,
        model=model or os.environ.get(MODEL_ENV) or None,
        http=http,
        allow_not_recommended=allow_not_recommended,
    )
    if check:
        parser.check_model()
    return parser
