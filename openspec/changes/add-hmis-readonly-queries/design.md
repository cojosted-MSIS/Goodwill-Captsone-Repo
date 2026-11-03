# Design: Read-only HMIS queries by email

## Context
Until now the system entered into HMIS and never read it. The Week 10 stakeholder meeting made case notes and service documentation the core MVP and asked for stronger same-name and same-date-of-birth verification. Both need lookups. This change adds reads, deliberately and narrowly, for the prototype. Read access to the real HMIS is [TBC] with CHIP and the HMIS administrator: there is no confirmed API or SQL access, and the Week 10 minutes call broader HMIS querying a future enhancement.

```text
Worker email "Query: ..." -> authorized? -> parser picks a query type and extracts parameters
  -> code validates the parameters (or asks for what is missing; nothing runs)
  -> fixed parameterized query on allowlisted read-only views, read-only connection, row limit
  -> visibility filter for the worker's project
  -> minimal reply by email  +  audit record (who, when, type, parameters, row count)
```

## Decisions
1. **Reads are a separate, narrow path.** Writes still go only through the three entry operations (and, after `add-existing-client-updates`, the case note and service operations), each after CONFIRM. Reads go only through three fixed query types. Nothing shares a code path between the two.
2. **Email is the only channel.** A query is an email from an authorized worker whose subject starts with "Query:" [TBC]. The reply is an email. A query never creates a draft, so a query email cannot be confirmed into an entry.
3. **The model never writes SQL.** The parser returns one of `briefing`, `lookup`, or `status`, plus parameters, under a strict schema like the note parser's. Code validates every parameter. The query text for each type is a constant in code. The rule-based stub handles the demo phrasings; REALLMS can be used with the same guardrails.
4. **Mock read-only SQL layer.** The mock HMIS keeps its records in a SQLite database file [TBC: replacing its in-memory store] with tables for clients, contacts, services, ID documents, housing assessments, and a visibility setting per record. The HTTP entry routes stay POST only. The intake app opens the database with a read-only connection (`mode=ro`), reads only allowlisted views (`v_briefing`, `v_lookup`, `v_status`), binds every parameter, and limits rows (25 [TBC]). This stands in for SQL read access to the real HMIS, which is unconfirmed.
5. **Parameters.**

   | Parameter | Rule |
   |---|---|
   | Quadrant | NW, NE, SW, or SE |
   | Name | First and last name, compared without case, spacing, or punctuation |
   | Date of birth | Full date, copied as written and read in code; partial dates are refused |
   | Client ID | HMIS client ID format [TBC: demo uses HMIS-C-NNNNNN] |
   | Status type | `id_document` or `housing_assessment` [TBC with Horizon House] |

   A name lookup needs a date of birth, so the system never searches by name alone.
6. **Minimal replies.** Briefing: count, then per neighbor the client ID, first name and last initial, last contact date, and open item labels. Lookup: client ID, first name and last initial, quadrant and date of the last contact. Status: the status and its date. Never a Social Security number, a date of birth (even one the worker sent), case note text, a full last name, a precise location, or other people. Tell us if a different default is wanted (open question 3).
7. **Visibility.** Each record has a visibility setting; each worker belongs to a project in `config/workers.yaml` [TBC]. Queries filter by it, and a hidden record is answered exactly like a missing one.
8. **Audit.** Every query, including refused ones, is audited: worker, time, type, parameters, row count. Returned values are never stored. Whether names and dates of birth given as parameters are kept in full is open question 4.
9. **Seed data.** Synthetic only: about a dozen neighbors across the four quadrants, contacts and services over recent weeks, ID document statuses (requested, received), housing assessments (scheduled, completed), at least one pair sharing a name and date of birth for `add-existing-client-updates`, and one record hidden from the demo worker's project. Seed client IDs use their own range [TBC] so new entries still start at HMIS-C-000001.
10. **Reset.** The demo-only reset clears the layer and reloads the seed data, with the same guards as today (local mock only, explicit confirmation, never by email).

