# Project: Horizon House outreach email intake demo

## Purpose
A basic, runnable demo of an email-driven "headless application" for Horizon House street outreach workers (Goodwill of Central & Southern Indiana). A worker emails plain-language notes after meeting a neighbor. The system drafts structured HMIS fields, the worker confirms or corrects by email, and only then is the record entered into a mock HMIS.

This is a feasibility and prototype concept for an MSIS capstone (Crimson Consulting Group: JD Wrightsman, Ankush Nehra, Collin Stedman). It is not a production system.

## Ground rules
- **Synthetic data only.** Never use real neighbor data anywhere in code, tests, fixtures, docs, or prompts.
- **Enter only, never read.** The system enters information into HMIS. It never searches, looks up, or reads HMIS. Workers search HMIS themselves.
- **The worker approves everything.** Nothing is entered without an explicit CONFIRM from the worker who wrote the note.
- **No inferred values.** A field is filled only from the email. Missing fields stay blank and are flagged.
- **HMIS is a mock.** CHIP owns the real HMIS and API access is unconfirmed. The demo uses a mock HMIS that accepts entries only.
- **AI stays inside the approved environment.** In the demo, the parser must be swappable (rule-based stub or LLM) behind one interface, and only synthetic text may reach it.

## Conventions
- OpenSpec format: `## ADDED Requirements`, `### Requirement: ...` with SHALL, `#### Scenario:` with WHEN/THEN/AND bullets.
- Open items are marked [TBC] and listed in the change's `design.md`.
- No em dashes in any written output (docs, comments, UI text).
- Validate specs with `openspec validate <change> --strict`.

## Reference material
- `docs/reference/hmis-manual-new-client-enrollment-and-ce-intake.md` (HMIS manual excerpts)
- `docs/reference/encounter-workflow-mockups.md` and `docs/reference/mockups/*.png` (screens the demo follows)
- `docs/reference/previous-draft/` (earlier OpenSpec draft, read only, superseded where it conflicts)
