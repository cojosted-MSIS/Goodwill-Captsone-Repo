# Goodwill Capstone: Horizon House outreach notes

Shared repository for the Goodwill Capstone team (Crimson Consulting Group) to build our outreach prototype.

## What it is

A **web application** for street outreach workers, with offline capture. A worker signs in on a phone, writes a plain-language note after meeting a neighbor, and the system:

1. Parses the note into draft HMIS fields. Each value keeps the words it came from and a confidence label. Anything not stated stays blank and is flagged.
2. Shows the draft on screen. The worker corrects it in plain words if needed, and presses **Confirm**.
3. After Confirm, and only then, enters it into a **mock** HMIS: for a visit, a case note and a service entry on the existing client; for someone new, the client, the program enrollment, then the Coordinated Entry enrollment with the triage assessment.

The worker can also ask four fixed read-only questions (a quadrant briefing, a lookup, a status check, and a 60-day no-contact watchlist) against the mock HMIS [TBC with CHIP]. Supervisors see drafts not confirmed in 48 hours; staff see the audit.

**Offline is capture only.** A note written with no connection is sealed on the device and uploads by itself when the connection returns. Review, corrections, Confirm, and the questions need a connection, and the screens say so: "You can write notes now. You will review and confirm them when you are back online."

The specs are the source of truth: [openspec/specs/](openspec/specs/) and the open change [openspec/changes/add-web-application/](openspec/changes/add-web-application/) (its `design.md` section 5a is the offline and security plan). Rules for contributors, including Claude Code, are in [CLAUDE.md](CLAUDE.md).

**Handoff docs for DeveloperTown:** [docs/HANDOFF.md](docs/HANDOFF.md) (start here), [docs/QUESTIONS.md](docs/QUESTIONS.md) (every open question, by who can answer it), [docs/PROMPTS.md](docs/PROMPTS.md), [docs/CONFIDENCE.md](docs/CONFIDENCE.md), [docs/FUTURE.md](docs/FUTURE.md), and [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md).

## Synthetic data only

**Never put real neighbor information anywhere in this repo**: not in code, tests, notes, prompts, screenshots, or commit messages. Use the made-up notes in [sample-data/](sample-data/) or write new made-up ones. This matters even more with the LLM parser, because note text is sent to an external service (REALLMS).

## Setup

You need Python 3.11 or newer (developed on 3.13) and git. Node.js 22 or newer and Chrome or Edge are needed only for the browser tests, the screenshots, and `--auto` in the demo.

```bash
git clone https://github.com/cojosted-MSIS/Goodwill-Captsone-Repo.git
cd Goodwill-Captsone-Repo

python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS or Linux:        source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env              # Windows: copy .env.example .env
python scripts/make_seal_key.py   # adds a sealing key to .env and prints only its key ID
```

Then open `.env` and choose your own passwords for the demo accounts (`DEMO_PASSWORD_J_ALVAREZ`, `DEMO_PASSWORD_M_CHEN`, `DEMO_PASSWORD_SUPERVISOR`, `DEMO_PASSWORD_STAFF`). `.env` is git-ignored. **Never commit a password, a key, or a session token.** Only scrypt hashes of the passwords are kept, in memory.

In VS Code, choose the `.venv` interpreter (Ctrl+Shift+P, "Python: Select Interpreter") so imports resolve.

### REALLMS key (only for the LLM parser)

The default parser is the rule-based stub, which needs no key. To use REALLMS (the IU-hosted LLM service), read [docs/reference/reallms/REALLMS_GUIDE.md](docs/reference/reallms/REALLMS_GUIDE.md) first. Each teammate needs their own key from the RT Projects allocation page (keys from the REALLMS Chat site do not work). Then:

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Then open `.env` and set `LLM_API_KEY` to your key. `LLM_BASE_URL` and `LLM_MODEL` are optional overrides. `.env` is git-ignored. **Never commit a key, paste it into code or config, or share it in chat.** If REALLMS answers `401 token_not_found_in_db`, the key is wrong, mistyped, has a stray line break, or is not approved: it is a key problem, not a code bug.

## Run the tests

```bash
pytest
```

About 1,500 tests. They use the rule-based stub, so they need no network or key. The browser tests drive real headless Chrome against a real app server that they stop and start, and are skipped if Chrome or Node.js is missing. One live REALLMS test runs only when `LLM_API_KEY` is set.

