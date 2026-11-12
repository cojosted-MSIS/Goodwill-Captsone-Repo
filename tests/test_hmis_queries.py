"""add-hmis-readonly-queries: read-only HMIS queries by email.

Spec: openspec/specs/hmis-readonly-queries/spec.md. The mock
HMIS is seeded from sample-data/hmis_seed.yaml with dates counted back from the test clock's
day (conftest.SEED_TODAY). All data is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, timedelta

import httpx
import pytest

from app.config_loader import ConfigError, load_config
from app.hmis_reader import HmisReader, ReadRefused
from mock_hmis.rules import load_rules
from mock_hmis.store import MockHmisStore
from parser.interface import QueryRequest
from parser.llm_v2 import build_query_schema

from .conftest import SEED_TODAY
from .test_config import _edit
from .test_llm_parser import FakeReallms, make_parser

CONFIG = load_config()
PROJECT = "horizon_house_outreach"


def ask(intake, question: str, *, subject: str = "Query: question", sender: str | None = None):
    kwargs = {"subject": subject}
    if sender:
        kwargs["sender"] = sender
    outcome = intake.receive_text(question, **kwargs)
    reply = intake.last_email(outcome.ref, "query_reply") if outcome.ref else None
    return outcome, (reply.body if reply else None)


def events(intake, ref):
    return intake.store.audit_events(ref)


def hmis_snapshot(intake) -> str:
    """A fingerprint of every row in the mock HMIS database (read with a plain connection)."""
    path = intake.hmis.app.state.store.db_path
    conn = sqlite3.connect(path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        dump = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in tables}
    finally:
        conn.close()
    return hashlib.sha256(json.dumps(dump, default=str).encode()).hexdigest()


# Accept HMIS queries by email


def test_query_from_an_authorized_worker(intake):
    outcome, reply = ask(intake, "Who has been reported in the SW quadrant?")
    assert outcome.action == "query_answered" and outcome.ref.startswith("QRY-")
    assert reply.startswith("Pre-visit briefing for the SW quadrant (last 90 days): 4 neighbors reported.")
    assert intake.last_email(outcome.ref, "query_reply").recipient == "j.alvarez@goodwill-outreach.example"


def test_query_from_an_unrecognized_sender(intake):
    outcome = intake.receive_text("Who has been reported in the SW quadrant?", subject="Query: SW",
                                  sender="someone@example.com")
    assert outcome.action == "dropped"
    assert intake.store.emails() == []


def test_a_query_never_becomes_a_draft(intake):
    outcome, _ = ask(intake, "Look up Sam Example, DOB 2/14/1980")
    assert outcome.action == "query_answered"
    assert intake.store.drafts() == []


def test_query_prefix_survives_a_reply_prefix(intake):
    outcome, _ = ask(intake, "how many in the southwest?", subject="Re: Query: SW again")
    assert outcome.action == "query_answered"


# Choose only from a fixed set of query types


def test_request_matches_a_query_type(intake):
    outcome, reply = ask(intake, "Has Jordan Sample's ID come in? DOB 6/12/1979")
    assert outcome.action == "query_answered"
    assert "ID document status for HMIS-C-000101  Jordan S.:" in reply
    assert "State ID: requested" in reply


def test_request_matches_no_query_type(intake):
    outcome, reply = ask(intake, "List everyone born in 1985")
    assert outcome.action == "query_needs_more"
    assert "no query was run" in reply and "I can answer four kinds of question" in reply
    assert [e["event"] for e in events(intake, outcome.ref)] == ["query_refused"]
    assert events(intake, outcome.ref)[0]["refused"] == "no_query_type"


def test_query_text_in_the_email_is_data(intake):
    before = hmis_snapshot(intake)
    outcome, reply = ask(intake, "Look up client HMIS-C-000101'; DROP TABLE clients; --")
    assert outcome.action == "query_answered" and "HMIS-C-000101  Jordan S." in reply
    assert hmis_snapshot(intake) == before


def test_the_parser_never_returns_query_text():
    assert set(QueryRequest.model_fields) == {"query_type", "quadrant", "first_name", "last_name",
                                              "date_of_birth_as_written", "client_id", "status_type", "failure"}
    schema = build_query_schema(CONFIG)
    assert schema["additionalProperties"] is False and "sql" not in json.dumps(schema).lower()


# Validate query parameters before running anything


@pytest.mark.parametrize(("question", "asks_for"), [
    ("Look up Rosa Sample", "the date of birth or the HMIS client ID"),
    ("Look up Rosa Sample, born 1985", "the full date of birth"),
    ("Who has been reported downtown?", "the quadrant: NW, NE, SW, or SE"),
    ("Look up client HMIS-C-12", "the client ID in the HMIS format"),
    ("Has her ID come in?", "the neighbor's first and last name with the date of birth, or the HMIS client ID"),
])
def test_missing_or_invalid_parameters_run_nothing(intake, monkeypatch, question, asks_for):
    monkeypatch.setattr(intake.service.reader, "connect", lambda: pytest.fail("a query ran"))
    outcome, reply = ask(intake, question)
    assert outcome.action == "query_needs_more"
    assert asks_for in reply and reply.startswith("No query was run.")
    assert events(intake, outcome.ref)[0]["refused"] == "missing_parameters"


# Run only parameterized queries on allowlisted read-only views


def test_row_limit_reached(intake):
    intake.service.reader = HmisReader(intake.service.reader.database, 2)
    outcome, reply = ask(intake, "Who has been reported in the SW quadrant?")
    assert reply.startswith("Pre-visit briefing for the SW quadrant (last 90 days): 4 neighbors reported.")
    assert reply.count("  - HMIS-C-") == 2
    assert "2 more were not shown (limit 2). Please narrow the question." in reply
    assert events(intake, outcome.ref)[0]["rows"] == 2


@pytest.mark.parametrize("sql", [
    "INSERT INTO contacts (client_id, contact_date) VALUES ('x', 'y')",
    "UPDATE clients SET first_name = 'x'",
    "DELETE FROM contacts",
    "PRAGMA query_only = OFF",
    "ATTACH DATABASE 'other.db' AS other",
    "CREATE TABLE t (x)",
])
def test_connection_cannot_write(intake, sql):
    conn = intake.service.reader.connect()
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql)
    finally:
        conn.close()


@pytest.mark.parametrize("sql", ["SELECT * FROM clients", "SELECT fields FROM enrollments", "SELECT * FROM sqlite_master"])
def test_view_not_on_the_allowlist(intake, sql):
    conn = intake.service.reader.connect()
    try:
        with pytest.raises(sqlite3.DatabaseError, match="prohibited"):
            conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_reads_are_bound_parameters_never_text():
    import app.hmis_reader as reader

    for name in dir(reader):
        value = getattr(reader, name)
        if isinstance(value, str) and value.lstrip().startswith("SELECT"):
            assert "{" not in value and "%" not in value, name  # fixed text, values bound with ?


def test_missing_database_is_refused(tmp_path):
    with pytest.raises(ReadRefused):
        HmisReader(tmp_path / "absent.db", 25).connect()


# Answer a pre-visit briefing for a quadrant


def test_briefing_for_a_quadrant(intake):
    _, reply = ask(intake, "Pre-visit briefing for the SW quadrant please")
    lines = reply.splitlines()
    assert "  - HMIS-C-000101  Jordan S.  last contact 10/04/2026  open: ID document pending; housing assessment scheduled" in lines
    assert "  - HMIS-C-000102  Casey E.  last contact 09/25/2026" in lines
    assert "Quinn" not in reply  # NW, and outside the window anyway
    assert "Morgan D." in reply and "Sam E." in reply


def test_nobody_reported_in_the_quadrant(tmp_path):
    store = MockHmisStore(load_rules().id_prefixes, db_path=tmp_path / "empty.db", seed_path=None)
    reader = HmisReader(store.db_path, 25)
    b = reader.briefing("nw", SEED_TODAY - timedelta(days=90), SEED_TODAY, PROJECT)
    assert b.total == 0 and b.neighbors == []
    store.close()


def test_briefing_window_is_configured(intake):
    assert CONFIG.settings.hmis_queries.briefing_window_days == 90
    _, reply = ask(intake, "Who has been reported in the NW quadrant?")
    assert "(last 90 days): 2 neighbors reported." in reply  # Avery and Robin Demo (HMIS-C-000113)
    assert "Avery E." in reply and "Quinn D." not in reply  # 7 days ago is in, 120 days ago is out


# Look up a neighbor by name and date of birth or by client ID


def test_lookup_by_client_id(intake):
    _, reply = ask(intake, "Look up client HMIS-C-000104")
    assert reply.startswith("Neighbor lookup: 1 found.")
    assert "HMIS-C-000104  Riley P.  last contact 10/05/2026 in the NE quadrant" in reply


def test_two_neighbors_share_a_name_and_date_of_birth(intake):
    _, reply = ask(intake, "Look up Sam Example, DOB 2/14/1980")
    assert reply.startswith("Neighbor lookup: 2 found.")
    assert "HMIS-C-000109  Sam E.  last contact 09/22/2026 in the SE quadrant" in reply
    assert "HMIS-C-000110  Sam E.  last contact 09/07/2026 in the SW quadrant" in reply
    assert "Tell them apart by client ID, quadrant, and last contact." in reply


def test_lookup_with_no_match_suggests_nothing(intake):
    _, reply = ask(intake, "Look up Sam Example, DOB 2/15/1980")  # one day off
    assert reply.startswith("No neighbor was found.") and "HMIS-C-" not in reply


def test_names_match_without_case_spacing_or_punctuation(intake):
    reader = intake.service.reader
    assert len(reader.lookup_by_name(" SAM ", "ex-ample", date(1980, 2, 14), PROJECT)) == 2
    assert reader.lookup_by_name("Sam", "Examples", date(1980, 2, 14), PROJECT) == []  # no near matches


# Answer status checks from service and assessment records


def test_id_document_received(intake):
    _, reply = ask(intake, "Has Casey Example's ID come in? DOB 1/23/1990")
    assert "Birth certificate: received 10/03/2026" in reply


def test_nothing_recorded(intake):
    _, reply = ask(intake, "Has the housing assessment for client HMIS-C-000103 been done?")
    assert "Housing assessment status for HMIS-C-000103  Morgan D.:" in reply
    assert "No housing assessment recorded." in reply


def test_status_when_more_than_one_neighbor_matches(intake):
    outcome, reply = ask(intake, "Has Sam Example's ID come in? DOB 2/14/1980")
    assert reply.startswith("2 neighbors match, so I did not answer. Please ask again with the client ID:")
    assert "received" not in reply


# Keep query replies to minimal data


def test_lookup_reply_does_not_repeat_the_date_of_birth(intake):
    _, reply = ask(intake, "Look up Sam Example, DOB 2/14/1980")
    for text in ("2/14/1980", "02/14/1980", "1980-02-14", "Example", "2468", "1357"):
        assert text not in reply


def test_briefing_shows_only_open_item_labels(intake):
    _, reply = ask(intake, "Who has been reported in the SW quadrant?")
    assert "ID document pending" in reply
    for text in ("Sample", "1979", "3301", "state_id"):
        assert text not in reply


# Return only records the worker's project can see


def test_hidden_record_is_never_counted_listed_or_answered(intake):
    _, briefing = ask(intake, "Who has been reported in the SW quadrant?")
    assert "4 neighbors" in briefing and "Drew" not in briefing and "000111" not in briefing
    _, lookup = ask(intake, "Look up Drew Placeholder, DOB 8/21/1993")
    assert lookup.startswith("No neighbor was found.")
    _, by_id = ask(intake, "Look up client HMIS-C-000111")
    assert by_id.startswith("No neighbor was found.")


def test_every_worker_has_a_project():
    assert all(w.project for w in CONFIG.workers.authorized_workers)


# Audit every query


def test_query_answered_is_audited_without_returned_values(intake):
    outcome, _ = ask(intake, "Look up Sam Example, DOB 2/14/1980")
    (event,) = events(intake, outcome.ref)
    assert event["event"] == "query" and event["actor"] == "j.alvarez"
    assert event["query_type"] == "lookup" and event["rows"] == 2
    assert event["name"] == "given" and event["date_of_birth"] == "given"
    text = json.dumps(event)
    for value in ("Sam", "Example", "1980", "HMIS-C-000109", "HMIS-C-000110"):
        assert value not in text


def test_client_id_quadrant_and_status_type_are_kept_in_full(intake):
    outcome, _ = ask(intake, "Has the housing assessment for client HMIS-C-000101 been scheduled?")
    (event,) = events(intake, outcome.ref)
    assert (event["client_id"], event["status_type"], event["name"]) == ("HMIS-C-000101", "housing_assessment", None)
    outcome, _ = ask(intake, "Who has been reported in the NE quadrant?")
    assert events(intake, outcome.ref)[0]["quadrant"] == "ne"


def test_query_refused_is_audited(intake):
    outcome, _ = ask(intake, "Look up Rosa Sample")
    (event,) = events(intake, outcome.ref)
    assert event["event"] == "query_refused" and event["refused"] == "missing_parameters"
    assert event["rows"] is None and event["name"] == "given"


# Queries never change anything


def test_hmis_and_drafts_unchanged_after_queries(intake):
    before = hmis_snapshot(intake)
    for q in ("Who has been reported in the SW quadrant?", "Look up Sam Example, DOB 2/14/1980",
              "Has Casey Example's ID come in? DOB 1/23/1990"):
        assert ask(intake, q)[0].action == "query_answered"
    assert hmis_snapshot(intake) == before
    assert intake.store.drafts() == []
    assert intake.hmis.app.state.store.counts() == {"clients": 0, "enrollments": 0, "ce_enrollments": 0}


def test_query_emails_deleted_after_the_retention_period(intake):
    outcome, _ = ask(intake, "Who has been reported in the SW quadrant?")
    intake.service.purge_emails()
    assert intake.store.emails(ref=outcome.ref)  # still readable right after the answer
    intake.clock.advance(hours=24)
    intake.service.purge_emails()
    assert intake.store.emails(ref=outcome.ref) == []
    assert [e["event"] for e in events(intake, outcome.ref)] == ["query", "copies_deleted"]


# Mock HMIS read-only layer with synthetic seed data


def test_seeded_neighbor(intake):
    _, reply = ask(intake, "Look up Lee Demo, DOB 5/5/1985")
    assert "HMIS-C-000112  Lee D." in reply


def test_entered_client_becomes_visible(intake):
    ref = intake.receive_sample("01b_clean_new_client_complete").ref
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    _, reply = ask(intake, "Look up Pat Example, DOB 3/4/1975")
    assert reply.startswith("Neighbor lookup: 1 found.") and "HMIS-C-000001  Pat E." in reply


def test_reset_reseeds(intake):
    ref = intake.receive_sample("01b_clean_new_client_complete").ref
    intake.reply(ref, "CONFIRM")
    intake.hmis.post("/_admin/reset")
    _, pat = ask(intake, "Look up Pat Example, DOB 3/4/1975")
    assert pat.startswith("No neighbor was found.")
    _, sam = ask(intake, "Look up Sam Example, DOB 2/14/1980")
    assert "2 found" in sam


def test_seed_ids_leave_room_for_demo_entries():
    import yaml

    from mock_hmis.store import DEFAULT_SEED

    ids = [c["id"] for c in yaml.safe_load(DEFAULT_SEED.read_text(encoding="utf-8"))["clients"]]
    assert min(int(i.rsplit("-", 1)[1]) for i in ids) >= 101


# review-and-submit: reset reseeds; email cannot reset


def test_demo_reset_reseeds_the_read_only_layer(phone):
    from .test_review_ui import WORKER, latest_review, start, send

    start(phone, "A")
    send(phone, f"Re: {latest_review(phone)['subject']}", "CONFIRM")
    assert phone.post("/demo/reset", json={"confirm": "reset demo"}).status_code == 200
    out = send(phone, "Query: lookup", "Look up Pat Example, DOB 3/4/1975")
    reply = phone.get(f"/mail/inbox/{WORKER}").json()[0]
    body = phone.get(f"/mail/message/{reply['id']}").json()["body"]
    assert out["action"] == "query_answered" and body.startswith("No neighbor was found.")


def test_a_query_saying_reset_demo_resets_nothing(intake):
    ref = intake.receive_sample("01b_clean_new_client_complete").ref
    intake.reply(ref, "CONFIRM")
    outcome, _ = ask(intake, "reset demo", subject="Query: reset demo")
    assert outcome.action == "query_needs_more"
    assert intake.hmis.app.state.store.counts()["clients"] == 1 and intake.draft(ref).state == "submitted"


# Parsers: the rule-based stub and REALLMS only pick a type and copy parameters


@pytest.mark.parametrize(("question", "expected"), [
    ("Who has been reported in the SW quadrant before I go?", {"query_type": "briefing", "quadrant": "sw"}),
    ("how many in the southwest?", {"query_type": "briefing", "quadrant": "sw"}),
    ("Has Rosa Sample's ID come in? DOB 11/2/1985",
     {"query_type": "status", "first_name": "Rosa", "last_name": "Sample", "date_of_birth_as_written": "11/2/1985",
      "status_type": "id_document"}),
    ("Has her housing assessment come in? Client HMIS-C-000101",
     {"query_type": "status", "client_id": "HMIS-C-000101", "status_type": "housing_assessment"}),
    ("Look up Sam Example, DOB 2/14/1980",
     {"query_type": "lookup", "first_name": "Sam", "last_name": "Example", "date_of_birth_as_written": "2/14/1980"}),
    ("List everyone born in 1985", {}),
])
def test_stub_reads_queries(question, expected):
    from datetime import datetime, timezone

    from app.email_message import IntakeEmail
    from parser.rule_stub import RuleStubParser

    email = IntakeEmail(sender="j.alvarez@goodwill-outreach.example", recipient="x", subject="Query: q",
                        sent_at=datetime.now(timezone.utc), body=question)
    assert RuleStubParser(CONFIG).parse_query(email).model_dump(exclude_none=True) == expected


def _query_reply(**values) -> dict:
    reply = {"query_type": "unknown", "quadrant": "unknown", "first_name": "", "last_name": "",
             "date_of_birth_as_written": "", "client_id": "", "status_type": "unknown"}
    reply.update(values)
    return reply


def _query_email(body: str):
    from datetime import datetime, timezone

    from app.email_message import IntakeEmail

    return IntakeEmail(sender="j.alvarez@goodwill-outreach.example", recipient="x", subject="Query: q",
                       sent_at=datetime.now(timezone.utc), body=body)


def test_reallms_query_uses_the_strict_query_schema():
    fake = FakeReallms(_query_reply(query_type="lookup", first_name="Sam", last_name="Example",
                                    date_of_birth_as_written="2/14/1980"))
    request = make_parser(fake).parse_query(_query_email("Look up Sam Example, DOB 2/14/1980"))
    assert request.query_type == "lookup" and request.first_name == "Sam" and request.quadrant is None
    body = fake.chat_bodies()[0]
    assert body["response_format"]["json_schema"]["name"] == "query"
    assert body["response_format"]["json_schema"]["strict"] is True and body["temperature"] == 0
    assert "never write SQL" in body["messages"][0]["content"]


def test_reallms_query_values_must_be_copied_exactly():
    bad = _query_reply(query_type="lookup", first_name="Samuel", last_name="Example", date_of_birth_as_written="2/14/1980")
    fake = FakeReallms(bad, bad)
    request = make_parser(fake).parse_query(_query_email("Look up Sam Example, DOB 2/14/1980"))
    assert request.failure is not None and request.failure.code == "invalid_output"
    assert len(fake.chat_bodies()) == 2  # one retry


def test_reallms_query_failure_runs_nothing(intake):
    fake = FakeReallms(httpx.Response(500), httpx.Response(500), httpx.Response(500), httpx.Response(500))
    intake.service.parser = make_parser(fake)
    outcome, reply = ask(intake, "Look up Sam Example, DOB 2/14/1980")
    assert outcome.action == "query_failed" and "No query was run" in reply
    assert events(intake, outcome.ref)[0]["event"] == "query_refused"


def test_status_types_must_match_between_stub_and_settings(config_copy):
    _edit(config_copy / "settings.yaml", lambda d: d["hmis_queries"]["status_types"].pop("housing_assessment"))
    with pytest.raises(ConfigError, match="status_types"):
        load_config(config_copy)


@pytest.fixture
def phone(hmis):
    from .test_review_ui import phone as phone_fixture

    return phone_fixture.__wrapped__(hmis)
