# Tasks

Depends on `add-hmis-readonly-queries` (the neighbor lookup and the read-only layer).

## 1. Decisions before code
- [x] 1.1 Answer the open questions in `design.md` (match rule, retention mode, seven-day deletion, own-records check, corrections, demographics); the real service fields, edits after save, the override, and production supervisor approval stay [TBC]
- [x] 1.2 Configure the service fields and service types in `config/` (not code)

## 2. Mock HMIS
- [x] 2.1 POST-only operations to add a case note and a service to an existing client, and to update entries made by this system
- [x] 2.2 Unknown client ID fails with a plain-words reason and no other data
- [x] 2.3 Possible-duplicate rejection keeps giving no details; `confirmed_distinct` accepted only with a reason
- [x] 2.4 New entries appear in the read-only views (contacts with their quadrant)
- [x] 2.5 Seed a same-name pair with matching digits and one with different digits

## 3. Update flow
- [x] 3.1 "Update:" notes from authorized workers create update drafts
- [x] 3.2 Client ID check (format and existence through the lookup); subject and note disagreement stops the draft
- [x] 3.3 Lookup candidates by name and date of birth and the "CLIENT <ID>" reply
- [x] 3.4 Parse a case note and a service entry (rule-based stub and REALLMS, same privacy rules)
- [x] 3.5 Review, CONFIRM or corrections, entry of case note then service, retry from the failed step, receipt with entry IDs, audit without note text, email purge
- [x] 3.6 Corrections after entry: new version referencing the entry ID, CONFIRM, update operation, audit field names only
- [x] 3.7 Record the quadrant on every contact (new-client Coordinated Entry entry and each service) so briefings list the neighbor right away

## 4. Same-name verification
- [x] 4.1 Lookup on every new-client draft with a full name and date of birth; say so when the check cannot run
- [x] 4.2 Grade candidates by the second identifier; verification email; CONFIRM refused until SAME CLIENT <ID> or DIFFERENT PERSON with a reason
- [x] 4.3 SAME CLIENT turns the draft into an update; DIFFERENT PERSON enters with the confirmed-distinct override
- [x] 4.4 Audit the verification decision
- [x] 4.5 Own-records check over open drafts with a keyed hash; key from `INTAKE_MATCH_KEY`, required in production mode, random in memory in demo mode; placeholder in `.env.example`
- [x] 4.6 Retention mode setting (production stub at submission, demo keeps values) and seven-day deletion of held notes and unsubmitted drafts with their emails
- [x] 4.7 DIFFERENT PERSON on matching SSN digits: minimum reason length and a supervisor review flag in the audit

- [x] 4.8 Candidate cards show the entered date, enrollment status, and last service type (two more read-only views); two or more strong matches show a possible-duplicates notice, recommend none, and are audited with client IDs only; seed D1 as one strong match and one warning; the seed holds no duplicate records

## 5. Screens and demo
- [x] 5.1 Phone: update compose, query compose and replies, verification email and replies, receipt with entry IDs, correction reply
- [x] 5.2 Staff: queries and verification decisions in the audit view
- [x] 5.3 Demo Scenarios C, D (both outcomes), and E in `scripts/demo.py` and on the home screen (E's briefing shows a neighbor entered earlier in the demo); reset clears and reseeds
- [x] 5.4 Retake the screenshots

## 6. Tests and checks
- [x] 6.1 A test for every scenario in `specs/existing-client-updates`, `specs/review-and-submit`, and `specs/encounter-email-intake`
- [x] 6.2 Update the docs (HANDOFF.md, PROMPTS.md for the new parser output, README)
- [x] 6.3 `openspec validate add-existing-client-updates --strict`
