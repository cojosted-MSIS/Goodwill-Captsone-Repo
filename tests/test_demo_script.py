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
        assert all(phone.intake.draft(refs[sid]).entry.model_dump().values())
    assert phone.intake.draft(refs["B"]).version == 2
    assert text.count("Client ID: HMIS-C-") == 2
    assert "Missing before entry: Veteran status" in text
    assert "scripted demo example" in text.lower()
    assert len(shown) == len(pauses) == w.step == 8


def test_demo_screens_all_open(phone):
    _, _, _, shown, _ = walk(phone)
    assert shown[0].startswith("/ui/#/mail/") and shown[-1].startswith("/ui/staff.html#/audit/")
    for page in shown:
        assert phone.get(page.split("#")[0]).status_code == 200


def test_demo_never_prints_note_text_or_em_dashes(phone):
    _, _, text, _, _ = walk(phone)
    scenarios = {s["id"]: s for s in phone.get("/demo/scenarios").json()}
    for sid in ("A", "B"):
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


def test_duplicate_step_shows_the_rejection_then_resets(phone):
    w, refs, text, shown, _ = walk(phone, skip_duplicate=False)
    assert w.step == 9 and w.resets == 1
    assert "rejected as a possible duplicate" in text and "earlier run" in text
    assert "HMIS did not accept the client record" in text
    assert shown[3].startswith("/ui/#/receipt/")
    # After the reset only Scenario B is left, and its IDs start again at 000001.
    assert set(refs) == {"B"} and refs["B"].endswith("-0001")
    assert "Client ID: HMIS-C-000001" in text.split("SCENARIO B")[1]
    assert [d["id"] for d in phone.get("/demo/drafts").json()] == [refs["B"]]


def test_s_at_the_receipt_skips_the_duplicate_step(phone):
    w, refs, text, _, _ = walk(phone, skip_duplicate=False, typed=["", "", "s"])
    assert w.step == 8 and w.resets == 0 and "possible duplicate" not in text
    assert set(refs) == {"A", "B"}


def test_r_resets_and_starts_again(phone):
    w, refs, text, _, _ = walk(phone, typed=["", "r"])  # R at step 2
    assert w.resets == 1 and text.count("SCENARIO A") == 2
    assert "Demo reset (demo only)" in text
    assert refs["A"].endswith("-0001") and refs["B"].endswith("-0002")
    assert phone.get(f"/drafts/{refs['A']}/receipt").json()["hmis_ids"][0]["value"] == "HMIS-C-000001"
