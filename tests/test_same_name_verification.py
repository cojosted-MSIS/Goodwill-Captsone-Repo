"""add-existing-client-updates, section B: same name and date of birth verification on new-client
drafts, the confirmed-distinct override, the open-draft keyed hash, and retention.

Spec: openspec/specs/existing-client-updates/spec.md and
specs/review-and-submit/spec.md. Seed (sample-data/hmis_seed.yaml, synthetic): Robin Demo
1975-09-09 is HMIS-C-000113 (SSN digits 5555) and HMIS-C-000114 (8642, older and exited); Sam Example
1980-02-14 is HMIS-C-000109 (2468) and HMIS-C-000110 (1357).
"""

from __future__ import annotations

import json

import pytest

from app.config_loader import load_config
from app.match_key import MatchKeyMissing, load_match_key, match_key

from .conftest import Intake, client_fields

NOTE = ("Met {name}, DOB {dob}, NW quadrant around 10:15am. Searched HMIS first, no match. Slept outside last "
        "night. Has been staying outside for over a year. Been on the street about 3 times in the last 3 years, "
        "around 14 months total. Started being homeless this time on 8/15/2025. Male, white, not Hispanic. "
        "Has a disabling condition (bad back). Not a veteran.{ssn} Enroll in street outreach, CE region 7. "
        "Single adult. Gave water and a hygiene kit. Spent 15 minutes with him. Follow up Thursday.")
LONG_REASON = "He is about twenty years younger than the person in HMIS and has a different tattoo"


def note(name="Robin Demo", dob="9/9/1975", ssn="5555"):
    return NOTE.format(name=name, dob=dob, ssn=f" SSN ends {ssn}." if ssn else "")


def new_client(intake, body=None, **kwargs):
    return intake.receive_text(body or note(), subject="New client: neighbor", **kwargs)


def events(intake, ref):
    return [e["event"] for e in intake.store.audit_events(ref)]


def grades(intake, ref):
    return {c.client_id: c.grade for c in intake.draft(ref).verification.candidates}


# Check new-client drafts for the same name and date of birth


def test_match_found_sends_verification_and_refuses_confirm(intake):
    out = new_client(intake)
    assert out.action == "drafted"
    mail = intake.last_email(out.ref)
    assert mail.kind == "verification" and intake.last_email(out.ref, "review") is None
    assert "HMIS-C-000113  Robin D.  last contact 09/29/2026 in the NW quadrant" in mail.body
    assert "HMIS-C-000114" in mail.body
    assert "1975" not in mail.body and "5555" not in mail.body  # no date of birth or SSN digits
    assert intake.reply(out.ref, "CONFIRM").action == "verification"
    assert "CONFIRM is not accepted yet" in intake.last_email(out.ref).body
    assert intake.hmis.app.state.store.counts()["clients"] == 0
    assert "confirm_blocked_verification" in events(intake, out.ref)


def test_no_match_goes_to_review_as_before(intake):
    out = new_client(intake, note(name="Kim Placeholder", dob="1/2/1990"))
    review = intake.last_email(out.ref)
    assert review.kind == "review"
    assert "SAME-NAME CHECK: no client in HMIS that your project can see has this name" in review.body


def test_check_cannot_run_without_a_date_of_birth(intake):
    out = new_client(intake, note(dob="sometime in 1975").replace("DOB sometime in 1975", "born sometime in 1975"))
    review = intake.last_email(out.ref)
    assert review.kind == "review"
    assert "SAME-NAME CHECK: it runs once your note gives the full name and date of birth." in review.body
    assert intake.store.match_key_count() == 0


def test_hidden_client_is_not_a_candidate(intake):
    out = new_client(intake, note(name="Drew Placeholder", dob="8/21/1993"))  # visible to another program only
    assert intake.last_email(out.ref).kind == "review"


# Grade a same-name match by the second identifier


def test_matching_digits_are_likely_the_same_person(intake):
    out = new_client(intake)
    assert grades(intake, out.ref) == {"HMIS-C-000113": "likely_same", "HMIS-C-000114": "warning"}
    body = intake.last_email(out.ref).body
    assert "Likely the same person: the last four SSN digits match. We recommend SAME CLIENT." in body
    assert body.count("We recommend SAME CLIENT") == 1 and "POSSIBLE DUPLICATES" not in body
    assert "at least 40 characters" in body


