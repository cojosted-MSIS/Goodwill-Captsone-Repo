# Goodwill Capstone: Horizon House outreach email intake demo

Shared repository for the Goodwill Capstone team (Crimson Consulting Group) to build our outreach prototype.

## What the demo is

A street outreach worker emails plain-language notes after meeting a new neighbor. The system:

1. Parses the note into draft HMIS fields. Each value keeps the sentence it came from and a confidence level. Anything not stated stays blank and is flagged.
2. Emails the draft back to the worker, who replies CONFIRM or corrects it in plain words.
3. After CONFIRM, and only then, enters the record into a **mock** HMIS in order: new client, program enrollment, then Coordinated Entry enrollment with the triage assessment.

The system writes to HMIS only through entry operations after CONFIRM. It can answer three fixed read-only queries by email (a pre-visit briefing for a quadrant, a neighbor lookup, and a status check) against the mock HMIS [TBC with CHIP]. The worker still says in a new-client note that they searched HMIS.

The specs are the source of truth: [openspec/specs/](openspec/specs/) (one folder per capability) and the open changes in [openspec/changes/](openspec/changes/). The first change (proposal, design, tasks) is archived in [openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/](openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/). Rules for contributors, including Claude Code, are in [CLAUDE.md](CLAUDE.md). Progress is tracked in each open change's `tasks.md`.

