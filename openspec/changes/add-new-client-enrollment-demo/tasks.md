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
- [ ] 5.1 Screens matching mockups A1 to A5 and B1 to B8, plus a staged-record (API) view
- [ ] 5.2 One-command demo script for Scenario A (clean) and Scenario B (AI error corrected)

## 6. Validation
- [ ] 6.1 `openspec validate add-new-client-enrollment-demo --strict`
- [ ] 6.2 Tests for every scenario in the four specs