def test_different_digits_are_a_warning(intake):
    out = new_client(intake, note(name="Sam Example", dob="2/14/1980", ssn="9753"))
    assert grades(intake, out.ref) == {"HMIS-C-000109": "warning", "HMIS-C-000110": "warning"}
    assert "Warning: the last four SSN digits are different" in intake.last_email(out.ref).body


def test_digits_missing_are_a_hard_stop(intake):
    out = new_client(intake, note(ssn=None))
    assert set(grades(intake, out.ref).values()) == {"hard_stop"}
    assert "get the digits from the neighbor if you can" in intake.last_email(out.ref).body


def test_digits_missing_in_hmis_are_a_hard_stop(intake):
    out = new_client(intake, note(name="Morgan Demo", dob="9/30/1968", ssn="1234"))  # seed has no digits
    assert grades(intake, out.ref) == {"HMIS-C-000103": "hard_stop"}


# SAME CLIENT turns the draft into an update


def test_same_client_becomes_an_update(intake):
    ref = new_client(intake).ref
    out = intake.reply(ref, "SAME CLIENT HMIS-C-000113")
    assert out.action == "verified_same"
    d = intake.draft(ref)
    assert (d.kind, d.client_id, d.version) == ("update", "HMIS-C-000113", 2)
    review = intake.last_email(ref, "review").body
    assert "Update for client HMIS-C-000113 (Robin D.)" in review
    assert "You replied SAME CLIENT HMIS-C-000113" in review
    assert intake.store.match_key_count() == 0
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    store = intake.hmis.app.state.store
    assert store.counts()["clients"] == 0  # no new client
    assert store.update_counts() == {"case_notes": 1, "services": 1}
    service = store.entry_fields("services", intake.draft(ref).entry.service_id)
    assert service["time_spent_minutes"] == "15" and service["service_area"] == "nw"


def test_demographics_are_shown_as_update_in_hmis_yourself(intake):
    ref = new_client(intake).ref
    intake.reply(ref, "SAME CLIENT HMIS-C-000113")
    review = intake.last_email(ref, "review").body
    part = review.split("UPDATE IN HMIS YOURSELF")[1].split("\n\n")[0]
    assert "Gender" in part and "Veteran" in part
    intake.reply(ref, "CONFIRM")
    d = intake.draft(ref)
    store = intake.hmis.app.state.store
    written = {**store.entry_fields("services", d.entry.service_id), **store.entry_fields("case_notes", d.entry.case_note_id)}
    assert not {"gender", "veteran_status", "race", "first_name", "date_of_birth"} & set(written)


def test_same_client_id_not_among_the_candidates(intake):
    ref = new_client(intake).ref
    assert intake.reply(ref, "SAME CLIENT HMIS-C-000101").action == "verification"
    body = intake.last_email(ref).body
    assert body.startswith("Please reply SAME CLIENT with one of these client IDs: HMIS-C-000113, HMIS-C-000114.")
    assert intake.draft(ref).kind == "new_client"


# DIFFERENT PERSON needs a reason and is entered as confirmed distinct


def test_different_person_with_a_reason(intake):
    ref = new_client(intake, note(name="Sam Example", dob="2/14/1980", ssn="9753")).ref
    out = intake.reply(ref, "DIFFERENT PERSON: he is 20 years younger than the person in HMIS")
    assert out.action == "verified_different"
    review = intake.last_email(ref)
    assert review.kind == "review" and "marked confirmed distinct" in review.body
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    assert intake.draft(ref).entry.client_id == "HMIS-C-000001"
    ev = intake.store.audit_events(ref)
    decided = next(e for e in ev if e["event"] == "verification_decided")
    assert decided["decision"] == "different_person" and decided["supervisor_review"] is False
    assert decided["reason"] == "he is 20 years younger than the person in HMIS"
    assert "confirmed_distinct_override" in [e["event"] for e in ev]


