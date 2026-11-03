"""One-command presentation demo (task 5.3): python scripts/demo.py

Starts a fresh mock HMIS and intake app, opens the phone screens in your browser, and walks
through Scenario A (a clean note confirmed on the first reply), Scenario B (a scripted parser
error and a missing field, caught and corrected by the worker), Scenario C (a second visit to
Scenario A's client: a case note and a service entry), Scenario D (a same-name verification:
once ending SAME CLIENT, once ending DIFFERENT PERSON, and once with two records that may be
duplicates of each other in HMIS), and Scenario E (a read-only
briefing for the SW quadrant that lists Scenario A's client, then a status check). Each step
says what is happening, opens the screen to show, and waits for Enter. When the walk-through ends,
the servers keep running so you can click around; press Ctrl+C to stop.

At each pause: Enter goes on, R resets the demo (mock HMIS and staging store, demo only) and
starts again from the first step, and S at the Scenario A receipt skips the duplicate step.
The duplicate step resends Scenario A's note on purpose to show the same-name check catching
it before review: a verification email, and CONFIRM refused. Nothing is entered.

Options: --auto N advances every N seconds instead of waiting for Enter; --skip-duplicate
leaves out the duplicate step; --no-browser only prints the screens; --exit stops the servers
after the last step; --parser reallms parses Scenario A with REALLMS (needs the key in .env;
Scenario B stays scripted).

Synthetic data only. The terminal shows subjects, draft IDs and HMIS IDs, never note text.
"""

from __future__ import annotations

import argparse
import sys
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from servers import fresh_servers


class Restart(Exception):
    """The presenter pressed R: reset the demo and start again."""


