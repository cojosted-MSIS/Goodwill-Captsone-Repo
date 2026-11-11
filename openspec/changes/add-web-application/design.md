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
- **What works offline:** opening the app; writing a new-client note or an update note; seeing the status of queued entries. A correction needs the draft, so it needs a connection. Parsing, verification, review, confirmation, HMIS entry, and queries need the server.
- **Queue:** each entry is saved to IndexedDB with a client-generated idempotency key (a random UUID), the note type, the client ID for updates, the note text, and the time it was written. Status (Decided): **Saved on device**, **Uploading**, **Uploaded** (the server has it; it is not in HMIS until the worker confirms), **Needs attention** (with a plain reason). Drafts that have been entered are shown as **Entered in HMIS**.
- **Upload:** from the page, when the app opens and when the connection returns. Retries back off exponentially (5 s, then doubling, capped at 5 minutes, with jitter) and never run more than one upload per entry at a time.
- **Idempotency (built in Stage 2c):** every worker write accepts an `Idempotency-Key`. The server stores a SHA-256 hash of the key per user, a hash of the route and request, and the result as action, reference, and message IDs (never note text). A repeat returns the original result and creates nothing; the same key with a different request gets 409 (Needs attention); a repeat that arrives while the first is still running waits for its result; keys are forgotten after `web.idempotency_key_hours` (96, longer than the 72-hour device queue). Replays are audited with the type and draft ID only.
- **HMIS keys (built in Stage 2c):** when the author confirms a version, the core makes a random key and saves it with the draft before the first HMIS call; each step sends `<key>:<step>`, and every retry (RETRY, or Confirm on a failed draft) reuses it. No request can set it. The mock HMIS remembers accepted results by key: a repeat gets the first result with `Idempotent-Replay: true` and makes nothing, and the same key with a different request is refused. Its failure modes `timeout` (nothing saved) and `lost_response` (saved, then the same timeout) test both cases. A retry never reruns the same-name check, and the possible-duplicate backstop still applies to a new key [TBC with CHIP: whether the real HMIS accepts such a key].
- **Conflicts:** the server's existing checks still decide: an unknown or invisible client ID, a same-name match, an open draft for the same neighbor, an expired session, a draft that moved on, and the HMIS possible-duplicate rejection. Each shows as Needs attention or as the existing review flag, with the plain-words reason the email version gave.
- **Verification and confirmation for an entry written offline:** none happens on the device. When the entry uploads, the server parses it and runs the same-name lookup and the open-draft hash check, exactly as for an email. The worker sees the review (or the verification screen) the next time they are online and confirms there. The device never confirms on the worker's behalf, and a Confirm pressed for a version that is no longer current is refused as before. Decided: Confirm is disabled while offline and never queued, so a confirmation always reflects a review the worker saw against the server.

## 5. Offline safety (Decided for the demo; open items [TBC with Goodwill and CHIP])
- **Stored on the device:** only queued entries (note type, client ID for updates, note text, time written, idempotency key, status) and the app shell. No query results, no drafts from the server, no other neighbors' data.
- **No full SSN:** the queue holds the raw note text before the server parses it, so SSNs cannot be removed field by field. Instead, four layers act on the text in memory before anything is written to IndexedDB:
  1. **Mask by pattern.** The same pattern the server uses for a full number (`shared.ssn.any_full_number` in `config/mappings.yaml`: `123-45-6789` or nine digits in a row), sent to the app at sign-in, replaces each full number with `***-**-` and its last four digits. The worker sees the masked text and a notice before saving.
  2. **Block what looks like a full SSN in another form.** A looser detector (`shared.ssn.possible_full_number`) looks for an SSN word (SSN, social, soc sec) followed closely by seven or more digits in any grouping, such as `123 45 6789` or `123.45.6789`. If it matches after masking, the entry is not saved; the app asks the worker to rewrite it with only the last four digits.
  3. **Warn.** The note form says to write only the last four SSN digits.
  4. **Server second layer.** On upload, the server masks again exactly as for an email.
  Limits: a number written in words or split across sentences cannot be detected, which is why the warning stays [TBC with Goodwill and CHIP: whether this is enough]. Whether even the last four digits may be stored on the device is [TBC with Goodwill and CHIP]; if not, step 1 masks all nine digits and the worker adds the last four after upload.
