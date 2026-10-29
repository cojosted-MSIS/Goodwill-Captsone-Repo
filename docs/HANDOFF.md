# Developer handoff

A short guide for a developer picking up the Horizon House outreach intake prototype. The README has more detail on every command.

## What it is

An outreach worker emails a plain-language note after meeting someone new. The system drafts the HMIS new-client record from the note, emails the draft back for review, and after the worker replies CONFIRM, enters it into a **mock** HMIS: client, then program enrollment, then Coordinated Entry enrollment. Email is simulated, the HMIS is a local mock, and all data is synthetic.

## Run it

Needs Python 3.11 or newer (developed on 3.13). Edge or Chrome is needed only for the screenshot script.

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell; on macOS or Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest                                 # about 300 tests, no network or key needed
```

The presentation demo, in one command (ports 8765 and 8000 must be free):

```bash
python scripts/demo.py                 # walks through Scenarios A and B, Enter between steps
python scripts/demo.py --auto 8        # advance every 8 seconds
```

Or run the two servers and click through yourself:

```bash
python -m mock_hmis --port 8765        # terminal 1: entry-only mock HMIS
python -m app --port 8000              # terminal 2: intake app (add --db :memory: for a throwaway store)
```

Then open:

- Phone screens (the worker): http://127.0.0.1:8000/ui/
- Staff screens (parser run, mapped draft, staged record, audit): http://127.0.0.1:8000/ui/staff.html
- **Reset demo (demo only)** on the phone home screen clears everything between runs.

The default parser is a rule-based stub that needs no key. To use the live model, add your own REALLMS key to `.env` (copy `.env.example`) and start the app with `--parser reallms`. Read `docs/reference/reallms/REALLMS_GUIDE.md` first.

## Repo layout

| Path | What is there |
|---|---|
| `app/` | The intake workflow (`workflow.py`), staging store (`storage.py`, SQLite), validation, review email and screen data (`review.py`, `staff.py`), the API and UI routes (`api.py`), demo scenarios and the demo-only reset (`demo.py`, `demo_reset.py`), and the entry-only HMIS gateway (`hmis_gateway.py`) |
| `parser/` | The parser interface, the rule-based stub, the REALLMS parser and its prompt and checks, the scripted demo parser, and rules shared by all parsers |
| `mock_hmis/` | The mock HMIS service: POST-only entry routes plus demo admin routes |
| `ui/static/` | The screens: `index.html` and `app.js` (phone), `staff.html` and `staff.js` (staff), `common.js`, and two stylesheets. Plain HTML and JavaScript, no build step. |
| `config/` | Fields, validation rules, phrase rules, programs, workers, settings, HMIS rules. Change behavior here before changing code. |
| `sample-data/` | Synthetic emails, expected parses, evaluation notes, and the demo scenarios |
| `scripts/` | The presentation demo, the screenshot script, the model evaluation, and the prompt doc generator |
| `tests/` | The pytest suite, named after the spec scenarios |
| `openspec/` | The specs (see below) |
| `docs/` | This guide, `PROMPTS.md`, `CONFIDENCE.md`, `FUTURE.md`, screenshots, and reference material (HMIS manual excerpt, workflow mockups, REALLMS guide) |

`Prototype-Attempt1` and `push_test.py` at the top level are early repo setup tests, not part of the prototype.

## Where the specs are

`openspec/changes/add-new-client-enrollment-demo/` holds the proposal, the design (decisions, open questions, signature and photo notes), `tasks.md`, and four specs under `specs/`:

- `encounter-email-intake`: accepting notes and drafting from them
- `new-client-enrollment`: the client record and program enrollment
- `coordinated-entry-intake`: the Coordinated Entry enrollment and triage
- `review-and-submit`: review, CONFIRM, entry, screens, audit, and the demo reset

The specs are the source of truth: if code and spec disagree, the spec wins. After any spec edit, run `openspec validate add-new-client-enrollment-demo --strict` (needs Node.js and `npm install -g @fission-ai/openspec`). `CLAUDE.md` has the contributor rules.

## Rules that must not change

1. **Enter only, never read HMIS.** The system never searches, lists, or reads HMIS. The worker searches HMIS and says so in the note. Only success or failure and the IDs HMIS assigns come back. The gateway offers exactly three entry operations, and tests check that the mock HMIS answers no GET.
2. **No inferred values.** A field is filled only from what the note or the worker's reply states. Anything else stays blank and is flagged. "Client doesn't know", "client refused", and "data not collected" are used only when the text says so. No placeholder dates of birth or Social Security numbers.
3. **CONFIRM is required.** Nothing is entered until the note's author replies CONFIRM to the current version. CONFIRM is refused while a required field is missing, from anyone else, or for an older version.
4. **No secrets in the repo.** The REALLMS key lives only in `.env`, which is git-ignored. It is never committed, logged, put in a message, or sent to the browser. Search for secrets before every commit.

Also keep: synthetic data only, location at quadrant level, nothing recorded about people other than the neighbor, only the last four SSN digits, and no note text in logs or the audit record.

## Good to know

- `docs/PROMPTS.md` explains the live parser's prompt, schema, and settings. After changing the prompt, bump `PROMPT_VERSION`, re-run `scripts/eval_parser.py`, and run `python scripts/update_prompt_doc.py`.
- `docs/CONFIDENCE.md` explains the High, Medium, Worker and Review labels. They describe the note's wording, not correctness.
- `docs/FUTURE.md` covers signature documents and photos, which are out of scope.
- `python scripts/take_screenshots.py` regenerates `docs/screenshots/`.