To check the specs (needs Node.js and `npm install -g @fission-ai/openspec`):

```bash
openspec validate --all --strict
```

## Run the web app

```bash
python -m mock_hmis --port 8765   # terminal 1: the mock HMIS
python -m app --port 8000         # terminal 2: the app (drafts kept in data/intake.db, git-ignored)
```

Open http://127.0.0.1:8000/app/ and sign in as `j.alvarez` (worker), `m.chen` (a second worker), `outreach.supervisor`, or `outreach.staff`, with the passwords you set in `.env`. On a laptop, Chrome can install it as an app. A real phone needs it served over HTTPS [TBC with Goodwill IT: hosting].

## Presentation demo

One command starts a fresh mock HMIS and app and walks through the scenarios in the real web app, waiting for Enter between steps:

```bash
python scripts/demo.py                 # the web demo, Scenarios A to F (ports 8765 and 8000 must be free)
python scripts/demo.py --auto 8        # advance every 8 seconds; a real Chrome window does Scenario F
python scripts/demo.py --no-browser    # only print the screens to open
python scripts/demo.py --skip-offline  # leave out Scenario F
python scripts/demo.py --email-channel # the original email demo, Scenarios A to E
```

It needs a sealing key and the demo passwords in `.env`, and stops and says what to run if they are missing. It never uses a temporary key, because Scenario F restarts the app server.

| Scenario | What it shows |
|---|---|
| A | A new neighbor with a complete note, confirmed and entered; an optional step writes it again to show the same-name check |
| B | A deliberate parser error, labeled on screen as a scripted demo example, and a missing answer; Confirm is refused, the worker corrects it, then confirms |
| C | A visit note for Scenario A's client: a case note and a service entry |
| D1 | Robin Demo: HMIS-C-000113 matches the SSN digits (recommended), HMIS-C-000114 does not; Same person makes it a visit |
| D2 | Sam Example: same name and date of birth, different SSN digits; Different person with a reason, entered as confirmed distinct |
| E1 to E3 | The four questions: a SW briefing, a lookup and a status check, and the 60-day no-contact watchlist; then the staff query log |
| F | Offline capture: network off, write a note, "Saved on device", network on, it uploads and appears as In review, then review and Confirm |

At each pause: **Enter** goes on, **R** resets the demo (the mock HMIS, the server's drafts and audit, and the device: its saved notes, notices, cached public key and rules, and profile; the app's own files stay), **S** skips the optional step (the duplicate after A, or all of F), **K** stops or starts the app server, and **Ctrl+C** stops everything.

**Going offline in Scenario F**, on a Windows laptop: prefer Chrome DevTools (F12, the Network tab, the "No throttling" dropdown, Offline). Chrome tells the app at once, so the status line and the upload react with no wait. Press **K** instead to really stop the app server, when the DevTools panel is in the way or someone wants proof; then click My notes so the app checks at once. Turning off Wi-Fi does nothing: the app runs on the laptop itself.

Screenshots of every screen are in [docs/screenshots/](docs/screenshots/) ([the list](docs/screenshots/INDEX.md)). To regenerate all of them (ports 8765 and 8000 must be free; needs Chrome or Edge and Node.js):

```bash
python scripts/take_screenshots.py
```

## Security design

- **Sealed notes, no key on the device.** A note kept on the device is encrypted with a new AES-GCM key, which is wrapped with the server's RSA-OAEP public key and dropped. The device can write a note but never read it back. The server holds the private keys (several at once, newest first, so a rotation strands nothing), from `INTAKE_SEAL_PRIVATE_KEYS` in `.env` [TBC with Goodwill IT: custody].
- **Bound to the user and the key.** The user ID and the Idempotency-Key are authenticated data, so a note cannot be moved to another account or replayed under another key. The server also checks a signed contact stamp (the 12-hour offline limit), the times against its own clock, and the SSNs again.
- **Little on the device.** Only the worker's sealed notes with a few clear fields, their profile, the public key, and the SSN rules. Never a query result, a draft, or an API answer: the service worker caches only the static app shell, and every /api/ answer is `no-store`. Notes expire after 72 hours; sign-out wipes them, after a warning.
- **SSNs.** Masked on the device and the server with the same rules (one shared test table); text that looks like a full number in another form is refused and never written anywhere.
- **Sessions.** Server-side, HttpOnly SameSite=Strict cookies, a CSRF token on every write, idle and absolute timeouts, a sign-in lockout, and a strict Content-Security-Policy.