@dataclass
class Walkthrough:
    """Runs the scenario steps against any httpx-style client (the real app or a test client)."""

    client: httpx.Client
    say: Callable[[str], None] = print
    show: Callable[[str], None] = lambda page: None
    pause: Callable[[], str] = lambda: ""  # returns what the presenter typed ("", "r", "s")
    skip_duplicate: bool = False
    refs: dict[str, str] = field(default_factory=dict)
    step: int = 0
    resets: int = 0

    def __post_init__(self) -> None:
        self.scenarios = {s["id"]: s for s in self._get("/demo/scenarios")}
        self.worker = self.scenarios["A"]["sender"]

    # helpers

    def _get(self, path: str):
        out = self.client.get(path)
        out.raise_for_status()
        return out.json()

    def _send(self, subject: str, body: str) -> dict:
        out = self.client.post("/mail/send", json={"sender": self.worker, "subject": subject, "body": body})
        out.raise_for_status()
        return out.json()

    def _newest_review(self) -> dict:
        mail = next(m for m in self._get(f"/mail/inbox/{self.worker}") if m["kind"] == "review")
        return self._get(f"/mail/message/{mail['id']}")

    def _expect(self, outcome: dict, action: str) -> str:
        if outcome["action"] != action:
            raise RuntimeError(f"expected {action!r} but the system answered {outcome['action']!r}")
        return outcome["ref"]

    def _step(self, title: str, lines: list[str], page: str) -> str:
        self.step += 1
        self.say("")
        self.say(f"Step {self.step}. {title}")
        for line in lines:
            self.say(f"   {line}")
        self.say(f"   Screen: {page}")
        self.show(page)
        typed = (self.pause() or "").strip().lower()
        if typed == "r":
            raise Restart
        return typed

    def reset(self) -> None:
        """Demo only: clear the mock HMIS and the staging store through the guarded route."""
        out = self.client.post("/demo/reset", json={"confirm": "reset demo"})
        if out.status_code != 200:
            raise RuntimeError(f"the reset was refused: {out.json().get('detail', out.status_code)}")
        self.resets += 1
        self.refs.clear()
        self.say("")
        self.say("Demo reset (demo only): mock HMIS records, drafts, inbox and audit cleared. IDs start again at 0001.")

    def _ids(self, ref: str) -> list[str]:
        receipt = self._get(f"/drafts/{ref}/receipt")
        return [f"{i['label']}: {i['value']}" for i in receipt["hmis_ids"]]

    # the walk-through

    def _newest(self, kind: str) -> dict:
        mail = next(m for m in self._get(f"/mail/inbox/{self.worker}") if m["kind"] == kind)
        return self._get(f"/mail/message/{mail['id']}")

    def _duplicate(self, a: dict) -> None:
        """Optional step: resend Scenario A's note on purpose; the same-name check catches it before review."""
        ref = self._expect(self._send(a["subject"], a["body"]), "drafted")
        mail = self._newest("verification")
        self._expect(self._send(f"Re: {mail['subject']}", "CONFIRM"), "verification")
        self.refs["A again"] = ref
        self._step("Optional: the same note sent again is caught by the same-name check", [
            f"Draft {ref} has the same name and date of birth as the client just entered, so the worker gets a",
            "verification email instead of a review. CONFIRM is refused until the worker replies SAME CLIENT <ID>",
            "or DIFFERENT PERSON with a reason. Nothing new was sent to HMIS. The draft stays open; the demo goes on.",
        ], f"/ui/#/mail/{mail['id']}")

    def run(self) -> dict[str, str]:
        """The walk-through. R at any pause resets the demo and starts again."""
        while True:
            try:
                return self._run_once()
            except Restart:
                self.reset()
                self.step = 0

    def _run_once(self) -> dict[str, str]:
        a, b = self.scenarios["A"], self.scenarios["B"]

        self.say("SCENARIO A: a clean note, confirmed on the first reply")
        ref_a = self._expect(self._send(a["subject"], a["body"]), "drafted")
        self.refs["A"] = ref_a
        review = self._newest_review()
        r = review["review"]
        self._step("The worker emails a note; the system drafts the record and emails it back", [
            f"Draft {ref_a} ({a['subject']}), parsed by {r['parser']}{' with ' + r['model'] if r['model'] else ''}.",
            "Each field shows its value, the sentence it came from, and where it came from.",
            "Nothing has been sent to HMIS. Every required field is present, so CONFIRM is enabled.",
        ], f"/ui/#/mail/{review['id']}")
        self._step("Behind the scenes: the parser run", [
            "The fixed instructions, the note as received, and the verified output with quotes and confidence.",
        ], f"/ui/staff.html#/run/{ref_a}")
        self._expect(self._send(f"Re: {review['subject']}", "CONFIRM"), "submitted")
        typed = self._step("The worker replies CONFIRM; the system enters the record into the mock HMIS", [
            "Entered in order: client, program enrollment, Coordinated Entry enrollment.",
            *self._ids(ref_a),
            "The system wrote only through entry operations, after CONFIRM.",
            *([] if self.skip_duplicate else ["(Next: the duplicate step. Type S to skip it.)"]),
        ], f"/ui/#/receipt/{ref_a}")
        if not self.skip_duplicate and typed != "s":
            self._duplicate(a)

        self.say("")
        self.say("SCENARIO B: a parser error and a missing field, caught by the worker")
        ref_b = self._expect(self._send(b["subject"], b["body"]), "drafted")
        self.refs["B"] = ref_b
        review = self._newest_review()
        r = review["review"]
        self._step("A note the parser gets wrong (a scripted demo example, not a live model result)", [
            f"Draft {ref_b} ({b['subject']}).",
            "The declined shelter bed was read as where she is staying now: current living situation = Emergency shelter.",
            f"Missing before entry: {', '.join(r['missing'])}. CONFIRM is disabled until it is supplied.",
        ], f"/ui/#/mail/{review['id']}")
        self._expect(self._send(f"Re: {review['subject']}", "CONFIRM"), "still_missing")
        self._step("Typing CONFIRM anyway is refused", [
            "The workflow holds the draft and replies with what is still needed. Nothing is entered.",
        ], "/ui/#/inbox")
        reply = b["suggested_reply"]
        self._expect(self._send(f"Re: {review['subject']}", reply), "revised")
        review = self._newest_review()
        self._step("The worker corrects the draft in plain words", [
            f"Reply: \"{reply}\"",
            "Draft v2: current living situation = Place not meant for habitation, veteran status = No,",
            "both marked as from the worker's reply. The case note is rewritten to match.",
        ], f"/ui/#/mail/{review['id']}")
        self._expect(self._send(f"Re: {review['subject']}", "CONFIRM"), "submitted")
        self._step("The worker confirms version 2; the record is entered", [*self._ids(ref_b)], f"/ui/#/receipt/{ref_b}")
        self._step("The audit trail", [
            "Who confirmed and when, each version, the corrected fields, each HMIS step, and the deletion of the",
            "email copies. The audit record never holds the note text.",
        ], f"/ui/staff.html#/audit/{ref_b}")

        self._scenario_c()
        self._scenario_d()
        self._scenario_e()
        return self.refs

    def _scenario_c(self) -> None:
        c = next(s for s in self._get("/demo/scenarios") if s["id"] == "C")  # filled with Scenario A's client ID
        self.say("")
        self.say("SCENARIO C: a second visit to the neighbor from Scenario A")
        if not c["ready"]:
            raise RuntimeError(c["not_ready"])
        self.say(f"   Uses client {c['client_id']} from Scenario A's receipt.")
        ref = self._expect(self._send(c["subject"], c["body"]), "drafted")
        self.refs["C"] = ref
        review = self._newest_review()
        client = review["review"]["client"]
        self._step("An \"Update:\" note for a client already in HMIS", [
            f"Draft {ref}: update for client {client['id']} ({client['label']}), checked through the read-only lookup.",
            "One visit's case note and service entry: service date, type, quadrant, and time spent, each from the note.",
        ], f"/ui/#/mail/{review['id']}")
        self._expect(self._send(f"Re: {review['subject']}", "CONFIRM"), "submitted")
        self._step("CONFIRM adds the case note and the service entry to that client", [
            *self._ids(ref),
            "The earlier entries are not changed. The service records its quadrant, so briefings list this visit.",
        ], f"/ui/#/receipt/{ref}")

    def _verification(self, sid: str, title: str) -> tuple[str, dict]:
        s = self.scenarios[sid]
        ref = self._expect(self._send(s["subject"], s["body"]), "drafted")
        self.refs[sid] = ref
        mail = self._newest("verification")
        v = mail["verification"]
        self._step(title, [
            f"Draft {ref}: HMIS already has {len(v['candidates'])} clients with this name and date of birth.",
            *([f"Possible duplicates in HMIS: {v['duplicates_notice']}"] if v["duplicates_notice"] else []),
            *[f"{c['client_id']} {c['label']} ({c['record']}): {c['grade_text']}"
              + (" Recommended." if c["recommended"] else "") for c in v["candidates"]],
            "A verification email comes instead of the review. CONFIRM is not offered until the worker answers.",
        ], f"/ui/#/mail/{mail['id']}")
        return ref, mail

    def _scenario_d(self) -> None:
        self.say("")
        self.say("SCENARIO D: the same name and date of birth already in HMIS, two outcomes")
        ref, mail = self._verification("D1", "Robin Demo: the SSN digits match, so SAME CLIENT is recommended")
        reply = self.scenarios["D1"]["suggested_reply"]
        self._expect(self._send(f"Re: {mail['subject']}", reply), "verified_same")
        review = self._newest_review()
        self._step("The worker replies SAME CLIENT; the note becomes an update for that client", [
            f"Reply: \"{reply}\". No new client is created.",
            "Gender, race and other answers are shown as \"update in HMIS yourself\" and never written.",
        ], f"/ui/#/mail/{review['id']}")
        self._expect(self._send(f"Re: {review['subject']}", "CONFIRM"), "submitted")
        self._step("CONFIRM adds a case note and a service entry to the existing client", [*self._ids(ref)],
                   f"/ui/#/receipt/{ref}")

        ref, mail = self._verification("D2", "Sam Example: the SSN digits are different, a warning")
        reply = self.scenarios["D2"]["suggested_reply"]
        self._expect(self._send(f"Re: {mail['subject']}", reply), "verified_different")
        review = self._newest_review()
        self._expect(self._send(f"Re: {review['subject']}", "CONFIRM"), "submitted")
        self._step("DIFFERENT PERSON with a reason, then CONFIRM: entered as a new client, confirmed distinct", [
            f"Reply: \"{reply}\"",
            *self._ids(ref),
            "HMIS got the confirmed-distinct override with the reason. The audit shows the decision and the reason.",
        ], f"/ui/staff.html#/audit/{ref}")

        ref, mail = self._verification("D3", "Dana Placeholder: two strong matches, possible duplicates in HMIS")
        reply = self.scenarios["D3"]["suggested_reply"]
        self._expect(self._send(f"Re: {mail['subject']}", reply), "verified_same")
        review = self._newest_review()
        self._expect(self._send(f"Re: {review['subject']}", "CONFIRM"), "submitted")
        self._step("The worker checks HMIS and picks the current record; the pair is kept for follow-up", [
            f"Reply: \"{reply}\" (the newer, active record), then CONFIRM: a case note and a service entry.",
            *self._ids(ref),
            "The audit records the possible duplicate pair in HMIS, with client IDs only.",
        ], f"/ui/staff.html#/audit/{ref}")

    def _scenario_e(self) -> None:
        self.say("")
        self.say("SCENARIO E: read-only questions to HMIS before the next visit")
        e1, e2 = self.scenarios["E1"], self.scenarios["E2"]
        self.refs["E1"] = self._expect(self._send(e1["subject"], e1["body"]), "query_answered")
        mail = self._newest("query_reply")
        first = mail["body"].split("\n")[0]
        a_client = self._get(f"/drafts/{self.refs['A']}/receipt")["hmis_ids"][0]["value"]
        listed = a_client in mail["body"]
        self._step("A pre-visit briefing for the SW quadrant", [
            first,
            (f"It lists {a_client}, Scenario A's client, because the contact recorded its quadrant." if listed
             else f"Scenario A's client {a_client} is not listed."),
            "Minimal data only: client ID, first name and last initial, last contact, and open items. Nothing in HMIS changed.",
        ], f"/ui/#/mail/{mail['id']}")
        self.refs["E2"] = self._expect(self._send(e2["subject"], e2["body"]), "query_answered")
        mail = self._newest("query_reply")
        self._step("A status check: has Jordan Sample's ID come in?", [
            mail["body"].split("\n")[0],
            "The model only picks the query type and copies the name and date of birth; code checks them and runs",
            "a fixed read-only query.",
        ], f"/ui/#/mail/{mail['id']}")
        self._step("Staff view: every query in the audit", [
            "Type, parameters (a name or date of birth only as \"given\"), and row counts. Never the returned values.",
        ], "/ui/staff.html#/queries")


