"""add-web-application, Stage 3c: the four fixed read-only queries as forms.

Specs: openspec/changes/add-web-application/specs/web-application/spec.md ("Ask HMIS with fixed
forms") and the main spec openspec/specs/hmis-readonly-queries/spec.md, whose limits are unchanged:
fixed query types only, the row limit, the 90-day briefing window, the project visibility flag,
minimal results (no SSN, date of birth, or note text), and the same audit as an email query. The
forms never pass through a parser: there is no free text to turn into a query. Synthetic data only.
"""

from __future__ import annotations

import json

import pytest

from .conftest import SEED_TODAY

ROW_KEYS = {"client_id", "name", "last_contact", "quadrant", "detail"}
NOT_FOUND = "No client was found with these details."


def ask(client, kind: str, body: dict):
    return client.post(f"/api/v1/queries/{kind}", json=body)


def audit_of(web, ref: str) -> list[dict]:
    return [{k: v for k, v in e.items() if k != "at"} for e in web.intake.store.audit_events(ref)]


@pytest.fixture
def worker(web):
    # The query dates count back from the test clock, which is the seed's "today".
    assert web.intake.clock().date() == SEED_TODAY
    return web.as_user("j.alvarez")


def test_the_forms_never_use_the_parser(web, worker, monkeypatch):
    def no_parser(*_):
        raise AssertionError("a form query must not reach the parser")

    monkeypatch.setattr(web.intake.service.parser, "parse_query", no_parser)
    assert ask(worker, "briefing", {"quadrant": "SW"}).json()["action"] == "query_answered"


def test_there_is_no_free_text_query_route(worker):
    assert worker.post("/api/v1/queries", json={"text": "Who has been reported in the SW quadrant?"}).status_code in (404, 405)


def test_only_fixed_fields_are_accepted(worker):
    assert ask(worker, "briefing", {"quadrant": "SW", "sql": "SELECT 1"}).status_code == 422
    assert ask(worker, "briefing", {"quadrant": "downtown"}).status_code == 422
    assert ask(worker, "status", {"status_type": "anything", "client_id": "HMIS-C-000101"}).status_code == 422
    assert ask(worker, "lookup", {"client_id": "HMIS-C-000101", "project": "another"}).status_code == 422


# Results: plain language, minimal data


def test_briefing_lists_minimal_rows_in_the_window(worker):
    out = ask(worker, "briefing", {"quadrant": "SW"}).json()
    r = out["result"]
    assert out["action"] == "query_answered" and r["summary"] == "4 neighbors reported in the last 90 days."
    rows = [row for g in r["groups"] for row in g["rows"]]
    assert len(rows) == 4 and all(set(row) == ROW_KEYS for row in rows)
    assert all(row["quadrant"] == "SW" for row in rows)
    assert "HMIS-C-000101" in [row["client_id"] for row in rows]
    jordan = next(row for row in rows if row["client_id"] == "HMIS-C-000101")
    assert jordan["name"] == "Jordan S."


def test_the_watchlist_groups_past_and_approaching(worker):
    r = ask(worker, "no-contact", {}).json()["result"]
    groups = {g["label"]: [row["client_id"] for row in g["rows"]] for g in r["groups"]}
    assert groups["Past 60 days"] == ["HMIS-C-000107", "HMIS-C-000120", "HMIS-C-000119"]
    assert set(groups["Approaching 60 days"]) == {"HMIS-C-000105", "HMIS-C-000118", "HMIS-C-000117", "HMIS-C-000116"}
    blair = next(row for g in r["groups"] for row in g["rows"] if row["client_id"] == "HMIS-C-000116")
    assert blair == {"client_id": "HMIS-C-000116", "name": "Blair E.", "last_contact": "08/16/2026", "quadrant": "SE",
                     "detail": "52 days without a contact. Open: ID document pending"}  # open items, as in the email reply
    one_quadrant = ask(worker, "no-contact", {"quadrant": "SE"}).json()["result"]
    assert all(row["quadrant"] == "SE" for g in one_quadrant["groups"] for row in g["rows"])


def test_lookup_and_status(worker):
    found = ask(worker, "lookup", {"first_name": "Jordan", "last_name": "Sample", "date_of_birth": "1979-06-12"}).json()["result"]
    assert [row["client_id"] for g in found["groups"] for row in g["rows"]] == ["HMIS-C-000101"]
    status = ask(worker, "status", {"status_type": "id_document", "first_name": "Casey", "last_name": "Example",
                                    "date_of_birth": "1990-01-23"}).json()["result"]
    assert status["client"]["name"].endswith(".") and status["items"] and all(set(i) == {"what", "status", "date"} for i in status["items"])