- **Encrypted:** queued entries are encrypted with AES-GCM and sealed to the server, so the device holds no key that can read them (section 5a).
- **Expiry:** an entry not uploaded within 72 hours is deleted from the device, leaving a tombstone with no content so the loss is never silent (section 5a).
- **Wipe:** signing out deletes the queue and the cached public key. If entries are still queued, the app warns first and offers to upload them. A session that merely times out keeps the unreadable envelopes until sign-in or expiry (section 5a). An uploaded entry is deleted from the device as soon as the server confirms it has it.
- **Shared devices:** not supported in the demo [TBC with Goodwill and CHIP]; each worker uses their own device and browser profile.

## 5a. Stage 4 plan: the offline queue (approved Nov 11, 2026)
Section 5 sets the rules; this section says how they will be built, and what they cannot do.

### Encryption: seal each note to the server
Each queued note is encrypted so that **the device can write it but cannot read it back**.
- When a note is saved, the page makes a new random AES-GCM 256-bit key with WebCrypto, encrypts the note (text, title, time written, the known-invalid SSN label) with a random 96-bit nonce, then wraps that key with the server's RSA-OAEP public key (3072-bit, SHA-256). The AES key exists only in memory for that moment and is then dropped.
- IndexedDB holds only the envelope: format version, public key ID, wrapped key, nonce, ciphertext; and in the clear, the metadata the queue needs: owner username, note kind, Idempotency-Key, time saved, status, retry count, plain reason. The clear metadata is bound to the ciphertext as AES-GCM additional data, so it cannot be swapped between notes without decryption failing.
- **Key IDs and rotation.** Each envelope names its key by key ID, a hash of the public key. The server holds several private keys at once, read from the environment (`.env` for the demo; placeholders only in `.env.example`; never committed, printed, or logged), and encrypts nothing itself: it picks the private key by ID, so a rotation never strands a note. Production custody (a key vault) is [TBC with Goodwill IT].
- **Bound to the user and the key.** The user ID and the Idempotency-Key are AES-GCM associated data, so a note cannot be moved to another user or replayed under a different key without decryption failing. Tests prove both.
- **How the page trusts the public key.** The page fetches it over HTTPS from its own origin while signed in, the same trust it places in the code the origin serves. It checks that the key ID really is the hash of the key, so one ID can never name two keys. When the server offers a new key, new notes use it and queued notes keep their old key ID, which the server still holds. A compromised server could hand out its own key, and the page could not tell, because that server also serves the page's code (see "cannot protect against").
- **Why not a device key?** Section 5 first proposed a non-extractable WebCrypto key in IndexedDB. "Non-extractable" only stops JavaScript from exporting it: any script on the origin can still use it to decrypt, and the key's bytes sit on the same disk as the data, so someone with the files can recover both. Keeping a key only in memory would lose every note when the tab closes. Deriving a key from a PIN adds a step for workers outdoors and a short PIN can be guessed offline. Sealing to the server leaves no decryption secret on the device at all.
- **The cost:** once saved, the note cannot be read on the device. My notes shows "Note saved 10:31 AM" and its status only, not its kind, title, or text. What a worker can do about a refused note is under "Fixing a refused note" below.
- This needs one new, well-known server dependency: the Python `cryptography` package, because the standard library has neither RSA-OAEP nor AES-GCM.

