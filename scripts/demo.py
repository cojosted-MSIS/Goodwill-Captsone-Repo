"""One-command presentation demo (task 5.3): python scripts/demo.py

Starts a fresh mock HMIS and intake app, opens the phone screens in your browser, and walks
through Scenario A (a clean note confirmed on the first reply) and Scenario B (a scripted
parser error and a missing field, caught and corrected by the worker). Each step says what
is happening, opens the screen to show, and waits for Enter. When the walk-through ends,
the servers keep running so you can click around; press Ctrl+C to stop.

Options: --auto N advances every N seconds instead of waiting for Enter; --no-browser only
prints the screens; --exit stops the servers after the last step; --parser reallms parses
Scenario A with REALLMS (needs the key in .env; Scenario B stays scripted).

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


@dataclass
class Walkthrough:
    """Runs the scenario steps against any httpx-style client (the real app or a test client)."""

    client: httpx.Client
    say: Callable[[str], None] = print
    show: Callable[[str], None] = lambda page: None
    pause: Callable[[], None] = lambda: None
    refs: dict[str, str] = field(default_factory=dict)
    step: int = 0

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

    def _step(self, title: str, lines: list[str], page: str) -> None:
        self.step += 1
        self.say("")
        self.say(f"Step {self.step}. {title}")
        for line in lines:
            self.say(f"   {line}")
        self.say(f"   Screen: {page}")
        self.show(page)
        self.pause()

    def _ids(self, ref: str) -> list[str]:
        receipt = self._get(f"/drafts/{ref}/receipt")
        return [f"{i['label']}: {i['value']}" for i in receipt["hmis_ids"]]

    # the walk-through

    def run(self) -> dict[str, str]:
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
        self._step("The worker replies CONFIRM; the system enters the record into the mock HMIS", [
            "Entered in order: client, program enrollment, Coordinated Entry enrollment.",
            *self._ids(ref_a),
            "The system only entered data. It never searched or read HMIS.",
        ], f"/ui/#/receipt/{ref_a}")

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
        return self.refs


def main() -> None:
    ap = argparse.ArgumentParser(description="Presentation demo: Scenarios A and B (synthetic data only)")
    ap.add_argument("--port", type=int, default=8000, help="port for the intake app (the mock HMIS port comes from config)")
    ap.add_argument("--auto", type=float, metavar="SECONDS", help="advance every N seconds instead of waiting for Enter")
    ap.add_argument("--no-browser", action="store_true", help="print the screens instead of opening them")
    ap.add_argument("--exit", action="store_true", help="stop the servers after the last step")
    ap.add_argument("--parser", choices=["rule_stub", "reallms"], default="rule_stub")
    ap.add_argument("--model", help="REALLMS model (default: config/settings.yaml)")
    args = ap.parse_args()

    if args.auto is not None:
        def pause() -> None:
            time.sleep(args.auto)
    else:
        def pause() -> None:
            input("   Press Enter for the next step... ")

    with fresh_servers(args.port, parser=args.parser, model=args.model) as servers:
        base = servers.app_url

        def show(page: str) -> None:
            if not args.no_browser:
                webbrowser.open(base + page)

        print(f"Phone screens: {base}/ui/    Staff screens: {base}/ui/staff.html")
        print("Synthetic data only. Mock HMIS: entry only, never searched or read.")
        walk = Walkthrough(httpx.Client(base_url=base, timeout=200), show=show, pause=pause)
        try:
            refs = walk.run()
        except RuntimeError as exc:
            sys.exit(f"The demo stopped: {exc}. Server logs: {servers.logs}")
        print("")
        print(f"Done. Scenario A: {refs['A']}, Scenario B: {refs['B']}.")
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
