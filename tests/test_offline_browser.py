"""add-web-application, Stage 4: offline behavior in a real browser.

Runs tests/browser/*.mjs: real headless Chrome over the DevTools protocol, against a real app
server that is actually stopped to prove offline, and inspects local and session storage,
IndexedDB, the service worker cache, every network request, and the server log. Skipped if
Chrome or Node is missing. Passwords are random for each run. Synthetic data only.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

from app.sealing import SEAL_KEYS_ENV, new_private_key

from .conftest import REPO_ROOT
from .test_web_screens import node

SENTINEL = "ZZSENTINEL"
NOTE = ("Met Kim Placeholder, DOB 1/2/1990, NW quadrant around 10:15am. Searched HMIS first, no match. Slept outside "
        f"last night. {SENTINEL} Has been staying outside for over a year. Been on the street about 3 times in the last 3 years, "
        "around 14 months total. Started being homeless this time on 8/15/2025. Male, white, not Hispanic. Has a "
        "disabling condition (bad back). Not a veteran. SSN ends 4821. Enroll in street outreach, CE region 7. "
        "Single adult. Gave water and a hygiene kit. Follow up Thursday.")
CAPTURE = "You can write notes now. You will review and confirm them when you are back online."
SHELL_PATHS = {"/app/", "/app/index.html", "/app/offline.html", "/app/style.css", "/app/app.js", "/app/screens.js", "/app/device.js", "/app/queue.js", "/app/seal.js", "/app/ssn.js",
               "/app/manifest.webmanifest", "/app/fonts/inter-latin-wght-normal.woff2", "/app/icons/icon-192.png", "/app/icons/icon-512.png"}
PASSWORD_VARS = ("DEMO_PASSWORD_J_ALVAREZ", "DEMO_PASSWORD_M_CHEN", "DEMO_PASSWORD_SUPERVISOR", "DEMO_PASSWORD_STAFF")


@lru_cache(maxsize=1)
def seal_key() -> str:
    """The server's private key for these runs: random, in memory, and passed only to the test server."""
    return new_private_key()


def chrome() -> str:
    found = next((p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium",
                              shutil.which("chrome"), shutil.which("google-chrome")) if p and Path(p).exists()), None)
    if not found:
        pytest.skip("Chrome is needed for the offline browser tests")
    return found


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_scenario(script: str, tmp: Path, **extra) -> tuple[dict, str, dict]:
    passwords = {name: secrets.token_urlsafe(18) for name in PASSWORD_VARS}
    log = tmp / "app.log"
    plan = {"browser": chrome(), "python": sys.executable, "root": str(REPO_ROOT), "port": free_port(), "db": str(tmp / "intake.db"), "log": str(log),
            "env": {**passwords, SEAL_KEYS_ENV: seal_key(), "PYTHONUNBUFFERED": "1"}, "password": passwords["DEMO_PASSWORD_J_ALVAREZ"],
            "passwords": {"j_alvarez": passwords["DEMO_PASSWORD_J_ALVAREZ"], "m_chen": passwords["DEMO_PASSWORD_M_CHEN"]}, "note": NOTE, **extra}
    run = subprocess.run([node(), str(REPO_ROOT / "tests" / "browser" / script)], input=json.dumps(plan), text=True, encoding="utf-8",
                         capture_output=True, check=False, timeout=480, env=os.environ.copy())
    assert run.returncode == 0, run.stderr[-3000:]
    out = json.loads(run.stdout)
    assert "error" not in out, out["error"]
    return out, log.read_text(encoding="utf-8", errors="replace"), passwords


@pytest.fixture(scope="module")
def shell(tmp_path_factory):
    return run_scenario("offline_shell.mjs", tmp_path_factory.mktemp("offline-shell"))


def stored_text(inspected: dict) -> str:
    return json.dumps(inspected)


def without_setup(inspected: dict) -> dict:
    """Leave out the device setup: a public key and a stamp are random, and may hold any digits by chance."""
    device = inspected["idb"].get("outreach-device", {})
    meta = [[k, v] for k, v in device.get("meta", []) if k != "setup"]
    return {**inspected, "idb": {**inspected["idb"], "outreach-device": {**device, "meta": meta}}}


def assert_nothing_personal(inspected: dict) -> None:
    text = stored_text(without_setup(inspected))
    for private in (SENTINEL, "Placeholder", "1990", "4821", "HMIS-C-"):
        assert private not in text, private
    assert inspected["local"] == {} and inspected["session"] == {}


