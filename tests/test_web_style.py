"""add-web-application, Stage 3e: the visual design of every web screen.

Specs: openspec/changes/add-web-application/specs/web-application/spec.md ("One themeable design").
Checks the design tokens, text contrast, tap targets, the focus ring, reduced motion, a word and
an icon on every status, and the structure of each screen. The behavior and wording checks stay in
tests/test_web_screens.py and tests/test_web_screens_roles.py. Synthetic data only.
"""

from __future__ import annotations

import re

import pytest

from .conftest import REPO_ROOT
from .test_web_screens import every_screen, text_of  # noqa: F401  (fixture)
from .test_web_screens_roles import role_screens  # noqa: F401  (fixture)

WEB = REPO_ROOT / "ui" / "web"
CSS = (WEB / "style.css").read_text(encoding="utf-8")
SCREENS = (WEB / "screens.js").read_text(encoding="utf-8")
SHELL = (WEB / "index.html").read_text(encoding="utf-8")

TOKENS = {
    "--page": "#F6F7F4", "--card": "#FFFFFF", "--border": "#D9DDD3", "--ink": "#14213D", "--muted": "#4B5563",
    "--primary": "#0F5C57", "--on-primary": "#FFFFFF", "--plain-border": "#9AA3AF", "--focus": "#0F5C57",
    "--green-bg": "#DCF2E5", "--green-ink": "#14532D", "--amber-bg": "#FDECC8", "--amber-ink": "#6B3500",
    "--red-bg": "#FBE0DC", "--red-ink": "#7F1D12", "--blue-bg": "#DDE8F8", "--blue-ink": "#1E3A6E",
    "--grey-bg": "#E5E7EB", "--grey-ink": "#1F2937",
}
PAIRS = [("--ink", "--page"), ("--ink", "--card"), ("--muted", "--page"), ("--muted", "--card"), ("--on-primary", "--primary"),
         ("--primary", "--card"), ("--primary", "--page"), ("--green-ink", "--green-bg"), ("--amber-ink", "--amber-bg"),
         ("--red-ink", "--red-bg"), ("--blue-ink", "--blue-bg"), ("--grey-ink", "--grey-bg"), ("--muted", "--grey-bg")]


