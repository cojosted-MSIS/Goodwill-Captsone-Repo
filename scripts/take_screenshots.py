"""Regenerate docs/screenshots in one command: python scripts/take_screenshots.py

Starts a fresh mock HMIS and a fresh intake app (in-memory store, rule-based stub parser),
drives Scenario A and Scenario B through the phone screens' routes, takes a screenshot of
every phone and staff screen with headless Edge or Chrome, then stops both servers.
Fresh servers matter: a mock HMIS left running from an earlier run still holds the same
synthetic clients and rejects them as possible duplicates.

Synthetic data only. No key is needed or read. Server logs go to a temporary folder.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config_loader import load_config  # noqa: E402

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]
PHONE_WIDTH, STAFF_WIDTH = 600, 1280


def find_browser(explicit: str | None) -> str:
    candidates = [explicit] if explicit else [*BROWSERS, *(shutil.which(n) for n in
                                                           ("msedge", "google-chrome", "chromium", "chrome"))]
    for path in candidates:
        if path and Path(path).exists():
            return path
    sys.exit("No Edge or Chrome found. Pass --browser with the path to one.")


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_until_up(url: str, seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"{url} did not start; see the server logs")


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


def run(args: argparse.Namespace) -> None:
    config = load_config()
    hmis_url = config.settings.hmis_base_url
    hmis_port = urlparse(hmis_url).port or 80
    for port in (hmis_port, args.port):
        if port_in_use(port):
            sys.exit(f"Port {port} is in use. Stop whatever is running there (an earlier mock HMIS or app) and retry.")

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    logs = Path(tempfile.mkdtemp(prefix="intake-screens-"))
    env = {**os.environ, "INTAKE_PARSER": "rule_stub"}
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, "-m", "mock_hmis", "--port", str(hmis_port)], cwd=ROOT, env=env,
                                      stdout=open(logs / "mock_hmis.log", "w"), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([sys.executable, "-m", "app", "--port", str(args.port), "--db", ":memory:",
                                       "--parser", "rule_stub"], cwd=ROOT, env=env,
                                      stdout=open(logs / "app.log", "w"), stderr=subprocess.STDOUT))
        base = f"http://127.0.0.1:{args.port}"
        wait_until_up(f"{base}/demo/scenarios")
        wait_until_up(f"{hmis_url}/docs")
        shoot = Shooter(find_browser(args.browser), base, out, logs / "browser-profile")
        drive(httpx.Client(base_url=base, timeout=30), httpx.Client(base_url=hmis_url, timeout=10), shoot)
        print(f"{len(shoot.taken)} screenshots in {out}")
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        print(f"Server logs: {logs}")


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

    # The failure screen: the mock HMIS is told to fail the next client entry
    hmis.post("/_admin/reset").raise_for_status()
    hmis.post("/_admin/failures", json={"operation": "create_client", "mode": "service_unavailable", "times": 1}).raise_for_status()
    f = send(scenarios["A"]["subject"], scenarios["A"]["body"])["ref"]
    assert send(f"Re: {newest()['subject']}", "CONFIRM")["action"] == "entry_failed"
    phone("18_entry_failed_screen.png", f"#/receipt/{f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Start fresh servers and retake docs/screenshots (synthetic data only)")
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("--port", type=int, default=8000, help="port for the intake app (the mock HMIS port comes from config)")
    ap.add_argument("--browser", help="path to Edge or Chrome (found automatically if omitted)")
    run(ap.parse_args())
