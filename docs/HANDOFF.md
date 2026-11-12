# Developer handoff

A guide for DeveloperTown picking up the Horizon House outreach prototype. The README has more detail on every command; `docs/QUESTIONS.md` lists every open question by who can answer it.

## What it is now

A **web application** for street outreach workers, with an optional email channel. A worker signs in on a phone, writes a plain-language note after meeting a neighbor, reviews the draft the system makes from it, and presses Confirm. Only then is anything entered in HMIS, here a **mock** HMIS. All data is synthetic.

What a worker can do:

- **Visit notes** for neighbors already in HMIS (the core of the product): each becomes a case note and a service entry on that client, after Confirm.
- **New neighbors**: client, program enrollment, then Coordinated Entry enrollment. Before review, the system checks HMIS for the same name and date of birth; a match shows a verification screen, and Confirm waits until the worker says same person (the note becomes a visit) or different person with a reason (entered with a confirmed-distinct override).
- **Four read-only questions** as fixed forms: a quadrant briefing, a lookup, a status check, and a 60-day no-contact watchlist. The model never writes SQL.
- **Write notes with no connection.** Offline is capture only: notes are sealed on the device and upload by themselves when the connection returns. Review, corrections, Confirm, and the questions need a connection.

Supervisors see drafts not confirmed within 48 hours and flagged decisions; staff see the audit. Neither can act for a worker or see note text.

## Run it

