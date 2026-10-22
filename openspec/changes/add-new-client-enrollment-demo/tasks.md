# Tasks

## 1. Foundation
- [x] 1.1 Scaffold the repo: `app/` (API and workflow), `mock_hmis/` (entry-only service), `parser/` (interface, stub, LLM), `ui/` (phone-style email view), `tests/`
- [x] 1.2 Load field definitions and validation rules from configuration files (not code)
- [x] 1.3 Add synthetic emails from `sample-data/emails/` as test fixtures

## 2. Mock HMIS (entry only)
- [x] 2.1 `create_client`, `enroll_in_program`, `create_ce_enrollment` with required-field checks and ordering
- [x] 2.2 Failure switches: missing required field, possible duplicate, service unavailable
- [x] 2.3 Confirm no read, search, or list endpoint exists

## 3. Parser
- [x] 3.1 Parser interface returning value, source sentence, and confidence per field
- [x] 3.2 Rule-based stub that passes all sample emails
- [x] 3.3 LLM implementation behind the same interface, synthetic data only
- [x] 3.4 Drop third-party details and keep location at quadrant level

## 4. Workflow
- [x] 4.1 Staged record and draft states
- [x] 4.2 Validation (required fields, formats, dates) that flags and never silently corrects
- [x] 4.3 Review email (v1) with CONFIRM and plain-language corrections; draft v2
- [x] 4.4 Entry into the mock HMIS in order; receipt and failure notice
- [x] 4.5 Audit record (who, when, changed-field flags, no narrative text) and deletion of email copies
- [x] 4.6 48-hour supervisor queue

## 5. Demo UI
- [x] 5.1 Phone screens matching mockups A1, A5, B1 and B5 to B7 (compose, inbox, review email, reply) plus the HMIS receipt, with read-only routes over the staging store
- [ ] 5.2 Staff screens matching mockups A2 to A4, B2 to B4 and B8 (parser run, mapped draft, staged record, submitted record with audit trail)
- [ ] 5.3 One-command demo script for Scenario A (clean) and Scenario B (scripted parser error corrected)
- [x] 5.4 Scripted, clearly labelled demo parser for Scenario B; the rule-based stub stays the default parser, with REALLMS as an option

## 6. Validation
- [x] 6.1 `openspec validate add-new-client-enrollment-demo --strict`
- [ ] 6.2 Tests for every scenario in the four specs