### Where the key lives, and destroying it
- There is no key on the device to protect. It holds only the server's public key (with its ID, fetched at sign-in) and the envelopes. Nothing on the device can decrypt a note.
- **Sign-out:** if notes are waiting, the app warns and offers to upload them first. Then it deletes this user's envelopes, the cached public key and profile, and the rules; the server deletes the session. The app shell stays, because it holds nothing personal.
- **Sign-out while offline (decided Nov 11, 2026):** after the same warning, the app wipes the device at once, in one IndexedDB transaction: this user's envelopes and notices, the cached public key and rules, and the profile. The cookie is HttpOnly, so the page cannot clear it. The same transaction sets a pending sign-out flag. Every request first waits for the sign-out to finish, so it is the first request sent on reconnection (only the connection check goes ahead of it, and that sends no cookie), and nobody can sign in on this device until the server has answered. Because no CSRF token can exist by then, it has its own route, `POST /api/v1/auth/sign-out-device`: it can only end the caller's own session, the cookie is SameSite=Strict, and the request's Origin must match its Host. A reverse proxy must keep the Host header for this check [TBC with Goodwill IT: hosting].
- **The stored worker profile** (username, display name, role, last contact) is accepted for now, kept to the minimum the app needs to open offline [TBC with Goodwill].

### When the session expires while offline
The device cannot tell, and the note must neither leak nor be lost silently.
- Writing goes on: saving needs only the public key, so a worker offline past the 30-minute idle limit keeps working. The device allows saving for up to `web.offline_write_hours` after its last contact with the server (12, the absolute session limit) [TBC with Goodwill]; after that the form says to sign in when there is a connection.
- On reconnection the upload gets 401. The app keeps the envelopes, stops retrying, and shows "Sign in to upload your 2 saved notes". After sign-in it fetches a new CSRF token and uploads under each note's original Idempotency-Key.
- Nothing leaks in between, because the device cannot read the notes. An expired session therefore needs no wipe: the envelopes wait, unreadable, until sign-in or the 72-hour expiry.
- `web.offline_write_hours` is 12 [TBC with Goodwill]. **The server enforces it when the envelope arrives.** Each setup response carries a contact stamp, signed by the server, saying when it last spoke to this user. The stamp is sealed with the note. The server refuses a note written more than the limit after its stamp, a note with a forged stamp or another user's, a note dated in the future or before its stamp (beyond `web.device_clock_skew_minutes`), and a note older than the 72-hour limit. These checks run after the replay check, so a late retry of an accepted note still gets its first answer.
- **72-hour expiry:** from 60 hours the note shows a warning. At 72 hours the envelope is deleted and a tombstone with no content stays ("A note saved Nov 9 expired before it could be uploaded. Nothing was sent.") until the worker dismisses it. This replaces section 5's earlier seven-day idea.

### Shared devices [TBC with Goodwill]
Recommended for the demo: one worker per device and browser profile. If someone else signs in anyway, each note belongs to its owner: the new user sees only "1 note from another account is waiting on this device", with no time or kind, cannot upload it, and the server also refuses an envelope whose owner is not the signed-in user. It stays until its owner signs in or it expires. A person holding an unlocked, still-signed-in device can add notes under that worker's name, but cannot read any, and nothing reaches HMIS without that worker's Confirm.

### One envelope, one key (built in 4c)
Every note the page writes is checked and sealed in memory first, online or offline. If the server can be reached, that envelope is sent to `POST /api/v1/notes/sealed`; if the send fails, the same envelope is saved under the same Idempotency-Key. A first attempt that reached the server but lost its answer is therefore recognized as a repeat and can never make a second draft. An online note touches the device only if its upload fails. 

