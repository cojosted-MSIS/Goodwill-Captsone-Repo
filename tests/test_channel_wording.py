"""add-web-application, Stage 3a: messages as neutral keys, worded by each channel, and neutral audit names.

Specs: openspec/changes/add-web-application/specs/web-application/spec.md ("Word messages for each
channel", "Staff audit views without neighbor information"). The email wording itself is pinned
by the existing email tests. Here: every web screen and API message is free of email wording,
the audit uses neutral names (old names still read correctly), and the views that show draft
contents are demo-only. Synthetic data only.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config_loader import load_config, with_draft_content_views
from app.email_wording import EMAIL, EMAIL_PHRASES
from app.web_wording import WEB, WEB_PHRASES
from parser.interface import ParseResult, ParserFailure

from .conftest import REPO_ROOT
from .test_web_api import JORDAN, NOTE, ROBIN

LONG_REASON = "He is about twenty years younger than the person in HMIS and has a different tattoo"
# Email wording a web screen must never show: the commands, "reply", "email", and reference tokens.
EMAIL_WORDS = re.compile(r"\b(reply|replies|replied|replying|email|emails|e-mail|resend|inbox)\b", re.IGNORECASE)
EMAIL_COMMANDS = re.compile(r"\bCONFIRM\b|\bRETRY\b|SAME CLIENT|DIFFERENT PERSON|CLIENT <ID>|\[(ENC|INT|UPD|QRY)-")
NOT_WORDING = {"origin"}  # internal codes ("email" is where a value came from), never shown as text


def texts(value, key=None):
    """Every string a screen could show from an API response."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k not in NOT_WORDING:
                yield from texts(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from texts(v, key)
    elif isinstance(value, str):
        yield value


def email_wording_in(value) -> list[str]:
    return [t for t in texts(value) if EMAIL_WORDS.search(t) or EMAIL_COMMANDS.search(t)]


class Recorder:
    """A signed-in worker whose every API response is kept for the wording check."""

    def __init__(self, web, username="j.alvarez"):
        self.client, self.seen = web.as_user(username), []

    def get(self, path):
        r = self.client.get(path)
        self.seen.append(r.json())
        return r.json()

    def post(self, path, body=None):
        r = self.client.post(path, json=body or {})
        self.seen.append(r.json())
        return r.json()


# Catalogs


def test_each_channel_words_every_message_and_phrase():
    assert set(EMAIL) == set(WEB) and set(EMAIL_PHRASES) == set(WEB_PHRASES)


def test_web_wording_has_no_email_words():
    for key, (subject, body) in WEB.items():
        for text in (subject, body):
            if isinstance(text, str):
                assert not EMAIL_WORDS.search(text) and not EMAIL_COMMANDS.search(text), key
    for key, text in WEB_PHRASES.items():
        if isinstance(text, str):
            assert not EMAIL_WORDS.search(text) and not EMAIL_COMMANDS.search(text), key


def test_messages_carry_their_neutral_key(web):
    w = Recorder(web)
    out = w.post("/api/v1/notes/new-client", {"text": NOTE.replace("Searched HMIS first, no match. ", "")})
    assert [m["key"] for m in out["messages"]] == ["search_request"]
    assert "I searched HMIS, no match" in out["messages"][0]["body"]


# The sweep: every web flow, every response, no email wording


def test_no_web_screen_or_message_uses_email_wording(web, monkeypatch):
    w = Recorder(web)
    intake = web.intake

    # A new client: rephrase, a correction, an old version, a failed entry, a retry, and the receipt.
    ref = w.post("/api/v1/notes/new-client", {"text": NOTE})["ref"]
    w.get(f"/api/v1/drafts/{ref}")
    w.post(f"/api/v1/drafts/{ref}/corrections", {"text": "Blue sky today."})
    w.post(f"/api/v1/drafts/{ref}/corrections", {"text": "Veteran: didn't ask about that"})
    w.post(f"/api/v1/drafts/{ref}/corrections", {"text": "It was the second time on the street, not the third."})
    w.post(f"/api/v1/drafts/{ref}/confirm", {"version": 1})
    w.get(f"/api/v1/drafts/{ref}")
    intake.fail_next("create_client", "service_unavailable")
    w.post(f"/api/v1/drafts/{ref}/confirm", {"version": intake.draft(ref).version})
    w.get(f"/api/v1/drafts/{ref}")
    w.post(f"/api/v1/drafts/{ref}/retry")
    w.get(f"/api/v1/drafts/{ref}")

    # A held note, and a note missing its CE region.
    held = w.post("/api/v1/notes/new-client", {"text": NOTE.replace("Searched HMIS first, no match. ", "").replace("Kim", "Kai")})
    w.post(f"/api/v1/held/{held['ref']}/searched", {"statement": "I looked around"})
    w.post(f"/api/v1/held/{held['ref']}/searched", {})
    missing = w.post("/api/v1/notes/new-client", {"text": NOTE.replace("Kim", "Kit").replace(", CE region 7", "")})["ref"]
    w.get(f"/api/v1/drafts/{missing}")
    w.post(f"/api/v1/drafts/{missing}/confirm", {"version": 1})

    # Same name and date of birth: blocked confirm, missing and short reasons, then each answer.
    robin = w.post("/api/v1/notes/new-client", {"text": ROBIN})["ref"]
    w.get(f"/api/v1/drafts/{robin}")
    w.post(f"/api/v1/drafts/{robin}/confirm", {"version": 1})
    w.post(f"/api/v1/drafts/{robin}/same-client", {"client_id": "HMIS-C-000101"})
    w.post(f"/api/v1/drafts/{robin}/different-person", {"reason": ""})
    w.post(f"/api/v1/drafts/{robin}/different-person", {"reason": "younger"})
    w.post(f"/api/v1/drafts/{robin}/different-person", {"reason": LONG_REASON})
    w.get(f"/api/v1/drafts/{robin}")
    w.post(f"/api/v1/drafts/{robin}/confirm", {"version": 1})
    w.get(f"/api/v1/drafts/{robin}")
    same = w.post("/api/v1/notes/new-client", {"text": ROBIN})["ref"]
    w.post(f"/api/v1/drafts/{same}/same-client", {"client_id": "HMIS-C-000113"})
    w.get(f"/api/v1/drafts/{same}")

    # Updates: a client ID, candidates to pick, and the notices when no client can be found.
    upd = w.post("/api/v1/notes/update", {"text": JORDAN})["ref"]
    w.post(f"/api/v1/drafts/{upd}/confirm", {"version": 1})
    w.get(f"/api/v1/drafts/{upd}")
    w.post(f"/api/v1/drafts/{upd}/corrections", {"text": "It was 45 minutes, not 20."})
    w.post(f"/api/v1/drafts/{upd}/confirm", {"version": 2})
    w.get(f"/api/v1/drafts/{upd}")
    pick = w.post("/api/v1/notes/update", {"text": "Talked with Sam Example, DOB 2/14/1980, SE quadrant. Gave water."})
    w.post(f"/api/v1/held/{pick['ref']}/client", {"client_id": "HMIS-C-000101"})
    w.post(f"/api/v1/held/{pick['ref']}/client", {"client_id": "HMIS-C-000109"})
    w.post("/api/v1/notes/update", {"text": "Saw someone (HMIS-C-1) and HMIS-C-000101. Gave water."})
    w.post("/api/v1/notes/update", {"text": "Saw HMIS-C-12. Gave water."})
    w.post("/api/v1/notes/update", {"text": "Saw HMIS-C-999999. Gave water."})
    w.post("/api/v1/notes/update", {"text": "Saw a neighbor by the river. Gave water."})
    w.post("/api/v1/notes/update", {"text": "Talked with Nobody Known, DOB 1/1/1950. Gave water."})

    # Queries: an answer, and a question that needs more.
    w.post("/api/v1/queries/briefing", {"quadrant": "SW"})
    w.post("/api/v1/queries/lookup", {"first_name": "Pat", "last_name": "Example"})
    w.post("/api/v1/queries/no-contact", {})
    w.post("/api/v1/queries/status", {"status_type": "housing_assessment", "client_id": "HMIS-C-000101"})

    # A parser failure, then expiry to the supervisor queue.
    def failing(note):
        return ParseResult(parser="rule_stub", model=None, prompt_version="stub",
                           failure=ParserFailure(code="timeout", message="The AI parser did not answer in time."))

    monkeypatch.setattr(intake.service.parser, "parse", failing)
    w.post("/api/v1/notes/new-client", {"text": NOTE})
    monkeypatch.undo()
    late = w.post("/api/v1/notes/new-client", {"text": NOTE.replace("Kim", "Kaz")})["ref"]
    intake.clock.advance(hours=intake.config.settings.supervisor_timeout_hours)
    intake.service.expire_stale()
    w = Recorder(web)  # the old session idled out
    w.post(f"/api/v1/drafts/{late}/confirm", {"version": 1})
    w.get(f"/api/v1/drafts/{late}")
    w.get("/api/v1/drafts")
    w.get("/api/v1/messages")
    w.get("/api/v1/session")

    shown = [t for response in w.seen for t in email_wording_in(response)]
    assert shown == []
    stored = [e for e in intake.store.emails() if e.direction == "out" and e.recipient == "j.alvarez@goodwill-outreach.example"]
    assert len(stored) > 20  # the sweep reached the messages
    assert [f"{e.message_key}: {e.subject} / {e.body}" for e in stored
            if EMAIL_WORDS.search(e.subject + e.body) or EMAIL_COMMANDS.search(e.subject + e.body)] == []


def test_the_email_channel_keeps_its_wording(intake):
    held = intake.receive_text(NOTE.replace("Searched HMIS first, no match. ", "")).ref
    mail = intake.last_email(held)
    assert mail.message_key == "search_request" and '[INT-' in mail.subject
    assert 'Reply "Searched HMIS, no match" once you have.' in mail.body


# Audit names


def test_the_audit_uses_neutral_names_for_every_channel(web):
    w = Recorder(web)
    web_ref = w.post("/api/v1/notes/new-client", {"text": ROBIN})["ref"]
    w.post(f"/api/v1/drafts/{web_ref}/different-person", {"reason": LONG_REASON})
    email_ref = web.intake.receive_text(NOTE).ref
    for ref in (web_ref, email_ref):
        names = [e["event"] for e in web.intake.store.audit_events(ref)]
        assert "ready_for_review" in names
        assert not {"review_sent", "verification_sent"} & set(names)
    assert "verification_requested" in [e["event"] for e in web.intake.store.audit_events(web_ref)]


def test_old_audit_names_still_read_correctly(intake):
    store = intake.store
    for old in ("review_sent", "verification_sent", "reply_ignored", "reply_ignored_not_author", "reply_after_expiry",
                "verification_reply_refused", "email_copies_deleted"):
        store._db.execute("INSERT INTO audit (ref, at, event, actor, details) VALUES ('ENC-OLD', '2026-10-01T00:00:00+00:00', ?, NULL, '{}')",
                          (old,))
    events = store.audit_events("ENC-OLD")
    assert [e["event"] for e in events] == ["ready_for_review", "verification_requested", "action_ignored",
                                            "action_ignored_not_author", "action_after_expiry",
                                            "verification_answer_refused", "copies_deleted"]
    assert events[0]["renamed_from"] == "review_sent"


# The parser-run and staged-record views are demo-only


def test_draft_content_views_are_off_in_the_shipped_configuration():
    assert load_config().settings.demo.draft_content_views is False


@pytest.mark.parametrize("path", ["/staff/drafts/{ref}/run", "/drafts/{ref}", "/drafts/{ref}/review"])
def test_draft_content_views_need_the_demo_flag(intake, path):
    ref = intake.receive_text(NOTE).ref
    assert TestClient(create_app(intake.service)).get(path.format(ref=ref)).status_code == 200  # tests turn it on
    intake.service.config = with_draft_content_views(intake.config, False)
    assert TestClient(create_app(intake.service)).get(path.format(ref=ref)).status_code == 404


def test_the_email_demo_switches_the_content_views_on():
    from app.api import build_service

    assert build_service(db_path=":memory:", email_channel=True, draft_content_views=True).config.settings.demo.draft_content_views
    servers = (REPO_ROOT / "scripts" / "servers.py").read_text(encoding="utf-8")
    assert "--draft-content-views" in servers