def test_without_the_override_the_mock_rejects_it_as_a_duplicate(intake):
    """The backstop is still there: the same note entered with no verification is rejected."""
    intake.service.reader = None  # the lookup cannot run, so no verification
    ref = new_client(intake, note(name="Sam Example", dob="2/14/1980", ssn="9753")).ref
    assert intake.last_email(ref).kind == "review"
    assert intake.reply(ref, "CONFIRM").action == "entry_failed"
    assert intake.draft(ref).last_failure == "possible_duplicate"


def test_different_person_without_a_reason(intake):
    ref = new_client(intake, note(name="Sam Example", dob="2/14/1980", ssn="9753")).ref
    assert intake.reply(ref, "DIFFERENT PERSON").action == "verification"
    assert intake.last_email(ref).body.startswith("Please say why this is a different person")
    assert intake.reply(ref, "CONFIRM").action == "verification"
    assert intake.hmis.app.state.store.counts()["clients"] == 0


def test_different_person_when_the_digits_match(intake):
    ref = new_client(intake).ref
    assert intake.reply(ref, "DIFFERENT PERSON: younger").action == "verification"
    assert "at least 40 characters" in intake.last_email(ref).body.split("\n")[0]
    assert intake.reply(ref, f"DIFFERENT PERSON: {LONG_REASON}").action == "verified_different"
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    record = intake.service.audit_record(ref)
    assert record["verification"]["supervisor_review"] is True
    submitted = next(e for e in record["events"] if e["event"] == "submitted")
    assert submitted["confirmed_distinct"] is True and submitted["supervisor_review"] is True


# Keep the possible-duplicate rejection as a backstop (mock HMIS)


def client_payload():
    return client_fields(first_name="Sam", last_name="Example", date_of_birth="1980-02-14")


def test_duplicate_without_an_override_says_nothing_about_the_record(hmis):
    out = hmis.post("/clients", json={"fields": client_payload()})
    assert out.status_code == 409 and out.json()["code"] == "possible_duplicate"
    assert "HMIS-C-" not in out.text and "Sam" not in out.text


def test_override_without_a_reason_is_rejected(hmis):
    out = hmis.post("/clients", json={"fields": client_payload(), "confirmed_distinct": {"reason": "  "}})
    assert out.status_code == 422 and out.json()["code"] == "override_needs_reason"


# Audit verification decisions


def test_audit_holds_the_decision_and_no_note_text(intake):
    ref = new_client(intake, note(name="Sam Example", dob="2/14/1980", ssn="9753")).ref
    intake.reply(ref, "DIFFERENT PERSON: he is 20 years younger than the person in HMIS")
    intake.reply(ref, "CONFIRM")
    v = intake.service.audit_record(ref)["verification"]
    assert v == {"checked": True, "candidates": 2, "grades": ["warning", "warning"], "decision": "different_person",
                 "chosen": None, "reason": "he is 20 years younger than the person in HMIS", "supervisor_review": False}
    text = json.dumps(intake.store.audit_events(ref))
    assert "hygiene kit" not in text and "Sam" not in text and "1980" not in text


# Check open drafts against each other with a keyed hash


def test_two_open_drafts_for_the_same_neighbor(intake):
    unique = note(name="Kim Placeholder", dob="1/2/1990")
    first = new_client(intake, unique).ref
    second = new_client(intake, unique, sender="m.chen@goodwill-outreach.example").ref
    review = intake.last_email(second, "review").body
    assert f"Another open draft ({first}) has the same name and date of birth" in review
    rows = intake.store._db.execute("SELECT * FROM match_keys").fetchall()
    assert len(rows) == 2 and not any("kim" in str(r).lower() or "1990" in str(r) for r in rows)


def test_hash_deleted_at_entry(intake):
    ref = new_client(intake, note(name="Kim Placeholder", dob="1/2/1990")).ref
    assert intake.store.match_key_count() == 1
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    assert intake.store.match_key_count() == 0


def test_hash_deleted_at_expiry(intake):
    new_client(intake, note(name="Kim Placeholder", dob="1/2/1990"))
    intake.clock.advance(hours=48)
    assert intake.service.expire_stale() and intake.store.match_key_count() == 0


