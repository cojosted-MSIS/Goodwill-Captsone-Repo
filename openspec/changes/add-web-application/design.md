# Design: Web application with offline support

> The Goodwill and DeveloperTown sponsors confirmed this direction on Nov 10, 2026. Decisions taken that day are marked "Decided"; open items are marked [TBC].

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
- **Auth (Decided):** server-side sessions in SQLite; an HttpOnly, Secure, SameSite=Strict cookie; a CSRF token on every write. Demo accounts are synthetic; their passwords come only from `.env` (placeholders in `.env.example`) and are stored only as hashes. No password is ever committed. Production sign-in through Goodwill's identity provider (single sign-on) [TBC with Goodwill IT].
- **Roles (Decided for Stage 2):** one role per account. Worker: own notes, drafts, receipts, and queries, within their project's visibility. Supervisor: the 48-hour queue. Staff: read-only audit views (draft IDs, states, workers, versions, times, entry identifiers, and the query log) with no note text, titles, field values, or written reasons. The parser run and staged-record views show draft contents, so they stay email-demo routes for now [TBC: who needs them]. Accounts are in `config/users.yaml`; a worker account names its record in `workers.yaml`, which holds the project.
- **Channel on each draft:** a draft remembers whether its note came from the web app or by email. Only email drafts get review and verification emails, even while the email channel is on.

## 4. Offline behavior
- **What works offline:** opening the app; writing a new-client note, an update note, or a correction; seeing the status of queued entries. Parsing, verification, review, confirmation, HMIS entry, and queries need the server.
- **Queue:** each entry is saved to IndexedDB with a client-generated idempotency key (a random UUID), the note type, the client ID for updates, the note text, and the time it was written. Status (Decided): **Saved on device**, **Uploading**, **Uploaded** (the server has it; it is not in HMIS until the worker confirms), **Needs attention** (with a plain reason). Drafts that have been entered are shown as **Entered in HMIS**.
- **Upload:** when the browser reports it is online, when the app opens, and through Background Sync where supported. Retries back off exponentially (5 s, then doubling, capped at 5 minutes, with jitter) and never run more than one upload per entry at a time.
- **Idempotency (built in Stage 2c):** every worker write accepts an `Idempotency-Key`. The server stores a SHA-256 hash of the key per user, a hash of the route and request, and the result as action, reference, and message IDs (never note text). A repeat returns the original result and creates nothing; the same key with a different request gets 409 (Needs attention); a repeat that arrives while the first is still running waits for its result; keys are forgotten after `web.idempotency_key_hours` (96, longer than the 72-hour device queue). Replays are audited with the type and draft ID only.
- **HMIS keys (built in Stage 2c):** when the author confirms a version, the core makes a random key and saves it with the draft before the first HMIS call; each step sends `<key>:<step>`, and every retry (RETRY, or Confirm on a failed draft) reuses it. No request can set it. The mock HMIS remembers accepted results by key: a repeat gets the first result with `Idempotent-Replay: true` and makes nothing, and the same key with a different request is refused. Its failure modes `timeout` (nothing saved) and `lost_response` (saved, then the same timeout) test both cases. A retry never reruns the same-name check, and the possible-duplicate backstop still applies to a new key [TBC with CHIP: whether the real HMIS accepts such a key].
- **Conflicts:** the server's existing checks still decide: an unknown or invisible client ID, a same-name match, an open draft for the same neighbor, an expired session, a draft that moved on, and the HMIS possible-duplicate rejection. Each shows as Needs attention or as the existing review flag, with the plain-words reason the email version gave.
- **Verification and confirmation for an entry written offline:** none happens on the device. When the entry uploads, the server parses it and runs the same-name lookup and the open-draft hash check, exactly as for an email. The worker sees the review (or the verification screen) the next time they are online and confirms there. The device never confirms on the worker's behalf, and a Confirm pressed for a version that is no longer current is refused as before. Decided: Confirm is disabled while offline and never queued, so a confirmation always reflects a review the worker saw against the server.

