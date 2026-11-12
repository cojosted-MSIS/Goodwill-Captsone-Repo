"""add-existing-client-updates, section C screens: the verification email on the phone, the update
and query compose shortcuts, and queries and verification decisions in the staff audit view.
Synthetic data only."""

from __future__ import annotations

from .conftest import REPO_ROOT
from .test_review_ui import WORKER, phone, send  # noqa: F401  (phone is a fixture)
from .test_same_name_verification import LONG_REASON, add_possible_duplicates, note

APP_JS = (REPO_ROOT / "ui" / "static" / "app.js").read_text(encoding="utf-8")
STAFF_JS = (REPO_ROOT / "ui" / "static" / "staff.js").read_text(encoding="utf-8")


def newest(api, kind):
    mail = next(m for m in api.get(f"/mail/inbox/{WORKER}").json() if m["kind"] == kind)
    return mail, api.get(f"/mail/message/{mail['id']}").json()


def test_verification_on_the_phone(phone):  # noqa: F811
    out = send(phone, "New client: Robin Demo", note())
    row, mail = newest(phone, "verification")
    assert row["current"] is True and mail["review"] is None
    v = mail["verification"]
    assert [c["client_id"] for c in v["candidates"]] == ["HMIS-C-000113", "HMIS-C-000114"]
    assert v["recommend"] == "HMIS-C-000113" and v["min_reason_length"] == 40 and v["confirm_allowed"] is False
    assert all("1975" not in str(c) and "5555" not in str(c) for c in v["candidates"])
    # the screen offers SAME CLIENT per candidate and DIFFERENT PERSON with a reason, and no CONFIRM
    screen = APP_JS.split("function verificationScreen")[1].split("async function mailScreen")[0]
    assert "SAME CLIENT ${c.client_id}" in screen and "DIFFERENT PERSON: ${reason.value.trim()}" in screen
    assert "CONFIRM" not in screen.replace("CONFIRM is not offered", "")
    # after SAME CLIENT the verification is no longer waiting and the update review is
    send(phone, f"Re: {mail['subject']}", "SAME CLIENT HMIS-C-000113")
    assert phone.get(f"/mail/message/{row['id']}").json()["current"] is False
    _, review = newest(phone, "review")
    assert review["review"]["kind"] == "update" and review["review"]["client"]["id"] == "HMIS-C-000113"
    assert {r["label"] for r in review["review"]["update_in_hmis_yourself"]} >= {"Gender"}
    assert out["action"] == "drafted"


def test_different_person_review_says_so(phone):  # noqa: F811
    send(phone, "New client: Robin Demo", note())
    _, mail = newest(phone, "verification")
    assert send(phone, f"Re: {mail['subject']}", f"DIFFERENT PERSON: {LONG_REASON}")["action"] == "verified_different"
    _, review = newest(phone, "review")
    assert review["current"] and review["review"]["confirm_allowed"]
    assert "confirmed distinct" in review["review"]["same_name_check"]


def test_compose_shortcuts_for_updates_and_queries():
    assert 'go("#/compose/update")' in APP_JS and '"Update a neighbor"' in APP_JS
    assert 'go("#/compose/query")' in APP_JS and '"Ask HMIS"' in APP_JS
    assert 'subject: "Update: "' in APP_JS and 'subject: "Query: "' in APP_JS


def test_queries_in_the_staff_audit(phone):  # noqa: F811
    send(phone, "Query: SW briefing", "Who has been reported in the SW quadrant?")
    send(phone, "Query: lookup", "Look up Jordan Sample, DOB 6/12/1979")
    log = phone.get("/staff/queries").json()
    assert [(e["event"], e["query_type"]) for e in log] == [("query", "briefing"), ("query", "lookup")]
    assert log[0]["quadrant"] == "sw" and log[0]["rows"] >= 1
    assert log[1]["name"] == "given" and log[1]["date_of_birth"] == "given"
    text = str(log)
    assert "Jordan" not in text and "1979" not in text and "Casey" not in text  # no returned values
    assert 'route === "queries"' in STAFF_JS and "Read-only queries" in STAFF_JS


def test_verification_decision_in_the_staff_audit(phone):  # noqa: F811
    ref = send(phone, "New client: Robin Demo", note())["ref"]
    _, mail = newest(phone, "verification")
    send(phone, f"Re: {mail['subject']}", f"DIFFERENT PERSON: {LONG_REASON}")
    _, review = newest(phone, "review")
    assert send(phone, f"Re: {review['subject']}", "CONFIRM")["action"] == "submitted"
    audit = phone.get(f"/drafts/{ref}/audit").json()
    assert audit["verification"]["decision"] == "different_person" and audit["verification"]["supervisor_review"]
    assert {"same_name_found", "verification_requested", "verification_decided", "confirmed_distinct_override"} <= {
        e["event"] for e in audit["events"]}
    for event in ("verification_decided", "confirmed_distinct_override", "same_name_found"):
        assert f'case "{event}"' in STAFF_JS


def test_candidate_cards_on_the_phone(phone):  # noqa: F811
    send(phone, "New client: Robin Demo", note())
    _, mail = newest(phone, "verification")
    v = mail["verification"]
    cards = {c["client_id"]: c for c in v["candidates"]}
    assert cards["HMIS-C-000113"]["recommended"] and not cards["HMIS-C-000114"]["recommended"]
    assert cards["HMIS-C-000114"]["record"] == "entered 12/07/2022; enrollment exited; last service: Transportation"
    assert v["duplicates_notice"] is None
    screen = APP_JS.split("function verificationScreen")[1].split("async function mailScreen")[0]
    assert "c.record" in screen and "v.duplicates_notice" in screen and "c.recommended" in screen


def test_possible_duplicates_on_the_phone(phone):  # noqa: F811
    add_possible_duplicates(phone.intake.hmis)
    send(phone, "New client: Dana Placeholder", note(name="Dana Placeholder", dob="11/20/1966", ssn="4040"))
    _, mail = newest(phone, "verification")
    v = mail["verification"]
    assert v["recommend"] is None and not any(c["recommended"] for c in v["candidates"])
    assert v["duplicates_notice"].startswith("HMIS-C-000915 and HMIS-C-000916 both match")
    assert 'case "possible_duplicate_pair_in_hmis"' in STAFF_JS


def test_staff_queries_view_names_the_watchlist(phone):  # noqa: F811
    send(phone, "Query: no-contact watchlist", "Who is coming up on 60 days with no contact?")
    log = phone.get("/staff/queries").json()
    assert log[-1]["query_type"] == "no_contact" and log[-1]["quadrant"] is None
    assert 'no_contact: "no-contact watchlist"' in STAFF_JS
    assert "Ask one of four things: a no-contact watchlist" in APP_JS
