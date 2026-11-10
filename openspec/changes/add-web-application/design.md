# Design: Web application with offline support

> Pending a call with the Goodwill and DeveloperTown sponsors. Open items are marked [TBC].

## Context
The prototype is an email-based headless app: a worker emails a note, the system drafts the HMIS record, emails a review back, and enters the record after the worker replies CONFIRM. It also handles updates for existing clients, same-name verification, and four read-only queries. The new direction is a web application case management system that keeps every use case and rule and adds offline support. The final email-based state is tagged `v1-email-headless`.

## Goals and non-goals
- **Goals:** the same use cases and rules on web screens; sign-in and roles; entries saved on the device when offline and uploaded automatically; no duplicates from retries; the same audit, retention, and privacy rules.
- **Non-goals (this change):** a native mobile app; real HMIS or real single sign-on; new HMIS fields or new use cases; offline parsing or offline HMIS writes.

## 1. What can be reused (module map)

| Module | Channel-independent? | Notes |
|---|---|---|
| `parser/` (interface, rule stub, REALLMS, checks, shared rules, scripted demo) | Yes | Takes an `IntakeEmail` today; that becomes a channel-neutral `Note` (author, submitted at, note type, text). Subject-prefix routing (`Query:`, `Update:`) is email-only; the web app says the note type explicitly. |
| `app/validation.py`, `app/dates.py`, `app/match_key.py` | Yes | Unchanged. "Email date" becomes "submission time" in labels only. |
| `app/drafts.py` | Yes | `author` is an email address and `subject` comes from the email; these become the user ID and a title. |
| `app/hmis_reader.py`, `app/queries.py` | Yes | `answer` returns reply text; the web app also needs the rows as structured data (same minimal fields). |
| `app/hmis_gateway.py` | Yes | Entry operations only. Gains an idempotency key per entry operation. |
| `app/review.py` | Mostly | `review_data`, `verification_data`, `receipt_data`, `staged_view` are the screen data already. `compose_review`, `compose_verification`, the subject token are email-only. |
| `app/staff.py`, staff screens | Yes | Parser run, mapped draft, staged record, audit, queries view. |
| `app/storage.py` | Mostly | Drafts, pending notes, audit, counters, match keys are reusable. The `emails` table, purge, and `NEIGHBOR_EMAIL_KINDS` are email-only. New tables: users, sessions, idempotency keys. |
| `app/workflow.py` | Mixed | The core logic (drafting, same-name check, corrections, verification decisions, entry steps with retry, corrections after entry, expiry, seven-day deletion, audit) is reusable but called through email handling: `receive` routes by subject token; commands are parsed from reply text (`CONFIRM`, `RETRY`, `SAME CLIENT`, `DIFFERENT PERSON`, `CLIENT <ID>`); replies are sent with `_send`; email copies are kept with `_keep_copy`. Stage 2 splits it into a channel-neutral core with one method per action, and an email adapter. |
| `app/email_message.py`, `/inbox`, `/outbox`, `/mail/*` routes, `ui/static/app.js` (simulated email phone) | No | Email-specific. |
| `config/workers.yaml` (sender allowlist, project) | Partly | The allowlist is replaced by user accounts; the project per worker moves to the user record. |
| `mock_hmis/` | Yes | Gains idempotency keys on entry routes. |
| `scripts/demo.py`, `scripts/take_screenshots.py`, demo reset | Partly | Rewritten for the web flow in Stage 5; the reset guard stays. |

## 2. Requirements that change

| Capability | Requirement | Change |
|---|---|---|
| encounter-email-intake | Accept messages only from authorized workers | MODIFIED: signed-in workers with the worker role |
| review-and-submit | Enter only after CONFIRM from the author | MODIFIED: a Confirm button on the current version |
| review-and-submit | Accept plain-language corrections | MODIFIED: a corrections box on the review screen |
| review-and-submit | Review on phone-style screens | MODIFIED: web screens, not simulated email |
| review-and-submit | Send a review email | REMOVED: the review is a screen |
| review-and-submit | Send unconfirmed drafts to a supervisor queue | MODIFIED: in-app notices and a supervisor screen |
| review-and-submit | Keep an audit record and delete email copies | MODIFIED: note copies, not email copies |
| hmis-readonly-queries | Accept HMIS queries by email | MODIFIED: asked and answered in the app |
| hmis-readonly-queries | Queries never change anything | MODIFIED: no query email retention |
| existing-client-updates | Accept update notes for an existing neighbor | MODIFIED: an "Update a neighbor" form, not a subject prefix |
| existing-client-updates | Offer lookup candidates when no client ID is given | MODIFIED: pick on screen, not a CLIENT reply |
| existing-client-updates | Correct an entry this system already made | MODIFIED: "Correct this entry" on the receipt |
| existing-client-updates | Check new-client drafts for the same name and date of birth | MODIFIED: a verification screen with buttons |

