# CLAUDE.md

Project guide for Claude Code. Read this first, then `openspec/project.md`.

## What we are building
A runnable demo of an email-driven intake for Horizon House street outreach. A worker emails notes about a new neighbor. The system drafts HMIS fields, the worker replies CONFIRM or plain-language corrections, and the confirmed record is entered into a mock HMIS: new client, program enrollment, then Coordinated Entry intake.

## Source of truth, in this order
1. `openspec/specs/` (the current specs, one folder per capability) and the open changes in `openspec/changes/` (proposal, design, tasks, and spec deltas). Build to these specs. If code and spec disagree, the spec wins, and ask before changing a spec. The first change, with its design decisions and open questions, is archived in `openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/`.
2. `docs/reference/encounter-workflow-mockups.md` and `docs/reference/mockups/*.png` (the screens the demo follows).
3. `docs/reference/hmis-manual-new-client-enrollment-and-ce-intake.md` (what HMIS expects).
4. `docs/reference/previous-draft/` is read only and superseded where it conflicts.

## Hard rules
- Synthetic data only. Never use or invent realistic real-person data. Use `sample-data/emails/`.
- The system writes to HMIS only through entry operations, each after CONFIRM, and entry operations return only success or failure and assigned identifiers. It reads HMIS only through the fixed read-only queries in `hmis-readonly-queries` (parameterized, allowlisted views, read-only connection, row limits, audited) [TBC with CHIP]. The mock HMIS HTTP routes stay POST only.
- Nothing is entered without an explicit CONFIRM from the note's author on the current draft version.
- Never infer or make up values. Missing values stay blank and flagged.
- Out of scope: signatures and consent signing, photos, family members, VI-SPDAT, diversion, DV, income, referrals and CE events, real email, real HMIS.
- Field names in the mockups are illustrative. Keep field mapping and validation rules in configuration files, not code.
- No em dashes in any text you write (docs, comments, UI strings, commit messages).

## How to work
- Work one task at a time from the open change's `tasks.md` in `openspec/changes/<change>/`. Tick the box when a task is done.
- Write a test for each spec scenario before or with the code. Name tests after the scenario.
- Keep the parser behind one interface with a rule-based stub and an LLM implementation.
- Run `openspec validate --all --strict` after any spec edit.
- When something is unclear or conflicts with the specs, stop and ask instead of guessing.
- Suggested stack is in `design.md` (Python, FastAPI, SQLite, simulated inbox). Use it unless told otherwise.
