Existing-client updates, same-name verification and read-only HMIS queries

Core MVP changes from the Week 10 stakeholder meeting. Two OpenSpec changes, both implemented and validating:

add-hmis-readonly-queries
- Read-only email queries: quadrant briefing, neighbor lookup, status check
- The model never writes SQL; it only picks one of three fixed query types and copies parameters that code validates
- Parameterized queries on allowlisted views, over a read-only connection, with row limits and a full audit
- Replies carry minimal data (no SSN, date of birth or case note text), and hidden records are answered as not found
- This changes the earlier enter-only rule on purpose. It is an assumption pending CHIP and the HMIS administrator [TBC]

add-existing-client-updates
- "Update:" emails for recurring case notes and services on a neighbor already in HMIS, with corrections after entry
- Same-name and date-of-birth verification: SAME CLIENT or DIFFERENT PERSON is required, and CONFIRM is refused until then
- The quadrant is recorded on every contact, so new neighbors appear in briefings right away
- Retention modes: production reduces drafts to a stub at submission, demo mode keeps values for the synthetic walkthrough

Also: the first change is archived, CLAUDE.md is updated, and the demo script has new Scenarios C, D and E.

Checks: all tests pass, openspec validate --all --strict passes, synthetic data only, and the secret scan is clean.

For reviewers: please read CLAUDE.md first, then the two proposals in openspec/changes/. The core rule changed (the system now reads HMIS through fixed queries), so please confirm you are comfortable with that before merging.