Requirements that mention "email" only as the source of the note (for example "Fill draft fields only from the email") keep their meaning: the note submitted in the app is the email's replacement. Renaming the `encounter-email-intake` capability is [TBC] once the direction is confirmed.

**Migration:** existing drafts and audit records in a staging store stay readable; email copies already stored are purged under the current rule; no HMIS data changes. The tag `v1-email-headless` keeps the email demo runnable.

## 3. Architecture
- **Server:** the existing FastAPI app. A versioned JSON API (`/api/v1/...`) calls the channel-neutral core. The current screen data functions become API responses.
- **Client:** plain HTML and JavaScript without a build step, as today, starting from the phone and staff screens. A service worker caches the app shell (HTML, JS, CSS) so the app opens offline. IndexedDB holds the offline queue.
- **Auth:** server-side sessions in SQLite; an HttpOnly, Secure, SameSite=Strict cookie; a CSRF token on every write. Demo accounts are synthetic, with password hashes only; demo passwords come from `.env` (placeholders in `.env.example`). Production sign-in through Goodwill's identity provider (single sign-on) [TBC with Goodwill IT].
- **Roles:** worker (own notes, drafts, receipts, and queries, within their project's visibility), supervisor (the 48-hour queue for their team, read-only access to their team's drafts), staff (the parser run, mapped draft, staged record, audit, and queries views). A user can hold more than one role. The project used for query visibility moves from `workers.yaml` to the user record.

