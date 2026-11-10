"""add-web-application, Stage 3b: the worker screens themselves.

Every worker screen is rendered from real /api/v1 data with ui/web/screens.js (in Node, the same
code the browser runs) and its HTML is checked: no email wording, a label on every field,
buttons that say what they do, the Confirm summary above the Confirm button, Confirm disabled
while a verification is open, and every value escaped. Specs:
openspec/changes/add-web-application/specs/web-application/spec.md ("Worker screens", "Word
messages for each channel"). Synthetic data only.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from .conftest import REPO_ROOT
from .test_channel_wording import EMAIL_COMMANDS, EMAIL_WORDS
from .test_web_api import JORDAN, NOTE, ROBIN

WEB_DIR = REPO_ROOT / "ui" / "web"
LONG_REASON = "He is about twenty years younger than the person in HMIS and has a different tattoo"
GENERIC_BUTTONS = {"ok", "submit", "go", "yes", "no", "next", "continue", "click here", "send", "save", "confirm", "back"}


def node() -> str:
    found = shutil.which("node") or next((p for p in (r"C:\Program Files\nodejs\node.exe", "/usr/local/bin/node",
                                                     "/usr/bin/node") if Path(p).exists()), None)
    if not found:
        pytest.skip("Node.js is needed to render the web screens")
    return found


def render(tmp_path: Path, screens: dict[str, tuple[str, list]]) -> dict[str, str]:
    spec = tmp_path / "screens.json"
    spec.write_text(json.dumps({name: {"fn": fn, "args": args} for name, (fn, args) in screens.items()}), encoding="utf-8")
    run = subprocess.run([node(), str(REPO_ROOT / "tests" / "render_screens.mjs"), str(WEB_DIR / "screens.js"), str(spec)],
                         capture_output=True, text=True, encoding="utf-8", check=False, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def text_of(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def buttons(page: str) -> list[str]:
    found = re.findall(r"<button\b[^>]*>(.*?)</button>", page, re.DOTALL)
    found += re.findall(r'<a class="btn[^"]*"[^>]*>(.*?)</a>', page, re.DOTALL)
    return [" ".join(text_of(b).split()) for b in found]


@pytest.fixture
def every_screen(web, tmp_path):
    """Every worker screen, rendered from real API data."""
    w = web.as_user("j.alvarez")
    get = lambda path: w.get(path).json()  # noqa: E731
    post = lambda path, body=None: w.post(path, json=body or {}).json()  # noqa: E731
    intake = web.intake
    s: dict[str, tuple[str, list]] = {}

    s["sign_in"] = ("signIn", [{}])
    s["sign_in_failed"] = ("signIn", [{"error": "Sign-in failed. Check your username and password."}])
    s["new_note"] = ("noteForm", [{"kind": "new"}])
    s["update_note"] = ("noteForm", [{"kind": "update"}])
    refused = w.post("/api/v1/notes/new-client", json={"text": "Her social is 234 56 7891."}).json()["detail"]["message"]
    s["new_note_ssn_refused"] = ("noteForm", [{"kind": "new", "error": refused, "text": "Her social is 234 56 7891."}])

    held = post("/api/v1/notes/new-client", {"text": NOTE.replace("Searched HMIS first, no match. ", "").replace("Kim", "Kai")})
    s["held_search"] = ("heldSearch", [get(f"/api/v1/held/{held['ref']}")])
    pick = post("/api/v1/notes/update", {"text": "Talked with Sam Example, DOB 2/14/1980, SE quadrant. Gave water."})
    s["pick_client"] = ("pickClient", [get(f"/api/v1/held/{pick['ref']}")])

    ref = post("/api/v1/notes/new-client", {"text": NOTE, "title": "<img src=x onerror=alert(1)>"})["ref"]
    s["review"] = ("draft", [get(f"/api/v1/drafts/{ref}")])
    s["correction"] = ("correction", [get(f"/api/v1/drafts/{ref}"), {}])
    revised = post(f"/api/v1/drafts/{ref}/corrections", {"text": "It was the second time on the street, not the third."})
    s["review_revised"] = ("draft", [get(f"/api/v1/drafts/{ref}")])
    s["flash_revised"] = ("flash", [{"text": "Your correction was applied.", "messages": revised["messages"]}])
    missing = post("/api/v1/notes/new-client", {"text": NOTE.replace("Kim", "Kit").replace(", CE region 7", "")})["ref"]
    s["review_missing"] = ("draft", [get(f"/api/v1/drafts/{missing}")])
    still = post(f"/api/v1/drafts/{missing}/confirm", {"version": 1})
    s["flash_still_missing"] = ("flash", [{"text": "Some answers are still needed.", "messages": still["messages"]}])

    robin = post("/api/v1/notes/new-client", {"text": ROBIN})["ref"]
    s["verification"] = ("draft", [get(f"/api/v1/drafts/{robin}")])
    s["different_person"] = ("differentPerson", [get(f"/api/v1/drafts/{robin}"), {}])
    short = post(f"/api/v1/drafts/{robin}/different-person", {"reason": "younger"})
    s["flash_reason_short"] = ("flash", [{"kind": "error", "text": "Please give a fuller reason.", "messages": short["messages"]}])
    s["different_person_error"] = ("differentPerson", [get(f"/api/v1/drafts/{robin}"), {"reason": "younger",
                                                                                       "error": short["messages"][0]["body"]}])
    post(f"/api/v1/drafts/{robin}/different-person", {"reason": LONG_REASON})
    s["review_after_different_person"] = ("draft", [get(f"/api/v1/drafts/{robin}")])
    post(f"/api/v1/drafts/{robin}/confirm", {"version": 1})
    s["receipt_new_client"] = ("draft", [get(f"/api/v1/drafts/{robin}")])
    same = post("/api/v1/notes/new-client", {"text": ROBIN})["ref"]
    post(f"/api/v1/drafts/{same}/same-client", {"client_id": "HMIS-C-000113"})
    s["review_after_same_client"] = ("draft", [get(f"/api/v1/drafts/{same}")])

    upd = post("/api/v1/notes/update", {"text": JORDAN})["ref"]
    s["review_update"] = ("draft", [get(f"/api/v1/drafts/{upd}")])
    post(f"/api/v1/drafts/{upd}/confirm", {"version": 1})
    s["receipt_update"] = ("draft", [get(f"/api/v1/drafts/{upd}")])
    s["correction_after_entry"] = ("correction", [get(f"/api/v1/drafts/{upd}"), {}])
    post(f"/api/v1/drafts/{upd}/corrections", {"text": "It was 45 minutes, not 20."})
    s["review_correction_of_entries"] = ("draft", [get(f"/api/v1/drafts/{upd}")])

    failed = post("/api/v1/notes/new-client", {"text": NOTE.replace("Kim", "Kaz")})["ref"]
    intake.fail_next("create_client", "service_unavailable")
    out = post(f"/api/v1/drafts/{failed}/confirm", {"version": 1})
    s["failure"] = ("draft", [get(f"/api/v1/drafts/{failed}")])
    s["flash_failure"] = ("flash", [{"kind": "error", "text": "HMIS did not accept the entry.", "messages": out["messages"]}])

    late = post("/api/v1/notes/new-client", {"text": NOTE.replace("Kim", "Kip")})["ref"]
    s["home"] = ("home", [{"user": get("/api/v1/session"), "drafts": get("/api/v1/drafts"), "held": get("/api/v1/held"),
                           "messages": get("/api/v1/messages")}])
    intake.clock.advance(hours=intake.config.settings.supervisor_timeout_hours)
    intake.service.expire_stale()
    w2 = web.as_user("j.alvarez")
    s["expired"] = ("draft", [w2.get(f"/api/v1/drafts/{late}").json()])
    s["not_found"] = ("notFound", [])
    return render(tmp_path, s)


def test_no_worker_screen_uses_email_wording(every_screen):
    assert len(every_screen) >= 29  # every worker screen and state built in the fixture
    found = {name: [m.group(0) for m in (*EMAIL_WORDS.finditer(text_of(page)), *EMAIL_COMMANDS.finditer(text_of(page)))]
             for name, page in every_screen.items()}
    assert {name: words for name, words in found.items() if words} == {}


def test_every_field_has_a_label(every_screen):
    for name, page in every_screen.items():
        for field_id in re.findall(r'<(?:input|textarea|select)\b[^>]*\bid="([^"]+)"', page):
            assert f'<label for="{field_id}"' in page, (name, field_id)
        assert not re.search(r"<(?:input|textarea|select)\b(?![^>]*\bid=)", page), name


def test_every_button_says_what_it_does(every_screen):
    for name, page in every_screen.items():
        for label in buttons(page):
            assert label and len(label.split()) >= 2 and label.lower() not in GENERIC_BUTTONS, (name, label)


def test_confirm_shows_what_will_be_entered_above_the_button(every_screen):
    page = every_screen["review"]
    summary, button = page.index("What Confirm will enter in HMIS"), page.index('data-action="confirm"')
    assert summary < button
    assert all(item in text_of(page[summary:button]) for item in
               ("A new client record", "Kim Placeholder", "A program enrollment", "A Coordinated Entry enrollment"))
    assert "A case note" in text_of(every_screen["review_update"]) and "A service entry" in text_of(every_screen["review_update"])
    assert "Confirm and enter in HMIS" in buttons(page)
    assert not re.search(r'data-action="confirm"[^>]*disabled', page)


def test_confirm_is_disabled_while_a_verification_is_open(every_screen):
    page = every_screen["verification"]
    assert re.search(r'data-action="confirm"[^>]*disabled aria-describedby="confirm-blocked"', page)
    assert "Confirm is not available until you choose Same person or Different person" in text_of(page)
    assert "Same person as HMIS-C-000113: add this as a visit" in buttons(page)
    assert "This is a different person" in buttons(page)


def test_confirm_is_disabled_while_answers_are_missing(every_screen):
    page = every_screen["review_missing"]
    assert re.search(r'data-action="confirm"[^>]*disabled', page)
    assert "Confirm is not available until you add" in text_of(page)


def test_the_review_shows_sources_and_the_four_certainty_states(every_screen):
    page = text_of(every_screen["review_revised"])
    for state in ("Stated in your note", "Check this: your note was not sure", "From your correction",
                  "Written by the system: check the wording"):
        assert state in page
    assert "Been on the street about 3 times in the last 3 years" in page  # a source quote
    assert 'class="certainty worker"' in every_screen["review_revised"].split("Case note")[0]  # a corrected answer


def test_the_reason_screen_states_the_forty_character_rule(every_screen):
    page = every_screen["different_person"]
    assert "at least 40 characters" in text_of(page) and 'minlength="40"' in page


def test_values_are_escaped(every_screen):
    assert "<img src=x" not in every_screen["review"] and "&lt;img src=x onerror=alert(1)&gt;" in every_screen["review"]


def test_failure_and_retry_screen(every_screen):
    page = every_screen["failure"]
    assert "Not entered in HMIS yet" in text_of(page) and "Try again to enter in HMIS" in buttons(page)
    assert "HMIS did not answer. It may be down for a short time." in text_of(page)


def test_no_screen_shows_developer_jargon(every_screen):
    for name, page in every_screen.items():
        assert not re.search(r"python|mock_hmis|-m app|stack trace|exception", text_of(page), re.IGNORECASE), name


def test_home_lists_messages_as_short_links(every_screen):
    page = every_screen["home"]
    recent = page.split("Recent messages")[1]
    assert 'href="#/drafts/ENC-' in recent and "Identifiers HMIS assigned" not in recent


def test_the_note_forms_warn_about_ssns(every_screen):
    for name in ("new_note", "update_note", "correction"):
        assert "Do not write a full Social Security number" in text_of(every_screen[name])
    assert "Nothing was saved" in text_of(every_screen["new_note_ssn_refused"])


def test_the_shell_has_the_sync_status_line_and_is_ready_for_a_service_worker():
    shell = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert re.search(r'id="sync-status" role="status"[^>]*>.*Online</p>', shell)
    assert '<html lang="en">' in shell and 'name="viewport"' in shell and 'href="#main"' in shell
    app = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "export const SHELL" in app and all(Path(WEB_DIR / f).exists() for f in ("index.html", "style.css", "screens.js", "app.js"))
    assert "eval(" not in app and "innerHTML = flash + html" in app  # only escaped screen HTML is inserted


def test_the_web_app_is_served(web):
    r = web.new_client().get("/app/")
    assert r.status_code == 200 and "Outreach notes" in r.text
    assert web.new_client().get("/app/screens.js").status_code == 200
