# Tasks

The sponsors (Goodwill, DeveloperTown) confirmed the direction on Nov 10, 2026. Start each stage only after approval.

## 1. Planning
- [x] 1.1 Map which modules are channel-independent and which are email-specific (`design.md` section 1)
- [x] 1.2 Proposal, design, and spec deltas for `web-application`, `offline-sync`, and the MODIFIED and REMOVED email requirements
- [x] 1.3 Archive `add-hmis-readonly-queries`, `add-existing-client-updates`, and `add-no-contact-query` so this change's MODIFIED deltas apply
- [x] 1.4 Answer the open questions in `design.md` that block Stage 2 (decided Nov 10, 2026: demo sign-in, labels, offline queries and Confirm, device storage, email kept as an optional channel)

## 2. Web API and auth on the existing core
- [x] 2.0 Email channel behind a config flag, off by default for the web app (the email demo and the email tests turn it on; the email demo's unauthenticated routes are served only while it is on)
- [x] 2.1 Split `app/workflow.py` into a channel-neutral core (one method per action: submit note, correct, confirm, retry, pick client, same client, different person, correct after entry, ask query) and an email adapter; keep every existing test passing
- [x] 2.2 A channel-neutral `Note` input for the core and the parsers (author, title, time written, text; the note type is the action called); the email channel converts each email to one
- [x] 2.3 Users, roles (worker, supervisor), server-side sessions (HttpOnly SameSite=Strict cookie, Secure over https, idle and absolute timeouts, sign-out deletes the session), CSRF tokens, scrypt password hashes for synthetic demo accounts with passwords from `.env`, sign-in lockout and rate limit, sign-in audit
- [x] 2.4 JSON API `/api/v1` for every worker action (each IntakeCore action) and the supervisor queue; role checks on the server; author and project visibility from the user record
- [x] 2.5 Idempotency keys on every worker write (key hash per user, request hash, result without note text); 409 on a reused key with a different request; expiry; one result for simultaneous repeats; replays audited
- [x] 2.6 Idempotency keys on HMIS entry operations: made at Confirm and saved before the first call, reused by every retry; the gateway and the mock HMIS honor them; `timeout` and `lost_response` failure modes in the mock
- [ ] 2.7 Tests for every scenario in `specs/web-application` and the MODIFIED requirements (Stage 2b: sign-in, sessions, CSRF, lockout, audit, roles on every route, Note input, email flag; screens come in Stage 3)
- [x] 2.8 A staff role: read-only audit views with no note text or draft contents (the parser run and staged-record views stay email-demo routes [TBC])
- [x] 2.9 Drafts made in the web app get no review or verification emails, even with the email channel on

## 3. Worker and supervisor UI
- [x] 3.0 Messages as neutral keys worded per channel (email wording unchanged, web wording names the buttons); neutral audit event names with old names still read; the parser-run and staged-record views demo-only behind a flag, off by default
- [x] 3.1 Sign-in screen and the worker's home (my notes, notes waiting, recent messages); supervisor and staff homes come in 3d
- [x] 3.2 New-client note and visit note forms with the SSN warning, and the SSN masking and refusal on the server until Stage 4
- [x] 3.2a Looking things up: the four fixed query forms (no free text, no parser), plain results shown once, the same limits and audit as email, offline message; the free-text query route removed
- [x] 3.3 Review screen with source quotes and the four labels, a correction screen, and a Confirm button under a summary of what it will enter (reusing the review screen data in `app/review.py`)
- [x] 3.4 Verification screen (Same person per candidate, a different person with a reason and the 40-character rule), client picking with buttons, receipts with "Make a correction", and the failure screen with Try again
- [x] 3.5 Supervisor screens (the queue, flagged decisions with the reason and never the digits, each draft's state and audit trail) and staff screens (draft list, audit, query log); read-only, no neighbor information; the 48-hour rule applied in the web app
- [x] 3.6 Screenshots of every web screen in `docs/screenshots/web/`, phone and desktop
- [x] 3.8 Visual design: one themeable style file, statuses with a word and an icon, card and table layouts, bottom bars and navigation, Inter served with the app
- [x] 3.7 The retention jobs run in the web app with the email channel on or off, before each signed-in request and on a timer; the audit records the deletion's type and count only

## 4. Offline queue and sync
Stops for approval after each checkpoint. Plan: `design.md` section 5a.

**4a. Plan**
- [x] 4a.1 How the queue is encrypted, where the key lives, session expiry offline, shared devices, how offline is tested, and what a browser cannot protect against (`design.md` section 5a)

**4b. App shell and installability**
- [x] 4b.1 Web app manifest and icons
- [x] 4b.2 Service worker for the shell only, from a fixed list; an offline fallback page; never caches `/api/`
- [x] 4b.3 `Cache-Control: no-store` on every `/api/` response, with a test; a strict Content-Security-Policy
- [x] 4b.4 Update handling that cannot break a queued note
- [x] 4b.5 The real sync status line (Online, Offline, Uploading, Needs attention), and offline screens that say offline is capture only

**4c. The encrypted queue**
- [x] 4c.0 Refused SSN text is never written anywhere: not the queue, local or session storage, an auto-saved draft, a log, or the server; leaving the screen discards it
- [x] 4c.1 Seal each note on the device (AES-GCM, key wrapped to the server's public key); the server opens it; the `cryptography` dependency
- [x] 4c.2 Save when offline and when an upload fails
- [x] 4c.3 SSN masking and detection on the device, with the same rules as the server (shared test cases)
- [x] 4c.4 72-hour expiry with a warning and a tombstone; wipe at sign-out, with a warning for unsent notes
- [x] 4c.5 Statuses Saved on device, Uploading, Uploaded, Needs attention; a queued note shows on My notes without its content
- [x] 4c.6 Sign-out while offline wipes the device at once; the sign-out request goes first on reconnection, and nobody can sign in until it completes
- [x] 4c.7 The server enforces the offline limit and the time bounds when an envelope arrives; another user's envelope is refused

**4d. Sync**
- [ ] 4d.1 Each note's Idempotency-Key is made when it is saved and never regenerated
- [ ] 4d.2 Upload when the connection returns, with backoff and jitter, one upload per note at a time
- [ ] 4d.3 An expired session: ask to sign in, keep the sealed note, refresh the CSRF token, then upload
- [ ] 4d.4 A 409 and a duplicate never make two drafts; a rejected note moves to Needs attention with a plain reason
- [ ] 4d.5 Queries and Confirm disabled offline, and never queued; review and Confirm happen online after upload
- [ ] 4d.6 Browser tests: real offline, storage and cache inspection, a lost response then a retry

**4e. Demo and docs**
- [ ] 4e.1 See sections 5 and 6: the web demo with an offline step, offline and sync screenshots, handoff, future work, and the questions for Goodwill and CHIP

## 5. Demo
- [ ] 5.1 Demo script and reset for the web flow (Scenarios A to E3)
- [ ] 5.2 An offline step: the presenter turns off the network, submits an entry, sees Saved on device, turns the network back on, and sees it upload once

## 6. Docs and handoff
- [ ] 6.1 README, HANDOFF, CLAUDE.md, PROMPTS, CONFIDENCE, FUTURE for the web app
- [ ] 6.2 Decide and carry out the email-code decision (`design.md` section 7)
- [ ] 6.3 `openspec validate --all --strict`, the full tests, and the secret scan