def test_match_key_is_keyed():
    assert match_key(b"one", "Kim", "Placeholder", "1990-01-02") != match_key(b"two", "Kim", "Placeholder", "1990-01-02")
    assert match_key(b"one", " kim ", "PLACE-holder", "1990-01-02") == match_key(b"one", "Kim", "Placeholder", "1990-01-02")


# Hash key from the environment


def test_production_mode_without_a_key_refuses_to_start(config_copy):
    path = config_copy / "settings.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("  mode: demo", "  mode: production"), encoding="utf-8")
    settings = load_config(config_copy).settings
    with pytest.raises(MatchKeyMissing, match="INTAKE_MATCH_KEY is not set"):
        load_match_key(settings, environ={})
    assert load_match_key(settings, environ={"INTAKE_MATCH_KEY": "a-test-value"}) == b"a-test-value"


def test_demo_mode_without_a_key_makes_a_random_one():
    settings = load_config().settings
    env: dict[str, str] = {}
    one, two = load_match_key(settings, environ=env), load_match_key(settings, environ=env)
    assert len(one) == 32 and one != two and env == {}  # written nowhere


def test_env_example_holds_only_a_placeholder():
    from .conftest import REPO_ROOT

    lines = [ln for ln in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines() if "INTAKE_MATCH_KEY=" in ln]
    assert lines == ["# INTAKE_MATCH_KEY=replace-with-a-long-random-value"]


# Retention mode and seven-day deletion


def production_intake(hmis, config_copy):
    path = config_copy / "settings.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("  mode: demo", "  mode: production"), encoding="utf-8")
    intake = Intake(hmis)
    intake.config = intake.service.config = load_config(config_copy)
    return intake


def test_production_mode_reduces_the_draft(hmis, config_copy):
    intake = production_intake(hmis, config_copy)
    ref = new_client(intake, note(name="Kim Placeholder", dob="1/2/1990")).ref
    intake.reply(ref, "CONFIRM")
    d = intake.draft(ref)
    assert d.stubbed and d.state == "submitted" and d.fields == {} and d.subject == "" and d.parse_output is None
    assert d.entry.client_id == "HMIS-C-000001" and d.version == 1 and d.submitted_at is not None


def test_demo_mode_keeps_the_values(intake):
    ref = new_client(intake, note(name="Kim Placeholder", dob="1/2/1990")).ref
    intake.reply(ref, "CONFIRM")
    d = intake.draft(ref)
    assert not d.stubbed and d.value("first_name") == "Kim"


def test_deleted_after_seven_days(intake):
    held = intake.receive_text(note(name="Kim Placeholder", dob="1/2/1990").replace("Searched HMIS first, no match. ", ""))
    assert held.action == "search_requested"
    expired = new_client(intake, note(name="Lou Sample", dob="1/3/1991")).ref
    kept = new_client(intake, note(name="Ash Example", dob="1/4/1992")).ref
    intake.reply(kept, "CONFIRM")
    intake.clock.advance(days=2)
    intake.service.expire_stale()
    intake.clock.advance(days=4)
    assert intake.service.delete_unsubmitted() == []
    intake.clock.advance(days=1)
    assert sorted(intake.service.delete_unsubmitted()) == sorted([held.ref, expired])
    assert intake.draft(expired) is None and intake.store.get_pending(held.ref) is None
    assert intake.store.emails(ref=expired) == [] and intake.store.emails(ref=held.ref) == []
    assert intake.draft(kept).state == "submitted"
    assert "deleted_after_retention" in events(intake, expired)  # the audit record remains


def test_verification_emails_are_deleted_after_submission(intake):
    ref = new_client(intake, note(name="Sam Example", dob="2/14/1980", ssn="9753")).ref
    intake.reply(ref, "DIFFERENT PERSON: he is 20 years younger than the person in HMIS")
    intake.reply(ref, "CONFIRM")
    assert {e.kind for e in intake.store.emails(ref=ref)} == {"receipt"}


