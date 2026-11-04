# Tasks

Depends on `add-hmis-readonly-queries` (archive it first) and `add-existing-client-updates` (the enrollment view).

## 1. Config and seed
- [x] 1.1 `no_contact_days` and `no_contact_warning_days` in `config/settings.yaml`, with load-time checks
- [x] 1.2 Synthetic seed neighbors with last contacts 20, 52, 58, 60, 61, and 90 days before the demo day, plus an exited one and a hidden one; every seed date relative to the day the demo starts or resets

## 2. Parsing and validation
- [x] 2.1 `no_contact` query type in the parser interface, the live prompt and schema (`query-v2`), and the rule-based stub
- [x] 2.2 Validation: an optional quadrant, nothing else read from the email

## 3. Answer
- [x] 3.1 Fixed parameterized reads for the count by group and the rows (active enrollments, optional quadrant, visibility, row limit)
- [x] 3.2 The reply: two groups, minimal fields, most overdue first, "N more were not shown"
- [x] 3.3 Audit: query type, quadrant, row count

## 4. Screens, demo, docs
- [x] 4.1 Staff queries view and the phone "Ask HMIS" hint
- [x] 4.2 Demo Scenario E3 in `scripts/demo.py` and on the home screen
- [x] 4.3 Every document that said three query types (CLAUDE.md, specs, HANDOFF, README, PROMPTS)
- [x] 4.4 Screenshots of changed screens

## 5. Checks
- [x] 5.1 A test for every scenario in the spec delta
- [x] 5.2 `openspec validate --all --strict`, the full tests, and the secret scan