**What a browser cannot protect against** (design section 5a): an unlocked phone in someone's hands, malware or a compromised browser, a malicious server (it ships the code), the keyboard and the operating system, SSNs written in words, a wrong device clock, metadata (how many notes, when, how long), secure erase on flash storage, remote wipe of a lost device that stays offline, and the browser evicting site data.

## Two channels

The **web app** is the default and always on. The **email channel** (notes and CONFIRM replies by simulated email, the phone and staff screens at /ui/, and the email demo) is kept as an option, **off by default**: `channels.email.enabled: false` in `config/settings.yaml`, or `python -m app --email-channel`. Whether email stays as a fallback is [TBC with the sponsors]. Both channels use the same core, so every rule below applies to both.

## What DeveloperTown would own in production

The HMIS integration (with CHIP), single sign-on and roles, HTTPS hosting, key custody and rotation, a managed database with backups and a real scheduler, where the AI parser may run, device policy, and removing every demo-only part (`--demo-reset`, `--draft-content-views`, the email demo routes, the scripted Scenario B parser). [docs/HANDOFF.md](docs/HANDOFF.md) has the table, and [docs/QUESTIONS.md](docs/QUESTIONS.md) the questions to settle first.

## How the core works

**Visit notes for a client already in HMIS** (the core of the MVP): in the web app, Add a visit; by email, a subject that starts with `Update:`. One note per visit, for example "Update: Jordan Sample" with "Saw Jordan Sample (HMIS-C-000101) in the SW quadrant. Gave her a bus pass. Spent 20 minutes with her." The system checks the client ID (format, and that the client exists and is visible) through the read-only lookup; with no ID, it looks the neighbor up by name and full date of birth and asks you to reply `CLIENT <ID>`, even when only one client matches. It drafts a case note and a service entry (service date, service type, contact type, quadrant, and time spent only if stated; the service fields and types are placeholders [TBC with Horizon House and CHIP]), and after CONFIRM adds them to the client's record. To correct an entry already made, reply to its receipt with the change; only the worker who wrote the note can, CONFIRM is needed again, and it is entered as an update (or, if HMIS does not allow edits, as a new entry that corrects the earlier one). Every contact records its quadrant (the new-client Coordinated Entry contact and every service), so a neighbor entered or visited appears in quadrant briefings right away [TBC with CHIP: the real HMIS may have no place for a quadrant on a contact].

**Same name and date of birth verification:** before a new-client draft goes to review, the system looks for clients in HMIS with the same first name, last name and full date of birth (the read-only lookup, only clients your project can see). If any match, you get a verification email instead of the review, listing each candidate's client ID, first name and last initial, quadrant, last contact, the date the record was entered, its enrollment status and its last service type (never a date of birth, SSN digits or case note text), graded by the last four SSN digits: matching digits are "likely the same person" (SAME CLIENT recommended when only one candidate has them; as a safeguard, since HMIS should not hold duplicates, two or more strong matches get a notice that they may be duplicates of each other in HMIS, no recommendation, and a "possible duplicate pair in HMIS" audit entry with client IDs only; the demo seed holds no duplicates), digits missing on either side are a hard stop (get the digits if you can), and different digits are a warning. CONFIRM is refused until you reply `SAME CLIENT <ID>` or `DIFFERENT PERSON: <reason>`. SAME CLIENT turns the note into an update (a case note and a service entry) for that client; answers such as gender or veteran status are listed as "update in HMIS yourself" and never written. DIFFERENT PERSON continues the new-client review and enters the client with a confirmed-distinct override carrying your reason [TBC with CHIP: whether the real HMIS allows an override]; when the SSN digits match, the reason must be at least 40 characters and the decision is flagged for supervisor review afterward, without blocking [TBC with Goodwill]. The mock HMIS still rejects a possible duplicate sent without the override, as a backstop that says nothing about the matching record.

**Open drafts for the same neighbor:** the lookup cannot see drafts still open here, so each open new-client draft keeps only a keyed hash (HMAC-SHA256) of the normalized name and date of birth. A second draft with the same hash gets a flag naming the other draft ID only. The hash is deleted at entry, expiry or failure. The key comes from `INTAKE_MATCH_KEY` in `.env`: required when `retention.mode` is `production` (the app refuses to start without it), and in `demo` mode a random key is made in memory for each run. `.env.example` holds only a placeholder; never commit a real key.