## 5. Offline safety (Decided for the demo; open items [TBC with Goodwill and CHIP])
- **Stored on the device:** only queued entries (note type, client ID for updates, note text, time written, idempotency key, status) and the app shell. No query results, no drafts from the server, no other neighbors' data.
- **No full SSN:** the queue holds the raw note text before the server parses it, so SSNs cannot be removed field by field. Instead, four layers act on the text in memory before anything is written to IndexedDB:
  1. **Mask by pattern.** The same pattern the server uses for a full number (`shared.ssn.any_full_number` in `config/mappings.yaml`: `123-45-6789` or nine digits in a row), sent to the app at sign-in, replaces each full number with `***-**-` and its last four digits. The worker sees the masked text and a notice before saving.
  2. **Block what looks like a full SSN in another form.** A looser detector (`shared.ssn.device_possible_full_number`) looks for an SSN word (SSN, social, soc sec) followed closely by seven or more digits in any grouping, such as `123 45 6789` or `123.45.6789`. If it matches after masking, the entry is not saved; the app asks the worker to rewrite it with only the last four digits.
  3. **Warn.** The note form says to write only the last four SSN digits.
  4. **Server second layer.** On upload, the server masks again exactly as for an email.
  Limits: a number written in words or split across sentences cannot be detected, which is why the warning stays [TBC with Goodwill and CHIP: whether this is enough]. Whether even the last four digits may be stored on the device is [TBC with Goodwill and CHIP]; if not, step 1 masks all nine digits and the worker adds the last four after upload.
- **Encrypted:** queued entries are encrypted with AES-GCM using a non-extractable WebCrypto key created at sign-in and kept only in this browser profile.
- **Expiry:** an entry not uploaded within 72 hours becomes Needs attention and is deleted from the device after 7 days, matching the seven-day rule for unsubmitted notes [TBC].
- **Wipe:** signing out deletes the queue and the key. If entries are still queued, the app warns first and offers to upload them. An uploaded entry is deleted from the device as soon as the server confirms it has it.
- **Shared devices:** not supported in the demo [TBC with Goodwill and CHIP]; each worker uses their own device and browser profile.

## 6. Read-only queries while offline (Decided: disabled)
The Ask HMIS screen says queries need a connection while offline. No query runs offline and no query result is stored on the device, so nothing about other neighbors is ever on it. (A stale snapshot, labelled with its time, was considered and not chosen.) An online query is audited as now.

## 7. Email code: delete or keep as an optional channel? [TBC with the sponsors]
**Decided for now (Nov 10, 2026): keep the email code as an optional channel, off by default behind a config flag (`channels.email.enabled: false`), and decide after the sponsors say whether they want email as a fallback.** The tradeoffs that led to this:
- **For keeping it:** the direction is pending the sponsors; keeping the adapter avoids a revert if they keep email. The 500 tests exercise the core through email today, so they keep guarding the core while web tests are added. A worker without the app could still send a note.
- **Against keeping it:** two channels to maintain, test, secure, and audit; a second way for personal information to arrive (email bodies); spec text that has to say "when the email channel is enabled"; reviewers may assume both channels are supported.
- **If we delete it:** a smaller surface and one channel to reason about; the tag keeps the history. Do it in Stage 6 once the web tests cover the core.
Either way, the email-only requirements are REMOVED or MODIFIED in this change's deltas; if the team keeps email, a separate `email-channel` capability would bring them back explicitly.

## 7a. Wording per channel (built in Stage 3a)
The core never writes wording. Each message to a worker or supervisor is a neutral key with parameters (`app/messages.py`), recorded with the message, and the draft's channel supplies the words: `app/email_wording.py` keeps the email text exactly (reply commands, reference tokens in subjects, which the email channel reads), and `app/web_wording.py` names the buttons on the screens. Short phrases inside flags, verification leads, and the review and receipt data follow the draft's channel the same way. Audit events are neutral (`ready_for_review`, `verification_requested`, `action_ignored`, `action_after_expiry`, `verification_answer_refused`, `copies_deleted`); rows recorded under the old names are read under the new ones, with `renamed_from`, so history is not broken. The parser-run, mapped-draft, and staged-record views show draft contents, so they are demo-only behind `demo.draft_content_views` (off by default; the email demo turns it on) [TBC with Goodwill: who needs them].

