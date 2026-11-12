"""add-web-application, Stage 4b: the app shell, installability, and what may be cached.

Specs: openspec/changes/add-web-application/specs/offline-sync/spec.md ("Open and write entries
offline", "Cache only the static app shell"). Plan: design.md section 5a. The service worker caches
only the static shell: never an /api response. Real offline behavior is in
tests/test_offline_browser.py. Synthetic data only.
"""

from __future__ import annotations

import json
import re
import struct
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.api import create_app

from .conftest import REPO_ROOT, Web
from .test_web_api import ALL, OPEN_ROUTES, REF, SUPERVISOR
from .test_web_screens import node, render, text_of

WEB = REPO_ROOT / "ui" / "web"


def sw_shell() -> list[str]:
    source = (WEB / "sw.js").read_text(encoding="utf-8")
    return json.loads(re.search(r"const SHELL = (\[.*?\]);", source, re.DOTALL).group(1))


# Every API response says no-store


@pytest.mark.parametrize(("method", "path", "body"), ALL)
def test_every_api_route_is_no_store_without_a_session(web, method, path, body):
    r = web.client.request(method, path, json=body) if body is not None else web.client.request(method, path)
    assert r.status_code == 401 and r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("method", "path", "body"), ALL)
def test_every_api_route_is_no_store_when_signed_in(web, method, path, body):
    web.sign_in(SUPERVISOR if "supervisor" in path else "outreach.staff" if "staff" in path else "j.alvarez")
    r = web.client.request(method, path, json=body) if body is not None else web.client.request(method, path)
    assert r.headers["cache-control"] == "no-store", r.status_code


@pytest.mark.parametrize("path", sorted(OPEN_ROUTES - {"/api/v1/auth/sign-in"}))
def test_open_routes_are_no_store(web, path):
    assert web.client.get(path).headers["cache-control"] == "no-store"


def test_sign_in_and_errors_are_no_store(web):
    pre = web.client.get("/api/v1/auth/csrf").json()["csrf_token"]
    failed = web.client.post("/api/v1/auth/sign-in", json={"username": "x", "password": "y"}, headers={"X-CSRF-Token": pre})
    assert failed.status_code == 401 and failed.headers["cache-control"] == "no-store"
    web.sign_in("j.alvarez")
    bad = web.client.post("/api/v1/notes/new-client", json={"nope": 1})
    assert bad.status_code == 422 and bad.headers["cache-control"] == "no-store"
    missing = web.client.get(f"/api/v1/drafts/{REF}")
    assert missing.status_code == 404 and missing.headers["cache-control"] == "no-store"
    assert web.client.get("/api/v1/no-such-route").headers["cache-control"] == "no-store"


def test_the_connection_check_holds_nothing(web):
    r = web.client.get("/api/v1/ping")
    assert r.status_code == 200 and r.json() == {"ok": True}


# The shell's headers


@pytest.mark.parametrize("path", ["/app/", "/app/sw.js", "/app/offline.html"])
def test_the_shell_has_a_strict_content_security_policy(web, path):
    r = web.client.get(path)
    policy = r.headers["content-security-policy"]
    assert r.status_code == 200 and r.headers["x-content-type-options"] == "nosniff"
    for rule in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "connect-src 'self'", "object-src 'none'",
                 "base-uri 'none'", "frame-ancestors 'none'"):
        assert rule in policy
    assert "unsafe" not in policy and "http" not in policy


def test_the_hidden_attribute_wins_over_any_class():
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important", (WEB / "style.css").read_text(encoding="utf-8"))


def test_the_shell_has_no_inline_script_or_style():
    for name in ("index.html", "offline.html"):
        page = (WEB / name).read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)", page) and "<style" not in page and " style=" not in page and " onclick=" not in page
    assert " style=" not in (WEB / "screens.js").read_text(encoding="utf-8")


# Installability


def test_the_manifest_makes_the_app_installable(web):
    r = web.client.get("/app/manifest.webmanifest")
    m = r.json()
    assert r.status_code == 200 and "manifest" in r.headers["content-type"]
    assert m["name"] == "Outreach notes" and m["short_name"] and m["display"] == "standalone"
    assert m["start_url"] == "./" and m["scope"] == "./"
    assert m["theme_color"] == "#0F5C57" and m["background_color"] == "#F6F7F4"
    sizes = {i["sizes"]: i for i in m["icons"]}
    assert {"192x192", "512x512"} <= set(sizes) and any("maskable" in i.get("purpose", "") for i in m["icons"])
    shell = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'rel="manifest" href="manifest.webmanifest"' in shell and 'name="theme-color"' in shell


@pytest.mark.parametrize("size", [192, 512])
def test_the_icons_are_real_pngs_of_the_right_size(size):
    data = (WEB / "icons" / f"icon-{size}.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", data[16:24]) == (size, size)


# The service worker


def test_the_worker_is_served_with_a_version_and_is_not_http_cached(web):
    r = web.client.get("/app/sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"] and r.headers["cache-control"] == "no-cache"
    assert "__SHELL_VERSION__" not in r.text and re.search(r'const VERSION = "[0-9a-f]{16}"', r.text)


