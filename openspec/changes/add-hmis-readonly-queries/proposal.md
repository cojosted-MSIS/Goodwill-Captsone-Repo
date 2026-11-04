# Change: Read-only HMIS queries by email

## Why
The Week 10 stakeholder meeting made case notes and service documentation the core of the MVP and asked for stronger verification when neighbors share a name and date of birth. Both need the system to look things up in HMIS. Workers also asked for help before they go out: who has been reported in a quadrant, and whether something they are waiting on (an ID document, a housing assessment) has come in.

The first change made the system enter only and never read HMIS. This change deliberately reverses that one rule for the prototype: the system may read HMIS through SQL queries, against a mock, under strict guardrails. The real HMIS has no confirmed API or SQL access, and the Week 10 minutes call broader HMIS querying a future enhancement, so read access is [TBC] with CHIP and the HMIS administrator.

Source: the Week 10 notes in `docs/reference/week10-minutes.md`.

This change comes first. `add-existing-client-updates` depends on its neighbor lookup.

## What Changes
- **ADD** `hmis-readonly-queries`: three query types (`add-no-contact-query` adds a fourth, the no-contact watchlist) requested and answered by email (pre-visit briefing for a quadrant, neighbor lookup by name and date of birth or by client ID, and status checks for ID documents and housing assessments), with guardrails: the model never writes SQL and only picks a query type and extracts parameters that code validates; parameterized queries on allowlisted read-only views over a read-only connection with row limits; minimal data in replies; record visibility; an audit record for every query without the returned values; and queries never change anything.
- **ADD** a read-only SQL layer to the mock HMIS, seeded with synthetic neighbors, services, ID document status, and housing assessments. Entries made through the entry operations become visible to queries. The demo reset clears and reseeds it.
- **MODIFY** `review-and-submit`: rename "Enter into HMIS without reading from it" to "Write to HMIS only through entry operations" and allow reads only through this capability. Writes still go only through entry operations, each after CONFIRM.
- **MODIFY** `encounter-email-intake`: the HMIS search requirement no longer says the system never searches or reads HMIS.
- **MODIFY** `review-and-submit`: the demo reset also reseeds the read-only layer.

## Impact
- **Affected systems:** the mock HMIS (new SQL layer and seed data), the intake workflow (a query path beside the note path), the parser (query type and parameter extraction), the audit record, and the demo reset.
- **Not changed:** writes to HMIS go only through entry operations after CONFIRM; email is the only channel; no inferred values; synthetic data only; no secrets in the repo.
- **Wording:** every place that said the system never reads or searches HMIS is listed in `design.md` with its new wording, applied with this change.
- **Status:** draft for review. Open items are marked [TBC] in `design.md`.
