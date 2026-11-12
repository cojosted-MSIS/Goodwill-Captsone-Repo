"""The web demo's walkthrough (add-web-application, Stage 4e), run by scripts/demo.py.

Scenarios A to E are driven through the same /api/v1 routes the app uses, as the signed-in
synthetic worker, and each step opens the matching screen of the real web app. Scenario F (offline
capture) is the real thing: the presenter, or with --auto a real Chrome window, goes offline,
writes a note, and sees it saved, uploaded, reviewed, and confirmed.

The terminal shows titles, draft IDs and HMIS IDs. The one note it prints is Scenario F's
synthetic note, for the presenter to paste. Never a password or a key. Synthetic data only.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from app.sealing import SEAL_KEYS_ENV
from parser.factory import load_env

ROOT = Path(__file__).resolve().parent.parent
WORKER = "j.alvarez"
STAFF = "outreach.staff"
REQUIRED_PASSWORDS = ("DEMO_PASSWORD_J_ALVAREZ", "DEMO_PASSWORD_STAFF")
PASSWORD_OF = {WORKER: "DEMO_PASSWORD_J_ALVAREZ", STAFF: "DEMO_PASSWORD_STAFF"}

F_NOTE = ("Met Noor Example, DOB 3/3/1991, NW quadrant around 10:15am. Searched HMIS first, no match. Slept outside last night. "
          "Has been staying outside for over a year. Been on the street about 3 times in the last 3 years, around 14 months total. "
          "Started being homeless this time on 8/15/2025. Male, white, not Hispanic. Has a disabling condition (bad back). Not a veteran. "
          "SSN ends 7302. Enroll in street outreach, CE region 7. Single adult. Gave water and a hygiene kit. Follow up Thursday.")

OFFLINE_WAYS = [
    "Two ways to go offline. Do one of them:",
    "  1. Chrome DevTools: click in the Outreach notes tab and press F12 (or Ctrl+Shift+I). In the panel, click the Network tab.",
    "     In the toolbar under the tabs, click the dropdown that says No throttling, and choose Offline.",
    "     A warning triangle appears on the Network tab. Keep the panel open until you turn the network back on.",
    "  2. Press K here, then Enter: the script really stops the app server.",
    "     Then click My notes in the app, so it checks the connection right away.",
    "Which to prefer on a Windows laptop: Prefer way 1 for a live audience. Chrome tells the app the moment it changes, so the status",
    "line turns to Offline and the upload starts with no waiting. Use way 2 if the DevTools panel gets in the way on a small screen or",
    "someone asks for proof: nothing is left to answer the app. The app only notices on its next check, so click My notes to hurry it.",
    "Do not use Airplane mode or turn off Wi-Fi: the app runs on this laptop at 127.0.0.1, so the browser would still reach it.",
]

ONLINE_WAYS = [
    "Turn the network back on, the same way you turned it off:",
    "  1. Chrome DevTools: in the Network tab, click the dropdown that now says Offline, and choose No throttling.",
    "  2. Or press K here, then Enter, to start the app server again. Then click My notes in the app.",
    "Do not touch the note. It uploads by itself.",
]


def environment() -> Mapping[str, str]:
    """The environment with .env loaded. Values are only checked for being set, never shown."""
    load_env()
    return os.environ


def missing_setup(env: Mapping[str, str]) -> str | None:
    """What the web demo still needs, by variable name only, or None."""
    problems = []
    if not env.get(SEAL_KEYS_ENV, "").strip():
        problems.append(f"No sealing key is set ({SEAL_KEYS_ENV} in .env). Run this, then start the demo again:\n"
                        "    python scripts/make_seal_key.py\n"
                        "Without it the server would use a temporary key, and a note saved on the device could not be opened "
                        "after a server restart, which is what Scenario F does.")
    absent = [name for name in REQUIRED_PASSWORDS if not env.get(name, "").strip()]
    if absent:
        problems.append("Set your own demo passwords in .env for: " + ", ".join(absent) + ". See .env.example.")
    return "\n\n".join(problems) or None


class Restart(Exception):
    """The presenter pressed R: reset the demo and start again."""


class Device(Protocol):
    """Who does Scenario F in the browser: the presenter, or a real Chrome window with --auto."""

    def go_offline(self) -> None: ...
    def write(self, note: str) -> None: ...
    def go_online(self) -> None: ...
    def confirm(self, ref: str) -> None: ...
    def after_reset(self) -> str: ...


class PresenterDevice:
    """The presenter does the clicking; the script only explains and checks with the server."""

    def go_offline(self) -> None:
        return None

    def write(self, note: str) -> None:
        return None

    def go_online(self) -> None:
        return None

    def confirm(self, ref: str) -> None:
        return None

    def after_reset(self) -> str:
        return ("Device: the open app clears itself at its next check: saved notes, notices, the cached public key and rules, the worker "
                "profile, and any unfinished sign-out. Reload the page to do it now; the page says what it cleared. The app's own files stay; they hold nothing personal.")


class HeadlessDevice:
    """A real Chrome window, driven through scripts/demo_device.mjs, for --auto."""

    def __init__(self, node: str, plan: dict, say: Callable[[str], None], servers: Any, method: str) -> None:
        self.say, self.servers, self.method = say, servers, method
        self.proc = subprocess.Popen([node, str(ROOT / "scripts" / "demo_device.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, encoding="utf-8", cwd=ROOT)
        self.ask({"cmd": "start", **plan})

    def ask(self, command: dict) -> dict:
        self.proc.stdin.write(json.dumps(command) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("the browser stopped")
        answer = json.loads(line)
        if answer.get("error"):
            raise RuntimeError(f"the browser step {command['cmd']} failed: {answer['error']}")
        return answer

    def go_offline(self) -> None:
        if self.method == "server":
            self.servers.stop_app()
            self.ask({"cmd": "reload_offline"})
        else:
            self.ask({"cmd": "network", "offline": True})
        self.say(f"   The device shows: {self.ask({'cmd': 'pill'})['pill']}")

    def write(self, note: str) -> None:
        answer = self.ask({"cmd": "write", "note": note})
        self.say(f"   The device shows: {answer['status']}, {answer['time']}")

    def go_online(self) -> None:
        if self.method == "server":
            self.servers.start_app()
            self.ask({"cmd": "nudge"})
        else:
            self.ask({"cmd": "network", "offline": False})
        self.say(f"   The device shows: {self.ask({'cmd': 'wait_uploaded'})['status']}")

    def confirm(self, ref: str) -> None:
        self.ask({"cmd": "confirm", "ref": ref})

    def after_reset(self) -> str:
        return f"Device: {self.ask({'cmd': 'after_reset'})['said']}"

    def close(self) -> None:
        try:
            self.ask({"cmd": "close"})
        except (RuntimeError, OSError, ValueError):
            pass
        self.proc.wait(timeout=15)


@dataclass
class WebWalkthrough:
    sign_in: Callable[[str], Any]  # a signed-in, httpx-style client for a username
    scenarios: dict[str, Any]
    today: date
    device: Device
    say: Callable[[str], None] = print
    show: Callable[[str], None] = lambda page: None
    pause: Callable[[], str] = lambda: ""
    skip_duplicate: bool = False
    skip_offline: bool = False
    toggle_server: Callable[[], str] | None = None  # the K key
    ensure_server: Callable[[], None] = lambda: None  # start the app server if K left it stopped
    sleep: Callable[[float], None] = time.sleep
    poll_seconds: float = 90
    refs: dict[str, str] = field(default_factory=dict)
    step: int = 0
    resets: int = 0
    f_intro_step: int = 0

    def __post_init__(self) -> None:
        self.worker = self.sign_in(WORKER)

    # helpers

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        out = self.worker.request(method, path, json=body) if body is not None else self.worker.request(method, path)
        if out.status_code >= 400:
            raise RuntimeError(f"{path} answered {out.status_code}")
        return out.json()

    def _expect(self, outcome: dict, action: str) -> str:
        if outcome["action"] != action:
            raise RuntimeError(f"expected {action!r} but the system answered {outcome['action']!r}")
        return outcome["ref"]

    def _step(self, title: str, lines: list[str], page: str | None) -> str:
        self.step += 1
        self.say("")
        self.say(f"Step {self.step}. {title}")
        for line in lines:
            self.say(f"   {line}")
        if page:
            self.say(f"   Screen: {page}")
            self.show(page)
        while True:
            typed = (self.pause() or "").strip().lower()
            if typed == "k":
                self.say(f"   {self.toggle_server() if self.toggle_server else 'The K key is not available in this run.'}")
                continue
            if typed == "r":
                raise Restart
            return typed

    def reset(self) -> None:
        """Demo only: clear the mock HMIS, the staging store, and the device."""
        self.ensure_server()
        out = self.worker.post("/api/v1/demo/reset", json={"confirm": "reset demo"})
        if out.status_code != 200:
            raise RuntimeError(f"the reset was refused: {out.status_code}")
        body = out.json()
        self.resets += 1
        self.refs.clear()
        self.say("")
        self.say("Demo reset (demo only). Cleared:")
        self.say(f"   HMIS: {body['hmis']}.")
        self.say(f"   Server: {body['staging_store']}.")
        self.say(f"   {self.device.after_reset()}")

    def _draft(self, ref: str) -> dict:
        return self._call("GET", f"/api/v1/drafts/{ref}")

    def _ids(self, ref: str) -> list[str]:
        return [f"{i['label']}: {i['value']}" for i in self._draft(ref)["receipt"]["hmis_ids"]]

    def _note(self, sid: str, route: str = "new-client", client_id: str | None = None) -> tuple[dict, dict]:
        s = self.scenarios[sid].public(self.today, client_id)
        return s, self._call("POST", f"/api/v1/notes/{route}", {"text": s["body"], "title": s["subject"]})

    def _confirm(self, ref: str, action: str = "submitted") -> None:
        self._expect(self._call("POST", f"/api/v1/drafts/{ref}/confirm", {"version": self._draft(ref)["version"]}), action)

    # the walk-through

    def run(self) -> dict[str, str]:
        while True:
            try:
                return self._run_once()
            except Restart:
                self.reset()
                self.step = 0

    def _run_once(self) -> dict[str, str]:
        self._scenario_a()
        self._scenario_b()
        self._scenario_c()
        self._scenario_d()
        self._scenario_e()
        if not self.skip_offline:
            self._scenario_f()
        return self.refs

    def _scenario_a(self) -> None:
        self.say("SCENARIO A: a new neighbor, with a complete note")
        s, out = self._note("A")
        ref = self.refs["A"] = self._expect(out, "drafted")
        r = self._draft(ref)["review"]
        self._step("The worker writes a note; the system drafts the record for review", [
            f"Draft {ref} ({s['subject']}), parsed by {r['parser']}.",
            "Each answer shows its value, the words it came from, and how sure the note was.",
            "Nothing has been sent to HMIS. Every required answer is present, so Confirm is enabled.",
        ], f"/app/#/drafts/{ref}")
        self._confirm(ref)
        typed = self._step("The worker presses Confirm; the system enters the record in the mock HMIS", [
            "Entered in order: client, program enrollment, Coordinated Entry enrollment.",
            *self._ids(ref),
            "The system wrote only through entry operations, after Confirm.",
            *([] if self.skip_duplicate else ["(Next: the duplicate step. Type S to skip it.)"]),
        ], f"/app/#/drafts/{ref}")
        if not self.skip_duplicate and typed != "s":
            self._duplicate()

    def _duplicate(self) -> None:
        s, out = self._note("A")
        ref = self.refs["A again"] = self._expect(out, "drafted")
        self._expect(self._call("POST", f"/api/v1/drafts/{ref}/confirm", {"version": 1}), "verification")
        self._step("Optional: the same note written again is caught by the same-name check", [
            f"Draft {ref} has the same name and date of birth as the client just entered, so the worker sees a verification screen",
            "instead of the review. Confirm is refused until the worker says same person or different person. Nothing was sent to HMIS.",
        ], f"/app/#/drafts/{ref}")

    def _scenario_b(self) -> None:
        self.say("")
        self.say("SCENARIO B: a deliberate parser error and a missing answer, caught by the worker")
        s, out = self._note("B")
        ref = self.refs["B"] = self._expect(out, "drafted")
        r = self._draft(ref)["review"]
        self._step("A note the parser gets wrong, labeled on screen", [
            f"Draft {ref} ({s['subject']}).",
            f"On screen: {r['scripted_label']}",
            f"Missing before entry: {', '.join(r['missing'])}. Confirm is disabled until it is given.",
        ], f"/app/#/drafts/{ref}")
        self._confirm(ref, "still_missing")
        self._step("Confirm anyway is refused", ["The server holds the draft and says what is still needed. Nothing is entered."], f"/app/#/drafts/{ref}")
        reply = s["suggested_reply"]
        self._expect(self._call("POST", f"/api/v1/drafts/{ref}/corrections", {"text": reply}), "revised")
        self._step("The worker corrects the draft in plain words", [
            f"Correction: \"{reply}\"", "Version 2 shows both answers as from the worker's correction.",
        ], f"/app/#/drafts/{ref}")
        self._confirm(ref)
        self._step("The worker confirms version 2; the record is entered", self._ids(ref), f"/app/#/drafts/{ref}")
        events = self.sign_in(STAFF).get(f"/api/v1/staff/drafts/{ref}/audit").json()["events"]
        self._step("The audit trail", [
            f"{len(events)} events: who confirmed and when, each version, the corrected fields, and each HMIS step. Never the note text.",
            "To see it, sign in as outreach.staff and open this draft.",
        ], "/app/#/drafts")

    def _scenario_c(self) -> None:
        self.say("")
        self.say("SCENARIO C: a second visit to the neighbor from Scenario A")
        client = next(i["value"] for i in self._draft(self.refs["A"])["receipt"]["hmis_ids"] if i["value"].startswith("HMIS-C-"))
        self.say(f"   Uses client {client} from Scenario A's receipt.")
        _, out = self._note("C", "update", client)
        ref = self.refs["C"] = self._expect(out, "drafted")
        self._step("A visit note for a client already in HMIS", [
            f"Draft {ref}: an update for client {client}, checked through the read-only lookup.",
            "One visit's case note and service entry, each answer from the note.",
        ], f"/app/#/drafts/{ref}")
        self._confirm(ref)
        self._step("Confirm adds the case note and the service entry", [*self._ids(ref), "Earlier entries are not changed."], f"/app/#/drafts/{ref}")

    def _verification(self, sid: str, title: str) -> str:
        _, out = self._note(sid)
        ref = self.refs[sid] = self._expect(out, "drafted")
        v = self._draft(ref)["verification"]
        self._step(title, [
            f"Draft {ref}: HMIS already has {len(v['candidates'])} clients with this name and date of birth.",
            *[f"{c['client_id']} {c['label']}: {c['grade_text']}" + (" Recommended." if c["recommended"] else "") for c in v["candidates"]],
            "The verification screen comes instead of the review. Confirm is refused until the worker answers.",
        ], f"/app/#/drafts/{ref}")
        return ref

    def _scenario_d(self) -> None:
        self.say("")
        self.say("SCENARIO D: the same name and date of birth already in HMIS, two outcomes")
        ref = self._verification("D1", "D1. Robin Demo: the SSN digits match, so Same person is recommended")
        client = self.scenarios["D1"].suggested_reply.split()[-1]
        self._expect(self._call("POST", f"/api/v1/drafts/{ref}/same-client", {"client_id": client}), "verified_same")
        self._step("The worker chooses Same person; the note becomes a visit for that client", [
            f"Client {client}. No new client is created. Other answers are listed to update in HMIS directly, never written.",
        ], f"/app/#/drafts/{ref}")
        self._confirm(ref)
        self._step("Confirm adds a case note and a service entry to the existing client", self._ids(ref), f"/app/#/drafts/{ref}")

        ref = self._verification("D2", "D2. Sam Example: the SSN digits are different, a warning")
        reason = self.scenarios["D2"].suggested_reply.split(":", 1)[1].strip()
        self._expect(self._call("POST", f"/api/v1/drafts/{ref}/different-person", {"reason": reason}), "verified_different")
        self._confirm(ref)
        self._step("Different person with a reason, then Confirm: entered as a new client, confirmed distinct", [
            f"Reason: \"{reason}\"", *self._ids(ref), "HMIS got the confirmed-distinct override with the reason.",
        ], f"/app/#/drafts/{ref}")

    def _ask(self, sid: str, kind: str, body: dict) -> dict:
        out = self._call("POST", f"/api/v1/queries/{kind}", body)
        self.refs[sid] = self._expect(out, "query_answered")
        return out["result"]

    def _scenario_e(self) -> None:
        self.say("")
        self.say("SCENARIO E: the four read-only questions, as fixed forms")
        client = next(i["value"] for i in self._draft(self.refs["A"])["receipt"]["hmis_ids"] if i["value"].startswith("HMIS-C-"))
        result = self._ask("E1", "briefing", {"quadrant": "SW"})
        listed = client in json.dumps(result)
        self._step("E1. A pre-visit briefing for the SW quadrant", [
            result["summary"], f"Scenario A's client {client} is {'listed' if listed else 'not listed'}.",
            "Minimal data only: client ID, first name and last initial, last contact, and open items. Nothing in HMIS changed.",
        ], "/app/#/queries/briefing")
        result = self._ask("E2a", "lookup", {"client_id": "HMIS-C-000101"})
        self._step("E2. A neighbor lookup by client ID", [result["summary"], "A record the worker cannot see is answered as if it does not exist."], "/app/#/queries/lookup")
        result = self._ask("E2b", "status", {"client_id": "HMIS-C-000101", "status_type": "id_document"})
        self._step("E2. A status check: has this client's ID come in?", [result["summary"], "A fixed form: no free text, and the model never writes SQL."], "/app/#/queries/status")
        result = self._ask("E3", "no-contact", {})
        options = self._call("GET", "/api/v1/queries/options")
        self._step(f"E3. The {options['no_contact_days']}-day no-contact watchlist", [
            result["summary"], f"Who is past or coming up on {options['no_contact_days']} days with no contact. Active enrollments only, most overdue first.",
        ], "/app/#/queries/no-contact")
        log = self.sign_in(STAFF).get("/api/v1/staff/queries").json()
        self._step("Staff view: every query in the audit", [
            f"{len(log)} queries: type, parameters (a name or date of birth only as \"given\"), and row counts. Never the returned values.",
            "To see it, sign in as outreach.staff and open Query log.",
        ], "/app/#/queries")

    def _new_ref(self, known: set[str]) -> str | None:
        return next((d["id"] for d in self._call("GET", "/api/v1/drafts") if d["id"] not in known), None)

    def _wait_for_upload(self, known: set[str]) -> str:
        """The app uploads by itself; the script only watches the server for the new draft."""
        self.ensure_server()
        waited = 0.0
        while True:
            ref = self._new_ref(known)
            if ref:
                return ref
            if waited >= self.poll_seconds:
                self._step("The note has not arrived yet", [
                    "Check that the network is back on (DevTools: No throttling), and click My notes in the app.",
                    "Press Enter to look again.",
                ], None)
                waited = 0.0
            self.sleep(1)
            waited += 1

    def _scenario_f(self) -> None:
        self.say("")
        self.say("SCENARIO F: offline capture")
        typed = self._step("Get ready: the app in your browser, on My notes", [
            "You can write notes with no connection. You review and confirm them when you are back online.",
            "Sign in as j.alvarez with the password you set in .env, if you have not already. Stay on this one tab from here on.",
            "Type S to skip this scenario.",
        ], "/app/#/")
        self.f_intro_step = self.step
        if typed == "s":
            self.say("Scenario F skipped.")
            return
        known = {d["id"] for d in self._call("GET", "/api/v1/drafts")}

        self._step("Turn the network off", OFFLINE_WAYS, None)
        self.device.go_offline()
        self._step("Write a note", [
            "The status line at the top says Offline, and the app says: You can write notes now.",
            "Click New note. Paste this into Your note, then press Save on this device:",
            "", F_NOTE, "",
        ], None)
        self.device.write(F_NOTE)
        self._step("See \"Saved on device\"", [
            "My notes shows \"Note saved\", the time, and the status Saved on device. Never the note's words: this device cannot read them back.",
            "The note is sealed with the server's key, and only the server can open it.",
        ], None)
        self._step("Turn the network back on", ONLINE_WAYS, None)
        self.device.go_online()
        ref = self.refs["F"] = self._wait_for_upload(known)
        self._step("Watch it upload and appear as In review", [
            f"The status moved from Saved on device to Uploading to Uploaded. The server made draft {ref}.",
            f"Status now: {self._draft(ref)['status_label']}. It appears under Recent on My notes. Nothing is in HMIS yet.",
            "Next: click it, read the draft, and press Confirm and enter in HMIS.",
        ], None)
        self.device.confirm(ref)
        while self._draft(ref)["state"] != "submitted":
            self._step("Not confirmed yet", ["In the app, open the draft and press Confirm and enter in HMIS. Then press Enter here."], None)
            self.device.confirm(ref)
        self._step("Reviewed and confirmed online: Entered in HMIS", [
            *self._ids(ref), "Review and Confirm always need a connection. Nothing reaches HMIS without the worker's Confirm.",
        ], None)