## 7b. Worker screens (built in Stage 3b)
- **No build step.** Plain HTML, one style file, and two ES modules served at `/app/` (`ui/web/`): `screens.js` holds pure functions that turn `/api/v1` data into escaped HTML, and `app.js` routes by the URL hash, calls the API (CSRF token and a fresh `Idempotency-Key` on every write), and handles the buttons and forms. No framework is needed for about fifteen screens, and none would add a build step. The app shell sits in one folder and `app.js` lists it (`SHELL`), ready for the Stage 4 service worker.
- **Tests render the real screens.** `tests/test_web_screens.py` renders every worker screen from real API data with `screens.js` in Node, the same code the browser runs, and checks the HTML: no email wording, a label on every field, buttons that say what they do, the Confirm summary above the button, Confirm disabled while a verification is open, escaped values, and no developer jargon. Node is needed only for these tests and the screenshots, never to run the app.
- **Screens.** Sign-in; my notes (drafts with "Entered in HMIS" and the other labels, notes waiting for the worker, recent messages as links); a new note and a visit note, each with the SSN warning; "Did you search HMIS?"; pick the client (one button per candidate); review (each answer with its source sentence and one of the four labels: Stated in your note, Check this: your note was not sure, From your correction, Written by the system: check the wording); a correction box; the same-name check (Same person per candidate, This is a different person with the 40-character rule when the SSN digits match); the receipt; and the failure screen with Try again. Confirm sits under a summary of each entry it will make. A sync status line in the header says Online until Stage 4 fills it in.
- **SSNs on the server for now.** Until the device queue exists, every text a worker types is guarded on the server before anything is kept (`app/ssn_guard.py`): full numbers are masked to the last four digits, and an SSN word followed by seven or more digits in another grouping is refused with a message asking for the last four only. When a masked number was a known invalid one, its label travels with the note so the parser still flags it. Stage 4 moves the same checks onto the device and keeps these as the server's second check.
- **Mobile first.** One column, text at 18px, buttons at least 52px tall and full width on a phone, high-contrast colors, a visible keyboard focus, a skip link, headings that take focus on each screen, and errors in `role="alert"` banners. Screenshots: `python scripts/take_screenshots.py --only web` writes `docs/screenshots/web/` at 390 px and 1280 px wide.

## 7c. Looking things up (built in Stage 3c)
- **Fixed forms, no parser.** Four forms with fixed fields: a quadrant for the briefing; a client ID, or a first and last name with the full date of birth, for a lookup; the same plus what to check (ID document or housing assessment) for a status check; and an optional quadrant for the no-contact watchlist. Each form becomes the same `QueryRequest` the email parser produces and goes through the same `check()`, read-only reader, row limit, 90-day briefing window, project visibility, and audit (`IntakeCore.ask_fixed`). The free-text `/api/v1/queries` route is gone; the email channel still reads "Query:" emails through the parser, which only picks a fixed type.
- **Plain results, shown once.** Results are structured for the screen (`app/queries.py` `structured`): each row is the client ID, first name and last initial, last contact date, quadrant, and one short detail (days without a contact, open items). The watchlist has "Past 60 days" and "Approaching 60 days" groups. A record the project cannot see is never read, so it is answered exactly as "No client was found with these details." Nothing is kept but the audit: no copy of the request and no copy of the answer. Queries take no Idempotency-Key, because they create nothing.
- **Offline.** The query screens say "You are offline" and disable the forms while the browser reports no connection, and the status line says Offline. Stage 4 replaces the browser flag with the sync state.
- **Short headings on the web.** Two review headings in `config/fields.yaml` carry long [TBC] notes; the web shows "Contact details" and "Service" with the note as a small hint (`WEB_SECTION_LABELS`). Email keeps the shared labels.
- **For Stage 4: refused SSN text.** A note refused because it still looks like it holds a full SSN stays only in the open form so the worker can rewrite it. It is never written to the device queue, browser storage, any saved or auto-saved draft, a log, or the server, and leaving the screen discards it (offline-sync spec, "Never keep refused SSN text").

