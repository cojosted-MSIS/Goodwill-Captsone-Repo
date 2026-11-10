"""add-existing-client-updates, section A: recurring updates (case notes and services) for
clients already in HMIS, client checks, entry, and corrections before and after entry.

Spec: openspec/specs/existing-client-updates/spec.md.
The mock HMIS is seeded from sample-data/hmis_seed.yaml (synthetic). conftest.SEED_TODAY
anchors the seed dates to the test clock.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from mock_hmis.rules import load_rules
from mock_hmis.service import create_app

from .conftest import SEED_TODAY, Intake

OTHER_WORKER = "m.chen@goodwill-outreach.example"
JORDAN = ("Saw Jordan Sample (HMIS-C-000101) in the SW quadrant. Gave her a bus pass and water. "
          "Spent 20 minutes with her. Still staying outside.")


def update(intake, body: str, subject: str = "Update: neighbor", **kwargs):
    return intake.receive_text(body, subject=subject, **kwargs)


def confirm_update(intake, body: str = JORDAN, subject: str = "Update: Jordan Sample"):
    ref = update(intake, body, subject).ref
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    return ref


def ask(intake, question: str) -> str:
    out = intake.receive_text(question, subject="Query: q")
    return intake.last_email(out.ref, "query_reply").body


def events(intake, ref) -> list[str]:
    return [e["event"] for e in intake.store.audit_events(ref)]


# Accept update notes for an existing neighbor


def test_second_visit_to_the_same_neighbor(intake):
    first = confirm_update(intake)
    first_ids = intake.draft(first).entry.model_dump()
    intake.clock.advance(days=3)
    second = confirm_update(intake, "Saw Jordan Sample (HMIS-C-000101) again in the SW quadrant. Gave her socks.")
    assert second != first and intake.draft(second).client_id == "HMIS-C-000101"
    assert intake.draft(first).entry.model_dump() == first_ids  # the earlier entries are not changed
    assert intake.hmis.app.state.store.update_counts() == {"case_notes": 2, "services": 2}


def test_update_from_an_unrecognized_sender(intake):
    out = update(intake, JORDAN, sender="someone@example.com")
    assert out.action == "dropped" and intake.store.emails() == []


def test_update_is_never_entered_without_confirm(intake):
    ref = update(intake, JORDAN).ref
    assert intake.draft(ref).state == "in_review"
    assert intake.hmis.app.state.store.update_counts() == {"case_notes": 0, "services": 0}


# Identify the client by a checked HMIS client ID


def test_valid_client_id(intake):
    out = update(intake, JORDAN)
    d = intake.draft(out.ref)
    assert out.action == "drafted" and d.kind == "update"
    assert (d.client_id, d.client_label) == ("HMIS-C-000101", "Jordan S.")
    assert "Update for client HMIS-C-000101 (Jordan S.)" in intake.last_email(out.ref, "review").body


def test_wrong_format(intake):
    out = update(intake, "Saw client HMIS-C-12 in the SW quadrant. Gave water.")
    assert out.action == "client_id_invalid" and intake.store.drafts() == []
    assert "not in the HMIS format" in intake.last_email(out.ref, "notice").body


def test_client_not_found(intake):
    out = update(intake, "Saw client HMIS-C-000999 in the SW quadrant. Gave water.")
    assert out.action == "client_not_found" and intake.store.drafts() == []
    assert "No client with the ID HMIS-C-000999 was found" in intake.last_email(out.ref, "notice").body


def test_hidden_client_is_answered_as_not_found(intake):
    out = update(intake, "Saw client HMIS-C-000111 in the SW quadrant. Gave water.")
    assert out.action == "client_not_found"


def test_subject_and_note_disagree(intake):
    out = update(intake, "Saw client HMIS-C-000102 in the SW quadrant. Gave water.", subject="Update: HMIS-C-000101")
    assert out.action == "client_ids_disagree" and intake.store.drafts() == []
    body = intake.last_email(out.ref, "notice").body
    assert "HMIS-C-000101, HMIS-C-000102" in body and "Nothing was drafted" in body


# Offer lookup candidates when no client ID is given


def test_one_candidate_still_needs_the_worker_to_pick(intake):
    out = update(intake, "Talked with Lee Demo, DOB 5/5/1985, NE quadrant. Gave water.")
    assert out.action == "pick_client" and intake.store.drafts() == []
    body = intake.last_email(out.ref, "pick_client").body
    assert "Reply CLIENT <ID>" in body and "HMIS-C-000112  Lee D." in body
    assert "1985" not in body and "Demo" not in body  # minimal data, as in query replies


def test_worker_picks_a_candidate(intake):
    out = update(intake, "Talked with Sam Example, DOB 2/14/1980, SE quadrant. Gave water.")
    body = intake.last_email(out.ref, "pick_client").body
    assert "HMIS-C-000109" in body and "HMIS-C-000110" in body
    picked = intake.reply(out.ref, "CLIENT HMIS-C-000109")
    assert picked.action == "drafted" and intake.draft(picked.ref).client_id == "HMIS-C-000109"
    assert "update_client_chosen" in events(intake, picked.ref)


def test_pick_must_be_one_of_the_candidates(intake):
    out = update(intake, "Talked with Sam Example, DOB 2/14/1980, SE quadrant. Gave water.")
    assert intake.reply(out.ref, "CLIENT HMIS-C-000101").action == "pick_client"
    assert intake.store.drafts() == []


def test_pick_from_another_worker_is_ignored(intake):
    out = update(intake, "Talked with Sam Example, DOB 2/14/1980, SE quadrant. Gave water.")
    assert intake.reply(out.ref, "CLIENT HMIS-C-000109", sender=OTHER_WORKER).action == "ignored"


def test_name_without_a_date_of_birth(intake):
    out = update(intake, "Talked with Lee Demo in the NE quadrant. Gave water.")
    assert out.action == "client_id_needed" and intake.store.drafts() == []
    assert "client ID, or their first and last name with the full date of birth" in intake.last_email(out.ref, "notice").body


def test_no_candidate(intake):
    out = update(intake, "Talked with Lee Demo, DOB 5/6/1985, NE quadrant. Gave water.")
    assert out.action == "client_not_found"
    assert 'send a "New client:" note' in intake.last_email(out.ref, "notice").body


def test_lookups_for_updates_are_audited_without_values(intake):
    out = update(intake, "Talked with Sam Example, DOB 2/14/1980, SE quadrant. Gave water.")
    lookup = next(e for e in intake.store.audit_events(out.ref) if e["event"] == "lookup")
    assert lookup["rows"] == 2 and lookup["name"] == "given" and lookup["date_of_birth"] == "given"
    assert "Sam" not in json.dumps(lookup) and "1980" not in json.dumps(lookup)


# Draft a case note and a service entry


def test_case_note_and_service_entry_drafted(intake):
    d = intake.draft(update(intake, JORDAN).ref)
    assert d.value("service_type") == "transportation" and d.value("service_area") == "sw"
    assert d.value("time_spent_minutes") == "20" and d.value("current_living_situation") == "place_not_meant_for_habitation"
    assert d.fields["service_date"].origin == "email_date" and d.fields["service_contact_type"].origin == "program_default"
    assert d.fields["case_note"].origin == "generated"


def test_update_drafts_keep_no_client_answers(intake):
    d = intake.draft(update(intake, "Saw Jordan Sample, DOB 6/12/1979, client HMIS-C-000101, SW quadrant. "
                                    "Female, white. Gave water.").ref)
    for name in ("first_name", "last_name", "date_of_birth", "gender", "race"):
        assert name not in d.fields and name not in d.parse_output["fields"]


def test_time_spent_not_stated(intake):
    d = intake.draft(update(intake, "Saw client HMIS-C-000101 in the SW quadrant. Gave water.").ref)
    assert d.value("time_spent_minutes") is None
    assert not any(f.field == "time_spent_minutes" for f in d.all_flags)  # optional, so not flagged either


def test_hedged_time_is_medium(intake):
    d = intake.draft(update(intake, "Saw client HMIS-C-000101 in the SW quadrant. Gave water. About 20 minutes.").ref)
    assert d.fields["time_spent_minutes"].confidence == "medium"


def test_service_type_not_on_the_list(intake):
    out = update(intake, "Saw client HMIS-C-000101 in the SW quadrant. We played chess.")
    d = intake.draft(out.ref)
    assert d.value("service_type") is None
    assert any(f.field == "service_type" and f.blocking for f in d.all_flags)
    assert intake.reply(out.ref, "CONFIRM").action == "still_missing"


def test_case_note_privacy(intake):
    d = intake.draft(update(intake, "Saw client HMIS-C-000101 at the camp behind the Example St overpass, SW quadrant. "
                                    "Her friend Jordan has a warrant. Gave water.").ref)
    note = d.value("case_note") + " ".join(f.source or "" for f in d.fields.values())
    assert "Example St" not in note and "warrant" not in note and "overpass" not in note


# Review and enter updates the same way as new clients


def test_update_confirmed(intake):
    ref = confirm_update(intake)
    d = intake.draft(ref)
    assert (d.entry.case_note_id, d.entry.service_id) == ("HMIS-N-000001", "HMIS-S-000002")
    receipt = intake.last_email(ref, "receipt").body
    assert "Case note ID: HMIS-N-000001" in receipt and "Service ID: HMIS-S-000002" in receipt
    stored = intake.hmis.app.state.store
    assert stored.entry_fields("case_notes", "HMIS-N-000001")["case_note"] == d.value("case_note")
    assert stored.entry_fields("services", "HMIS-S-000002")["time_spent_minutes"] == "20"


def test_audit_and_email_purge_for_updates(intake):
    ref = confirm_update(intake)
    names = events(intake, ref)
    assert "submitted" in names and "copies_deleted" in names
    assert "staying outside" not in json.dumps(intake.store.audit_events(ref))
    assert all(e.kind == "receipt" for e in intake.store.emails(ref=ref))


def test_correction_before_entry(intake):
    ref = update(intake, JORDAN).ref
    assert intake.reply(ref, "It was 30 minutes").action == "revised"
    d = intake.draft(ref)
    assert d.version == 2 and d.value("time_spent_minutes") == "30" and d.fields["time_spent_minutes"].origin == "worker"


def test_service_step_fails_after_the_case_note_was_added(intake):
    ref = update(intake, JORDAN).ref
    intake.fail_next("add_service", "service_unavailable")
    assert intake.reply(ref, "CONFIRM").action == "entry_failed"
    assert intake.draft(ref).entry.case_note_id and not intake.draft(ref).entry.service_id
    assert intake.reply(ref, "RETRY").action == "submitted"
    assert intake.hmis.app.state.store.update_counts() == {"case_notes": 1, "services": 1}


# Mock HMIS operations for existing clients


def test_unknown_client(hmis):
    out = hmis.post("/clients/HMIS-C-000999/case-notes", json={"fields": {"note_date": "2026-10-07", "case_note": "x"}})
    assert out.status_code == 404
    assert out.json() == {"status": "rejected", "code": "unknown_client", "reason": "No client with that ID exists"}


def test_case_note_added_returns_only_the_id(hmis):
    out = hmis.post("/clients/HMIS-C-000101/case-notes", json={"fields": {"note_date": "2026-10-07", "case_note": "x"}})
    assert out.status_code == 201 and set(out.json()) == {"status", "case_note_id"}


# Correct an entry this system already made


def test_correction_after_entry(intake):
    ref = confirm_update(intake)
    out = intake.reply(ref, "The service was 45 minutes, not 20")
    d = intake.draft(ref)
    assert out.action == "revised" and d.state == "in_review" and d.version == 2
    assert d.correction.changed_fields == ["time_spent_minutes"]
    assert "This is a CORRECTION to entries already in HMIS (HMIS-N-000001, HMIS-S-000002)" in intake.last_email(ref, "review").body
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    stored = intake.hmis.app.state.store
    assert stored.entry_fields("services", "HMIS-S-000002")["time_spent_minutes"] == "45"
    assert stored.update_counts() == {"case_notes": 1, "services": 1}  # updated, not added
    entered = next(e for e in intake.store.audit_events(ref) if e["event"] == "correction_entered")
    assert entered["entries"] == ["HMIS-N-000001", "HMIS-S-000002"] and entered["changed_fields"] == ["time_spent_minutes"]
    assert "45" not in json.dumps(entered)  # field names only, never values


def test_correction_from_someone_else_is_ignored(intake):
    ref = confirm_update(intake)
    assert intake.reply(ref, "It was 45 minutes", sender=OTHER_WORKER).action == "ignored"
    assert intake.draft(ref).state == "submitted" and intake.draft(ref).version == 1


def test_entry_not_made_by_this_system_is_refused(intake):
    ref = confirm_update(intake)
    out = intake.reply(ref, "Service HMIS-S-000777: it was 45 minutes")
    assert out.action == "correction_refused" and intake.draft(ref).state == "submitted"
    assert "Please correct it in HMIS" in intake.last_email(ref, "notice").body


def test_correction_that_cannot_be_understood_changes_nothing(intake):
    ref = confirm_update(intake)
    assert intake.reply(ref, "thanks!").action == "rephrase"
    d = intake.draft(ref)
    assert d.state == "submitted" and d.correction is None and d.version == 1


def test_hmis_forbids_edits_after_save():
    rules = load_rules().model_copy(update={"entry_updates_allowed": False})
    with TestClient(create_app(rules, today=SEED_TODAY)) as hmis:
        intake = Intake(hmis)
        ref = confirm_update(intake)
        intake.reply(ref, "It was 45 minutes")
        assert intake.reply(ref, "CONFIRM").action == "submitted"
        stored = hmis.app.state.store
        assert stored.entry_fields("services", "HMIS-S-000002")["time_spent_minutes"] == "20"  # the earlier entry is unchanged
        new = stored.entry_fields("services", "HMIS-S-000004")
        assert new["corrects"] == "HMIS-S-000002" and new["time_spent_minutes"] == "45"
        assert stored.entry_fields("case_notes", "HMIS-N-000003")["case_note"].startswith("Corrects case note HMIS-N-000001:")
        assert "a new entry HMIS-S-000004 was added that corrects HMIS-S-000002" in intake.last_email(ref, "receipt").body


# Record the quadrant with every contact


def test_new_client_appears_in_the_briefing(intake):
    ref = intake.receive_sample("01b_clean_new_client_complete").ref
    assert intake.reply(ref, "CONFIRM").action == "submitted"
    briefing = ask(intake, "Who has been reported in the SW quadrant?")
    assert "5 neighbors reported" in briefing and "HMIS-C-000001  Pat E.  last contact 10/07/2026" in briefing


def test_visit_appears_in_the_briefing(intake):
    confirm_update(intake, "Saw client HMIS-C-000105 in the NE quadrant. Gave water.", "Update: HMIS-C-000105")
    briefing = ask(intake, "Who has been reported in the NE quadrant?")
    assert "HMIS-C-000105  Taylor S.  last contact 10/07/2026" in briefing  # was 60 days ago before the visit


def test_quadrant_wording_says_it_is_entered_and_tbc(intake):
    """The review email, phone review and mapped draft show this section label."""
    label = intake.config.fields.sections["encounter"].label
    assert "entered on the Coordinated Entry contact" in label and "[TBC with CHIP" in label
    ref = intake.receive_sample("01b_clean_new_client_complete").ref
    assert label.upper() in intake.last_email(ref, "review").body
