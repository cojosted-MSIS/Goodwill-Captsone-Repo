"""add-web-application, Stage 4e: the web demo (scripts/demo.py, scripts/demo_web.py) and its reset.

The walkthrough runs in process against the real API with a stand-in device. The real device, in
real Chrome, with the real servers, is run end to end at the bottom of this file and in
tests/browser/demo_reset.mjs. Passwords and keys are random for each run. Synthetic data only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from app.api import demo_parser
from app.config_loader import load_config, with_web_reset
from app.demo import load_scenarios
from app.sealing import SEAL_KEYS_ENV, Sealer
from parser.rule_stub import RuleStubParser

from .conftest import REPO_ROOT, Intake, SEED_TODAY, Web
from .test_offline_browser import PASSWORD_VARS, chrome, free_port, seal_key
from .test_sealing import private_key
from .test_web_api import NOTE
from .test_web_screens import node

SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


demo_web = load("demo_web")
demo = load("demo")
CONFIG = load_config()
RESET = "/api/v1/demo/reset"


@pytest.fixture
def demo_app(hmis) -> Web:
    intake = Intake(hmis, parser=demo_parser(CONFIG, RuleStubParser(CONFIG)))
    intake.service.config = with_web_reset(intake.config, True)
    return Web(intake, sealer=Sealer([private_key()]), hmis_admin=hmis)


class FakeDevice:
    """Stands in for the browser: the note goes through the API when the connection returns."""

    def __init__(self, client):
        self.client, self.calls, self.note, self.after_reset_calls = client, [], None, 0

    def go_offline(self):
        self.calls.append("offline")

    def write(self, note):
        self.calls.append("write")
        self.note = note

    def go_online(self):
        self.calls.append("online")
        self.client.post("/api/v1/notes/new-client", json={"text": self.note, "title": "Offline note"})

    def confirm(self, ref):
        self.calls.append("confirm")
        self.client.post(f"/api/v1/drafts/{ref}/confirm", json={"version": 1})

    def after_reset(self):
        self.after_reset_calls += 1
        return "Device: test."


def walk(web: Web, typed=(), *, toggle=None, skip_duplicate=True):
    said, shown, pauses = [], [], []
    keys = list(typed)

    def pause():
        pauses.append(1)
        return keys.pop(0) if keys else ""

    device = FakeDevice(web.as_user("j.alvarez"))
    w = demo_web.WebWalkthrough(sign_in=web.as_user, scenarios=load_scenarios(CONFIG), today=SEED_TODAY, device=device, say=said.append,
                                show=shown.append, pause=pause, skip_duplicate=skip_duplicate, toggle_server=toggle, sleep=lambda s: None, poll_seconds=1)
    refs = w.run()
    return w, refs, "\n".join(said), shown, pauses, device


# Every scenario


def test_a_clean_note_is_entered(demo_app):
    _, refs, text, _, _, _ = walk(demo_app)
    d = demo_app.intake.draft(refs["A"])
    assert d.state == "submitted" and d.entry.client_id and d.entry.enrollment_id and d.entry.ce_enrollment_id
    assert f"Client ID: {d.entry.client_id}" in text


def test_b_shows_the_labeled_parser_error_and_is_corrected(demo_app):
    _, refs, text, _, _, _ = walk(demo_app)
    d = demo_app.intake.draft(refs["B"])
    assert d.state == "submitted" and d.version == 2
    assert "Scripted demo example" in text and "not a live model result" in text
    assert "Veteran status" in text and "refused" in text


def test_c_adds_a_case_note_and_service_to_a_clients_client(demo_app):
    _, refs, _, _, _, _ = walk(demo_app)
    a, c = demo_app.intake.draft(refs["A"]), demo_app.intake.draft(refs["C"])
    assert (c.kind, c.state, c.client_id) == ("update", "submitted", a.entry.client_id)
    assert c.entry.case_note_id and c.entry.service_id


def test_d1_same_client(demo_app):
    _, refs, _, _, _, _ = walk(demo_app)
    d = demo_app.intake.draft(refs["D1"])
    assert (d.kind, d.client_id, d.state, d.verification.decision) == ("update", "HMIS-C-000113", "submitted", "same_client")


def test_d2_different_person(demo_app):
    _, refs, _, _, _, _ = walk(demo_app)
    d = demo_app.intake.draft(refs["D2"])
    assert (d.kind, d.state, d.verification.decision) == ("new_client", "submitted", "different_person")


@pytest.mark.parametrize("sid", ["E1", "E2a", "E2b", "E3"])
def test_the_four_queries_are_answered_and_audited(demo_app, sid):
    _, refs, _, _, _, _ = walk(demo_app)
    assert refs[sid].startswith("QRY-") and demo_app.intake.store.audit_events(refs[sid])[0]["event"] == "query"


def test_the_watchlist_says_60_days(demo_app):
    _, _, text, _, _, _ = walk(demo_app)
    assert "60 days" in text


def test_query_results_show_no_date_of_birth_or_digits(demo_app):
    _, _, text, _, _, _ = walk(demo_app)
    assert "6/12/1979" not in text


def test_f_goes_offline_writes_comes_back_and_confirms_in_order(demo_app):
    _, refs, text, _, _, device = walk(demo_app)
    assert device.calls == ["offline", "write", "online", "confirm"]
    assert demo_app.intake.draft(refs["F"]).state == "submitted"
    for phrase in ("Saved on device", "In review", "Entered in HMIS"):
        assert phrase in text


def test_every_step_is_numbered_and_paused_on(demo_app):
    w, _, text, _, pauses, _ = walk(demo_app)
    assert len(pauses) == w.step and f"Step {w.step}." in text and "Step 1." in text


def test_screens_are_the_web_app(demo_app):
    _, _, _, shown, _, _ = walk(demo_app)
    assert shown and all(page.startswith("/app/") for page in shown)


def test_each_scenario_is_announced(demo_app):
    _, _, text, _, _, _ = walk(demo_app)
    for name in ("SCENARIO A", "SCENARIO B", "SCENARIO C", "SCENARIO D", "SCENARIO E", "SCENARIO F"):
        assert name in text


# What the presenter is told


def test_the_script_gives_the_exact_devtools_clicks():
    text = "\n".join(demo_web.OFFLINE_WAYS)
    for phrase in ("F12", "Network", "No throttling", "Offline"):
        assert phrase in text


def test_the_script_says_how_to_come_back():
    text = "\n".join(demo_web.ONLINE_WAYS)
    assert "No throttling" in text and "K" in text


def test_the_script_says_which_way_to_prefer_on_windows():
    text = "\n".join(demo_web.OFFLINE_WAYS)
    assert "Windows" in text and "Prefer" in text and "Wi-Fi" in text


def test_the_presenter_gets_the_note_to_paste():
    assert "Searched HMIS first" in demo_web.F_NOTE and "Placeholder" not in demo_web.F_NOTE


# Keys


def test_r_resets_and_starts_over(demo_app):
    w, refs, text, _, _, _ = walk(demo_app, typed=["", "r"])
    assert w.resets == 1 and demo_app.intake.draft(refs["A"]).state == "submitted" and refs["A"].endswith("-0001")


def test_a_reset_says_what_it_cleared(demo_app):
    _, _, text, _, _, device = walk(demo_app, typed=["r"])
    assert device.after_reset_calls == 1
    for phrase in ("mock HMIS", "drafts", "audit", "Device: test."):
        assert phrase in text


def test_s_skips_the_duplicate_step(demo_app):
    w, _, text, _, _, _ = walk(demo_app, typed=["", "s"], skip_duplicate=False)
    assert "Optional:" not in text


def test_the_duplicate_step_runs_without_s(demo_app):
    _, _, text, _, _, _ = walk(demo_app, skip_duplicate=False)
    assert "Optional:" in text and "same-name check" in text


def test_s_skips_scenario_f(demo_app):
    plain, _, _, _, _, _ = walk(demo_app)
    stop_at = plain.f_intro_step
    demo_app.intake.service.store.reset()
    demo_app.intake.hmis.post("/_admin/reset")
    typed = [""] * (stop_at - 1) + ["s"]
    _, refs, text, _, _, device = walk(demo_app, typed=typed)
    assert "F" not in refs and device.calls == [] and "Scenario F skipped" in text


def test_k_stops_or_starts_the_server_and_does_not_advance(demo_app):
    toggles = []

    def toggle():
        toggles.append(1)
        return "App server stopped."

    w, _, text, _, pauses, _ = walk(demo_app, typed=["k", "k"], toggle=toggle)
    assert len(toggles) == 2 and "App server stopped." in text and len(pauses) == w.step + 2


def test_k_without_a_server_says_so(demo_app):
    _, _, text, _, _, _ = walk(demo_app, typed=["k"])
    assert "not available" in text


# The seal key and passwords


GOOD = {SEAL_KEYS_ENV: "x", "DEMO_PASSWORD_J_ALVAREZ": "y", "DEMO_PASSWORD_STAFF": "z"}


def test_a_complete_environment_passes():
    assert demo_web.missing_setup(GOOD) is None


@pytest.mark.parametrize("value", [None, "", "  "])
def test_a_missing_seal_key_says_to_run_the_script(value):
    env = {**GOOD}
    env.pop(SEAL_KEYS_ENV)
    if value is not None:
        env[SEAL_KEYS_ENV] = value
    message = demo_web.missing_setup(env)
    assert "python scripts/make_seal_key.py" in message and "temporary" in message


def test_a_missing_password_names_the_variable_only():
    env = {**GOOD}
    env.pop("DEMO_PASSWORD_STAFF")
    message = demo_web.missing_setup(env)
    assert "DEMO_PASSWORD_STAFF" in message and "z" not in message.replace("DEMO_PASSWORD_STAFF", "").replace("synthetic", "")


def test_the_setup_check_never_echoes_a_value():
    secret = "ZZSECRETVALUE"
    env = {SEAL_KEYS_ENV: secret, "DEMO_PASSWORD_J_ALVAREZ": secret}
    assert secret not in demo_web.missing_setup(env)


def test_the_demo_refuses_to_start_without_a_key(monkeypatch, capsys):
    monkeypatch.setattr(demo_web, "environment", lambda: {})
    monkeypatch.setattr(sys, "argv", ["demo.py", "--no-browser"])
    with pytest.raises(SystemExit) as stopped:
        demo.main()
    assert "python scripts/make_seal_key.py" in str(stopped.value)


# Which demo runs


def test_the_web_flow_is_the_default():
    args = demo.parser().parse_args([])
    assert args.email_channel is False


def test_the_email_demo_stays_runnable():
    assert demo.parser().parse_args(["--email-channel"]).email_channel is True


# The reset route


def test_the_reset_needs_the_flag(web):
    c = web.as_user("j.alvarez")
    assert c.post(RESET, json={"confirm": "reset demo"}).status_code == 404
    assert "x-demo-epoch" not in web.client.get("/api/v1/ping").headers


def test_the_reset_needs_a_session_and_the_token(demo_app):
    assert demo_app.client.post(RESET, json={"confirm": "reset demo"}).status_code == 401
    c = demo_app.as_user("j.alvarez")
    del c.headers["X-CSRF-Token"]
    assert c.post(RESET, json={"confirm": "reset demo"}).status_code == 403


@pytest.mark.parametrize("body", [{"confirm": ""}, {"confirm": "yes"}])
def test_the_reset_needs_the_phrase(demo_app, body):
    c = demo_app.as_user("j.alvarez")
    c.post("/api/v1/notes/new-client", json={"text": NOTE})
    assert c.post(RESET, json=body).status_code == 422 and demo_app.intake.store.drafts() != []


def test_the_reset_clears_the_server_and_changes_the_epoch(demo_app):
    c = demo_app.as_user("j.alvarez")
    c.post("/api/v1/notes/new-client", json={"text": NOTE})
    before = demo_app.client.get("/api/v1/ping").headers["x-demo-epoch"]
    r = c.post(RESET, json={"confirm": "reset demo"})
    assert r.status_code == 200 and demo_app.intake.store.drafts() == []
    assert demo_app.client.get("/api/v1/ping").headers["x-demo-epoch"] != before
    assert set(r.json()) >= {"hmis", "staging_store", "device"}
    assert c.get("/api/v1/session").status_code == 200  # the presenter stays signed in


def test_the_epoch_is_stable_without_a_reset(demo_app):
    first = demo_app.client.get("/api/v1/ping").headers["x-demo-epoch"]
    assert demo_app.client.get("/api/v1/ping").headers["x-demo-epoch"] == first and int(first) > 0


def test_the_reset_refuses_a_real_hmis(hmis):
    from .test_config import _edit  # noqa: F401  (the same guard as the email demo's reset)

    intake = Intake(hmis)
    settings = intake.config.settings.model_copy(update={"hmis_base_url": "https://hmis.example.org"})
    intake.service.config = with_web_reset(intake.config.model_copy(update={"settings": settings}), True)
    web = Web(intake, sealer=Sealer([private_key()]), hmis_admin=hmis)
    c = web.as_user("j.alvarez")
    c.post("/api/v1/notes/new-client", json={"text": NOTE})
    assert c.post(RESET, json={"confirm": "reset demo"}).status_code == 409 and intake.store.drafts() != []


def test_the_reset_flag_is_off_by_default():
    assert CONFIG.settings.demo.web_reset is False


# Real runs: real Chrome, real servers


def real_env() -> dict:
    passwords = {name: secrets.token_urlsafe(18) for name in PASSWORD_VARS}
    return {**os.environ, **passwords, SEAL_KEYS_ENV: seal_key(), "PYTHONUTF8": "1"}, passwords


def ports_free() -> bool:
    import socket

    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", 8765)) != 0


@pytest.fixture(scope="module", params=["server", "devtools"])
def real_run(request):
    if not ports_free():
        pytest.skip("port 8765 is in use")
    env, passwords = real_env()
    run = subprocess.run([sys.executable, str(SCRIPTS / "demo.py"), "--auto", "0", "--no-browser", "--exit", "--port", str(free_port()),
                          "--browser", chrome(), "--offline-method", request.param], capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=env, cwd=str(SCRIPTS), timeout=280, check=False)
    node()  # the run needs it; skips if missing
    return run, passwords


def test_the_real_demo_runs_to_the_end(real_run):
    run, _ = real_run
    assert run.returncode == 0, (run.stdout[-1500:], run.stderr[-1500:])
    assert "Done." in run.stdout and "SCENARIO F" in run.stdout


def test_the_real_offline_note_is_saved_uploaded_and_entered(real_run):
    out = real_run[0].stdout
    for phrase in ("The device shows: Saved on device", "The device shows: Uploaded", "In review", "Entered in HMIS"):
        assert phrase in out, phrase


def test_the_real_run_prints_no_password_or_key(real_run):
    run, passwords = real_run
    text = run.stdout + run.stderr
    assert not [p for p in passwords.values() if p in text] and seal_key() not in text


def test_the_real_demo_leaves_the_ports_free(real_run):
    assert ports_free()


def test_the_email_demo_still_runs():
    if not ports_free():
        pytest.skip("port 8765 is in use")
    run = subprocess.run([sys.executable, str(SCRIPTS / "demo.py"), "--email-channel", "--auto", "0", "--no-browser", "--exit", "--port", str(free_port())],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(SCRIPTS), timeout=200, check=False)
    assert run.returncode == 0, run.stdout[-1500:]
    assert sum(1 for line in run.stdout.splitlines() if line.startswith("Step")) == 20
