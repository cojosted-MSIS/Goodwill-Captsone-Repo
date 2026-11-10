# Tasks

Pending the sponsor call (Goodwill, DeveloperTown). Start each stage only after approval.

## 1. Planning
- [x] 1.1 Map which modules are channel-independent and which are email-specific (`design.md` section 1)
- [x] 1.2 Proposal, design, and spec deltas for `web-application`, `offline-sync`, and the MODIFIED and REMOVED email requirements
- [ ] 1.3 Archive `add-hmis-readonly-queries`, `add-existing-client-updates`, and `add-no-contact-query` so this change's MODIFIED deltas apply
- [ ] 1.4 Answer the open questions in `design.md` that block Stage 2 (sign-in for the demo, roles)

## 2. Web API and auth on the existing core
- [ ] 2.1 Split `app/workflow.py` into a channel-neutral core (one method per action: submit note, correct, confirm, retry, pick client, same client, different person, correct after entry, ask query) and an email adapter; keep every existing test passing
- [ ] 2.2 A channel-neutral `Note` input for the parsers (author, submitted at, note type, text)
- [ ] 2.3 Users, roles, sessions (HttpOnly cookie, CSRF token), password hashes for synthetic demo accounts, passwords from `.env`
- [ ] 2.4 JSON API `/api/v1` for every worker, supervisor, and staff action; role checks; project visibility from the user record
- [ ] 2.5 Idempotency keys on every write (stored key, request hash, response); conflict on a reused key with a different request
- [ ] 2.6 Idempotency keys on HMIS entry operations in the gateway and the mock HMIS
- [ ] 2.7 Tests for every scenario in `specs/web-application` and the MODIFIED requirements

## 3. Worker and supervisor UI
- [ ] 3.1 Sign-in screen and role-based home
- [ ] 3.2 New-client note, "Update a neighbor", and "Ask HMIS" forms
- [ ] 3.3 Review screen with a corrections box and a Confirm button (reusing the current review screen)
- [ ] 3.4 Verification screen (SAME CLIENT per candidate, DIFFERENT PERSON with a reason), client picking, receipts, "Correct this entry"
- [ ] 3.5 Supervisor queue screen and in-app notices; staff views behind the staff role
- [ ] 3.6 Screenshots

## 4. Offline queue and sync
- [ ] 4.1 Service worker caching the app shell
- [ ] 4.2 IndexedDB queue, encrypted (AES-GCM, non-extractable key), SSN masking before saving
- [ ] 4.3 Upload with idempotency keys, exponential backoff with jitter, Background Sync where supported
- [ ] 4.4 Status per entry: Saved on device, Uploading, Submitted, Needs attention (with the reason)
- [ ] 4.5 Expiry and wipe at sign-out (with a warning for unsent entries)
- [ ] 4.6 Queries offline per the decision on `design.md` section 6
- [ ] 4.7 Tests, including a lost response followed by a retry creating no duplicate draft and no duplicate in HMIS

## 5. Demo
- [ ] 5.1 Demo script and reset for the web flow (Scenarios A to E3)
- [ ] 5.2 An offline step: the presenter turns off the network, submits an entry, sees Saved on device, turns the network back on, and sees it upload once

## 6. Docs and handoff
- [ ] 6.1 README, HANDOFF, CLAUDE.md, PROMPTS, CONFIDENCE, FUTURE for the web app
- [ ] 6.2 Decide and carry out the email-code decision (`design.md` section 7)
- [ ] 6.3 `openspec validate --all --strict`, the full tests, and the secret scan
