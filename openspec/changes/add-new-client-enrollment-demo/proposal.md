# Change: Add new-client entry demo (client record, program enrollment, Coordinated Entry intake)

## Why
The team has not received an answer on whether documents that need signatures belong in the headless application. Until then, the demo narrows to one job: an outreach worker enters a person experiencing homelessness into HMIS as a new client, enrolls them in a program, and starts their Coordinated Entry intake, using nothing but an email.

The HMIS manual describes this as a multi-screen workflow that a worker completes after the encounter, often from memory. The demo shows the same result from one plain-language email, with a human check before anything is entered.

## What Changes
- **ADD** `encounter-email-intake`: accept the worker's email, parse it into a draft, ask for missing fields, never invent values.
- **ADD** `new-client-enrollment`: draft the HMIS basic client information and the HUD program enrollment with its universal data elements.
- **ADD** `coordinated-entry-intake`: draft the Coordinated Entry enrollment and triage assessment fields.
- **ADD** `review-and-submit`: review email, CONFIRM or plain-language corrections, entry into a mock HMIS, audit trail, and supervisor queue.

The screens and steps follow the team's Encounter Workflow Mockups (email, parse, map, stage, review, confirm, submit).

## Impact
- **Affected systems:** a simulated secure intake inbox, a swappable parser, and a mock HMIS that accepts entries only.
- **Not changed:** the real HMIS, CHIP credentialing, and data standards.
- **Out of scope for this change:** documents that need signatures (Form 101, verification letter, client consent signature), photos, family and household members beyond a household of one, VI-SPDAT and other scored assessments, diversion assessment, domestic violence assessment, income and benefits, veteran assessment, Coordinated Entry events and referrals, any HMIS lookup or read, and production deployment.
- **Supersedes:** the scope of `docs/reference/previous-draft/` for the demo. Where the earlier draft and this change disagree, this change wins.
- **Status:** draft for review with the team, Goodwill, and DeveloperTown. Open items are marked [TBC] in `design.md`.