def test_chrome_finds_the_app_installable(shell):
    out, _, _ = shell
    assert out["manifest"]["errors"] == [] and out["manifest"]["url"].endswith("/app/manifest.webmanifest")
    assert out["installability"]["installabilityErrors"] == []


def test_only_the_shell_is_ever_in_the_cache(shell):
    out, _, _ = shell
    for name in ("signed_in", "online_inspect", "offline_inspect", "review_offline_inspect"):
        for urls in out[name]["cache"].values():
            assert set(urls) == SHELL_PATHS, name


def test_no_api_response_comes_from_the_worker_and_all_are_no_store(shell):
    out, _, _ = shell
    answered = [r for r in out["online_requests"] if "status" in r]
    assert len(answered) >= 4
    for r in answered:
        assert not r["fromServiceWorker"] and r["cacheControl"] == "no-store", r["url"]


def test_nothing_personal_is_stored_at_any_point(shell):
    out, _, _ = shell
    for name in ("signed_in", "online_inspect", "offline_inspect", "review_offline_inspect"):
        assert_nothing_personal(out[name])


def test_the_device_keeps_only_the_workers_own_profile(shell):
    out, _, _ = shell
    meta = dict(out["offline_inspect"]["idb"]["outreach-device"]["meta"])
    assert set(meta["profile"]) == {"username", "display_name", "role", "last_contact_at"}
    assert meta["profile"]["username"] == "j.alvarez"


def test_the_app_opens_with_the_server_really_stopped(shell):
    out, _, _ = shell
    assert out["controlled_offline"] is True
    assert out["offline_home"]["pill"] == "Offline" and CAPTURE in out["offline_home"]["text"]
    assert "Write a note about someone new" in out["offline_home"]["text"] and out["offline_home"]["nav_hidden"] is False


def test_offline_screens_say_what_needs_a_connection(shell):
    out, _, _ = shell
    assert CAPTURE in out["offline_new"]
    assert "You are offline." in out["offline_queries"]
    assert "needs a connection" in out["offline_draft"]


def test_requests_while_offline_never_reach_the_network_for_the_shell(shell):
    out, _, _ = shell
    answered = [r for r in out["offline_requests"] if r.get("status") == 200]
    assert answered and all(r["fromServiceWorker"] and "/api/" not in r["url"] for r in answered)


def test_back_online_the_real_screens_return(shell):
    out, _, _ = shell
    assert out["back_online"]["pill"] == "Online" and "Recent" in out["back_online"]["text"]


def test_confirm_is_disabled_offline_and_never_sent(shell):
    out, _, _ = shell
    assert out["confirm_online"] is False and out["confirm_offline"] is True
    assert CAPTURE in out["review_offline_text"]
    assert out["requests_after_clicking_disabled_confirm"] == []
    assert out["confirm_back_online"] is False


def test_a_draft_is_not_available_after_an_offline_reload(shell):
    out, _, _ = shell
    assert "needs a connection" in out["review_after_offline_reload"] and "Placeholder" not in out["review_after_offline_reload"]


def test_network_emulation_also_shows_offline(shell):
    out, _, _ = shell
    assert out["emulated"]["pill"] == "Offline" and out["emulated_back"] == "Online"


def test_a_new_version_waits_while_a_note_is_being_typed(shell):
    out, _, _ = shell
    u = out["update_while_typing"]
    assert u["text"] == "A note being typed while a new version arrives." and u["renders_same"] and u["waiting"]


def test_the_new_version_takes_over_when_it_is_safe(shell):
    out, _, _ = shell
    assert len(out["after_update"]["caches"]) == 1 and out["after_update"]["caches"] != out["update_while_typing"]["caches_before"]


def test_sign_out_removes_the_device_profile(shell):
    out, _, _ = shell
    meta = dict(out["after_sign_out"]["idb"].get("outreach-device", {}).get("meta", []))
    assert "profile" not in meta


def test_no_content_security_violations(shell):
    assert shell[0]["violations"] == []


def test_the_server_log_holds_no_note_or_password(shell):
    _, log, passwords = shell
    assert log and SENTINEL not in log and "Placeholder" not in log
    assert not [p for p in passwords.values() if p in log]


def test_requests_never_carry_a_password_in_a_url(shell):
    out, _, passwords = shell
    assert not [r["url"] for r in out["all_requests"] for p in passwords.values() if p in r["url"]]
