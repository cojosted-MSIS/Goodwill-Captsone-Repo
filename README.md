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

The default parser is the rule-based stub, which needs no key. To use REALLMS (the IU-hosted LLM service):

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Then open `.env` and replace the placeholder with your own key. `.env` is git-ignored. **Never commit a key, paste it into code or config, or share it in chat.**

## Run the tests

```bash
pytest
```

All tests use the rule-based stub and a mocked HTTP client, so they need no network. One live REALLMS test runs only when `REALLMS_API_KEY` is set and is skipped otherwise.

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
python -m parser sample-data/emails/02_hedged_referral_trap.txt --parser reallms --model glm-5.2
```

**Compare REALLMS models** on every sample email (needs the key):

```bash
python scripts/compare_models.py --models gpt-oss-120b glm-5.2 gemma-4-31B-it
```

**The intake app** (inbox, review emails, CONFIRM, entry, audit) is not built yet. See tasks 4 and 5 in tasks.md.

## Configuration

Field definitions, validation rules, phrase rules and settings live in [config/](config/), not in code:

| File | What it holds |
|---|---|
| `fields.yaml` | Draft fields, answer options, required rules, items left for HMIS |
| `validation.yaml` | Date and format rules, known invalid SSN patterns |
| `mappings.yaml` | Phrase rules for the stub parser, plus rules both parsers share (name quality, SSN, notices) |
| `programs.yaml` | Project and CE region IDs (placeholders), program defaults |
| `workers.yaml` | Intake address and authorized worker addresses (synthetic) |
| `settings.yaml` | Which parser to use (`rule_stub` or `reallms`), REALLMS model, timeouts |
| `hmis.yaml` | What the mock HMIS requires and accepts |

To switch parsers, set `parser: reallms` in `config/settings.yaml`. To try another model, change `reallms.model` there, or set `REALLMS_MODEL` in `.env` for one run.

## Repository layout

```
app/          intake workflow (config loader, email reader, HMIS gateway; more to come)
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