### Sync (built in 4d)
- **When:** the connection returning, the app opening, sign-in, and a check once a minute while notes are waiting. "Upload my saved notes" stays as a manual fallback.
- **Backoff:** 5 seconds, doubling to 5 minutes, with jitter (50 to 100 percent of the step). The state (times only) is in IndexedDB, so tabs and reloads share it. The connection returning, a sign-in, and the manual button skip the backoff.
- **Retry-After:** a 429 or 503 with Retry-After is never cut short, by anything, including the manual button. A header is capped at one hour, so a broken proxy cannot strand a note near its 72 hours. A 409 that means "still running" carries Retry-After and is retried.
- **Quiet while offline:** no upload is tried. The connection check runs once a minute online and backs off from 20 seconds to 2 minutes offline, with a hard limit of 3 a minute however often the worker changes screens; only the operating system's own online and offline events go around it.
- **One upload at a time:** a Web Lock across tabs; a tab that cannot take it leaves the work to the tab that holds it, and other tabs refresh through a BroadcastChannel that carries no content. Correctness does not depend on the lock: a repeat with the same Idempotency-Key is a replay.
- **Session and CSRF:** each run first asks who the browser's session really is, which also refreshes the CSRF token; a 403 refreshes it and tries once more. A 401, or a session belonging to someone else, stops the run, keeps the envelopes, and shows "Sign in to upload your 2 saved notes"; the run resumes after sign-in.
- **Audit:** `sealed_note_uploaded` records the actor, the type (new client or update), and a count, never content or keys. A replay is not counted again.

### Fixing a refused note (decided in 4d)
A refused note shows Needs attention with a fixed, plain reason from the server that holds no note content. The device cannot read the envelope, so nothing can be edited. The worker has two choices:
- **Try again:** sends the same envelope under the same Idempotency-Key. It is offered only where the cause can change: the server could not open it (for example the wrong account was signed in), a key the server no longer has, or a time that did not fit the server's clock. It is not offered where the same bytes would be refused again: past the offline limit, too old, a possible full SSN, or a conflict.
- **Delete:** after a warning that the note cannot be read, never reached the server as a draft, and must be written again from memory.

An earlier plan had the server open the note and show it back to its owner for correcting. That is dropped: it would add a route that returns note text, would show back a refused SSN, and is not needed for the demo. No key is added to the device. A note left in Needs attention still expires at 72 hours.

### Refused SSN text, and what is written where (task 4.0)
Masking and the looser detector run in memory, in `ui/web/ssn.js`, before any storage call and before any request, online or offline, on both the text and the title, using the server's patterns sent at sign-in; a table of test cases runs in both Node and Python to prove they agree, including digits from other alphabets. A note with a full number is first shown masked, with a notice, and is kept only when the worker presses the button again. Refused text stays only in the open form: no queue entry, no localStorage or sessionStorage, no auto-save, no log, no request. The note fields get `autocomplete="off"` and `spellcheck="false"`, and are cleared on `pagehide`.

### Service worker, headers, and updates
- The service worker precaches a fixed list of shell files (HTML, CSS, JS, font, icons) under a versioned cache, and answers only same-origin GET requests for exactly those paths, plus an offline fallback for navigations. Everything else, including every `/api/` request, goes straight to the network and is never cached.
- **The sync status line** comes from a real check (`/api/v1/ping` and every API call), not the browser's flag, which only says a network exists. Offline comes first, then Needs attention, then Uploading, then Online.
- **Offline is capture only.** The screens say so: "You can write notes now. You will review and confirm them when you are back online." A screen open when the connection goes keeps what is on it, with its buttons disabled; after an offline reload it shows only that it needs a connection.
- Every `/api/` response, including errors, carries `Cache-Control: no-store`. The app gets a strict Content-Security-Policy (no inline script, nothing from other origins), which limits what injected content could do.
- A new version installs and waits; it takes over only when no note is being typed. The envelope has a format version and IndexedDB changes are additive, so a new version can always read a queued note.
- Upload runs from the page (see "Sync"). Background Sync is dropped: Safari lacks it, and the service worker would need the CSRF token. A note waits until the app is next open.
- A correction needs the draft, which is never on the device, so corrections need a connection; only new notes and visit notes can be written offline.

