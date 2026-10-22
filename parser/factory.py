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
from .llm import ParserStartupError, ReallmsParser
from .rule_stub import RuleStubParser

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
API_KEY_ENV = "LLM_API_KEY"
BASE_URL_ENV = "LLM_BASE_URL"
MODEL_ENV = "LLM_MODEL"

__all__ = ["API_KEY_ENV", "BASE_URL_ENV", "MODEL_ENV", "ParserStartupError", "build_parser", "build_reallms_parser", "load_env"]


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
                         check: bool = True) -> ReallmsParser:
    """Build the REALLMS parser. With check=True (startup), GET /models must list the model."""
    load_env()
    parser = ReallmsParser(
        config,
        api_key=os.environ.get(API_KEY_ENV),
        base_url=os.environ.get(BASE_URL_ENV) or None,
        model=model or os.environ.get(MODEL_ENV) or None,
        http=http,
    )
    if check:
        parser.check_model()
    return parser
