"""Task 3.3: the REALLMS parser, with a mocked HTTP client. No network is used here."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.config_loader import load_config
from parser.factory import build_parser
from parser.llm import ReallmsParser
from parser.rule_stub import RuleStubParser
from parser.shared import split_sentences

CONFIG = load_config()
FAKE_KEY = "test-key-do-not-log-0123456789"


def _completion(content: str) -> dict:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}


def _reply_from_stub(email) -> dict:
    """A well-formed model reply equal to what the stub extracts (sources copied from the email)."""
    stub = RuleStubParser(CONFIG).parse(email)
    sentences = split_sentences(email.body, CONFIG)

    def original(source: str) -> str:
        # The stub's sources are already cleaned; a model quotes the sentence as written.
        prefix = source.split("[")[0].split("***")[0]
        return next(s for s in sentences if s.startswith(prefix))

    fields = {name: {"value": None} for name in CONFIG.parsable_fields()}
    for name, f in stub.fields.items():
        fields[name] = {"value": f.value, "source": original(f.source), "confidence": f.confidence}
    search = stub.hmis_search_stated
    return {
        "hmis_search_stated": {"value": bool(search), "source": search.source if search else None, "confidence": "high"},
        "fields": fields,
        "case_note": stub.case_note,
        "notices": [],
    }


class FakeReallms:
    """Records requests and plays back queued responses (dicts, strings, Responses, or exceptions)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        content = item if isinstance(item, str) else json.dumps(item)
        return httpx.Response(200, json=_completion(content))

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


def _parser(fake: FakeReallms, *, key: str | None = FAKE_KEY, model: str | None = None) -> ReallmsParser:
    http = httpx.Client(base_url=CONFIG.settings.reallms.base_url, transport=httpx.MockTransport(fake))
    return ReallmsParser(CONFIG, api_key=key, model=model, http=http)


@pytest.fixture
def email(sample_emails):
    return sample_emails["01b_clean_new_client_complete"]


# Spec scenario: Swappable parser


def test_swappable_parser(email):
    fake = FakeReallms(_reply_from_stub(email))
    llm = _parser(fake).parse(email)
    stub = RuleStubParser(CONFIG).parse(email)
    assert llm.ok
    assert {n: f.value for n, f in llm.fields.items()} == {n: f.value for n, f in stub.fields.items()}
    assert type(llm) is type(stub)


def test_request_uses_chat_completions_with_low_temperature_and_bearer_key(email):
    fake = FakeReallms(_reply_from_stub(email))
    _parser(fake).parse(email)
    request = fake.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://reallms.rescloud.iu.edu/direct/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    body = fake.bodies()[0]
    assert body["model"] == "gpt-oss-120b"
    assert body["temperature"] == 0
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "response_format" not in body  # no JSON mode is assumed


def test_only_the_note_and_sent_date_are_sent(email):
    fake = FakeReallms(_reply_from_stub(email))
    _parser(fake).parse(email)
    sent = json.dumps(fake.bodies()[0])
    assert email.sender not in sent
    assert email.body.split()[0] in sent
    assert "2026-10-07" in sent


def test_model_is_easy_to_change(email, monkeypatch, config_copy):
    fake = FakeReallms(_reply_from_stub(email))
    _parser(fake, model="glm-5.2").parse(email)
    assert fake.bodies()[0]["model"] == "glm-5.2"


def test_factory_builds_reallms_when_configured(monkeypatch):
    monkeypatch.setenv("REALLMS_API_KEY", FAKE_KEY)
    monkeypatch.setenv("REALLMS_MODEL", "gemma-4-31B-it")
    config = CONFIG.model_copy(update={"settings": CONFIG.settings.model_copy(update={"parser": "reallms"})})
    parser = build_parser(config)
    assert isinstance(parser, ReallmsParser)
    assert parser.model == "gemma-4-31B-it"


def test_code_fenced_json_is_accepted(email):
    fake = FakeReallms("```json\n" + json.dumps(_reply_from_stub(email)) + "\n```")
    assert _parser(fake).parse(email).ok


# Retry once, then flag


def test_invalid_json_is_retried_once_with_the_problems(email):
    fake = FakeReallms("Sure! Here is the data: {not json", _reply_from_stub(email))
    result = _parser(fake).parse(email)
    assert result.ok
    assert len(fake.requests) == 2
    retry = fake.bodies()[1]["messages"]
    assert [m["role"] for m in retry] == ["system", "user", "assistant", "user"]
    assert "not valid JSON" in retry[-1]["content"] or "did not contain" in retry[-1]["content"]


