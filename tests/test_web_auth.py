"""add-web-application, Stage 2b: sign-in, sessions, CSRF, lockout, and the sign-in audit.

Specs: openspec/changes/add-web-application/specs/web-application/spec.md ("Sign in with a role",
"Protect sessions"). The demo accounts are synthetic. Their passwords are made at random for
each test (tests/conftest.py, Web), so no password is written anywhere in the repository.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.auth import SESSION_COOKIE, hash_password, verify_password

from .conftest import Web

GENERIC_FAILURE = "Sign-in failed. Check your username and password."
GENERIC_LOCKED = "Too many sign-in attempts. Please wait and try again later."


def set_cookie(response) -> str:
    return "; ".join(response.headers.get_list("set-cookie"))


def all_audit_text(web: Web) -> str:
    rows = web.intake.store._db.execute("SELECT ref, event, actor, details FROM audit").fetchall()
    return json.dumps(rows)


# Passwords: salted hashes only


def test_passwords_are_kept_only_as_salted_scrypt_hashes():
    first, second = hash_password("synthetic-example"), hash_password("synthetic-example")
    assert first != second  # a new random salt each time
    assert first.startswith("scrypt$") and "synthetic-example" not in first
    assert verify_password("synthetic-example", first) and not verify_password("synthetic-examplf", first)
    assert not verify_password("synthetic-example", "not a hash")


def test_the_directory_keeps_no_plain_password(web):
    kept = repr(vars(web.users))
    assert not any(p in kept for p in web.passwords.values())


def test_an_account_without_a_password_in_the_environment_cannot_sign_in(intake):
    web = Web(intake, env={})
    assert sorted(web.users.missing) == sorted(a.password_env for a in intake.config.users.accounts)
    r = web.sign_in("j.alvarez", password="anything")
    assert r.status_code == 401 and r.json()["detail"] == GENERIC_FAILURE


# Sign-in and the session cookie


def test_sign_in_starts_a_server_side_session(web):
    r = web.sign_in("j.alvarez")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "j.alvarez" and body["role"] == "worker"
    assert body["project"] == "horizon_house_outreach" and body["csrf_token"]
    cookie = set_cookie(r)
    assert f"{SESSION_COOKIE}=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie.replace("Strict", "strict")
    assert "Path=/" in cookie and "Secure" not in cookie  # plain http in the local demo
    token = web.client.cookies.get(SESSION_COOKIE)
    assert token and token not in r.text  # the session token is only in the cookie
    stored = web.intake.store._db.execute("SELECT token_hash, username FROM sessions").fetchall()
    assert len(stored) == 1 and stored[0][1] == "j.alvarez" and token not in stored[0][0]
    assert web.client.get("/api/v1/session").json()["username"] == "j.alvarez"


def test_the_cookie_is_secure_over_https(intake):
    web = Web(intake, base_url="https://testserver")
    r = web.sign_in("j.alvarez")
    assert r.status_code == 200 and "Secure" in set_cookie(r)


def test_a_session_id_chosen_before_sign_in_is_never_used(web):
    web.client.cookies.set(SESSION_COOKIE, "chosen-by-someone-else", domain="testserver.local")
    web.sign_in("j.alvarez")
    assert web.client.cookies.get(SESSION_COOKIE) != "chosen-by-someone-else"


def test_wrong_password_and_unknown_username_get_the_same_answer(web):
    wrong = web.sign_in("j.alvarez", password="not-the-password")
    unknown = web.sign_in("no.such.person", password="not-the-password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": GENERIC_FAILURE}
    assert SESSION_COOKIE not in set_cookie(wrong)


def test_a_validation_error_never_echoes_the_password(web):
    pre = web.client.get("/api/v1/auth/csrf").json()["csrf_token"]
    r = web.client.post("/api/v1/auth/sign-in", json={"password": "echo-me-not-123"}, headers={"X-CSRF-Token": pre})
    assert r.status_code == 422 and "echo-me-not-123" not in r.text


# CSRF on sign-in and sign-out


@pytest.mark.parametrize("header", [None, "wrong-token"])
def test_sign_in_needs_the_csrf_token(web, header):
    web.client.get("/api/v1/auth/csrf")
    headers = {"X-CSRF-Token": header} if header else {}
    r = web.client.post("/api/v1/auth/sign-in", json={"username": "j.alvarez", "password": web.passwords["j.alvarez"]},
                        headers=headers)
    assert r.status_code == 403 and SESSION_COOKIE not in set_cookie(r)


def test_sign_in_csrf_token_without_its_cookie_is_refused(web):
    token = web.new_client().get("/api/v1/auth/csrf").json()["csrf_token"]  # fetched by another browser
    r = web.client.post("/api/v1/auth/sign-in", json={"username": "j.alvarez", "password": web.passwords["j.alvarez"]},
                        headers={"X-CSRF-Token": token})
    assert r.status_code == 403


@pytest.mark.parametrize("header", [None, "wrong-token"])
def test_sign_out_needs_the_csrf_token(web, header):
    web.sign_in("j.alvarez")
    headers = {"X-CSRF-Token": header} if header else {}
    del web.client.headers["X-CSRF-Token"]
    assert web.client.post("/api/v1/auth/sign-out", headers=headers).status_code == 403
    assert web.client.get("/api/v1/session").status_code == 200  # still signed in


# Sign-out and timeouts


def test_sign_out_ends_the_session_on_the_server(web):
    web.sign_in("j.alvarez")
    token = web.client.cookies.get(SESSION_COOKIE)
    r = web.client.post("/api/v1/auth/sign-out")
    assert r.status_code == 200 and SESSION_COOKIE in set_cookie(r) and "Max-Age=0" in set_cookie(r)
    assert web.intake.store._db.execute("SELECT COUNT(username) FROM sessions").fetchone()[0] == 0
    replay = web.new_client()
    replay.cookies.set(SESSION_COOKIE, token)  # the old cookie, kept by someone
    assert replay.get("/api/v1/session").status_code == 401


def test_an_idle_session_expires(web):
    web.sign_in("j.alvarez")
    idle = web.intake.config.settings.web.session_idle_minutes
    web.intake.clock.advance(minutes=idle - 1)
    assert web.client.get("/api/v1/session").status_code == 200  # activity resets the idle timer
    web.intake.clock.advance(minutes=idle - 1)
    assert web.client.get("/api/v1/session").status_code == 200
    web.intake.clock.advance(minutes=idle + 1)
    assert web.client.get("/api/v1/session").status_code == 401
    assert "session_expired" in [e["event"] for e in web.intake.store.audit_events("AUTH")]


def test_a_session_ends_at_the_absolute_limit_even_when_active(web):
    web.sign_in("j.alvarez")
    settings = web.intake.config.settings.web
    step = settings.session_idle_minutes - 1
    elapsed = 0
    while elapsed + step < settings.session_absolute_hours * 60:
        web.intake.clock.advance(minutes=step)
        elapsed += step
        assert web.client.get("/api/v1/session").status_code == 200
    web.intake.clock.advance(minutes=step)
    assert web.client.get("/api/v1/session").status_code == 401


# Brute force: lockout and rate limit


def test_repeated_failures_lock_the_username_for_a_while(web):
    rules = web.intake.config.settings.web.sign_in
    for _ in range(rules.max_failures):
        assert web.sign_in("j.alvarez", password="guess").status_code == 401
    locked = web.sign_in("j.alvarez")  # even the right password is refused while locked
    assert locked.status_code == 429 and locked.json() == {"detail": GENERIC_LOCKED}
    web.intake.clock.advance(minutes=rules.lockout_minutes + 1)
    assert web.sign_in("j.alvarez").status_code == 200


def test_an_unknown_username_locks_the_same_way(web):
    rules = web.intake.config.settings.web.sign_in
    for _ in range(rules.max_failures):
        assert web.sign_in("no.such.person", password="guess").status_code == 401
    assert web.sign_in("no.such.person", password="guess").json() == {"detail": GENERIC_LOCKED}


def test_failures_spread_out_in_time_do_not_lock(web):
    rules = web.intake.config.settings.web.sign_in
    for _ in range(rules.max_failures + 2):
        assert web.sign_in("j.alvarez", password="guess").status_code == 401
        web.intake.clock.advance(minutes=rules.window_minutes)
    assert web.sign_in("j.alvarez").status_code == 200


def test_too_many_attempts_from_one_client_are_slowed(web):
    rules = web.intake.config.settings.web.sign_in
    for i in range(rules.max_attempts_per_client):
        web.sign_in(f"guess.{i}", password="guess")
    r = web.sign_in("j.alvarez")
    assert r.status_code == 429 and r.json() == {"detail": GENERIC_LOCKED}


# Audit: sign-in events, never a password or a token


def test_sign_in_events_are_audited_without_secrets(web):
    rules = web.intake.config.settings.web.sign_in
    web.sign_in("j.alvarez", password="guess-one")
    web.sign_in("no.such.person", password="guess-two")
    for _ in range(rules.max_failures):
        web.sign_in("m.chen", password="guess-three")
    web.sign_in("m.chen")
    web.sign_in("j.alvarez")
    token, csrf = web.client.cookies.get(SESSION_COOKIE), web.client.headers["X-CSRF-Token"]
    web.client.post("/api/v1/auth/sign-out")

    events = [(e["event"], e["actor"]) for e in web.intake.store.audit_events("AUTH")]
    assert ("sign_in_failed", "j.alvarez") in events
    assert ("sign_in_failed", None) in events  # an unknown username is not recorded
    assert ("sign_in_locked", "m.chen") in events and ("sign_in_refused_locked", "m.chen") in events
    assert ("sign_in", "j.alvarez") in events and ("sign_out", "j.alvarez") in events
    text = all_audit_text(web)
    secrets = [*web.passwords.values(), "guess-one", "guess-two", "guess-three", token, csrf, "no.such.person"]
    assert not [s for s in secrets if s in text]


def test_no_password_or_token_reaches_the_logs(web, caplog):
    caplog.set_level(logging.DEBUG)
    web.sign_in("j.alvarez", password="logged-never-1")
    web.sign_in("j.alvarez")
    token = web.client.cookies.get(SESSION_COOKIE)
    web.client.get("/api/v1/session")
    web.client.post("/api/v1/auth/sign-out")
    for secret in ("logged-never-1", web.passwords["j.alvarez"], token):
        assert secret not in caplog.text