## 4. Offline behavior
- **What works offline:** opening the app; writing a new-client note, an update note, or a correction; seeing the status of queued entries. Parsing, verification, review, confirmation, HMIS entry, and queries need the server.
- **Queue:** each entry is saved to IndexedDB with a client-generated idempotency key (a random UUID), the note type, the client ID for updates, the note text, and the time it was written. Status: **Saved on device**, **Uploading**, **Submitted** (the server has it; it is not in HMIS until the worker confirms), **Needs attention** (with a plain reason). [TBC: "Submitted" means received by the server here, while a draft's own state "submitted" means entered in HMIS. Propose showing drafts as "Entered in HMIS" to avoid the clash.]
- **Upload:** when the browser reports it is online, when the app opens, and through Background Sync where supported. Retries back off exponentially (5 s, then doubling, capped at 5 minutes, with jitter) and never run more than one upload per entry at a time.
- **Idempotency:** every write request carries an `Idempotency-Key`. The server keeps the key with a hash of the request and the response. A repeat with the same key and request returns the stored response and creates nothing new; the same key with a different request is rejected as a conflict (Needs attention). The HMIS gateway sends a key per entry operation (draft ID, version, and step) so a lost response followed by a retry cannot enter a client twice [TBC with CHIP: whether the real HMIS accepts such a key]. The existing entry progress (steps already recorded are not repeated) and the possible-duplicate backstop stay.
- **Conflicts:** the server's existing checks still decide: an unknown or invisible client ID, a same-name match, an open draft for the same neighbor, an expired session, a draft that moved on, and the HMIS possible-duplicate rejection. Each shows as Needs attention or as the existing review flag, with the plain-words reason the email version gave.
- **Verification and confirmation for an entry written offline:** none happens on the device. When the entry uploads, the server parses it and runs the same-name lookup and the open-draft hash check, exactly as for an email. The worker sees the review (or the verification screen) the next time they are online and confirms there. The device never confirms on the worker's behalf, and a Confirm pressed for a version that is no longer current is refused as before. A Confirm press that cannot reach the server is not queued [proposal; TBC]: the button is disabled while offline, so a confirmation always reflects a review the worker saw against the server.

## 5. Offline safety [TBC with Goodwill and CHIP]
- **Stored on the device:** only queued entries (note type, client ID for updates, note text, time written, idempotency key, status) and the app shell. No query results, no drafts from the server, no other neighbors' data.
- **No SSN:** before saving, the app masks any full Social Security number in the note to its last four digits (the same rule the server applies) and tells the worker. [TBC: whether even the last four digits may be stored on the device.]
- **Encrypted:** queued entries are encrypted with AES-GCM using a non-extractable WebCrypto key created at sign-in and kept only in this browser profile.
- **Expiry:** an entry not uploaded within 72 hours becomes Needs attention and is deleted from the device after 7 days, matching the seven-day rule for unsubmitted notes [TBC].
- **Wipe:** signing out deletes the queue and the key. If entries are still queued, the app warns first and offers to upload them. An uploaded entry is deleted from the device as soon as the server confirms it has it.
- **Shared devices:** not supported [TBC]; each worker uses their own device and browser profile.

## 6. Read-only queries while offline [TBC]
Two options:
1. **Disabled offline (recommended):** the Ask HMIS screen says queries need a connection. Nothing about other neighbors is stored on the device.
2. **Stale snapshot:** the last answer per query type is kept on the device, encrypted, and shown labelled "as of <time>, may be out of date". Useful for a pre-visit briefing in a dead zone, but it puts other neighbors' minimal data on the device.
Either way, no query runs offline, and an online query is audited as now.

## 7. Email code: delete or keep as an optional channel? [TBC]
**Recommendation: keep the email code for now as an optional channel, off by default, and decide after the sponsor call (by Stage 6).**
- **For keeping it:** the direction is pending the sponsors; keeping the adapter avoids a revert if they keep email. The 500 tests exercise the core through email today, so they keep guarding the core while web tests are added. A worker without the app could still send a note.
- **Against keeping it:** two channels to maintain, test, secure, and audit; a second way for personal information to arrive (email bodies); spec text that has to say "when the email channel is enabled"; reviewers may assume both channels are supported.
- **If we delete it:** a smaller surface and one channel to reason about; the tag keeps the history. Do it in Stage 6 once the web tests cover the core.
Either way, the email-only requirements are REMOVED or MODIFIED in this change's deltas; if the team keeps email, a separate `email-channel` capability would bring them back explicitly.

## 8. Stages
1. Planning (this change) and archiving the three merged Week 10 changes.
2. Web API and auth on top of the existing core (split the workflow into a core and adapters).
3. Worker and supervisor UI reusing the review screens.
4. Offline queue and sync (service worker, IndexedDB, idempotency, retries, statuses).
5. Demo script and reset for the web flow, with an offline step (the presenter turns off the network and submits an entry).
6. Docs and handoff, and the email-code decision.

## Risks
- **A retry creates a duplicate in HMIS.** Mitigation: idempotency keys on every write and on every HMIS entry operation; entry progress; the possible-duplicate backstop.
- **Personal information on a lost device.** Mitigation: minimal, encrypted, expiring queue; wipe at sign-out; no query results offline (recommended).
- **Confirmation without a real review.** Mitigation: Confirm only online, only on the current version, only by the author.
- **Scope growth.** Mitigation: the same use cases only; new fields or reports are out of scope.

## Open questions [TBC]
1. Delete the email code or keep it as an optional channel (section 7). Ask: the team, after the sponsor call.
2. Device storage rules: last four SSN digits on the device, expiry times, shared devices. Ask: Goodwill and CHIP.
3. Queries offline: disabled or a stale snapshot. Ask: Horizon House, Goodwill.
4. Production sign-in and roles source (single sign-on, who assigns roles). Ask: Goodwill IT.
5. Whether the real HMIS accepts idempotency keys on entry operations. Ask: CHIP.
6. The "Submitted" label on device entries versus "submitted" drafts. Ask: Horizon House (worker wording).
7. Renaming the `encounter-email-intake` capability. Ask: the team.
8. Archive order: archive `add-hmis-readonly-queries`, `add-existing-client-updates`, and `add-no-contact-query` before this change.
