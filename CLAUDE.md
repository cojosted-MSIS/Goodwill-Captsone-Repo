# CLAUDE.md

Project guide for Claude Code. Read this first, then `openspec/project.md`.

## What we are building
A web application for Horizon House street outreach workers, with offline capture. The core MVP is recurring case notes and service documentation for neighbors already in HMIS, plus entering new neighbors (client, program enrollment, then Coordinated Entry intake) and four read-only questions as fixed forms (quadrant briefing, lookup, status check, 60-day no-contact watchlist). The worker writes a note, reviews the draft on screen, corrects it in plain words if needed, and presses Confirm before anything is entered into the mock HMIS. Notes can be written offline: they are sealed on the device and upload by themselves; review, corrections, Confirm, and the questions need a connection. An email channel (the original demo) is kept as an option, off by default. The open change is `openspec/changes/add-web-application/`; `docs/HANDOFF.md` is the overview and `docs/QUESTIONS.md` lists every open question.

## Source of truth, in this order
1. `openspec/specs/` (the current specs, one folder per capability) and the open changes in `openspec/changes/` (proposal, design, tasks, and spec deltas). Build to these specs. If code and spec disagree, the spec wins, and ask before changing a spec. The first change, with its design decisions and open questions, is archived in `openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/`.
2. `docs/reference/encounter-workflow-mockups.md` and `docs/reference/mockups/*.png` (the screens the demo follows).
3. `docs/reference/hmis-manual-new-client-enrollment-and-ce-intake.md` (what HMIS expects).
4. `docs/reference/previous-draft/` is read only and superseded where it conflicts.

## Hard rules
- Synthetic data only. Never use or invent realistic real-person data. Use `sample-data/emails/`.
- The system writes to HMIS only through entry operations, each after CONFIRM, and entry operations return only success or failure and assigned identifiers. It reads HMIS only through the fixed read-only queries in `hmis-readonly-queries` (parameterized, allowlisted views, read-only connection, row limits, audited) [TBC with CHIP]. The mock HMIS HTTP routes stay POST only.
- Nothing is entered without an explicit Confirm (the button, or a CONFIRM reply in the email channel) from the note's author on the current draft version. Confirm is disabled offline and never queued.
- Nothing about a client is stored on a device except the worker's own queued notes, sealed so the device cannot read them. The service worker caches only the static app shell, never an `/api` answer. Refused SSN text is never written anywhere.
- The model never writes SQL, and nothing writes to HMIS except Confirm.
- Never infer or make up values. Missing values stay blank and flagged.
- Never commit, print or log an API key or any secret. `.env` stays git-ignored. Run the secret scan and show the result before any push.
- The language model never writes SQL and never decides what data a reply contains. It only picks one of the fixed query types and copies parameters, which code validates.
- Query replies carry minimal data: no SSN, no date of birth and no case note text. A record the worker cannot see is answered exactly as if it does not exist.
- When a same-name verification is open, Confirm is refused until the worker says same person or different person.
- Never commit, print, or log a password, a session token, or a sealing key. Placeholders only in `.env.example`.
- Out of scope: signatures and consent signing, photos, family members, VI-SPDAT, diversion, DV, income, referrals and CE events, real email, real HMIS, production hosting and sign-in, and HMIS search or reporting beyond the four fixed query types.
- Field names in the mockups are illustrative. Keep field mapping and validation rules in configuration files, not code.
- No em dashes in any text you write (docs, comments, UI strings, commit messages).

## How to work
- Work one task at a time from the open change's `tasks.md` in `openspec/changes/<change>/`. Tick the box when a task is done.
- Write a test for each spec scenario before or with the code. Name tests after the scenario.
- Keep the parser behind one interface with a rule-based stub and an LLM implementation.
- Run `openspec validate --all --strict` after any spec edit.
- When something is unclear or conflicts with the specs, stop and ask instead of guessing.
- Do not push or open a pull request unless asked.
- Stage files by explicit path (`git add <path> ...`), never `git add -A` or `git add .`, and check `git status` before every commit so nothing unintended is committed.
- The stack: Python, FastAPI, SQLite, and a plain-module web app with no build step (`ui/web/`). Node.js and Chrome are used only by tests, screenshots, and the demo's `--auto`.
- Work in checkpoints, write tests first, and keep all existing tests passing. Offline behavior is proven in a real browser with the app server really stopped.
- When a new [TBC] is added, add it to `docs/QUESTIONS.md` and run `python scripts/update_questions_doc.py`.