def test_still_invalid_after_retry_flags_the_draft(email):
    fake = FakeReallms("no json here", "still no json")
    result = _parser(fake).parse(email)
    assert not result.ok
    assert result.failure.code == "invalid_output"
    assert "Nothing was drafted or entered" in result.failure.message
    assert result.fields == {} and result.case_note is None
    assert len(fake.requests) == 2


def test_source_not_in_the_email_is_rejected(email):
    bad = _reply_from_stub(email)
    bad["fields"]["veteran_status"] = {"value": "yes", "source": "He served in the army.", "confidence": "high"}
    fake = FakeReallms(bad, bad)
    result = _parser(fake).parse(email)
    assert result.failure.code == "invalid_output"
    assert any("veteran_status" in f and "copied exactly" in f for f in result.flags)


def test_invented_day_is_rejected(sample_emails):
    email = sample_emails["01_clean_new_client"]
    bad = _reply_from_stub(email)
    bad["fields"]["approx_date_homelessness_started"] = {
        "value": "2025-03-01", "source": "Started being homeless around March 2025.", "confidence": "medium",
    }
    fake = FakeReallms(bad, _reply_from_stub(email))
    result = _parser(fake).parse(email)
    assert result.ok
    assert "approx_date_homelessness_started" not in result.fields
    assert "does not state the day" in fake.bodies()[1]["messages"][-1]["content"]


def test_value_outside_the_allowed_options_is_rejected(email):
    bad = _reply_from_stub(email)
    bad["fields"]["gender"]["value"] = ["man"]
    fake = FakeReallms(bad, bad)
    assert _parser(fake).parse(email).failure.code == "invalid_output"


def test_program_defaults_and_fixed_values_are_never_taken_from_the_model(email):
    reply = _reply_from_stub(email)
    reply["fields"]["record_contact"] = {"value": False, "source": email.body.split(".")[0], "confidence": "high"}
    reply["fields"]["verified_by_project"] = {"value": "Somewhere", "source": email.body.split(".")[0], "confidence": "high"}
    result = _parser(FakeReallms(reply)).parse(email)
    assert "record_contact" not in result.fields and "verified_by_project" not in result.fields


def test_full_ssn_from_the_model_is_masked_and_checked(sample_emails):
    email = sample_emails["05_privacy_traps"]
    reply = _reply_from_stub(email)
    reply["fields"]["ssn_last4"] = {"value": "6789", "source": "SSN 123-45-6789.", "confidence": "high"}
    reply["fields"]["ssn_quality"] = {"value": "full_ssn_reported", "source": "SSN 123-45-6789.", "confidence": "high"}
    reply["case_note"] = "Met Alex D. SSN 123-45-6789 noted."
    result = _parser(FakeReallms(reply)).parse(email)
    assert "123-45-6789" not in result.model_dump_json()
    assert "ssn_quality" not in result.fields
    assert any(f.startswith("ssn_known_invalid_pattern") for f in result.flags)


# Errors: clear failure, never a silent empty draft, never the key


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.ReadTimeout("timed out"), "timeout"),
        (httpx.ConnectError("refused"), "unreachable"),
        (httpx.Response(401, json={"error": "invalid key"}), "unauthorized"),
        (httpx.Response(429, json={"error": "slow down"}), "rate_limited"),
        (httpx.Response(500, text="boom"), "service_error"),
        (httpx.Response(200, text="<html>not json</html>"), "malformed_response"),
        (httpx.Response(200, json={"choices": []}), "malformed_response"),
        (httpx.Response(200, json=_completion("")), "malformed_response"),
    ],
)
def test_service_errors_produce_a_clear_failure(email, caplog, response, code):
    caplog.set_level(logging.DEBUG)
    result = _parser(FakeReallms(response)).parse(email)
    assert not result.ok
    assert result.failure.code == code
    assert "Nothing was drafted or entered" in result.failure.message
    assert result.fields == {} and result.case_note is None
    assert FAKE_KEY not in result.model_dump_json()
    assert FAKE_KEY not in caplog.text
    assert email.body[:20] not in caplog.text


def test_missing_key_fails_without_calling_the_service(email):
    fake = FakeReallms()
    result = _parser(fake, key=None).parse(email)
    assert result.failure.code == "not_configured"
    assert fake.requests == []


def test_key_is_not_in_the_parser_repr():
    parser = _parser(FakeReallms())
    assert FAKE_KEY not in repr(parser)