def test_results_never_hold_an_ssn_dob_or_note_text(worker):
    results = [ask(worker, kind, body).json() for kind, body in (
        ("briefing", {"quadrant": "SW"}), ("briefing", {"quadrant": "NW"}), ("no-contact", {}),
        ("lookup", {"first_name": "Jordan", "last_name": "Sample", "date_of_birth": "1979-06-12"}),
        ("status", {"status_type": "id_document", "client_id": "HMIS-C-000101"}))]
    text = json.dumps(results)
    assert "1979" not in text and "06/12" not in text and "ssn" not in text.lower() and "case_note" not in text


def test_the_row_limit_applies_and_says_so(web, worker, monkeypatch):
    monkeypatch.setattr(web.intake.service.reader, "row_limit", 2)
    r = ask(worker, "briefing", {"quadrant": "SW"}).json()["result"]
    assert len([row for g in r["groups"] for row in g["rows"]]) == 2
    assert r["more"] == "2 more were not shown (limit 2). Narrow the search, for example to one quadrant."


def test_a_hidden_record_is_answered_as_not_found(worker):
    hidden = ask(worker, "lookup", {"first_name": "Drew", "last_name": "Placeholder", "date_of_birth": "1993-08-21"}).json()
    nobody = ask(worker, "lookup", {"first_name": "Nobody", "last_name": "Known", "date_of_birth": "1950-01-01"}).json()
    assert hidden["result"] == nobody["result"] and hidden["result"]["empty"] == NOT_FOUND
    by_id = ask(worker, "lookup", {"client_id": "HMIS-C-000111"}).json()
    assert by_id["result"]["empty"] == NOT_FOUND
    briefing = json.dumps(ask(worker, "briefing", {"quadrant": "SW"}).json())
    assert "HMIS-C-000111" not in briefing and "Drew" not in briefing


def test_missing_details_run_nothing_and_say_what_is_needed(web, worker):
    out = ask(worker, "lookup", {"first_name": "Jordan", "last_name": "Sample"}).json()
    assert out["action"] == "query_needs_more" and out["result"] is None
    assert out["missing"] == ["the date of birth or the HMIS client ID (I never search by name alone)"]
    assert [e["event"] for e in audit_of(web, out["ref"])] == ["query_refused"]


# The same audit as an email query, and nothing else kept


def test_audited_exactly_as_an_email_query(web, worker):
    pairs = [
        (("briefing", {"quadrant": "SW"}), "Who has been reported in the SW quadrant?"),
        (("lookup", {"first_name": "Jordan", "last_name": "Sample", "date_of_birth": "1979-06-12"}),
         "Look up Jordan Sample, DOB 6/12/1979"),
        (("status", {"status_type": "id_document", "first_name": "Casey", "last_name": "Example", "date_of_birth": "1990-01-23"}),
         "Has Casey Example's ID come in? DOB 1/23/1990"),
        (("no-contact", {"quadrant": "SE"}), "Who is coming up on 60 days with no contact in the SE quadrant?"),
    ]
    for (kind, body), question in pairs:
        web_ref = ask(worker, kind, body).json()["ref"]
        email_ref = web.intake.receive_text(question, subject="Query: q").ref
        from_web, from_email = audit_of(web, web_ref), audit_of(web, email_ref)
        assert from_web[0] == from_email[0], kind  # type, quadrant or client ID, status type, rows, names and DOB as "given"
        assert from_web[0]["event"] == "query"
    lookup = audit_of(web, ask(worker, "lookup", {"first_name": "Jordan", "last_name": "Sample", "date_of_birth": "1979-06-12"}).json()["ref"])[0]
    assert lookup["name"] == "given" and lookup["date_of_birth"] == "given" and "Jordan" not in json.dumps(lookup)


def test_a_form_query_keeps_no_copy_and_never_becomes_a_draft(web, worker):
    ask(worker, "briefing", {"quadrant": "SW"})
    ask(worker, "lookup", {"first_name": "Jordan", "last_name": "Sample", "date_of_birth": "1979-06-12"})
    assert web.intake.store.emails() == [] and web.intake.store.drafts() == []
    assert web.intake.hmis.app.state.store.counts()["clients"] == 0


def test_the_options_for_the_forms(worker):
    o = worker.get("/api/v1/queries/options").json()
    assert o["quadrants"] == ["NW", "NE", "SW", "SE"]
    assert o["status_types"] == {"id_document": "ID document", "housing_assessment": "Housing assessment"}
    assert o["no_contact_days"] == 60 and o["briefing_window_days"] == 90


@pytest.mark.parametrize("role", ["outreach.supervisor", "outreach.staff"])
def test_supervisors_and_staff_cannot_query(web, role):
    other = web.as_user(role)
    assert ask(other, "briefing", {"quadrant": "SW"}).status_code == 403
    assert other.get("/api/v1/queries/options").status_code == 403