### How it will be tested
1. **Logic, in Node with real WebCrypto:** the queue, statuses, expiry, backoff, and owner rules, with a fake clock and an in-memory store. SSN cases shared with Python.
2. **Across languages:** Node seals, Python opens; a changed byte or swapped metadata must fail.
3. **API, in pytest:** `no-store` on every `/api/` route and error; the upload route's roles, CSRF, owner check, and idempotency.
4. **A real browser:** headless Chrome over the DevTools protocol from Node (as `scripts/web_screenshots.mjs` does), against real servers. Offline is simulated with network emulation on the page and on the service worker's own target, and proven by **actually stopping the app server** and reloading, because emulation has not always covered service workers. Each scenario then inspects localStorage, sessionStorage, IndexedDB, and Cache Storage (every URL must be on the shell list), records every network request, greps the server log, and searches the browser profile's files for a sentinel string after closing it. That file search is supporting evidence only, since storage engines may compress values.

### What a browser can and cannot protect against
**It can protect against:** someone copying the browser's files or a backup reading queued notes; another site reading them (same-origin rule); a note surviving sign-out in readable form; API data lingering in caches.

**It cannot protect against:**
- An unlocked phone in someone's hands: they can see what is being typed and add notes.
- Malware, a rooted phone, or a compromised browser: text is in plain memory while typed, before it is sealed.
- A malicious or hacked server: it serves the code, and could change it. Encryption cannot defend against the party that ships the app.
- The keyboard and the operating system: predictive keyboards may learn words, cloud keyboards may send them, and the app switcher may keep a snapshot. Browsers may also restore form text after a crash despite the settings above.
- SSNs written in words or broken up, which the detector misses.
- A wrong device clock, which can stretch or shorten the 72 hours; the server checks the time written against its own bounds on upload.
- Metadata: someone with the files can see how many notes exist, when, of what kind, how long each is, and whose.
- Secure erase: deleted data may linger on flash storage until overwritten.
- Remote wipe: an offline, lost device cannot be told to delete anything; the 72-hour expiry runs only if the app opens.
- Eviction: the browser or OS may clear site data under storage pressure (Safari after about 7 days without use), which would lose a queued note. The app requests persistent storage, which is not guaranteed.

Service workers and `crypto.subtle` work only over HTTPS or on localhost, so a real phone needs the app served over HTTPS [TBC with Goodwill IT: hosting].

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

## 7e. Visual design (built in Stage 3e)
- **One style file.** `ui/web/style.css` starts with the design tokens as CSS variables; no color appears anywhere else in the file, so DeveloperTown can re-theme it by editing that block. A test checks the tokens and that every text and background pair has a contrast of at least 4.5:1.
- **Statuses.** Every status is a chip with a word and a small inline SVG icon: green for done, amber for check, red for not entered or past the limit, blue for in progress or corrected, grey for on the device or offline.
- **Inter, served with the app.** The font is in `ui/web/fonts/` under its SIL Open Font License, not loaded from a font service, so it works offline and the app makes no requests to another site.
- **Layouts.** Check your draft is one card per answer. The Confirm summary and buttons, and the different-person reason on the same-name check, sit in a bar that stays at the bottom of the screen while the page scrolls (`position: sticky`, so it never covers the end of the page). Workers have bottom navigation on their top-level screens. Supervisor and staff lists are real tables that stack into cards on a phone.
- **Same-name cards.** Each shows the client ID, first name and last initial, last contact, quadrant, and open items, plus one chip saying whether the last four SSN digits match, differ, or are missing, because the recommendation and the 40-character rule depend on it. The digits are never shown. Whether to show that chip at all is [TBC with Goodwill and CHIP].
- **Compact Confirm bar.** On the review screen the bar is one line ("3 entries in HMIS"), the Confirm button, and Make a correction; "See what will be entered" opens the full summary (a native `<details>`, so it works by keyboard without script).

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
9. Whether the same-name screen may show that the last four SSN digits match, differ, or are missing (never the digits). Ask: Goodwill and CHIP.
10. Offline: how long a device may keep accepting notes without reaching the server (12 hours for now), shared devices, and the worker profile kept on the device (username, display name, role, last contact). Ask: Goodwill.
11. Hosting over HTTPS, and custody of the private key that opens queued notes. Ask: Goodwill IT.