def luminance(color: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def rule(selector: str) -> str:
    match = re.search(r"^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS, re.MULTILINE)
    assert match, selector
    return match.group(1)


def px(body: str, prop: str) -> float:
    match = re.search(rf"(?:^|[;\s]){prop}:\s*([\d.]+)px", body)
    assert match, (prop, body)
    return float(match.group(1))


# Tokens


@pytest.mark.parametrize(("name", "value"), TOKENS.items())
def test_each_token_is_a_css_variable(name, value):
    assert re.search(rf"{name}:\s*{value}\s*;", CSS, re.IGNORECASE), name


def test_colors_live_only_in_the_variables():
    """So DeveloperTown can re-theme by editing one block."""
    body = CSS[CSS.index("}", CSS.index(":root")):]
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", body) == []


@pytest.mark.parametrize(("ink", "paper"), PAIRS)
def test_text_contrast_is_at_least_4_5(ink, paper):
    assert contrast(TOKENS[ink], TOKENS[paper]) >= 4.5, (ink, paper)


def test_radius_font_and_sizes():
    assert 14 <= px(rule(":root"), "--radius") <= 16
    assert "Inter" in rule("body") and "system-ui" in rule("body")
    assert 16 <= px(rule("body"), "font-size") <= 17
    assert 26 <= px(rule("h1"), "font-size") <= 28
    assert 12 <= px(rule(".eyebrow"), "font-size") <= 13 and "uppercase" in rule(".eyebrow") and "letter-spacing" in rule(".eyebrow")
    assert px(rule(".answer .value"), "font-size") == 18


def test_inter_is_served_with_the_app_and_nothing_comes_from_elsewhere():
    assert (WEB / "fonts" / "inter-latin-wght-normal.woff2").read_bytes()[:4] == b"wOF2"
    assert (WEB / "fonts" / "LICENSE.txt").exists()
    for text in (CSS, SHELL):
        assert not re.search(r"https?://", text.replace("http://www.w3.org/2000/svg", ""))


def test_tap_targets():
    assert px(rule(".btn"), "min-height") >= 48
    assert px(rule(".btn.primary"), "min-height") >= 56
    for selector in (".back a", ".nav-item", "summary", ".choices .choice", "input, textarea, select"):
        assert px(rule(selector), "min-height") >= 48, selector


def test_button_kinds():
    assert "var(--primary)" in rule(".btn.primary") and "var(--on-primary)" in rule(".btn.primary")
    assert "2px solid var(--primary)" in rule(".btn") and "var(--card)" in rule(".btn")
    assert "2px solid var(--plain-border)" in rule(".btn.plain")


def test_focus_ring_and_reduced_motion():
    focus = rule(":focus-visible")
    assert "3px solid var(--focus)" in focus and "outline-offset: 2px" in focus
    assert "prefers-reduced-motion: reduce" in CSS


def test_no_emoji_or_icon_font():
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-➿⚠]")
    assert not emoji.search(SCREENS) and not emoji.search(SHELL)
    assert "font-awesome" not in CSS.lower() and "material-icons" not in CSS.lower()


# Every status is a word and an icon


def chips(page: str) -> list[str]:
    return re.findall(r'<(?:span|p) class="(?:chip|certainty)\b[^"]*"[^>]*>(.*?)</(?:span|p)>', page, re.DOTALL)


def test_every_status_has_a_word_and_an_icon(every_screen, role_screens):  # noqa: F811
    found = 0
    for name, page in {**every_screen, **role_screens}.items():
        assert 'class="status' not in page, name  # the old color-only pills are gone
        for chip in chips(page):
            found += 1
            assert "<svg" in chip and text_of(chip).strip(), (name, chip)
            assert 'aria-hidden="true"' in chip, (name, chip)
    assert found > 80


@pytest.mark.parametrize(("screen", "color", "word"), [
    ("receipt_new_client", "green", "Entered in HMIS"), ("failure", "red", "Not entered yet"),
])
def test_chip_colors_by_meaning(every_screen, screen, color, word):  # noqa: F811
    assert re.search(rf'class="chip {color}"[^>]*>.*?{word}', every_screen[screen], re.DOTALL)


def test_the_labels_use_their_colors():
    for cls, color in (("high", "green"), ("medium", "amber"), ("worker", "blue")):
        assert f"var(--{color}-bg)" in rule(f".certainty.{cls}") and f"var(--{color}-ink)" in rule(f".certainty.{cls}")
    for color in ("green", "amber", "red", "blue", "grey"):
        assert f"var(--{color}-bg)" in rule(f".chip.{color}") and f"var(--{color}-ink)" in rule(f".chip.{color}")


# Each screen's structure


def test_check_your_draft_answers_are_cards(every_screen):  # noqa: F811
    page = every_screen["review_revised"]
    assert 'class="answer check"' in page and "2px solid var(--amber-ink)" in rule(".answer.check")
    card = re.search(r'<div class="answer check">(.*?)</div>', page, re.DOTALL).group(1)
    assert 'class="eyebrow"' in card and 'class="value"' in card and 'class="certainty medium"' in card and "You wrote:" in card


def test_the_bottom_bar_holds_the_summary_confirm_and_correction(every_screen):  # noqa: F811
    bar = every_screen["review"][every_screen["review"].index('<section class="confirm bar"'):]
    assert "What Confirm will enter in HMIS" in bar and 'data-action="confirm"' in bar and "Make a correction" in bar
    assert "position: sticky" in rule(".bar") and "bottom: 0" in rule(".bar")


def test_the_same_name_check_shows_only_what_it_should(every_screen):  # noqa: F811
    page = every_screen["verification"]
    card = page[page.index('<li class="candidate'):page.index("</li>")]
    for shown in ("HMIS-C-000113", "Robin D.", "Last contact", "NW quadrant", "Same person"):
        assert shown in text_of(card), shown
    for hidden in ("entered 0", "enrollment", "last service"):
        assert hidden not in text_of(card).lower(), hidden
    bar = page[page.index('<section class="bar"'):]
    assert 'id="reason"' in bar and 'id="reason-count"' in bar and "at least 40 characters" in text_of(bar)
    assert "This is a different person" in text_of(bar)


def test_home_has_two_actions_a_needs_you_card_and_recent(every_screen):  # noqa: F811
    page = every_screen["home"]
    top = page[:page.index("needs-you")]
    assert len(re.findall(r'<a class="btn', top)) == 2
    assert 'class="card needs-you"' in page and page.index("needs-you") < page.index("<h2>Recent</h2>")
    recent = page[page.index("<h2>Recent</h2>"):]
    assert "Entered in HMIS" in recent and 'class="chip' in recent


def test_the_bottom_navigation_is_in_the_shell():
    nav = SHELL[SHELL.index('id="bottom-nav"'):SHELL.index("</nav>")]
    for href, word in (("#/", "My notes"), ("#/new", "New note"), ("#/queries", "Look up")):
        assert f'href="{href}"' in nav and word in nav
    assert nav.count("<svg") == 3


def test_the_sync_pill_has_a_word_and_an_icon():
    assert re.search(r'class="chip green sync"[^>]*><svg[^\n]*Online</p>', SHELL)
    assert 'syncPill' in SCREENS and "wifiOff" in SCREENS


def test_the_watchlist_has_two_tiles(every_screen):  # noqa: F811
    page = every_screen["result_watchlist"]
    assert re.search(r'class="tile red".*?Past 60 days', page, re.DOTALL)
    assert re.search(r'class="tile amber".*?Approaching 60 days', page, re.DOTALL)
    assert page.index('class="tile red"') < page.index('class="results"')


@pytest.mark.parametrize("screen", ["supervisor_queue", "supervisor_flags", "supervisor_drafts", "staff_drafts", "staff_queries",
                                    "supervisor_draft_flagged", "staff_audit"])
def test_role_screens_are_tables_that_stack_on_a_phone(role_screens, screen):  # noqa: F811
    page = role_screens[screen]
    assert '<table class="stack-table"' in page and "<th scope=\"col\"" in page and 'data-label="' in page
    assert re.search(r"@media \(max-width: 719px\)[^@]*\.stack-table", CSS)


# The review screen's bottom bar is compact until asked


def test_the_review_bar_is_compact_by_default(every_screen):  # noqa: F811
    page = every_screen["review"]
    bar = page[page.index('<section class="confirm bar"'):]
    details = bar[bar.index("<details"):bar.index("</details>")]
    assert "<details" in bar and "<details open" not in bar
    assert "See what will be entered" in details and "3 entries in HMIS" in details
    assert "A new client record" in details  # the full summary is inside, for whoever opens it
    assert bar.index("</details>") < bar.index('data-action="confirm"')  # Confirm is always visible


def test_why_confirm_is_blocked_stays_visible_in_the_compact_bar(every_screen):  # noqa: F811
    page = every_screen["review_missing"]
    bar = page[page.index('<section class="confirm bar"'):]
    assert bar.index("</details>") < bar.index('id="confirm-blocked"')


def test_the_digits_chip_is_marked_tbc(every_screen):  # noqa: F811
    assert "[TBC with Goodwill and CHIP" in text_of(every_screen["verification"])
