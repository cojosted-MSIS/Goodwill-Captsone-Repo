# Change: No-contact watchlist query

## Why
Outreach workers need to know which neighbors are about to go 60 days without a contact, so they can find them before the gap matters [TBC with Horizon House: whether 60 days is the rule that matters for them, for example for enrollment exits]. Today a worker can ask for a quadrant briefing, a lookup, or a status check, but nothing lists who has gone longest without being seen. The read-only query path from `add-hmis-readonly-queries` already has the guardrails this needs (fixed query types, validated parameters, allowlisted views, minimal replies, row limits, visibility, audit), so this adds a fourth fixed query type to it. It follows the Week 10 direction to support workers before they go out (`docs/reference/week10-minutes.md`).

Depends on `add-hmis-readonly-queries` (the query path) and `add-existing-client-updates` (the enrollment view used to count only active enrollments).

## What Changes
- **MODIFY** `hmis-readonly-queries`, "Choose only from a fixed set of query types": four types instead of three, adding the no-contact watchlist. The parser still only picks the type and copies its parameters (here, an optional quadrant); it never writes SQL, and code validates every parameter.
- **ADD** to `hmis-readonly-queries`: the no-contact watchlist reply, with two groups, "Approaching 60 days" (46 to 60 days since the last contact) and "Past 60 days", from two config values (`no_contact_days: 60`, `no_contact_warning_days: 14`); only neighbors with an active enrollment; minimal fields per neighbor; most overdue first; the existing row limit, visibility, and audit rules.
- **ADD** to `hmis-readonly-queries`: synthetic seed neighbors with a spread of days since the last contact, with every seed date counted back from the day the demo starts or resets, so the demo stays correct over time.
- **ADD** demo Scenario E3 (ask the watchlist question, then show the reply).

## Impact
- **Affected:** the parsers (a fourth query type; the live prompt becomes `query-v2`), query validation and replies (`app/queries.py`), the read-only reader (one more fixed query), the mock seed, the staff queries view, the phone compose hint, the demo script, and every document that said there are three query types.
- **Not changed:** writes go only through entry operations after CONFIRM; the model never writes SQL; replies carry no SSN, date of birth, or case note text; email is the only channel; synthetic data only.
- **Open:** what counts as a contact [TBC with Horizon House]; whether 60 days and the 14-day warning are the right numbers [TBC with Horizon House].
