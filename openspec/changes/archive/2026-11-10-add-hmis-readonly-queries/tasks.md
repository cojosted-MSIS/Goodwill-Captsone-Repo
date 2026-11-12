# Tasks

Depends on nothing new. `add-existing-client-updates` depends on this change.

## 1. Decisions before code
- [x] 1.1 Answer the open questions in `design.md` (subject prefix, audit parameters, briefing window, row limit, seed ID range, worker project)
- [x] 1.2 Update the wording listed in `design.md` (CLAUDE.md, openspec/project.md, README, HANDOFF.md, FUTURE.md, the first change's design and proposal, receipt and demo text, comments)

## 2. Mock HMIS read-only layer
- [x] 2.1 Move the mock HMIS store to a SQLite file; keep the HTTP routes POST only
- [x] 2.2 Tables for clients, contacts, services, ID documents, housing assessments, and visibility; views `v_clients`, `v_contacts`, `v_id_documents`, `v_housing_assessments`
- [x] 2.3 Synthetic seed data, including a pair sharing a name and date of birth and a record hidden from the demo project
- [x] 2.4 Entries made through the entry operations appear in the views
- [x] 2.5 Demo reset clears and reseeds the layer

## 3. Query path
- [x] 3.1 Recognize query emails from authorized workers; never create a draft from one
- [x] 3.2 Query type and parameter extraction in the parser interface (rule-based stub and REALLMS, strict schema, no SQL)
- [x] 3.3 Parameter validation (quadrant, name, full date of birth, client ID format, status type) with replies asking for what is missing
- [x] 3.4 Read-only connection, allowlisted views, bound parameters, row limit
- [x] 3.5 Briefing, lookup, and status replies with minimal fields
- [x] 3.6 Visibility filter by the worker's project
- [x] 3.7 Audit every query without returned values; query emails follow the retention rule

## 4. Tests and checks
- [x] 4.1 A test for every scenario in `specs/hmis-readonly-queries`, `specs/review-and-submit`, and `specs/encounter-email-intake`
- [x] 4.2 Tests that the query connection cannot write, that only allowlisted views are read, and that SQL-like text in an email never runs
- [x] 4.3 `openspec validate add-hmis-readonly-queries --strict`