## Wording that says the system never reads or searches HMIS
Listed for later. This change does not edit these files. Line numbers are as of `main` at 82195b4.

| Place | Current wording | Proposed wording |
|---|---|---|
| `CLAUDE.md:16` | The system enters into HMIS and never reads it. No search, lookup, list, or get endpoint on the mock HMIS. The only things coming back are success or failure and assigned identifiers. | The system writes to HMIS only through entry operations, each after CONFIRM, and entry operations return only success or failure and assigned identifiers. It reads HMIS only through the fixed read-only queries in `hmis-readonly-queries` (parameterized, allowlisted views, read-only connection, row limits, audited) [TBC with CHIP]. The mock HMIS HTTP routes stay POST only. |
| `openspec/project.md:10` | **Enter only, never read.** The system enters information into HMIS. It never searches, looks up, or reads HMIS. Workers search HMIS themselves. | **Write only through entry operations; read only through fixed queries.** The system writes to HMIS only through entry operations after CONFIRM. It reads HMIS only through three fixed, read-only, audited query types [TBC with CHIP]. |
| `openspec/project.md:13` | ... a mock HMIS that accepts entries only. | ... a mock HMIS that accepts entries and answers the fixed read-only queries. |
| `add-new-client-enrollment-demo/specs/review-and-submit/spec.md:80-81` | Enter into HMIS without reading from it; SHALL NOT search, list, or read any HMIS record | Modified by this change (renamed "Write to HMIS only through entry operations"). |
| `add-new-client-enrollment-demo/specs/review-and-submit/spec.md:118` | The routes the screens use ... SHALL NOT search, list, or read HMIS | No change needed: the screens still read only the staging store; queries go by email. |
| `add-new-client-enrollment-demo/specs/encounter-email-intake/spec.md:12-17` | ... and SHALL NOT search or read HMIS itself; the system does not query HMIS | Modified by this change. |
| `add-new-client-enrollment-demo/design.md:16` | Search HMIS first to avoid duplicates (the worker does this, not the system). | Search HMIS first to avoid duplicates. The worker still states the search; the system also checks name and date of birth with a read-only lookup (`add-existing-client-updates`). |
| `add-new-client-enrollment-demo/design.md:23` | Mock HMIS (logical operations, entry only) | Mock HMIS: entry operations (writes) |
| `add-new-client-enrollment-demo/design.md:35` | **Enter only, never read.** The system never searches HMIS. ... | **Write only through entry operations.** The first prototype never read HMIS; `add-hmis-readonly-queries` adds narrow read-only queries [TBC with CHIP]. For a new client HMIS still assigns the ID on entry. |
| `add-new-client-enrollment-demo/design.md:75` | Assumed: An entry-only interface can be agreed with CHIP. | Assumed: an entry interface, and read-only query access, can be agreed with CHIP [TBC]. |
| `add-new-client-enrollment-demo/proposal.md:19` | Out of scope: ... any HMIS lookup or read ... | Out of scope: ... any HMIS read beyond the fixed queries in `add-hmis-readonly-queries` ... |
| `add-new-client-enrollment-demo/tasks.md:4, 8, 11` | entry-only service; Mock HMIS (entry only); Confirm no read, search, or list endpoint exists | Keep as the record of what was done. The HTTP routes are still POST only. |
| `README.md:13` | The system only enters data into HMIS. It never searches or reads HMIS. The worker searches HMIS themselves and says so in the email. | The system writes to HMIS only through entry operations after CONFIRM. It can answer three fixed read-only queries by email (briefing, lookup, status), against the mock HMIS [TBC with CHIP]. The worker still says in a new-client note that they searched HMIS. |
| `README.md:66, 72` | Mock HMIS (entry only) ... It has no search, list or read route. | Mock HMIS: POST-only entry routes, plus a read-only SQL layer for the fixed queries. It has no HTTP read route. |
| `README.md:159` | mock_hmis/ entry-only mock HMIS service | mock_hmis/ mock HMIS: entry routes and a read-only SQL layer |
| `README.md:172` | Out of scope: Any HMIS search, lookup or read, and the real HMIS | Out of scope: HMIS reads beyond the fixed queries, and the real HMIS |
| `docs/HANDOFF.md:30` | entry-only mock HMIS | mock HMIS (entry routes and read-only queries) |
| `docs/HANDOFF.md:72` | **Enter only, never read HMIS.** The system never searches, lists, or reads HMIS. ... | **Write only through entry operations.** Writes go only through entry operations after CONFIRM; reads only through the fixed, read-only, audited queries [TBC with CHIP]. Only success or failure and assigned IDs come back from an entry. |
| `docs/FUTURE.md:24` | ... the prototype only enters three records through a mock. | ... the prototype writes only through entry operations to a mock. |
| `app/review.py:233` (receipt screen text) | You searched HMIS and found no match. The system only entered data and never searched HMIS. | You searched HMIS and found no match. The system wrote these records only through entry operations, after your CONFIRM. |
| `scripts/demo.py:150` (demo narration) | The system only entered data. It never searched or read HMIS. | The system wrote only through entry operations, after CONFIRM. |
| `scripts/demo.py:215` | Mock HMIS: entry only, never searched or read. | Mock HMIS: writes through entry operations only; reads only through fixed read-only queries. |
| `mock_hmis/__init__.py:1-4`, `mock_hmis/service.py:59`, `mock_hmis/__main__.py:13` | entry-only; no search, lookup, list, or read endpoint | Entry routes (POST only) plus a read-only SQL layer; no HTTP read route. |
| `app/workflow.py:3, 9, 368`, `config/hmis.yaml:1`, `ui/static/staff.js:4` (comments) | Entry only ...; nothing here reads HMIS | Writes: entry only. Staff screens still read only the staging store. |
| `tests/test_mock_hmis_no_read.py` | Every mock HMIS route is a POST; no route answers a GET | Keep for the HTTP routes. Add tests that the SQL layer is read-only and allowlisted. |

