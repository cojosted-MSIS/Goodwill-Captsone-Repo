"""add-web-application, Stage 3d: the supervisor and staff screens themselves.

Rendered from real /api/v1 data with ui/web/screens.js in Node, the same code the browser runs, and
checked like the worker screens: no email wording, a label on every field, buttons that say
what they do, escaped values. These screens are read-only and show no neighbor information.
Synthetic data only.
"""

from __future__ import annotations

import re

import pytest

from .test_channel_wording import EMAIL_COMMANDS, EMAIL_WORDS
from .test_web_api import NOTE, ROBIN, STAFF, SUPERVISOR
from .test_web_screens import GENERIC_BUTTONS, buttons, render, text_of

LONG_REASON = "He is about twenty years younger than the person in HMIS and has a different tattoo"
PRIVATE = ("Robin", "Demo", "Kim", "Placeholder", "1975", "1990", "5555", "4821", "hygiene kit", "bad back")


@pytest.fixture
def role_screens(web, tmp_path):
    alvarez = web.as_user("j.alvarez")
    post = lambda path, body=None: alvarez.post(path, json=body or {}).json()  # noqa: E731
    flagged = post("/api/v1/notes/new-client", {"text": ROBIN, "title": "New client: Robin"})["ref"]
    post(f"/api/v1/drafts/{flagged}/different-person", {"reason": LONG_REASON})
    post(f"/api/v1/drafts/{flagged}/confirm", {"version": 1})
    post("/api/v1/queries/lookup", {"first_name": "Robin", "last_name": "Demo", "date_of_birth": "1975-09-09"})
    post("/api/v1/queries/briefing", {"quadrant": "SW"})
    post("/api/v1/queries/lookup", {"first_name": "Robin"})
    late = post("/api/v1/notes/new-client", {"text": NOTE, "title": "Kim, NW"})["ref"]
    empty_user = {"display_name": "Someone"}
    s: dict[str, tuple[str, list]] = {
        "supervisor_queue_empty": ("supervisorQueue", [[]]), "supervisor_flags_empty": ("supervisorFlags", [[]]),
        "staff_queries_empty": ("staffQueries", [[]]), "staff_drafts_empty": ("staffDrafts", [[]]),
        "supervisor_drafts_empty": ("supervisorDrafts", [[]]),
        "supervisor_home_empty": ("supervisorHome", [{"user": empty_user, "queue": [], "flags": []}]),
    }
    web.intake.clock.advance(hours=web.intake.config.settings.supervisor_timeout_hours + 1)
    sup = web.as_user(SUPERVISOR)
    get = lambda path: sup.get(path).json()  # noqa: E731
    queue, flags = get("/api/v1/supervisor/queue"), get("/api/v1/supervisor/flags")
    s["supervisor_home"] = ("supervisorHome", [{"user": get("/api/v1/session"), "queue": queue, "flags": flags}])
    s["supervisor_queue"] = ("supervisorQueue", [queue])
    s["supervisor_flags"] = ("supervisorFlags", [flags])
    s["supervisor_drafts"] = ("supervisorDrafts", [get("/api/v1/supervisor/drafts")])
    s["supervisor_draft_flagged"] = ("supervisorDraft", [get(f"/api/v1/supervisor/drafts/{flagged}")])
    s["supervisor_draft_expired"] = ("supervisorDraft", [get(f"/api/v1/supervisor/drafts/{late}")])
    staff = web.as_user(STAFF)
    sget = lambda path: staff.get(path).json()  # noqa: E731
    s["staff_home"] = ("staffHome", [{"user": sget("/api/v1/session")}])
    s["staff_drafts"] = ("staffDrafts", [sget("/api/v1/staff/drafts")])
    s["staff_audit"] = ("staffAudit", [sget(f"/api/v1/staff/drafts/{flagged}/audit")])
    s["staff_queries"] = ("staffQueries", [sget("/api/v1/staff/queries")])
    s["escaping_flags"] = ("supervisorFlags", [[{"draft_id": "<b>x</b>", "flag": "<i>y</i>", "reason": "<script>z</script>"}]])
    return render(tmp_path, s)


def test_no_role_screen_uses_email_wording(role_screens):
    assert len(role_screens) >= 17
    found = {n: [m.group(0) for m in (*EMAIL_WORDS.finditer(text_of(p)), *EMAIL_COMMANDS.finditer(text_of(p)))]
             for n, p in role_screens.items()}
    assert {n: w for n, w in found.items() if w} == {}


def test_every_field_has_a_label(role_screens):
    for name, page in role_screens.items():
        for field_id in re.findall(r'<(?:input|textarea|select)\b[^>]*\bid="([^"]+)"', page):
            assert f'<label for="{field_id}"' in page, (name, field_id)
        assert not re.search(r"<(?:input|textarea|select)\b(?![^>]*\bid=)", page), name


def test_every_button_says_what_it_does(role_screens):
    for name, page in role_screens.items():
        for label in buttons(page):
            assert label and len(label.split()) >= 2 and label.lower() not in GENERIC_BUTTONS, (name, label)


def test_these_screens_are_read_only(role_screens):
    for name, page in role_screens.items():
        assert "data-action=" not in page and "<form" not in page and "<button" not in page, name


def test_no_neighbor_information_on_any_role_screen(role_screens):
    for name, page in role_screens.items():
        text = text_of(page)
        assert not [p for p in PRIVATE if p in text], name
        assert "New client: Robin" not in text and "Kim, NW" not in text, name


def test_the_written_reason_is_only_on_the_supervisors_flag_screen(role_screens):
    allowed = {"supervisor_flags", "supervisor_draft_flagged"}
    assert "twenty years younger" in text_of(role_screens["supervisor_flags"])
    for name, page in role_screens.items():
        if name not in allowed:
            assert "twenty years younger" not in text_of(page), name
    assert "twenty years younger" not in text_of(role_screens["staff_audit"])


def test_the_queue_reads_in_plain_language(role_screens):
    page = text_of(role_screens["supervisor_queue"])
    assert "Not confirmed in time" in page and "49 hours" in page and "j.alvarez" in page
    assert "No drafts are waiting" in text_of(role_screens["supervisor_queue_empty"])


def test_the_home_screens_link_to_each_view(role_screens):
    home = role_screens["supervisor_home"]
    assert all(f'href="#/{p}"' in home for p in ("queue", "flags", "drafts"))
    assert "1 waiting" in text_of(home) and "1 flagged" in text_of(home)
    staff = role_screens["staff_home"]
    assert all(f'href="#/{p}"' in staff for p in ("drafts", "queries"))


def test_the_audit_trail_is_in_plain_words(role_screens):
    for name in ("supervisor_draft_flagged", "staff_audit"):
        page = text_of(role_screens[name])
        assert "Worker confirmed version 1." in page and "verification_decided" not in page, name


def test_the_query_log_reads_in_plain_words(role_screens):
    page = text_of(role_screens["staff_queries"])
    assert "Lookup by name and date of birth (both given). 3 rows." in page and "Briefing, SW quadrant." in page
    assert "Nothing was run" in page  # a refused query


def test_values_are_escaped(role_screens):
    page = role_screens["escaping_flags"]
    assert "<script>z" not in page and "<b>x" not in page and "&lt;script&gt;z" in page