**Retention** (`config/settings.yaml`, `retention`): in `production` mode a submitted draft is reduced to a stub of IDs, states, versions and times. `demo` mode is the exception and keeps the synthetic values so the staff screens still work. In both modes, held notes and drafts never submitted are deleted with their emails after 7 days (`POST /maintenance/delete-unsubmitted`); their audit records stay and hold no note text.

**Read-only queries:** in the web app, four fixed forms under Look up (no free text and no parser). By email, a subject that starts with `Query:`, for example "Query: who has been reported in the SW quadrant?", "Query: look up Sam Example, DOB 2/14/1980", "Query: has client HMIS-C-000101's ID come in?", or "Query: who is coming up on 60 days with no contact?". The reply is an email. The parser only picks one of the four query types and copies its parameters; code validates them and runs fixed, parameterized reads (at most 25 rows). Replies never include an SSN, a date of birth, case note text, or a full last name, only records the worker's project can see are counted, and every query is audited without the returned values. A query never changes anything.

**Parser** (try it on one sample email):

```bash
python -m parser sample-data/emails/05_privacy_traps.txt
python -m parser sample-data/emails/02_hedged_referral_trap.txt --parser reallms --model qwen3.8-27b
```

**Evaluate REALLMS models** on the sample emails and the hard evaluation notes (needs the key; results go to the git-ignored `eval_results.json`):

```bash
python scripts/eval_parser.py
python scripts/eval_parser.py --models gemma-4-31B-it --parser-stub
```

Re-run it after any change to the prompt, schema, or model. Passing checks is not the same as correct: spot-check passing drafts by hand.

Latest run (2026-10-20, prompt `intake-v2.1`, 24 cases, temperature 0, strict json_schema, one retry then human review):

| Model | Valid | Correct | Sent to human review | Wrong but passed every check | Avg s |
|---|---|---|---|---|---|
| gemma-4-31B-it (default) | 24 | 22 | 0 | 2 | 12.4 |
| qwen3.8-27b | 24 | 22 | 0 | 2 | 23.2 |
| gpt-oss-120b | 23 | 18 | 1 | 5 | 19.2 |

Errors that passed the checks were an inferred length of stay (all three models), the word "signed" in the generated case note for `05_privacy_traps` (all three), and for gpt-oss-120b a past living situation used as the prior one (`e02`) and a refusal left blank (`e07`).

Fixed since that run: length of stay is kept only when its quote states how long (otherwise it is left blank and flagged), and consent statements in the generated case note become "[consent pending]". The times and months homeless checks now skip the number in a window such as "in 3 years", which had sent `02` to human review as a false alarm. A live re-run of `01`, `02`, `04` and `05` on gemma-4-31B-it had no wrong answers that passed the checks, and `02` now passes on the first reply with its inferred length of stay left blank and flagged.

> **Known blind spot: a correct-looking quote about the wrong person.** The two-person evaluation note (`e04` in `sample-data/eval_notes.yaml`) mentions Pete and a second man who is "staying with his mom". A parser can attach the other man's living situation to Pete with an exact, consistent quote, and every automated check passes, because the quote really is in the note and really does say "staying with his mom". The checks cannot tell whose sentence it is. Notes that mention more than one person need a human spot-check of the draft before any real use.

## The email channel (optional)

**The intake app and phone screens** (simulated inbox and outbox, review emails, CONFIRM, entry, audit), with the mock HMIS running:

```bash
python -m mock_hmis --port 8765      # terminal 1
python -m app --port 8000            # terminal 2 (drafts are kept in data/intake.db, git-ignored)
python -m app --parser reallms       # or use REALLMS (gemma-4-31B-it); INTAKE_PARSER=reallms also works
```

Open http://127.0.0.1:8000/ui/ for the phone screens: compose a note (or start a scenario, or use "Update a neighbor" or "Ask HMIS"), read the review email with each field's value, source quote and flags, reply CONFIRM or with changes, and see the HMIS receipt. CONFIRM is disabled while required fields are missing, and the workflow refuses it too. Every action is sent as a simulated email through the same workflow as `/inbox`. The default parser is the rule-based stub, so the screens run offline with no key; the key is never sent to the browser or written to the logs.

