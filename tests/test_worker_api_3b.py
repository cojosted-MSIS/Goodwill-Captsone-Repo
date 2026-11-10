"""add-web-application, Stage 3b: what the worker screens need from the API.

Specs: openspec/changes/add-web-application/specs/offline-sync/spec.md ("Keep full SSNs out of the
device queue", applied on the server until Stage 4) and specs/web-application/spec.md ("Worker
screens"). Synthetic data only; the SSNs here are made up.
"""

from __future__ import annotations

import json

from .test_web_api import NOTE, ROBIN

NO_SSN = NOTE.replace(" SSN ends 4821.", "")


def everything_stored(web) -> str:
    db = web.intake.store._db
    return json.dumps([db.execute(f"SELECT * FROM {t}").fetchall() for t in ("drafts", "pending", "emails", "audit")])


# SSNs in web notes: masked, refused in other forms, and never stored in full


def test_a_full_ssn_is_masked_before_anything_is_kept(web):
    alvarez = web.as_user("j.alvarez")
    out = alvarez.post("/api/v1/notes/new-client", json={"text": NO_SSN + " SSN 234-56-7891."}).json()
    assert out["action"] == "drafted" and out["ssn"] == {"masked": 1}
    draft = web.intake.draft(out["ref"])
    assert draft.value("ssn_last4") == "7891" and draft.value("ssn_quality") == "full_ssn_reported"
    stored = everything_stored(web)
    assert "234-56-7891" not in stored and "234567891" not in stored and "***-**-7891" in stored


def test_a_known_invalid_full_ssn_is_still_flagged_after_masking(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NO_SSN + " SSN 123-45-6789."}).json()["ref"]
    draft = web.intake.draft(ref)
    assert draft.value("ssn_last4") == "6789" and draft.value("ssn_quality") is None
    assert any(f.code == "ssn_known_invalid_pattern" and "a known example number" in f.message for f in draft.parser_flags)
    assert "123-45-6789" not in everything_stored(web)


def test_an_ssn_in_another_form_is_refused_and_nothing_is_kept(web):
    alvarez = web.as_user("j.alvarez")
    r = alvarez.post("/api/v1/notes/new-client", json={"text": NO_SSN + " Her social is 234 56 7891."})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ssn_possible_full_number"
    assert "last four" in r.json()["detail"]["message"]
    assert web.intake.store.drafts() == [] and "7891" not in everything_stored(web)


def test_the_last_four_alone_is_unchanged(web):
    alvarez = web.as_user("j.alvarez")
    out = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()  # "SSN ends 4821"
    assert out["action"] == "drafted" and out["ssn"] == {"masked": 0}
    assert web.intake.draft(out["ref"]).value("ssn_last4") == "4821"


def test_corrections_and_reasons_are_guarded_too(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NO_SSN}).json()["ref"]
    fixed = alvarez.post(f"/api/v1/drafts/{ref}/corrections", json={"text": "SSN 234-56-7891."}).json()
    assert fixed["action"] == "revised" and web.intake.draft(ref).value("ssn_last4") == "7891"
    robin = alvarez.post("/api/v1/notes/new-client", json={"text": ROBIN}).json()["ref"]
    refused = alvarez.post(f"/api/v1/drafts/{robin}/different-person", json={"reason": "His soc sec is 234-56 7891 per card"})
    assert refused.status_code == 422
    assert "234-56-7891" not in everything_stored(web)


# Held notes for the "I searched HMIS" and "pick a client" screens


def test_held_notes_list_and_detail_for_their_author_only(web):
    alvarez = web.as_user("j.alvarez")
    search = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE.replace("Searched HMIS first, no match. ", "")}).json()
    pick = alvarez.post("/api/v1/notes/update", json={"text": "Talked with Sam Example, DOB 2/14/1980, SE quadrant. Gave water."}).json()
    held = alvarez.get("/api/v1/held").json()
    assert sorted(h["id"] for h in held) == sorted([search["ref"], pick["ref"]])
    detail = alvarez.get(f"/api/v1/held/{pick['ref']}").json()
    assert detail["kind"] == "pick_client"
    assert [c["client_id"] for c in detail["candidates"]] == ["HMIS-C-000109", "HMIS-C-000110"]
    assert all(set(c) == {"client_id", "label", "last_contact", "quadrant"} for c in detail["candidates"])
    assert "1980" not in json.dumps(detail)  # minimal data: no date of birth
    assert alvarez.get(f"/api/v1/held/{search['ref']}").json()["kind"] == "search"
    chen = web.as_user("m.chen")
    assert chen.get(f"/api/v1/held/{pick['ref']}").status_code == 404 and chen.get("/api/v1/held").json() == []


# What Confirm will enter, shown above the button


def test_the_draft_says_what_confirm_will_enter(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": NOTE}).json()["ref"]
    view = alvarez.get(f"/api/v1/drafts/{ref}").json()
    summary = view["entry_summary"]
    assert [s["what"] for s in summary] == ["A new client record", "A program enrollment", "A Coordinated Entry enrollment"]
    assert "Kim Placeholder" in summary[0]["detail"] and view["confirm_allowed"] is True
    upd = alvarez.post("/api/v1/notes/update", json={"text": "Saw Jordan Sample (HMIS-C-000101) in the SW quadrant. "
                                                     "Gave her a bus pass and water. Spent 20 minutes with her."}).json()["ref"]
    assert [s["what"] for s in alvarez.get(f"/api/v1/drafts/{upd}").json()["entry_summary"]] == ["A case note", "A service entry"]


def test_confirm_is_not_allowed_while_a_verification_is_open(web):
    alvarez = web.as_user("j.alvarez")
    ref = alvarez.post("/api/v1/notes/new-client", json={"text": ROBIN}).json()["ref"]
    view = alvarez.get(f"/api/v1/drafts/{ref}").json()
    assert view["verification"] is not None and view["confirm_allowed"] is False
    assert view["verification"]["min_reason_length"] == 40
