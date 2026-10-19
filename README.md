# Goodwill Capstone: Horizon House outreach email intake demo

Shared repository for the Goodwill Capstone team (Crimson Consulting Group) to build our outreach prototype.

## What the demo is

A street outreach worker emails plain-language notes after meeting a new neighbor. The system:

1. Parses the note into draft HMIS fields. Each value keeps the sentence it came from and a confidence level. Anything not stated stays blank and is flagged.
2. Emails the draft back to the worker, who replies CONFIRM or corrects it in plain words.
3. After CONFIRM, and only then, enters the record into a **mock** HMIS in order: new client, program enrollment, then Coordinated Entry enrollment with the triage assessment.

The system only enters data into HMIS. It never searches or reads HMIS. The worker searches HMIS themselves and says so in the email.

The specs are the source of truth: [openspec/changes/add-new-client-enrollment-demo/](openspec/changes/add-new-client-enrollment-demo/) (proposal, design, tasks, four specs). Rules for contributors, including Claude Code, are in [CLAUDE.md](CLAUDE.md). Progress is tracked in [tasks.md](openspec/changes/add-new-client-enrollment-demo/tasks.md).

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
openspec validate add-new-client-enrollment-demo --strict
```

## Run the pieces

**Mock HMIS** (entry only, a separate local service):

```bash
python -m mock_hmis --port 8765
```

It accepts only POSTs to `/clients`, `/clients/{id}/enrollments` and `/clients/{id}/ce-enrollments`, and returns only success or failure plus the IDs it assigns. It has no search, list or read route. For demos, `POST /_admin/failures` makes the next entry fail on purpose, and `POST /_admin/reset` clears everything.

**Parser** (try it on one sample email):

```bash
python -m parser sample-data/emails/05_privacy_traps.txt
python -m parser sample-data/emails/02_hedged_referral_trap.txt --parser reallms --model gpt-oss-120b
```

**Evaluate REALLMS models** on the sample emails and the hard evaluation notes (needs the key; results go to the git-ignored `eval_results.json`):

```bash
python scripts/eval_parser.py
python scripts/eval_parser.py --models gemma-4-31B-it --parser-stub
```

Re-run it after any change to the prompt, schema, or model. Passing checks is not the same as correct: spot-check passing drafts by hand.

**The intake app** (simulated inbox and outbox, review emails, CONFIRM, entry, audit), with the mock HMIS running:

```bash
python -m mock_hmis --port 8765      # terminal 1
python -m app --port 8000            # terminal 2 (drafts are kept in data/intake.db, git-ignored)
```

Then send a worker email to `POST /inbox` as `{"raw": "<the whole email>"}`, read what the system sent with `GET /outbox/<worker address>`, reply with `CONFIRM` or plain-language changes by posting another email whose subject keeps the `[ENC-... vN]` tag, and look at the staged record with `GET /drafts/<id>` and its audit with `GET /drafts/<id>/audit`. `POST /maintenance/expire` moves drafts older than 48 hours to `GET /supervisor-queue`. The phone-style screens (task 5) are not built yet.

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

To switch parsers, set `parser: reallms` in `config/settings.yaml`. The default model is `gemma-4-31B-it`; `gpt-oss-120b` and `qwen3.8-27b` are allowed as fallbacks (set `LLM_MODEL` in `.env` for one run). At startup the parser calls `GET /models` and stops with a clear message if the model is not listed.

## Repository layout

```
app/          intake workflow, staging store, validation, review emails, API, HMIS gateway
mock_hmis/    entry-only mock HMIS service
parser/       parser interface, rule-based stub, REALLMS parser, shared privacy rules
ui/           phone-style screens (not built yet)
config/       YAML configuration
sample-data/  synthetic emails and the expected parse for each
scripts/      model comparison
tests/        pytest suite
openspec/     specs and tasks
docs/         HMIS manual excerpts and workflow mockups (reference only)
```

## Out of scope for this demo

- Any HMIS search, lookup or read, and the real HMIS (we use a mock)
- Signatures and consent signing (shown as pending), photos and ID documents
- Family or household members beyond a household of one
- VI-SPDAT, diversion, domestic violence, income and benefits, health insurance, veteran assessment details
- Coordinated Entry events and referrals
- Real email and production deployment