def main() -> None:
    ap = argparse.ArgumentParser(description="Presentation demo: Scenarios A to E (synthetic data only)")
    ap.add_argument("--port", type=int, default=8000, help="port for the intake app (the mock HMIS port comes from config)")
    ap.add_argument("--auto", type=float, metavar="SECONDS", help="advance every N seconds instead of waiting for Enter")
    ap.add_argument("--skip-duplicate", action="store_true", help="leave out the optional duplicate step")
    ap.add_argument("--no-browser", action="store_true", help="print the screens instead of opening them")
    ap.add_argument("--exit", action="store_true", help="stop the servers after the last step")
    ap.add_argument("--parser", choices=["rule_stub", "reallms"], default="rule_stub")
    ap.add_argument("--model", help="REALLMS model (default: config/settings.yaml)")
    args = ap.parse_args()

    if args.auto is not None:
        def pause() -> str:
            time.sleep(args.auto)
            return ""
    else:
        def pause() -> str:
            return input("   Enter: next step   R: reset the demo and start over   ")

    with fresh_servers(args.port, parser=args.parser, model=args.model) as servers:
        base = servers.app_url

        def show(page: str) -> None:
            if not args.no_browser:
                webbrowser.open(base + page)

        print(f"Phone screens: {base}/ui/    Staff screens: {base}/ui/staff.html")
        print("Synthetic data only. Mock HMIS: writes through entry operations only; reads only through fixed read-only queries.")
        walk = Walkthrough(httpx.Client(base_url=base, timeout=200), show=show, pause=pause,
                           skip_duplicate=args.skip_duplicate)
        try:
            refs = walk.run()
        except RuntimeError as exc:
            sys.exit(f"The demo stopped: {exc}. Server logs: {servers.logs}")
        print("")
        kept = ", ".join(f"Scenario {sid}: {ref}" for sid, ref in refs.items())
        print(f"Done. Drafts in the demo now: {kept}.")
        if args.exit:
            return
        print(f"The servers keep running so you can click around: {base}/ui/  Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Stopping the servers.")


if __name__ == "__main__":
    main()