**Staff screens** at http://127.0.0.1:8000/ui/staff.html (after mockups A2 to A4 and B8): for each draft, the parser run (the fixed instructions, the note with a full SSN cut to its last four digits and precise locations and other people removed, the verified output with quotes and confidence, and which parser and model made it), the mapped draft, the staged record, and after entry the submitted record with the HMIS identifiers, any same-name verification decision, and the audit trail. A read-only queries view (`#/queries`) lists every query with its type, parameters and row count, never the returned values. If entry fails, the phone shows what failed in plain words (for example "The mock HMIS did not answer") and offers RETRY.

Screenshots of every phone and staff screen are in [docs/screenshots/](docs/screenshots/). To regenerate them in one command (it starts a fresh mock HMIS and app, so ports 8765 and 8000 must be free, and needs Edge or Chrome):

```bash
python scripts/take_screenshots.py
```

Scenario B uses a **scripted demo parser** (`sample-data/scenarios/scenarios.yaml`): for that exact note it returns a deliberate error (a declined shelter bed read as the current living situation, a mistake seen in the model evaluation) and leaves veteran status missing, so the demo always shows the worker catching a mistake. Those drafts are labelled on screen as a scripted demo example, not a live model result. If you edit the note before sending, it is parsed normally.

To use the API directly, send a worker email to `POST /inbox` as `{"raw": "<the whole email>"}`, read what the system sent with `GET /outbox/<worker address>`, reply with `CONFIRM` or plain-language changes by posting another email whose subject keeps the `[ENC-... vN]` tag, and look at the staged record with `GET /drafts/<id>` and its audit with `GET /drafts/<id>/audit`. `POST /maintenance/expire` moves drafts older than 48 hours to `GET /supervisor-queue`.

## Configuration

Field definitions, validation rules, phrase rules and settings live in [config/](config/), not in code:

| File | What it holds |
|---|---|
| `fields.yaml` | Draft fields, answer options, required rules, items left for HMIS |
| `validation.yaml` | Date and format rules, known invalid SSN patterns |
| `mappings.yaml` | Phrase rules for the stub parser, plus rules both parsers share (name quality, SSN, notices) |
| `programs.yaml` | Project and CE region IDs (placeholders), program defaults |
| `workers.yaml` | Worker records: address, display name, project (synthetic) |
| `users.yaml` | Web sign-in accounts and roles; passwords come only from `.env` |
| `settings.yaml` | Which parser to use, REALLMS model and fallbacks, timeouts, retries; `web` (sessions, sign-in limits, idempotency, the offline limits); `channels.email.enabled`; demo-only flags |
| `hmis.yaml` | What the mock HMIS requires and accepts |

To switch parsers, set `parser: reallms` in `config/settings.yaml`. The default model is `gemma-4-31B-it`; `qwen3.8-27b` is allowed as a fallback (set `LLM_MODEL` in `.env` for one run). `gpt-oss-120b` is marked not recommended after the model comparison and is refused unless `LLM_ALLOW_NOT_RECOMMENDED=1` is set; the comparison script still measures it. At startup the parser calls `GET /models` and stops with a clear message if the model is not listed.

## Repository layout

```
app/          the core, the web API, sign-in, sealing, the email channel, the staging store, the HMIS gateway
ui/web/       the web app: screens, the device queue, sealing, the service worker (served at /app)
ui/static/    the email demo's phone and staff screens (served at /ui when the email channel is on)
mock_hmis/    mock HMIS: entry routes and a read-only SQL layer
parser/       parser interface, rule-based stub, REALLMS parser, shared privacy rules
config/       YAML configuration
sample-data/  synthetic notes, the demo scenarios, and the expected parse for each
scripts/      the demo, screenshots, the sealing-key script, model comparison, doc generators
tests/        pytest suite; tests/browser/ holds the real-browser scenarios
openspec/     specs and changes
docs/         handoff docs, questions, screenshots, and reference material
```

## Out of scope for this demo

- HMIS reads beyond the fixed queries, and the real HMIS (we use a mock)
- Production hosting, sign-in, and key custody
- Signatures and consent signing (shown as pending), photos and ID documents
- Family or household members beyond a household of one
- VI-SPDAT, diversion, domestic violence, income and benefits, health insurance, veteran assessment details
- Coordinated Entry events and referrals
- Real email