def test_same_client_case_note_is_rebuilt_from_this_visit_only(intake):
    ref = new_client(intake).ref
    assert "Times on the street" in intake.draft(ref).value("case_note")  # the new-client note had history
    intake.reply(ref, "SAME CLIENT HMIS-C-000113")
    d = intake.draft(ref)
    note = d.value("case_note")
    assert d.fields["case_note"].origin == "generated"
    assert note.startswith("Met Robin D. in the Northwest quadrant.") and "hygiene kit" in note
    assert "Times on the street" not in note
    # the visit text keeps this visit's sentences and drops history, demographics, enrollment and the search
    for kept in ("Gave water and a hygiene kit.", "Spent 15 minutes with him.", "Follow up Thursday."):
        assert kept in d.visit_note
    for gone in ("Not a veteran", "Male, white", "Been on the street", "staying outside for over a year",
                 "Started being homeless", "CE region", "Single adult", "Searched HMIS"):
        assert gone not in d.visit_note
    # the worker can still change it before CONFIRM, and the rewrite stays this visit only
    assert intake.reply(ref, "It was 30 minutes").action == "revised"
    d = intake.draft(ref)
    assert d.value("time_spent_minutes") == "30" and "Times on the street" not in d.value("case_note")
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    entered = intake.hmis.app.state.store.entry_fields("case_notes", intake.draft(ref).entry.case_note_id)
    assert "Times on the street" not in entered["case_note"]


# Candidate details, and the possible-duplicates safeguard. HMIS should not hold duplicate records,
# so the demo seed has none; these tests make a pair in the mock HMIS to check the safeguard.

DANA = dict(name="Dana Placeholder", dob="11/20/1966", ssn="4040")


def add_possible_duplicates(hmis):
    """Two records for one synthetic neighbor (same name, date of birth, and SSN digits), test only."""
    store = hmis.app.state.store
    with store._lock, store._db:
        for client_id, entered in (("HMIS-C-000915", "2025-12-11"), ("HMIS-C-000916", "2026-08-08")):
            store._db.execute(
                "INSERT INTO clients (client_id, first_name, last_name, date_of_birth, ssn_last4, name_key, fields,"
                " seeded, entered_date) VALUES (?, 'Dana', 'Placeholder', '1966-11-20', '4040', 'danaplaceholder',"
                " '{}', 1, ?)", (client_id, entered))
            store._db.execute("INSERT INTO enrollments (enrollment_id, client_id, fields, entry_date, seeded)"
                              " VALUES (?, ?, '{}', ?, 1)", (f"TEST-E-{client_id}", client_id, entered))
            store._db.execute("INSERT INTO contacts (client_id, contact_date, quadrant) VALUES (?, ?, 'se')",
                              (client_id, entered))


def test_seed_holds_no_duplicate_records(hmis):
    rows = hmis.app.state.store._db.execute(
        "SELECT name_key, date_of_birth, ssn_last4, COUNT(*) FROM clients WHERE ssn_last4 IS NOT NULL"
        " GROUP BY name_key, date_of_birth, ssn_last4 HAVING COUNT(*) > 1").fetchall()
    assert rows == []


def test_one_strong_match_is_recommended_and_the_cards_differ(intake):
    out = new_client(intake)
    body = intake.last_email(out.ref).body
    assert "    entered 06/09/2026; enrollment active; last service: Basic needs (food, water, hygiene)" in body
    assert "    entered 12/07/2022; enrollment exited; last service: Transportation" in body
    assert "HMIS-C-000114  Robin D.  last contact 03/21/2024 in the NE quadrant" in body
    assert intake.draft(out.ref).verification.possible_duplicates == []
    assert "possible_duplicate_pair_in_hmis" not in events(intake, out.ref)


