"""Choose the parser from config/settings.yaml (`parser: rule_stub` or `parser: reallms`)."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.config_loader import AppConfig

from .interface import EmailParser
from .llm import ReallmsParser
from .rule_stub import RuleStubParser

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
API_KEY_ENV = "REALLMS_API_KEY"
MODEL_ENV = "REALLMS_MODEL"


def load_env() -> None:
    """Load .env without overriding variables already set in the environment."""
    load_dotenv(ENV_FILE, override=False)


def build_parser(config: AppConfig, *, model: str | None = None, http: httpx.Client | None = None) -> EmailParser:
    if config.settings.parser == "rule_stub":
        return RuleStubParser(config)
    return build_reallms_parser(config, model=model, http=http)


def build_reallms_parser(config: AppConfig, *, model: str | None = None, http: httpx.Client | None = None) -> ReallmsParser:
    load_env()
    return ReallmsParser(
        config,
        api_key=os.environ.get(API_KEY_ENV),
        model=model or os.environ.get(MODEL_ENV) or None,
        http=http,
    )