`docs/KICKOFF_PROMPT.md` and `docs/reference/` are historical and stay as they are. `docs/PROMPTS.md` and `docs/CONFIDENCE.md` need no change for this rule.

## Risks
- **Read access spreads.** Mitigation: three fixed query types, allowlisted views, read-only connection, minimal replies, row limits, audit.
- **A query reveals too much.** Mitigation: no date of birth or SSN in replies, first name and last initial only, visibility filter.
- **Wrong person.** A lookup can return two people with the same name and date of birth. Mitigation: show client ID, quadrant and last contact so the worker can tell them apart; never pick one.
- **The real HMIS may never allow SQL reads.** Mitigation: the query types are defined by what they answer, not by SQL, so they can move to another read method later.

## Open questions [TBC]
1. Can the system read the real HMIS at all, by SQL or an API, and under what agreement? Ask: CHIP, HMIS administrator.
2. How does record visibility work in the real HMIS, and which project does a Horizon House outreach worker belong to? Ask: CHIP.
3. Are the minimal reply fields right (no date of birth, first name and last initial only)? Ask: Hannah, Horizon House.
4. Should the audit keep names and dates of birth given as query parameters in full? Recommendation: keep the client ID, quadrant, and status type; record names and dates of birth only as "given" (or a keyed hash), since the audit outlives the emails. Ask: the team, Dennis.
5. What time window defines "reported in a quadrant" for a briefing (proposed 90 days)? Ask: Hannah.
6. Which ID document and housing assessment statuses matter to workers? Ask: Hannah, Horizon House.
7. Row limit (proposed 25) and subject prefix ("Query:"). Ask: the team.