Needs Python 3.11 or newer (developed on 3.13). Node.js 22 or newer and Chrome or Edge are needed only for the browser tests, the screenshots, and `--auto` in the demo.

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell; on macOS or Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env                 # then set your own demo passwords in .env
python scripts/make_seal_key.py        # adds a sealing key to .env and prints only its key ID
pytest                                 # about 1,500 tests, no network or key needed
```

Run the two servers and use the app yourself:

```bash
python -m mock_hmis --port 8765        # terminal 1: mock HMIS (entry routes and read-only views)
python -m app --port 8000              # terminal 2: the app (add --db :memory: for a throwaway store)
```

Then open http://127.0.0.1:8000/app/ and sign in as `j.alvarez` (worker), `outreach.supervisor`, or `outreach.staff` with the passwords you set in `.env`.

The default parser is a rule-based stub that needs no key. To use the live model, add your own REALLMS key to `.env` and start the app with `--parser reallms`. Read `docs/reference/reallms/REALLMS_GUIDE.md` first.

## Run the demo

```bash
python scripts/demo.py                 # the web demo: Scenarios A to F, Enter between steps
python scripts/demo.py --auto 8        # advance every 8 seconds; a real Chrome window does Scenario F
python scripts/demo.py --email-channel # the original email demo, Scenarios A to E
```

The web demo stops at once, and says what to run, if the sealing key or a demo password is missing from `.env`. It never falls back to a temporary key, because Scenario F restarts the app server and a temporary key would be lost.

| Scenario | What it shows |
|---|---|
| A | A new neighbor with a complete note, confirmed and entered. An optional step writes it again to show the same-name check catch it. |
| B | A deliberate parser error, labeled on screen as a scripted demo example, and a missing answer; Confirm is refused, the worker corrects it, then confirms. |
| C | A visit note for Scenario A's client: a case note and a service entry. |
| D1, D2 | Same name and date of birth already in HMIS: same person (D1), and different person with a reason (D2). |
| E1 to E3 | The four questions: a SW briefing, a lookup and a status check, and the 60-day no-contact watchlist; then the staff query log. |
| F | Offline capture: network off, write a note, "Saved on device", network on, it uploads and appears as In review, then review and Confirm. |

At each pause: **Enter** goes on, **R** resets the demo (the mock HMIS, the server's drafts and audit, and the device), **S** skips the optional step (the duplicate after A, or all of F), **K** stops or starts the app server, and **Ctrl+C** stops everything.

**Going offline in Scenario F.** The script gives two ways, with the exact clicks. Prefer Chrome DevTools (F12, Network tab, the "No throttling" dropdown, Offline) on a Windows laptop: Chrome tells the app at once, so the status line and the upload react with no wait. The K key really stops the app server; use it when the DevTools panel is in the way or someone wants proof, and click My notes so the app checks at once. Turning off Wi-Fi does nothing, because the app runs on the laptop itself.

`python scripts/take_screenshots.py` regenerates every screenshot in `docs/screenshots/` and writes `docs/screenshots/INDEX.md`.

## How offline works, and what protects it

- **Capture only.** A note written offline, or one whose upload fails, is checked for full SSNs on the device (the same rules as the server, tested against one shared table), then **sealed**: a new AES-GCM key for each note, wrapped with the server's RSA-OAEP public key. The device keeps the envelope and a few clear fields (owner, kind, time saved, status, Idempotency-Key), never the text or title, and **holds no key that can read it back**. My notes shows "Note saved 10:31 AM" and a status: Saved on device, Uploading, Uploaded, or Needs attention.
- **Bound and checked.** Each envelope is bound to the user and its Idempotency-Key as authenticated data, so it cannot be moved to another account or replayed under another key. The server holds several private keys (rotation never strands a note), enforces the 12-hour offline limit with a signed contact stamp, checks the times against its own clock, and masks SSNs again.
- **Upload.** By itself when the connection returns, when the app opens, after sign-in, and on a slow check; one at a time across tabs (Web Locks); with backoff and jitter; never sooner than a server's Retry-After. A lost answer is retried under the same key and makes one draft. An expired session stops uploads and asks the worker to sign in.
- **Refused notes** show a plain reason that holds no note content. The worker can try again (only where the cause can change) or delete the note after a warning that it must be written again.
- **Limits.** 72 hours on the device, with a warning from 60; then the envelope is deleted and a notice with no content stays. Sign-out warns about unsent notes and wipes this worker's data from the device; a sign-out made offline wipes at once and is the first request sent on reconnection.
- **Never cached.** The service worker caches only the static app shell. Every /api/ answer is `no-store`. Refused SSN text is never written anywhere.

What a browser **cannot** protect against is written out in `openspec/changes/add-web-application/design.md`, section 5a: an unlocked phone in someone's hands, malware or a compromised browser, a malicious server (it ships the code), the keyboard and the operating system, SSNs written in words, a wrong device clock, metadata (how many notes, when, how long), secure erase on flash storage, remote wipe of a lost offline device, and eviction of site data by the browser.

## Two channels

The web app is the default and always on. The email channel (notes and replies by simulated email, the phone screens at /ui/, and the email demo) is kept as an option, **off by default** (`channels.email.enabled: false`, or `python -m app --email-channel`), until the sponsors decide whether to keep it as a fallback. Both channels use the same core (`app/core.py`), so every rule applies to both.

## What DeveloperTown would own in production

The prototype stands in for each of these; none is production-ready.

| Area | What the prototype does | What production needs |
|---|---|---|
| HMIS integration | A mock HMIS with entry routes and read-only views | An entry-only interface and read access agreed with CHIP; idempotency keys, the override, edits after save, and the real fields (`docs/QUESTIONS.md`) |
| Sign-in and roles | Synthetic accounts, passwords in `.env`, scrypt hashes, in-memory lockout | Goodwill's identity provider (single sign-on), roles from a directory, a shared lockout store |
| Hosting | Localhost | HTTPS (service workers and browser encryption need it), a reverse proxy that keeps the Host header, monitoring that never logs content |
| Keys | Private keys in `.env` | A key vault, a rotation procedure (keep old keys at least 72 hours), and who may hold them |
| Data | SQLite, retention jobs on a timer in the app | A managed database, backups, a real scheduler, and Goodwill's retention limits |
| The parser | A rule stub; REALLMS for synthetic text only | Where AI may run under Goodwill's AI policy, evaluation on real-shaped notes, and a human spot-check for multi-person notes |
| Devices | Any browser | Managed devices or a policy for shared ones, and a decision on the last four SSN digits on a device |
| Demo-only parts | `--demo-reset`, `--draft-content-views`, the email demo routes, the scripted Scenario B parser | Removed or switched off; none is safe with real data |

## Repo layout

| Path | What is there |
|---|---|
| `app/` | The channel-neutral core (`core.py`), the web API (`web_api.py`), sign-in and sessions (`auth.py`), opening sealed notes (`sealing.py`), the SSN guard (`ssn_guard.py`), the email channel (`email_channel.py`), the staging store (`storage.py`, SQLite), review data (`review.py`), the read-only queries (`queries.py`, `hmis_reader.py`), the entry-only gateway (`hmis_gateway.py`), and the demo reset (`demo_reset.py`) |
| `ui/web/` | The web app: `ui/web/index.html`, `ui/web/app.js` (routing and actions), `ui/web/screens.js` (pure screen functions), `ui/web/queue.js` (the device queue and sync rules), `ui/web/seal.js`, `ui/web/ssn.js`, `ui/web/device.js` (IndexedDB), `ui/web/sw.js` (the service worker), and `ui/web/style.css`. Plain modules, no build step. |
| `ui/static/` | The email demo's phone and staff screens |
| `parser/` | The parser interface, the rule-based stub, the REALLMS parser and its prompt and checks, and the scripted demo parser |
| `mock_hmis/` | The mock HMIS: POST-only entry routes, demo admin routes, and its SQLite records with the read-only views |
| `config/` | Fields, validation, phrase rules, programs, workers, accounts (`config/users.yaml`), settings, HMIS rules. Change behavior here before code. |
| `scripts/` | The demo (`scripts/demo.py`, `scripts/demo_web.py`, `scripts/demo_device.mjs`), screenshots, the sealing-key script, the model evaluation, and the doc generators |
| `tests/` | The pytest suite, named after spec scenarios; `tests/browser/` holds the real-browser scenarios |
| `openspec/` | The specs and changes |
| `docs/` | This guide, `QUESTIONS.md`, `PROMPTS.md`, `CONFIDENCE.md`, `FUTURE.md`, `DEPENDENCIES.md`, screenshots, and reference material |

`Prototype-Attempt1` and `push_test.py` at the top level are early repo setup tests, not part of the prototype.

## Where the specs are

`openspec/specs/` holds the current specs, one folder per capability. The open change `openspec/changes/add-web-application/` holds the web application: its proposal, its design (section 5a is the offline and security plan), its tasks, and spec deltas for `web-application`, `offline-sync`, and the MODIFIED email requirements. Earlier changes are archived in `openspec/changes/archive/`.

The specs are the source of truth: if code and spec disagree, the spec wins. After any spec edit, run `openspec validate --all --strict` (needs Node.js and `npm install -g @fission-ai/openspec`). `CLAUDE.md` has the contributor rules.

## Rules that must not change

1. **Write only through entry operations, only after Confirm.** Reads go only through the fixed, read-only, audited queries [TBC with CHIP]. Only success or failure and the IDs HMIS assigns come back from an entry. Confirm is never queued and is disabled offline.
2. **No inferred values.** A field is filled only from what the note or the worker's correction states. Anything else stays blank and flagged. No placeholder dates of birth or SSNs.
3. **The author confirms the current version.** Confirm is refused while a required answer is missing, from anyone else, for an older version, or while a same-name check is open.
4. **No secrets in the repo.** API keys, passwords, and sealing keys live only in `.env`, which is git-ignored, and are never committed, logged, printed, or sent to the browser. Run the secret scan before every push.
5. **Nothing about a client on the device** except the worker's own sealed notes. No query results, no drafts, no cached API answers.

Also keep: synthetic data only, location at quadrant level (the quadrant is entered on the Coordinated Entry contact and every service [TBC with CHIP: the real HMIS may have no place for a quadrant on a contact]), nothing recorded about people other than the neighbor, only the last four SSN digits, and no note text in logs or the audit.

## Good to know

- `docs/QUESTIONS.md` compiles every open item; `python scripts/update_questions_doc.py` refreshes its appendix, and a test fails if a new [TBC] has no question.
- `docs/PROMPTS.md` explains the live parser's prompt, schema, and settings. After changing the prompt, bump `PROMPT_VERSION`, re-run `scripts/eval_parser.py`, and run `python scripts/update_prompt_doc.py`.
- `docs/CONFIDENCE.md` explains the answer labels. They describe the note's wording, not correctness.
- `docs/FUTURE.md` covers signature documents and photos, which are out of scope.
- `docs/DEPENDENCIES.md` records each added dependency and its license.