def test_two_strong_matches_are_possible_duplicates(intake):
    add_possible_duplicates(intake.hmis)
    out = new_client(intake, note(**DANA))
    d = intake.draft(out.ref)
    assert grades(intake, out.ref) == {"HMIS-C-000915": "likely_same", "HMIS-C-000916": "likely_same"}
    assert d.verification.possible_duplicates == ["HMIS-C-000915", "HMIS-C-000916"]
    body = intake.last_email(out.ref).body
    assert ("POSSIBLE DUPLICATES IN HMIS: HMIS-C-000915 and HMIS-C-000916 both match on name, date of birth, and SSN "
            "digits. They may be duplicates of each other in HMIS. Check HMIS and pick the current record; no "
            "candidate is recommended.") in body
    assert "We recommend" not in body
    # the cards still tell the two records apart
    assert "entered 12/11/2025; enrollment active" in body and "entered 08/08/2026; enrollment active" in body


def test_possible_duplicate_pair_is_audited_with_client_ids_only(intake):
    add_possible_duplicates(intake.hmis)
    ref = new_client(intake, note(**DANA)).ref
    intake.reply(ref, "CONFIRM")  # refused, and the verification is checked again
    pairs = [e for e in intake.store.audit_events(ref) if e["event"] == "possible_duplicate_pair_in_hmis"]
    assert len(pairs) == 1  # recorded once per draft
    assert {k: v for k, v in pairs[0].items() if k not in ("at", "event", "actor")} == {
        "client_ids": ["HMIS-C-000915", "HMIS-C-000916"]}
    # the worker still picks one, and the update goes to that record
    assert intake.reply(ref, "SAME CLIENT HMIS-C-000916").action == "verified_same"
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    assert intake.draft(ref).client_id == "HMIS-C-000916"


def test_candidate_details_keep_the_minimal_data_rule(intake):
    add_possible_duplicates(intake.hmis)
    ref = new_client(intake, note(**DANA)).ref
    for c in intake.draft(ref).verification.candidates:
        text = c.model_dump_json()
        assert "4040" not in text and "1966" not in text and "11/20" not in text
    body = intake.last_email(ref).body
    assert "4040" not in body and "1966" not in body and "hygiene kit." not in body  # no SSN, DOB, or note text
    assert "HMIS-C-000915  Dana P.  last contact 12/11/2025 in the SE quadrant" in body  # quadrant level only


def test_details_for_a_client_entered_through_this_system(intake):
    ref = new_client(intake, note(name="Kim Placeholder", dob="1/2/1990")).ref
    intake.reply(ref, "CONFIRM")
    again = new_client(intake, note(name="Kim Placeholder", dob="1/2/1990")).ref
    body = intake.last_email(again).body
    assert "    entered 10/07/2026; enrollment active; no service recorded" in body


def test_new_read_views_are_read_only(intake):
    from app.hmis_reader import ReadRefused

    reader = intake.service.reader
    assert reader._rows("SELECT COUNT(client_id) FROM v_enrollments", ())[0][0] >= 14
    assert reader._rows("SELECT COUNT(client_id) FROM v_services", ())[0][0] >= 2
    for sql in ("SELECT * FROM enrollments", "SELECT * FROM services", "DELETE FROM v_services"):
        with pytest.raises(ReadRefused):
            reader._rows(sql, ())


def test_an_older_mock_database_is_upgraded(tmp_path):
    import sqlite3

    from mock_hmis.store import MockHmisStore
    from mock_hmis.rules import load_rules

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
    CREATE TABLE clients (client_id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, date_of_birth TEXT,
        ssn_last4 TEXT, name_key TEXT, fields TEXT NOT NULL, visible_to TEXT NOT NULL DEFAULT 'all',
        seeded INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE enrollments (enrollment_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, fields TEXT NOT NULL,
        visible_to TEXT NOT NULL DEFAULT 'all');
    CREATE TABLE services (service_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, service_date TEXT,
        service_type TEXT, quadrant TEXT, fields TEXT NOT NULL, visible_to TEXT NOT NULL DEFAULT 'all');
    CREATE VIEW v_clients AS SELECT client_id, first_name FROM clients;
    """)
    old.close()
    store = MockHmisStore(load_rules().id_prefixes, db_path=path)
    try:
        cols = [r[1] for r in store._db.execute("PRAGMA table_info(v_clients)")]
        assert "entered_date" in cols
        assert store._db.execute("SELECT COUNT(*) FROM v_enrollments").fetchone()[0] >= 14
    finally:
        store.close()
