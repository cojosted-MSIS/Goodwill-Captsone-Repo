# Change: Web application with offline support

> **Status: pending a call with the Goodwill and DeveloperTown sponsors.** This change records the proposed new direction so it can be reviewed. Nothing here is built yet. The email-based demo is preserved at the tag `v1-email-headless`.

## Why
The product is changing from an email-based headless app to a web application case management system. Outreach workers would sign in to a web app on their phone, write the same plain-language note, review the draft on screen, and press a Confirm button, instead of emailing notes and replying CONFIRM. Workers are often on the street with a weak or no connection, so the app must keep working offline: entries are cached on the device and uploaded automatically when the connection returns.

Every existing use case and rule stays. Most of the code is already independent of email (parsing, validation, the review and verification logic, the read-only queries, the entry-only HMIS gateway, the audit, retention), so this change replaces the email channel with a web channel on top of the same core instead of starting again. Source for the use cases: the Week 10 notes in `docs/reference/week10-minutes.md`.

## What Changes
- **ADD** `web-application`: sign-in with roles (worker, supervisor, staff) replacing the email sender allowlist; worker screens to write a note, review a draft, correct it, verify a same-name match, pick a client, confirm with a button, ask the four read-only queries, and see receipts; a supervisor screen for the 48-hour queue; a web API over the existing core.
- **ADD** `offline-sync`: a service worker and an IndexedDB queue on the device; an idempotency key per submission so a retry never creates a duplicate draft or a duplicate in HMIS; upload retries with backoff; a visible status per entry (saved on device, uploading, submitted, needs attention); conflict handling, including the existing duplicate rejection; what may be stored on the device [TBC with Goodwill and CHIP]; read-only queries while offline [TBC]; how verification and confirmation work for an entry queued offline.
- **MODIFY** `review-and-submit`: confirmation by a Confirm button on the current version instead of a CONFIRM reply; corrections in a box on the review screen; web screens instead of simulated email; the supervisor queue notifies in the app; the note copies (not email copies) are deleted at submission.
- **REMOVE** `review-and-submit`, "Send a review email": the review is a screen. Migration note in the delta.
- **MODIFY** `encounter-email-intake`: notes come only from signed-in workers, not from senders on an email allowlist.
- **MODIFY** `hmis-readonly-queries`: queries are asked and answered in the app; query email retention goes away.
- **MODIFY** `existing-client-updates`: update notes, client picking, corrections after entry, and same-name verification use screens and buttons instead of subject prefixes and email replies.

## Rules that do NOT change
- The model never writes SQL. It only picks one of the four fixed query types and copies parameters, which code validates.
- Writes to HMIS happen only through entry operations, only after an explicit confirmation by the author of the current version (now a button).
- Query replies carry minimal data (no SSN, date of birth, or case note text); a record the worker cannot see is answered as if it does not exist; every query is audited without its returned values.
- No inferred values; worker-sourced, email-date (now "submission time"), and program-default origins stay labelled.
- Retention: drafts are reduced to a stub at submission in production mode; unsubmitted drafts are deleted after 7 days.
- Same-name and date of birth verification, the open-draft keyed hash, the 48-hour supervisor queue, the possible-duplicate backstop, and synthetic data only.

## Impact
- **Affected:** a new web API and auth layer; new worker and supervisor screens (built from the current review screens); a service worker and offline queue; the workflow split into a channel-neutral core and channel adapters; the demo script and reset; docs.
- **Specs:** the three Week 10 changes (`add-hmis-readonly-queries`, `add-existing-client-updates`, `add-no-contact-query`) are merged but not archived. They must be archived first, so this change's MODIFIED deltas apply to their requirements.
- **Open:** whether to delete the email code or keep it as an optional channel [TBC]; device storage rules [TBC with Goodwill and CHIP]; queries while offline [TBC]; production sign-in (single sign-on) [TBC with Goodwill IT]; whether the real HMIS accepts idempotency keys [TBC with CHIP]. See `design.md`.
