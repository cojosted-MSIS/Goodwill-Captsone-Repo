"""Regenerate docs/screenshots in one command: python scripts/take_screenshots.py [--only email|web]

Email screens (docs/screenshots/*.png): starts a fresh mock HMIS and a fresh intake app
(in-memory store, rule-based stub parser, email channel on), drives the scenarios through the
phone screens' routes, and takes a screenshot of every phone and staff screen.

Web screens (docs/screenshots/web/*.png, add-web-application): starts fresh servers again with
the shipped settings (email off), makes drafts in each state through /api/v1 as a synthetic
worker, and has scripts/web_screenshots.mjs (Node, no packages) sign in through the real
sign-in form in headless Edge or Chrome and capture every worker, supervisor, and staff screen at
a phone width (390 px) and a desktop width (1280 px).

STAGED: the 48-hour queue screenshots (31 and 35) are staged. A real server cannot wait two days,
so one synthetic draft's review time is set back 50 hours (set_back). The tests use a fake clock. The demo passwords are made at random for the run and
never printed. Then both servers stop.
Fresh servers matter: a mock HMIS left running from an earlier run still holds the same
synthetic clients and rejects them as possible duplicates.

Synthetic data only. No key is needed or read. Server logs go to a temporary folder.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import httpx

from servers import ROOT, fresh_servers

from app.storage import Store

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]
PHONE_WIDTH, STAFF_WIDTH = 600, 1280
WEB_PHONE, WEB_DESKTOP = 390, 1280
PASSWORD_VARS = ("DEMO_PASSWORD_J_ALVAREZ", "DEMO_PASSWORD_M_CHEN", "DEMO_PASSWORD_SUPERVISOR", "DEMO_PASSWORD_STAFF")
NOTE = ("Met Kim Placeholder, DOB 1/2/1990, NW quadrant around 10:15am. Searched HMIS first, no match. Slept outside "
        "last night. Has been staying outside for over a year. Been on the street about 3 times in the last 3 years, "
        "around 14 months total. Started being homeless this time on 8/15/2025. Male, white, not Hispanic. Has a "
        "disabling condition (bad back). Not a veteran. SSN ends 4821. Enroll in street outreach, CE region 7. "
        "Single adult. Gave water and a hygiene kit. Follow up Thursday.")
ROBIN = NOTE.replace("Kim Placeholder", "Robin Demo").replace("1/2/1990", "9/9/1975").replace("4821", "5555")
JORDAN = ("Saw Jordan Sample (HMIS-C-000101) in the SW quadrant. Gave her a bus pass and water. "
          "Spent 20 minutes with her. Still staying outside.")


def find_browser(explicit: str | None) -> str:
    candidates = [explicit] if explicit else [*BROWSERS, *(shutil.which(n) for n in
                                                           ("msedge", "google-chrome", "chromium", "chrome"))]
    for path in candidates:
        if path and Path(path).exists():
            return path
    sys.exit("No Edge or Chrome found. Pass --browser with the path to one.")


class Shooter:
    def __init__(self, browser: str, base: str, out: Path, profile: Path) -> None:
        self.browser, self.base, self.out, self.profile = browser, base, out, profile
        self.taken: list[str] = []

    def _browser(self, width: int, height: int, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([self.browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                               f"--user-data-dir={self.profile}", f"--window-size={width},{height}",
                               "--virtual-time-budget=5000", *extra], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False, timeout=120)

    def page_height(self, url: str, width: int) -> int:
        """Render once in a short window and read the height the page records (markPageHeight)."""
        dom = self._browser(width, 600, "--dump-dom", url).stdout
        match = re.search(r'data-page-height="(\d+)"', dom)
        if not match:
            raise RuntimeError(f"could not read the page height of {url}")
        return min(int(match.group(1)) + 24, 20000)

    def __call__(self, name: str, page: str, width: int) -> None:
        """A full-page screenshot: the window is as tall as the rendered page."""
        target = self.out / name
        url = f"{self.base}{page}"
        self._browser(width, self.page_height(url, width), f"--screenshot={target}", url)
        if not target.exists():
            raise RuntimeError(f"the browser did not write {name}")
        self.taken.append(name)
        print(f"  {name}")


def find_node() -> str:
    for path in (shutil.which("node"), r"C:\Program Files\nodejs\node.exe", "/usr/local/bin/node", "/usr/bin/node"):
        if path and Path(path).exists():
            return path
    sys.exit("Node.js 22 or newer is needed for the web screenshots (it drives the browser).")


def run(args: argparse.Namespace) -> None:
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    browser = find_browser(args.browser)
    # Demo passwords for this run only: random, in the servers' environment, never printed. They take
    # precedence over .env, which is not read here.
    passwords = {name: secrets.token_urlsafe(18) for name in PASSWORD_VARS}
    os.environ.update(passwords)
    if args.only in ("all", "email"):
        run_email(args, out, browser)
    if args.only in ("all", "web"):
        run_web(args, out / "web", browser, passwords)


def run_email(args: argparse.Namespace, out: Path, browser: str) -> None:
    with fresh_servers(args.port) as servers:
        for old in out.glob("*.png"):
            old.unlink()
        shoot = Shooter(browser, servers.app_url, out, servers.logs / "browser-profile")
        drive(httpx.Client(base_url=servers.app_url, timeout=30), httpx.Client(base_url=servers.hmis_url, timeout=10), shoot)
        print(f"{len(shoot.taken)} screenshots in {out}")
        print(f"Server logs: {servers.logs}")


def drive(c: httpx.Client, hmis: httpx.Client, shoot: Shooter) -> None:
    scenarios = {s["id"]: s for s in c.get("/demo/scenarios").json()}
    worker = scenarios["A"]["sender"]

    def send(subject: str, body: str) -> dict:
        out = c.post("/mail/send", json={"sender": worker, "subject": subject, "body": body})
        out.raise_for_status()
        return out.json()

    def newest() -> dict:
        return c.get(f"/mail/inbox/{worker}").json()[0]

    def phone(name: str, page: str) -> None:
        shoot(name, f"/ui/{page}", PHONE_WIDTH)

    def staff(name: str, page: str) -> None:
        shoot(name, f"/ui/staff.html{page}", STAFF_WIDTH)

    phone("01_home.png", "#/")
    phone("02_compose_scenario_b.png", "#/compose/B")

    # Scenario A: clean note, confirmed on the first reply
    a = send(scenarios["A"]["subject"], scenarios["A"]["body"])["ref"]
    review_a = newest()
    phone("03_review_scenario_a.png", f"#/mail/{review_a['id']}")
    staff("10_staff_parser_run_scenario_a.png", f"#/run/{a}")
    staff("11_staff_mapped_draft_scenario_a.png", f"#/mapped/{a}")
    staff("12_staff_staged_record_scenario_a.png", f"#/record/{a}")
    assert send(f"Re: {review_a['subject']}", "CONFIRM")["action"] == "submitted"
    phone("04_receipt_scenario_a.png", f"#/receipt/{a}")

    # Scenario B: scripted parser error and a missing field, corrected, then confirmed
    b = send(scenarios["B"]["subject"], scenarios["B"]["body"])["ref"]
    review_b1 = newest()
    phone("05_inbox.png", "#/inbox")
    phone("06_review_scenario_b_v1_blocked.png", f"#/mail/{review_b1['id']}")
    phone("07_reply_scenario_b.png", f"#/reply/{review_b1['id']}")
    staff("13_staff_parser_run_scenario_b.png", f"#/run/{b}")
    staff("14_staff_mapped_draft_scenario_b_v1.png", f"#/mapped/{b}")
    staff("15_staff_staged_record_scenario_b_v1.png", f"#/record/{b}")
    body = c.get(f"/mail/message/{review_b1['id']}").json()["body"]
    quoted = "\n".join(f"> {line}" for line in body.splitlines())
    assert send(f"Re: {review_b1['subject']}", f"{scenarios['B']['suggested_reply']}\n\n{quoted}")["action"] == "revised"
    review_b2 = newest()
    phone("08_review_scenario_b_v2_revised.png", f"#/mail/{review_b2['id']}")
    assert send(f"Re: {review_b2['subject']}", "CONFIRM")["action"] == "submitted"
    phone("09_receipt_scenario_b.png", f"#/receipt/{b}")
    c.post("/maintenance/purge-emails").raise_for_status()  # the retention rule, so the audit shows it
    staff("16_staff_submitted_record_and_audit_scenario_b.png", f"#/audit/{b}")
    staff("17_staff_all_drafts.png", "#/")

    # A read-only query by email (add-hmis-readonly-queries): a pre-visit briefing for a quadrant
    assert send("Query: SW briefing", "Who has been reported in the SW quadrant?")["action"] == "query_answered"
    phone("19_query_briefing_answer.png", f"#/mail/{newest()['id']}")

    # An update for a client already in HMIS (add-existing-client-updates): review, then receipt
    u = send("Update: Jordan Sample", "Saw Jordan Sample (HMIS-C-000101) in the SW quadrant. Gave her a bus pass and "
                                      "water. Spent 20 minutes with her. Still staying outside.")
    assert u["action"] == "drafted"
    review_u = newest()
    phone("20_update_review.png", f"#/mail/{review_u['id']}")
    staff("21_staff_staged_record_update.png", f"#/record/{u['ref']}")
    assert send(f"Re: {review_u['subject']}", "CONFIRM")["action"] == "submitted"
    phone("22_update_receipt.png", f"#/receipt/{u['ref']}")
    phone("23_compose_update.png", "#/compose/update")
    phone("24_compose_query.png", "#/compose/query")

    # Same-name verification (add-existing-client-updates): D1 ends SAME CLIENT, D2 ends DIFFERENT PERSON
    d1 = send(scenarios["D1"]["subject"], scenarios["D1"]["body"])["ref"]
    v1 = newest()
    phone("25_verification_matching_digits.png", f"#/mail/{v1['id']}")
    assert send(f"Re: {v1['subject']}", scenarios["D1"]["suggested_reply"])["action"] == "verified_same"
    phone("26_update_review_after_same_client.png", f"#/mail/{newest()['id']}")
    d2 = send(scenarios["D2"]["subject"], scenarios["D2"]["body"])["ref"]
    v2 = newest()
    phone("27_verification_different_digits.png", f"#/mail/{v2['id']}")
    assert send(f"Re: {v2['subject']}", scenarios["D2"]["suggested_reply"])["action"] == "verified_different"
    assert send(f"Re: {newest()['subject']}", "CONFIRM")["action"] == "submitted"
    staff("28_staff_audit_different_person.png", f"#/audit/{d2}")
    assert d1 and send(scenarios["E2"]["subject"], scenarios["E2"]["body"])["action"] == "query_answered"
    phone("29_query_status_answer.png", f"#/mail/{newest()['id']}")
    # The no-contact watchlist (add-no-contact-query)
    assert send(scenarios["E3"]["subject"], scenarios["E3"]["body"])["action"] == "query_answered"
    phone("31_query_no_contact_watchlist.png", f"#/mail/{newest()['id']}")
    staff("30_staff_queries.png", "#/queries")

    # The failure screen: the mock HMIS is told to fail the next client entry
    hmis.post("/_admin/reset").raise_for_status()
    hmis.post("/_admin/failures", json={"operation": "create_client", "mode": "service_unavailable", "times": 1}).raise_for_status()
    f = send(scenarios["A"]["subject"], scenarios["A"]["body"])["ref"]
    assert send(f"Re: {newest()['subject']}", "CONFIRM")["action"] == "entry_failed"
    phone("18_entry_failed_screen.png", f"#/receipt/{f}")


def run_web(args: argparse.Namespace, out: Path, browser: str, passwords: dict[str, str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    db = Path(tempfile.mkdtemp(prefix="web-shots-db-")) / "intake.db"  # a file, so one draft can be set back below
    with fresh_servers(args.port, email_channel=False, db=str(db)) as servers:
        steps, flagged, late = make_web_states(servers.app_url, servers.hmis_url, passwords["DEMO_PASSWORD_J_ALVAREZ"])

        def shoot_as(username: str, password: str, plan_steps: list[dict], sign_in_shot: bool = False) -> None:
            plan = {"browser": browser, "base": servers.app_url, "out": str(out), "username": username, "password": password,
                    "widths": {"phone": WEB_PHONE, "desktop": WEB_DESKTOP}, "steps": plan_steps, "signInShot": sign_in_shot}
            run = subprocess.run([find_node(), str(ROOT / "scripts" / "web_screenshots.mjs")], input=json.dumps(plan), text=True,
                                 encoding="utf-8", capture_output=True, check=False, timeout=600)
            print(run.stdout, end="")
            if run.returncode != 0:
                sys.exit(f"The web screenshots stopped: {run.stderr.strip()[-2000:]}\nServer logs: {servers.logs}")

        shoot_as("j.alvarez", passwords["DEMO_PASSWORD_J_ALVAREZ"], steps, sign_in_shot=True)
        print("  (staged: one synthetic draft's review time is set back 50 hours for the 48-hour queue)")
        set_back(db, late)  # after the worker's screens, so the draft is still in review on them
        shoot_as("outreach.supervisor", passwords["DEMO_PASSWORD_SUPERVISOR"], [
            {"name": "30_supervisor_start", "hash": "#/"},
            {"name": "31_supervisor_queue", "hash": "#/queue"},
            {"name": "32_supervisor_flags", "hash": "#/flags"},
            {"name": "33_supervisor_every_draft", "hash": "#/drafts"},
            {"name": "34_supervisor_flagged_draft", "hash": f"#/drafts/{flagged}"},
            {"name": "35_supervisor_expired_draft", "hash": f"#/drafts/{late}"},
        ])
        shoot_as("outreach.staff", passwords["DEMO_PASSWORD_STAFF"], [
            {"name": "36_staff_start", "hash": "#/"},
            {"name": "37_staff_drafts", "hash": "#/drafts"},
            {"name": "38_staff_draft_audit", "hash": f"#/drafts/{flagged}"},
            {"name": "39_staff_query_log", "hash": "#/queries"},
        ])
        print(f"{len(list(out.glob('*.png')))} web screenshots in {out}")


def set_back(db: Path, draft_id: str) -> None:
    """STAGED for the screenshots only: put one synthetic draft past the 48-hour limit, because a real
    server cannot wait two days. Nothing in the app does this."""
    store = Store(str(db))
    draft = store.get_draft(draft_id)
    draft.review_since = draft.review_since - timedelta(hours=50)
    store.save_draft(draft)


def make_web_states(base: str, hmis_url: str, password: str) -> tuple[list[dict], str, str]:
    """Drafts in every state the worker screens show, made through /api/v1 as the synthetic worker."""
    c = httpx.Client(base_url=base, timeout=60)
    pre = c.get("/api/v1/auth/csrf").json()["csrf_token"]
    me = c.post("/api/v1/auth/sign-in", json={"username": "j.alvarez", "password": password}, headers={"X-CSRF-Token": pre})
    me.raise_for_status()
    c.headers["X-CSRF-Token"] = me.json()["csrf_token"]

    def post(path: str, body: dict | None = None) -> dict:
        r = c.post(path, json=body or {})
        r.raise_for_status()
        return r.json()

    def new(text: str, title: str) -> str:
        return post("/api/v1/notes/new-client", {"text": text, "title": title})["ref"]

    held = post("/api/v1/notes/new-client", {"text": NOTE.replace("Searched HMIS first, no match. ", "").replace("Kim", "Kai"),
                                             "title": "Kai, NW quadrant"})["ref"]
    pick = post("/api/v1/notes/update", {"text": "Talked with Sam Example, DOB 2/14/1980, SE quadrant. Gave water.",
                                         "title": "Sam, SE quadrant"})["ref"]
    kim = new(NOTE, "Kim, NW quadrant")
    revised = new(NOTE.replace("Kim", "Kit"), "Kit, NW quadrant")
    assert post(f"/api/v1/drafts/{revised}/corrections", {"text": "It was the second time on the street, not the third."})["action"] == "revised"
    missing = new(NOTE.replace("Kim", "Kip").replace(", CE region 7", ""), "Kip, NW quadrant")
    robin = new(ROBIN, "Robin, NW quadrant")
    robin2 = new(ROBIN, "Robin again")
    assert post(f"/api/v1/drafts/{robin2}/same-client", {"client_id": "HMIS-C-000113"})["action"] == "verified_same"
    entered = new(NOTE.replace("Kim Placeholder", "Kaz Example"), "Kaz, NW quadrant")
    assert post(f"/api/v1/drafts/{entered}/confirm", {"version": 1})["action"] == "submitted"
    jordan = post("/api/v1/notes/update", {"text": JORDAN, "title": "Jordan, SW quadrant"})["ref"]
    assert post(f"/api/v1/drafts/{jordan}/confirm", {"version": 1})["action"] == "submitted"
    httpx.post(f"{hmis_url}/_admin/failures", json={"operation": "create_client", "mode": "service_unavailable", "times": 1}).raise_for_status()
    failed = new(NOTE.replace("Kim Placeholder", "Kay Sample"), "Kay, NW quadrant")
    assert post(f"/api/v1/drafts/{failed}/confirm", {"version": 1})["action"] == "entry_failed"
    social = "Met Lee Sample near the library. Her social is 234 56 7891. Gave water."
    flagged = new(ROBIN, "Robin, entered as a different person")
    reason = "He is about twenty years younger than the person in HMIS and has a different tattoo"
    assert post(f"/api/v1/drafts/{flagged}/different-person", {"reason": reason})["action"] == "verified_different"
    assert post(f"/api/v1/drafts/{flagged}/confirm", {"version": 1})["action"] == "submitted"
    late = new(NOTE.replace("Kim Placeholder", "Lou Example"), "Lou, NW quadrant")
    return [
        {"name": "02_my_notes", "hash": "#/"},
        {"name": "03_new_note", "hash": "#/new"},
        {"name": "04_new_note_ssn_refused", "hash": "#/new", "fill": {"#note-text": social}, "submit": "form[data-form=new-note]"},
        {"name": "05_update_note", "hash": "#/update"},
        {"name": "06_did_you_search_hmis", "hash": f"#/held/{held}"},
        {"name": "07_pick_the_client", "hash": f"#/held/{pick}"},
        {"name": "08_review_new_client", "hash": f"#/drafts/{kim}"},
        {"name": "09_make_a_correction", "hash": f"#/drafts/{kim}/correct"},
        {"name": "10_review_after_correction", "hash": f"#/drafts/{revised}"},
        {"name": "11_review_missing_answer", "hash": f"#/drafts/{missing}"},
        {"name": "12_same_name_verification", "hash": f"#/drafts/{robin}"},
        {"name": "13_different_person_reason", "hash": f"#/drafts/{robin}/different"},
        {"name": "14_review_after_same_person", "hash": f"#/drafts/{robin2}"},
        {"name": "15_entered_new_client", "hash": f"#/drafts/{entered}"},
        {"name": "16_entered_visit", "hash": f"#/drafts/{jordan}"},
        {"name": "17_not_entered_try_again", "hash": f"#/drafts/{failed}"},
        # Looking things up (Stage 3c): fixed forms, read-only, the answer shown once and never stored
        {"name": "18_look_something_up", "hash": "#/queries"},
        {"name": "19_briefing_form", "hash": "#/queries/briefing"},
        {"name": "20_briefing_result", "hash": "#/queries/briefing", "check": ["#quadrant-SW"], "submit": "form[data-form=query]"},
        {"name": "21_lookup_form", "hash": "#/queries/lookup"},
        {"name": "22_lookup_result", "hash": "#/queries/lookup", "submit": "form[data-form=query]",
         "fill": {"#first_name": "Jordan", "#last_name": "Sample", "#date_of_birth": "1979-06-12"}},
        {"name": "23_lookup_not_found", "hash": "#/queries/lookup", "fill": {"#client_id": "HMIS-C-000111"},
         "submit": "form[data-form=query]"},
        {"name": "24_status_form", "hash": "#/queries/status"},
        {"name": "25_status_result", "hash": "#/queries/status", "submit": "form[data-form=query]",
         "fill": {"#status_type": "id_document", "#client_id": "HMIS-C-000101"}},
        {"name": "26_watchlist_form", "hash": "#/queries/no-contact"},
        {"name": "27_watchlist_result", "hash": "#/queries/no-contact", "check": ["#quadrant-all"], "submit": "form[data-form=query]"},
        {"name": "28_lookup_needs_more", "hash": "#/queries/lookup", "fill": {"#first_name": "Jordan", "#last_name": "Sample"},
         "submit": "form[data-form=query]"},
        {"name": "29_queries_offline", "hash": "#/queries", "offline": True},
    ], flagged, late


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Start fresh servers and retake docs/screenshots (synthetic data only)")
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("--port", type=int, default=8000, help="port for the intake app (the mock HMIS port comes from config)")
    ap.add_argument("--browser", help="path to Edge or Chrome (found automatically if omitted)")
    ap.add_argument("--only", choices=["all", "email", "web"], default="all", help="which screenshots to retake")
    run(ap.parse_args())