**Handoff docs for DeveloperTown:** [docs/HANDOFF.md](docs/HANDOFF.md) (start here), [docs/PROMPTS.md](docs/PROMPTS.md) (the live parser's prompt, schema and settings), [docs/CONFIDENCE.md](docs/CONFIDENCE.md) (how confidence labels are produced), and [docs/FUTURE.md](docs/FUTURE.md) (signature documents and photos in production).

## Synthetic data only

**Never put real neighbor information anywhere in this repo**: not in code, tests, emails, prompts, screenshots, or commit messages. Use the made-up emails in [sample-data/emails/](sample-data/emails/) or write new made-up ones. This matters even more with the LLM parser, because note text is sent to an external service (REALLMS).

## Setup

You need Python 3.11 or newer (developed on 3.13) and git.

```bash
git clone https://github.com/cojosted-MSIS/Goodwill-Captsone-Repo.git
cd Goodwill-Captsone-Repo

python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS or Linux:        source .venv/bin/activate

pip install -e ".[dev]"
```

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

All tests use the rule-based stub and a mocked HTTP client, so they need no network. One live REALLMS test runs only when `LLM_API_KEY` is set and is skipped otherwise.

To check the specs (needs Node.js and `npm install -g @fission-ai/openspec`):

```bash
openspec validate --all --strict
```

## Run the pieces

**Mock HMIS** (a separate local service: POST-only entry routes, plus a read-only SQL layer for the fixed queries):

```bash
python -m mock_hmis --port 8765
```

It accepts only POSTs to `/clients`, `/clients/{id}/enrollments` and `/clients/{id}/ce-enrollments`, and returns only success or failure plus the IDs it assigns. It has no HTTP read route. Its records live in `data/mock_hmis.db` (git-ignored), seeded with synthetic neighbors from `sample-data/hmis_seed.yaml`; the intake app reads that file only through allowlisted read-only views. For demos, `POST /_admin/failures` makes the next entry fail on purpose, and `POST /_admin/reset` clears everything and reloads the seed data.

**Updates for a client already in HMIS** (the core of the MVP): send an email whose subject starts with `Update:`, one note per visit, for example "Update: Jordan Sample" with "Saw Jordan Sample (HMIS-C-000101) in the SW quadrant. Gave her a bus pass. Spent 20 minutes with her." The system checks the client ID (format, and that the client exists and is visible) through the read-only lookup; with no ID, it looks the neighbor up by name and full date of birth and asks you to reply `CLIENT <ID>`, even when only one client matches. It drafts a case note and a service entry (service date, service type, contact type, quadrant, and time spent only if stated; the service fields and types are placeholders [TBC with Horizon House and CHIP]), and after CONFIRM adds them to the client's record. To correct an entry already made, reply to its receipt with the change; only the worker who wrote the note can, CONFIRM is needed again, and it is entered as an update (or, if HMIS does not allow edits, as a new entry that corrects the earlier one). Every contact records its quadrant (the new-client Coordinated Entry contact and every service), so a neighbor entered or visited appears in quadrant briefings right away [TBC with CHIP: the real HMIS may have no place for a quadrant on a contact].

**Same name and date of birth verification:** before a new-client draft goes to review, the system looks for clients in HMIS with the same first name, last name and full date of birth (the read-only lookup, only clients your project can see). If any match, you get a verification email instead of the review, listing each candidate's client ID, first name and last initial, quadrant, last contact, the date the record was entered, its enrollment status and its last service type (never a date of birth, SSN digits or case note text), graded by the last four SSN digits: matching digits are "likely the same person" (SAME CLIENT recommended when only one candidate has them; as a safeguard, since HMIS should not hold duplicates, two or more strong matches get a notice that they may be duplicates of each other in HMIS, no recommendation, and a "possible duplicate pair in HMIS" audit entry with client IDs only; the demo seed holds no duplicates), digits missing on either side are a hard stop (get the digits if you can), and different digits are a warning. CONFIRM is refused until you reply `SAME CLIENT <ID>` or `DIFFERENT PERSON: <reason>`. SAME CLIENT turns the note into an update (a case note and a service entry) for that client; answers such as gender or veteran status are listed as "update in HMIS yourself" and never written. DIFFERENT PERSON continues the new-client review and enters the client with a confirmed-distinct override carrying your reason [TBC with CHIP: whether the real HMIS allows an override]; when the SSN digits match, the reason must be at least 40 characters and the decision is flagged for supervisor review afterward, without blocking [TBC with Goodwill]. The mock HMIS still rejects a possible duplicate sent without the override, as a backstop that says nothing about the matching record.

**Open drafts for the same neighbor:** the lookup cannot see drafts still open here, so each open new-client draft keeps only a keyed hash (HMAC-SHA256) of the normalized name and date of birth. A second draft with the same hash gets a flag naming the other draft ID only. The hash is deleted at entry, expiry or failure. The key comes from `INTAKE_MATCH_KEY` in `.env`: required when `retention.mode` is `production` (the app refuses to start without it), and in `demo` mode a random key is made in memory for each run. `.env.example` holds only a placeholder; never commit a real key.

**Retention** (`config/settings.yaml`, `retention`): in `production` mode a submitted draft is reduced to a stub of IDs, states, versions and times. `demo` mode is the exception and keeps the synthetic values so the staff screens still work. In both modes, held notes and drafts never submitted are deleted with their emails after 7 days (`POST /maintenance/delete-unsubmitted`); their audit records stay and hold no note text.

**Read-only queries** (by email, with both servers running): send an email whose subject starts with `Query:`, for example "Query: who has been reported in the SW quadrant?", "Query: look up Sam Example, DOB 2/14/1980", or "Query: has client HMIS-C-000101's ID come in?". The reply is an email. The parser only picks one of the three query types and copies its parameters; code validates them and runs fixed, parameterized reads (at most 25 rows). Replies never include an SSN, a date of birth, case note text, or a full last name, only records the worker's project can see are counted, and every query is audited without the returned values. A query never changes anything.

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

**Presentation demo** (one command, task 5.3): starts a fresh mock HMIS and app, opens the screens in your browser, and walks through the scenarios step by step, waiting for Enter between steps. The servers keep running afterwards until Ctrl+C.

| Scenario | What it shows |
|---|---|
| A | A clean new-client note, confirmed on the first reply |
| B | A scripted parser error and a missing field, corrected by the worker |
| C | An `Update:` note for Scenario A's client, using the client ID from Scenario A's receipt: a case note and a service entry |
| D1 | Robin Demo: HMIS-C-000113 matches the SSN digits (recommended), HMIS-C-000114 is an older, exited record with different digits (a warning); SAME CLIENT HMIS-C-000113 makes it an update |
| D2 | Sam Example: same name and date of birth, different SSN digits; DIFFERENT PERSON with a reason, entered as confirmed distinct |
| E1, E2 | Read-only `Query:` emails: a SW briefing that lists Scenario A's client, then a status check for Jordan Sample's ID; then the staff queries view |

```bash
python scripts/demo.py                  # ports 8765 and 8000 must be free
python scripts/demo.py --auto 8         # advance every 8 seconds instead of waiting for Enter
python scripts/demo.py --no-browser     # only print the screens to open
python scripts/demo.py --skip-duplicate # leave out the duplicate step
```

At each pause, Enter goes on and **R** resets the demo and starts again. After Scenario A, an optional step resends the same note to show the same-name check catching it (a verification email, CONFIRM refused, nothing entered); type **S** at the Scenario A receipt to skip it. Scenario C fills in the client ID from Scenario A's newest receipt; if Scenario A was skipped or the demo was reset, its card says to run Scenario A first and its Start button is disabled.

**Reset demo (demo only):** the button on the phone home screen (and R in the demo script) clears the mock HMIS records and the staging store (drafts, inbox, audit) and restarts the ID counters, so you can rerun the scenarios without restarting the servers. It only acts when the configured HMIS address is on this machine and the HMIS answers as the mock; otherwise nothing is cleared. No email or reply can trigger it.

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
| `workers.yaml` | Intake address and authorized worker addresses (synthetic) |
| `settings.yaml` | Which parser to use (`rule_stub` or `reallms`), REALLMS model and fallbacks, timeouts, retries |
| `hmis.yaml` | What the mock HMIS requires and accepts |

To switch parsers, set `parser: reallms` in `config/settings.yaml`. The default model is `gemma-4-31B-it`; `qwen3.8-27b` is allowed as a fallback (set `LLM_MODEL` in `.env` for one run). `gpt-oss-120b` is marked not recommended after the model comparison and is refused unless `LLM_ALLOW_NOT_RECOMMENDED=1` is set; the comparison script still measures it. At startup the parser calls `GET /models` and stops with a clear message if the model is not listed.

## Repository layout

```
app/          intake workflow, staging store, validation, review emails, API, HMIS gateway
mock_hmis/    mock HMIS: entry routes and a read-only SQL layer
parser/       parser interface, rule-based stub, REALLMS parser, shared privacy rules
ui/           phone-style screens (ui/static, served at /ui)
config/       YAML configuration
sample-data/  synthetic emails and the expected parse for each
scripts/      model comparison, screenshot regeneration
tests/        pytest suite
openspec/     specs and tasks
docs/         HMIS manual excerpts and workflow mockups (reference only)
```

## Out of scope for this demo

- HMIS reads beyond the fixed queries, and the real HMIS (we use a mock)
- Signatures and consent signing (shown as pending), photos and ID documents
- Family or household members beyond a household of one
- VI-SPDAT, diversion, domestic violence, income and benefits, health insurance, veteran assessment details
- Coordinated Entry events and referrals
- Real email and production deployment
