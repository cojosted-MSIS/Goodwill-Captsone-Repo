"""Optional live test against REALLMS. Skipped unless REALLMS_API_KEY is set (in the environment or .env).

Sends one synthetic sample email to the configured model.
"""

from __future__ import annotations

import os

import pytest

from app.config_loader import load_config
from parser.evaluation import evaluate, load_expected
from parser.factory import API_KEY_ENV, build_reallms_parser, load_env

load_env()

pytestmark = pytest.mark.skipif(not os.environ.get(API_KEY_ENV), reason=f"{API_KEY_ENV} is not set")


def test_live_reallms_parses_the_clean_sample(sample_emails):
    config = load_config()
    stem = "01b_clean_new_client_complete"
    result = build_reallms_parser(config).parse(sample_emails[stem])
    assert result.ok, result.failure
    evaluation = evaluate(result, load_expected()[stem], config, check_confidence=False)
    assert not evaluation.inferred, evaluation.inferred
    assert result.fields["first_name"].value == "Pat"
