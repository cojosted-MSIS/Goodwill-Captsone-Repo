# Change: Updates to existing clients, and same-name verification

## Why
The Week 10 stakeholder meeting made case notes and service documentation the core of the MVP. Outreach workers meet the same neighbor again and again, for example once and then a few days later, and each visit should add a case note and a service entry to the same HMIS record. Today the prototype can only create new clients.

The stakeholders also asked for stronger verification when two neighbors share a name and date of birth. Today the only protection is the mock HMIS's possible-duplicate rejection, which gives the worker no way to tell the two apart.

This change depends on `add-hmis-readonly-queries` for the neighbor lookup.

Source: the Week 10 notes in `docs/reference/week10-minutes.md`.

## What Changes
- **ADD** `existing-client-updates`:
  - "Update an existing neighbor" becomes the main flow: an email with the subject "Update: <name or client ID>", one note per visit, many entries per client over time, each with CONFIRM, a receipt, and an audit record without note text.
  - The client is identified by an HMIS client ID in the note, checked for format and existence, or chosen by the worker from lookup candidates.
  - The parser drafts a case note and a service entry (date, service type, quadrant, time spent if stated) [TBC with Horizon House and CHIP], through the same parse, validate, review, CONFIRM or corrections, entry, receipt, audit, and email purge flow as new clients.
  - The mock HMIS adds POST-only operations for adding a case note and a service to an existing client; an unknown client ID fails with a plain-words reason and nothing else.
  - A worker can correct a case note or service entry this system already entered: a new draft version that references the entry ID, CONFIRM required, entered as an update [TBC: the real HMIS may not allow edits after save].
  - Same name and date of birth: when a new-client draft matches a record the lookup finds, the verification email shows the candidates and CONFIRM alone is not enough; the worker replies SAME CLIENT <ID> or DIFFERENT PERSON with a reason. The mock's possible-duplicate rejection stays as a backstop; it accepts a confirmed-distinct override only with a reason, and the audit records the decision [TBC with CHIP].
  - Phone screens for updates, query replies, verification, and receipts with the new entry IDs; staff audit views showing verification decisions and queries; demo Scenarios C, D, and E.
- **MODIFY** `review-and-submit`: CONFIRM is not accepted while a same-name verification is open.
- **MODIFY** `encounter-email-intake`: a new-client draft is checked against HMIS by name and date of birth before review.

## Impact
- **Affected systems:** the intake workflow (update drafts, verification state, post-entry corrections), the parser (case note and service entry), the mock HMIS (new POST operations, override), the phone and staff screens, the demo script and reset.
- **Not changed:** no inferred values; CONFIRM before every entry; email is the only channel; writes only through entry operations; synthetic data only; no secrets in the repo.
- **Privacy:** `design.md` describes what the staging store keeps after entry and proposes changes for decision.
- **Status:** draft for review. Open items are marked [TBC] in `design.md`.