def test_the_version_changes_when_the_salt_does(intake, monkeypatch):
    first = TestClient(create_app(intake.service, users=Web(intake).users)).get("/app/sw.js").text
    monkeypatch.setenv("INTAKE_SHELL_SALT", "another-build")
    assert TestClient(create_app(intake.service, users=Web(intake).users)).get("/app/sw.js").text != first


def test_the_shell_list_is_fixed_and_static():
    shell = sw_shell()
    app_list = json.loads(re.search(r"export const SHELL = (\[.*?\]);", (WEB / "app.js").read_text(encoding="utf-8"), re.DOTALL).group(1))
    assert shell == app_list
    for path in shell:
        assert "api" not in path and (path == "./" or (WEB / path).is_file()), path
    assert {"index.html", "offline.html", "style.css", "app.js", "screens.js", "device.js", "manifest.webmanifest",
            "fonts/inter-latin-wght-normal.woff2", "icons/icon-192.png", "icons/icon-512.png"} <= set(shell)


def test_the_worker_never_writes_a_response_into_the_cache():
    source = (WEB / "sw.js").read_text(encoding="utf-8")
    assert ".put(" not in source and ".add(" not in source and "addAll" in source


def test_the_worker_answers_only_for_shell_files():
    run = subprocess.run([node(), str(REPO_ROOT / "tests" / "sw_check.mjs"), str(WEB / "sw.js")], capture_output=True, text=True,
                         encoding="utf-8", check=False, timeout=60)
    assert run.returncode == 0, run.stderr
    d = json.loads(run.stdout)
    for shell_url in ("/app/", "/app/index.html", "/app/app.js", "/app/style.css", "/app/fonts/inter-latin-wght-normal.woff2"):
        assert d[f"GET {shell_url}"] == "cache-first", shell_url
    for not_shell in ("/api/v1/drafts", "/api/v1/session", "/api/v1/ping", "/api/v1/supervisor/queue", "/app/sw.js", "/drafts/ENC-1"):
        assert d[f"GET {not_shell}"] == "not-handled", not_shell
    assert d["POST /app/app.js"] == "not-handled" and d["POST /api/v1/notes/new-client"] == "not-handled"
    assert d["GET https://other.example/app/app.js"] == "not-handled"
    assert d["NAVIGATE /app/unknown"] == "network-then-offline-page" and d["NAVIGATE /api/v1/drafts"] == "not-handled"
    assert d["installed"] == sorted(d["installed"]) or d["installed"]
    assert d["skip_waiting_on_install"] is False and d["skip_waiting_on_message"] is True  # a new version waits until it is safe
    assert d["deleted_on_activate"] == ["outreach-shell-old"] and d["kept_unrelated"] is True


# The sync status line and the offline screens


@pytest.fixture
def status_screens(tmp_path):
    cases = {
        "online": ("syncState", [{"online": True}]), "offline": ("syncState", [{"online": False}]),
        "uploading": ("syncState", [{"online": True, "uploading": 1}]),
        "attention": ("syncState", [{"online": True, "needsAttention": 2}]),
        "attention_beats_uploading": ("syncState", [{"online": True, "uploading": 1, "needsAttention": 1}]),
        "offline_beats_all": ("syncState", [{"online": False, "uploading": 1, "needsAttention": 1}]),
    }
    for s in ("online", "offline", "uploading", "attention"):
        cases[f"pill_{s}"] = ("syncPill", [s])
    user = {"display_name": "J. Alvarez"}
    cases["offline_home"] = ("offlineHome", [{"user": user}])
    cases["needs_connection"] = ("needsConnection", [{}])
    cases["needs_sign_in"] = ("needsConnection", [{"signedOut": True}])
    cases["note_offline"] = ("noteForm", [{"kind": "new", "online": False}])
    return render(tmp_path, cases)


def test_the_status_line_truth_table(status_screens):
    s = status_screens
    assert (s["online"], s["offline"], s["uploading"], s["attention"]) == ("online", "offline", "uploading", "attention")
    assert s["attention_beats_uploading"] == "attention" and s["offline_beats_all"] == "offline"


@pytest.mark.parametrize(("state", "word", "color"), [("online", "Online", "green"), ("offline", "Offline", "grey"),
                                                      ("uploading", "Uploading", "blue"), ("attention", "Needs attention", "red")])
def test_each_status_is_a_word_and_an_icon(status_screens, state, word, color):
    pill = status_screens[f"pill_{state}"]
    assert word in pill["html"] and "<svg" in pill["html"] and f"chip {color}" in pill["className"]


CAPTURE = "You can write notes now. You will review and confirm them when you are back online."


def test_the_offline_screens_say_what_can_be_done(status_screens):
    assert CAPTURE in text_of(status_screens["offline_home"]) and CAPTURE in text_of(status_screens["note_offline"])
    assert "Write a note about someone new" in text_of(status_screens["offline_home"])
    needs = text_of(status_screens["needs_connection"])
    assert "needs a connection" in needs and CAPTURE in needs
    assert "Signing in needs a connection" in text_of(status_screens["needs_sign_in"])
