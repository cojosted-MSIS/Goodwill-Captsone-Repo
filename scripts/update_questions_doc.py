"""Regenerate the appendix of docs/QUESTIONS.md: python scripts/update_questions_doc.py

Finds every [TBC] in the repository and assigns it to a question by the rules below. A [TBC] no rule
matches stops the script, so a new open item can never be left out. Rules are tried in order against
the text around each occurrence.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "QUESTIONS.md"
BEGIN = "<!-- BEGIN GENERATED: where each [TBC] appears -->"
END = "<!-- END GENERATED -->"
SKIP = ("docs/QUESTIONS.md", "docs/reference/week10-minutes.md", "scripts/update_questions_doc.py", "tests/test_questions_doc.py")
BINARY = (".png", ".woff2", ".pdf", ".db", ".jpg", ".ico")
POINTER = "pointer"  # says only that open items are marked, or a test checks another item's wording

RULES: list[tuple[str, str]] = [
    # Lines that only point at the convention, and tests that check another item's wording.
    (r"^tests/|a new \[TBC\]|every \[TBC\]|Items marked \[TBC\]|Open items are marked \[TBC\]|open items are marked \[TBC\]|## Open questions \[TBC\]|^[^:]+: \[TBC\] in `design\.md`", POINTER),
    # Files whose [TBC] stands alone on its line.
    (r"^config/users\.yaml", "IT-1"),
    (r"^ui/web/ssn\.js", "GW-3"),
    # Clauses that name more than one question.
    (r"service fields, edits after save, the override, and production supervisor approval", "HH-1/CHIP-8/CHIP-6/GW-12"),
    (r"last four SSN digits on the device and shared devices", "GW-2/GW-4"),
    (r"Offline safety", "GW-2/GW-3/GW-4"),
    (r"last four SSN digits may be on the device, and shared devices", "GW-2/GW-4"),
    # Specific wordings that share a line with other items
    (r"who needs them|Who needs them|email-demo routes", "GW-11"),
    (r"whether to show this|Whether to show that chip", "GW-7"),
    (r"without blocking|not blocking|should block", "GW-12"),
    (r"web_wording\.py: # \[TBC\]$|with the \[TBC\]", "DT-3"),
    (r": days \[TBC\]", "GW-18"),
    # CHIP
    (r"against the mock HMIS \[TBC with CHIP\]|\(app/queries\.py\) \[TBC with CHIP|\[TBC with CHIP and the HMIS|read-only, audited quer|Read access|read access|SQL access|read-only connection", "CHIP-1"),
    (r"client ID format|client_id_pattern|the real format|its format \[TBC|prefixes", "CHIP-3"),
    (r"fields CHIP requires|open question 2", "CHIP-2"),
    (r"idempotency key|accepts the key|accepts such a key|supports this|honors the key|honors it|never makes a second record", "CHIP-4"),
    (r"override", "CHIP-6"),
    (r"duplicate handling", "CHIP-7"),
    (r"edits after save|allows edits|can be changed after|Corrections after entry|corrections after entry", "CHIP-8"),
    (r"open question 10|optional case note|optional field \[TBC|optional \[TBC", "CHIP-9"),
    (r"visibility", "CHIP-10"),
    (r"signature|method CHIP accepts|CHIP-accepted|completed by the worker in HMIS|obtained from email content", "CHIP-11"),
    (r"discard any further digits", "CHIP-13"),
    # Horizon House (before the quadrant rule: a service clause can mention a quadrant)
    (r"what counts as a contact|What counts as|Who is counted|contacts count is", "HH-2"),
    (r"60 days|no_contact_days|right numbers|14-day", "HH-3"),
    (r"Status type|status_types|Statuses|Birth certificate|id -> label", "HH-4"),
    (r"open question 1,|demo placeholders", "HH-5"),
    (r"placeholder list|service fields|service types|service type|Service types|Service documentation|Contact Service|real fields|time spent|entry fields", "HH-1"),
    (r"completed in HMIS by the worker|No \[TBC\]", "HH-6"),
    (r"quadrant", "CHIP-5"),
    # Goodwill
    (r"fallback|sponsors|Email code", "GW-1"),
    (r"last four digits may be|last four SSN digits may be", "GW-2"),
    (r"written in words|Numbers in words|whether this is enough", "GW-3"),
    (r"[Ss]hared devices", "GW-4"),
    (r"offline_write|The limit is \[TBC with Goodwill\]|reached the server \[TBC|absolute session limit", "GW-5"),
    (r"open offline", "GW-6"),
    (r"whether to show this|Whether to show that chip", "GW-7"),
    (r"what supervisors may see|field values \[TBC with Goodwill", "GW-8"),
    (r"supervisor's team|how teams are defined|open question 9|Supervisor for the 48-hour", "GW-9"),
    (r"not audited|should they\]|not views \[TBC", "GW-10"),
    (r"who needs them|Who needs them|email-demo routes", "GW-11"),
    (r"without blocking|not blocking|should block", "GW-12"),
    (r"48 hours|after this many hours", "GW-13"),
    (r"limit set by Goodwill|Goodwill sets the real limit|open question 8", "GW-14"),
    (r"after the reply", "GW-15"),
    (r"set window|worker's supervisor|\[N\] days|retention rule set by Goodwill", "GW-18"),
    # Goodwill IT
    (r"idle and absolute times|real timeouts", "IT-2"),
    (r"shared store|lockout counts", "IT-3"),
    (r"custody", "IT-4"),
    (r"hosting\]", "IT-5"),
    (r"scheduler", "IT-6"),
    (r"sign-in|single sign-on|identity provider", "IT-1"),
    # DeveloperTown
    (r"encounter-email-intake", "DT-1"),
    (r"retry is still recognized|idempotency_key_hours", "DT-2"),
    (r"\[TBC\] note|\[TBC\] notes|long \[TBC\]", "DT-3"),
]


def occurrences() -> list[tuple[str, str]]:
    names = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    found = []
    for name in names:
        path = ROOT / name
        if name in SKIP or name.endswith(BINARY) or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line in text.splitlines():
            for match in re.finditer("TBC", line):
                found.append((name, clause(line, match.start())))
    return found


def clause(line: str, at: int) -> str:
    """The clause a [TBC] belongs to: from the end of the previous bracket on the line to the end of its own."""
    start = line.rfind("]", 0, max(0, at - 1)) + 1
    end = line.find("]", at)
    return line[start:end + 1 if end >= 0 else len(line)].strip()


def classify(text: str) -> str | None:
    return next((qid for pattern, qid in RULES if re.search(pattern, text)), None)


def appendix() -> str:
    table: dict[str, Counter] = defaultdict(Counter)
    unmatched = []
    total = 0
    for name, text in occurrences():
        total += 1
        qid = classify(f"{name}: {text}")
        if qid is None:
            unmatched.append(f"{name}: {text}")
        else:
            table[qid][name] += 1
    if unmatched:
        sys.exit("A [TBC] has no question. Add one to docs/QUESTIONS.md and a rule here:\n" + "\n".join(unmatched))
    lines = [BEGIN, "", f"## Appendix: where each [TBC] appears ({total} in all)", "",
             "Generated. Each line is a question, then each file that mentions it, with how many times.", ""]
    def order(qid: str) -> tuple:
        head = qid.split("/")[0]
        prefix, _, number = head.partition("-")
        return (qid == POINTER, prefix, int(number) if number.isdigit() else 0, qid)

    for qid in sorted(table, key=order):
        label = "Says only that open items are marked, or a test checks an item's wording" if qid == POINTER else qid
        files = ", ".join(f"`{name}` ({count})" for name, count in sorted(table[qid].items()))
        lines.append(f"- **{label}:** {files}")
    return "\n".join([*lines, "", END])


def updated(text: str) -> str:
    start, end = text.index(BEGIN), text.index(END) + len(END)
    return text[:start] + appendix() + text[end:]


if __name__ == "__main__":
    DOC.write_text(updated(DOC.read_text(encoding="utf-8")), encoding="utf-8")
    print("Updated docs/QUESTIONS.md")
