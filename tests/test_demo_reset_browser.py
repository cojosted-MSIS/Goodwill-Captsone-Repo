"""add-web-application, Stage 4e: the demo reset clears the device, in a real browser.

Runs tests/browser/demo_reset.mjs with a real mock HMIS and a real app server, stopped and restarted
to prove offline. A restart must never lose a note (the K key in the demo); a reset must clear the
device, and the page must say what it cleared. Synthetic data only.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time

import pytest

from .conftest import REPO_ROOT
from .test_offline_browser import NOTE, SENTINEL, SHELL_PATHS, run_scenario


def up(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="module")
def reset(tmp_path_factory):
    if up(8765):
        pytest.skip("port 8765 is in use")
    hmis = subprocess.Popen([sys.executable, "-m", "mock_hmis", "--port", "8765"], cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(200):
            if up(8765):
                break
            time.sleep(0.1)
        yield run_scenario("demo_reset.mjs", tmp_path_factory.mktemp("demo-reset"), app_args=["--demo-reset"])
    finally:
        hmis.terminate()
        hmis.wait(timeout=10)


def rows(seen: dict) -> list:
    return [v for _, v in seen["idb"].get("outreach-device", {}).get("queue", [])]


def meta(seen: dict) -> dict:
    return dict(seen["idb"].get("outreach-device", {}).get("meta", []))


def test_a_restart_keeps_the_saved_note(reset):
    out = reset[0]
    (before,) = rows(out["before_restart"])
    (after,) = rows(out["after_restart"])
    assert before["id"] == after["id"] and after["envelope"] == before["envelope"]
    assert meta(out["after_restart"])["demo_epoch"] == out["first_epoch"]
    assert "Note saved" in out["after_restart_text"]


def test_the_reset_clears_the_server_and_says_what(reset):
    r = reset[0]["reset"]
    assert r["status"] == 200 and {"hmis", "staging_store", "device"} <= set(r["body"])


def test_the_reset_clears_the_device(reset):
    seen = reset[0]["after_reset"]
    assert rows(seen) == []
    m = meta(seen)
    assert "pending_sign_out" not in m and "upload_backoff" not in m and m["demo_epoch"] != reset[0]["first_epoch"]


def test_the_page_says_what_it_cleared(reset):
    text = reset[0]["after_reset_text"]
    assert "Demo reset" in text and "1 saved note" in text and "public key" in text


def test_the_app_files_stay(reset):
    assert all(set(urls) == SHELL_PATHS for urls in reset[0]["after_reset"]["cache"].values())


def test_nothing_personal_at_any_point(reset):
    for name in ("before_restart", "after_restart", "after_reset"):
        text = json.dumps(reset[0][name])
        assert SENTINEL not in text and "Placeholder" not in text
        assert reset[0][name]["local"] == {} and reset[0][name]["session"] == {}


def test_nothing_was_uploaded_by_the_reset(reset):
    assert not [r for r in reset[0]["after_reset_requests"] if r["url"].endswith("/notes/sealed") and r.get("status") == 200]


def test_no_note_text_in_the_log(reset):
    assert reset[1] and SENTINEL not in reset[1] and NOTE not in reset[1]


def test_no_content_security_violations(reset):
    assert reset[0]["violations"] == []