## 7d. Supervisor and staff screens (built in Stage 3d)
- **Read-only, links only.** Supervisor: the queue of drafts not confirmed in time, decisions flagged because the SSN digits matched, every draft's state, and each draft's audit trail. Staff: the draft list, each draft's audit, and the query log. These screens have no buttons or forms, only links.
- **Show less.** A supervisor's views hold states, times, workers, HMIS identifiers, and the audit in plain words (`app/audit_text.py`, which uses only fixed words and safe details). No SSN digits, date of birth, title, field value, or note text [TBC with Goodwill: what supervisors may see]. The written reason appears only for a flagged decision, with any digits or dates hidden, even if the worker wrote them. Staff never see a reason, or the first word of a reply that an audit event records.
- **One supervisor for all drafts.** The demo has no team assignments, so a supervisor sees every draft [TBC with Goodwill: how teams are defined].
- **Views are not audited.** The existing rules audit HMIS reads, actions, and sign-ins, not views of the system's own records, so supervisor and staff views write nothing to the audit [TBC with Goodwill: should they].
- **The 48-hour rule in the web app.** Expiry ran only from a maintenance route of the email demo, which is off by default. The web API now applies it before each signed-in request, under a lock, so the queue is current and Confirm is refused after the limit, with no scheduler. A production scheduler is [TBC with Goodwill IT].
- **The retention jobs in the web app.** `IntakeCore.housekeeping` runs the 48-hour limit, the deletion of stored copies after their retention time, and the seven-day deletion of held notes and unsubmitted drafts, one run at a time. The web API runs it before each signed-in request, and the server runs it every `web.housekeeping_minutes` (15), so retention holds with the email channel off and with nobody signed in. The audit of a deletion records its type and count only.

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

## Decided on Nov 10, 2026
- The sponsors confirmed the web application direction.
- Email code: kept as an optional channel, off by default (config flag), until the sponsors decide [TBC].
- Device storage: the encrypted queue, the 72-hour expiry, and the wipe at sign-out are accepted for the demo, with SSN masking and blocking on the device (section 5).
- Queries are disabled offline. Confirm is disabled offline and never queued.
- Demo sign-in: synthetic accounts, passwords in `.env`, placeholders only in `.env.example`, never a committed password.
- Labels: drafts entered in HMIS are "Entered in HMIS"; device statuses are Saved on device, Uploading, Uploaded, Needs attention.
- The three merged Week 10 changes are archived before this change.
- Staff role: read-only audit views, sign-in required, no note text or draft contents.
- Drafts made in the web app get no review or verification emails, even with the email channel on.
- The sign-in lockout counts stay in memory for the demo [TBC with Goodwill IT].
- The idempotency key lifetime of 96 hours is accepted.
- The parser-run and staged-record views are demo-only, behind a flag that is off by default.
- The web shows short section headings ("Contact details", "Service") with the [TBC] notes as hints; email keeps its labels.
- Refused SSN text is never written to the device queue, browser storage, or any saved draft (for Stage 4).

## Open questions [TBC]
1. Keep or delete the email channel (section 7). Ask: the sponsors.
2. The last four SSN digits on the device; shared devices; whether the SSN layers are enough. Ask: Goodwill and CHIP.
3. Production sign-in and the source of roles (single sign-on, who assigns roles). Ask: Goodwill IT.
4. Whether the real HMIS accepts idempotency keys on entry operations. Ask: CHIP.
5. Renaming the `encounter-email-intake` capability. Ask: the team.
6. Sign-in lockout counts are in memory, so several app processes would each count separately. Ask: Goodwill IT.
7. Who needs the parser-run and staged-record views outside the demo (they show draft contents; demo-only for now). Ask: Goodwill.
8. What supervisors may see of a draft, how their teams are defined, and whether their views should be audited. Ask: Goodwill.
