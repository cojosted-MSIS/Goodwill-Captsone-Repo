"""Task 5.3: the one-command presentation demo (scripts/demo.py), run in process."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .test_review_ui import phone  # noqa: F401  (phone is a fixture)

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))  # demo.py imports its neighbour servers.py
spec = importlib.util.spec_from_file_location("demo", SCRIPTS / "demo.py")
demo = importlib.util.module_from_spec(spec)
sys.modules["demo"] = demo  # dataclasses look the module up here
spec.loader.exec_module(demo)


def walk(api, *, skip_duplicate=True, typed=()):
    """Run the walk-through; `typed` is what the presenter types at each pause, in order."""
    said, shown, pauses = [], [], []
    keys = list(typed)

    def pause():
        pauses.append(1)
        return keys.pop(0) if keys else ""

    w = demo.Walkthrough(api, say=said.append, show=shown.append, pause=pause, skip_duplicate=skip_duplicate)
    refs = w.run()
    return w, refs, "\n".join(said), shown, pauses


def test_demo_runs_both_scenarios_to_the_receipt(phone):
    w, refs, text, shown, pauses = walk(phone)
    for sid in ("A", "B"):
        assert phone.intake.draft(refs[sid]).state == "submitted"
        entry = phone.intake.draft(refs[sid]).entry
        assert entry.client_id and entry.enrollment_id and entry.ce_enrollment_id
    assert phone.intake.draft(refs["B"]).version == 2
    assert text.count("Client ID: HMIS-C-") == 3  # A, B, and D2 (the confirmed-distinct new client)
    assert "Missing before entry: Veteran status" in text
    assert "scripted demo example" in text.lower()
    assert len(shown) == len(pauses) == w.step == 20


def test_scenario_c_updates_scenario_a_client(phone):
    _, refs, text, _, _ = walk(phone)
    c = phone.intake.draft(refs["C"])
    assert (c.kind, c.state, c.client_id) == ("update", "submitted", "HMIS-C-000001")
    assert c.entry.case_note_id and c.entry.service_id
    assert f"Case note ID: {c.entry.case_note_id}" in text and f"Service ID: {c.entry.service_id}" in text


def test_scenario_d_shows_both_outcomes(phone):
    _, refs, text, _, _ = walk(phone)
    d1, d2 = phone.intake.draft(refs["D1"]), phone.intake.draft(refs["D2"])
    assert (d1.kind, d1.client_id, d1.state) == ("update", "HMIS-C-000113", "submitted")
    assert d1.verification.decision == "same_client"
    assert (d2.kind, d2.state, d2.verification.decision) == ("new_client", "submitted", "different_person")
    assert d2.entry.client_id not in ("HMIS-C-000109", "HMIS-C-000110")  # a new client
    assert phone.intake.hmis.app.state.store.counts()["clients"] == 3  # A, B and D2; D1 added none
    assert "Likely the same person" in text and "Warning: the last four SSN digits are different" in text
    assert "confirmed_distinct_override" in [e["event"] for e in phone.intake.store.audit_events(refs["D2"])]


def test_scenario_e_briefing_lists_scenario_a_client(phone):
    w, refs, text, shown, _ = walk(phone)
    assert "Pre-visit briefing for the SW quadrant (last 90 days)" in text
    assert "It lists HMIS-C-000001, Scenario A's client" in text
    assert "ID document status for HMIS-C-000101  Jordan S.:" in text
    assert shown[-1] == "/ui/staff.html#/queries"
    before = phone.intake.hmis.app.state.store.counts()
    assert [e["query_type"] for e in phone.get("/staff/queries").json()] == ["briefing", "status"]
    assert phone.intake.hmis.app.state.store.counts() == before  # nothing in HMIS changed


def test_demo_screens_all_open(phone):
    _, _, _, shown, _ = walk(phone)
    assert shown[0].startswith("/ui/#/mail/") and shown[-1].startswith("/ui/staff.html#/")
    for page in shown:
        assert phone.get(page.split("#")[0]).status_code == 200


def test_demo_never_prints_note_text_or_em_dashes(phone):
    _, _, text, _, _ = walk(phone)
    scenarios = {s["id"]: s for s in phone.get("/demo/scenarios").json()}
    for sid in ("A", "B", "C", "D1", "D2", "D3"):
        for sentence in scenarios[sid]["body"].split(". "):
            if len(sentence) > 25:
                assert sentence[:25] not in text
    em_dash = chr(0x2014)
    assert em_dash not in text and em_dash not in (SCRIPTS / "demo.py").read_text(encoding="utf-8")


def test_demo_stops_with_a_clear_message_when_entry_fails(phone):
    phone.intake.fail_next("create_client", "service_unavailable")
    w = demo.Walkthrough(phone, skip_duplicate=True)
    try:
        w.run()
    except RuntimeError as exc:
        assert "expected 'submitted'" in str(exc) and "entry_failed" in str(exc)
    else:
        raise AssertionError("the walk-through should stop when entry fails")


def test_duplicate_step_shows_the_same_name_check(phone):
    w, refs, text, shown, _ = walk(phone, skip_duplicate=False)
    assert w.step == 21 and w.resets == 0
    assert "caught by the same-name check" in text and "CONFIRM is refused" in text
    assert shown[3].startswith("/ui/#/mail/")
    assert phone.get(f"/drafts/{refs['A again']}").json()["state"] == "in_review"  # open, nothing entered
    assert phone.intake.hmis.app.state.store.counts()["clients"] == 3  # Scenarios A, B and D2 only


def test_s_at_the_receipt_skips_the_duplicate_step(phone):
    w, refs, text, _, _ = walk(phone, skip_duplicate=False, typed=["", "", "s"])
    assert w.step == 20 and w.resets == 0 and "same-name check" not in text
    assert "A again" not in refs


def test_r_resets_and_starts_again(phone):
    w, refs, text, _, _ = walk(phone, typed=["", "r"])  # R at step 2
    assert w.resets == 1 and text.count("SCENARIO A") == 2
    assert "Demo reset (demo only)" in text
    assert refs["A"].endswith("-0001") and refs["B"].endswith("-0002")
    assert phone.get(f"/drafts/{refs['A']}/receipt").json()["hmis_ids"][0]["value"] == "HMIS-C-000001"


def scenario_c(api):
    return next(s for s in api.get("/demo/scenarios").json() if s["id"] == "C")


def test_scenario_c_uses_the_client_id_from_scenario_a_receipt(phone):
    from .test_review_ui import send
    from .test_same_name_verification import note

    # Someone else is entered first, so Scenario A's client is not HMIS-C-000001.
    kim = send(phone, "New client: Kim Placeholder", note(name="Kim Placeholder", dob="1/2/1990"))["ref"]
    assert send(phone, f"Re: Please confirm: New client: Kim Placeholder [{kim} v1]", "CONFIRM")["action"] == "submitted"
    _, refs, text, _, _ = walk(phone)
    a_client = phone.intake.draft(refs["A"]).entry.client_id
    assert a_client != "HMIS-C-000001"
    assert phone.intake.draft(refs["C"]).client_id == a_client
    assert f"Uses client {a_client} from Scenario A's receipt." in text
    c = scenario_c(phone)
    assert c["ready"] and c["client_id"] == a_client and a_client in c["body"] and "{client_id}" not in c["body"]


def test_scenario_c_says_so_when_scenario_a_was_skipped_or_reset(phone):
    c = scenario_c(phone)  # Scenario A never run
    assert c["ready"] is False and c["client_id"] is None
    assert c["not_ready"].startswith("Run Scenario A first and reply CONFIRM.")
    assert "it was skipped, or the demo was reset" in c["not_ready"]
    assert "(Scenario A's client ID)" in c["body"]
    w = demo.Walkthrough(phone, skip_duplicate=True)
    w.refs["A"] = "ENC-none"
    try:
        w._scenario_c()
    except RuntimeError as exc:
        assert "Run Scenario A first" in str(exc)
    else:
        raise AssertionError("Scenario C should stop when there is no Scenario A client")
    walk(phone)
    assert scenario_c(phone)["ready"]
    assert phone.post("/demo/reset", json={"confirm": "reset demo"}).status_code == 200
    assert scenario_c(phone)["ready"] is False  # after a reset there is no Scenario A client again
    app_js = (SCRIPTS.parent / "ui" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'disabled: s.ready === false' in app_js and "scenario.not_ready" in app_js


def test_scenario_d3_shows_possible_duplicates_in_hmis(phone):
    _, refs, text, _, _ = walk(phone)
    assert "Possible duplicates in HMIS: HMIS-C-000115 and HMIS-C-000116 both match" in text
    d3 = phone.intake.draft(refs["D3"])
    assert (d3.kind, d3.client_id, d3.state) == ("update", "HMIS-C-000116", "submitted")
    assert "possible_duplicate_pair_in_hmis" in [e["event"] for e in phone.intake.store.audit_events(refs["D3"])]
    d1_line = next(line for line in text.splitlines() if "HMIS-C-000113 Robin D." in line)
    assert d1_line.endswith("Recommended.")
    assert not any("HMIS-C-00011" in line and "Recommended." in line for line in text.split("Dana Placeholder")[1].splitlines())
