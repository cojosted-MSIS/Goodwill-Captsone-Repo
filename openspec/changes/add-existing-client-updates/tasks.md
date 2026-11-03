# Tasks

Depends on `add-hmis-readonly-queries` (the neighbor lookup and the read-only layer).

## 1. Decisions before code
- [ ] 1.1 Answer the open questions in `design.md` (service fields and Contact Service options, edits after save, override, match rule, retention, own-records check, supervisor corrections)
- [ ] 1.2 Configure the service fields and service types in `config/` (not code)

## 2. Mock HMIS
- [ ] 2.1 POST-only operations to add a case note and a service to an existing client, and to update entries made by this system
- [ ] 2.2 Unknown client ID fails with a plain-words reason and no other data
- [ ] 2.3 Possible-duplicate rejection keeps giving no details; `confirmed_distinct` accepted only with a reason
- [ ] 2.4 New entries appear in the read-only views; seed a same-name pair with matching digits and one with different digits

## 3. Update flow
- [ ] 3.1 "Update:" notes from authorized workers create update drafts
- [ ] 3.2 Client ID check (format and existence through the lookup); subject and note disagreement stops the draft
- [ ] 3.3 Lookup candidates by name and date of birth and the "CLIENT <ID>" reply
- [ ] 3.4 Parse a case note and a service entry (rule-based stub and REALLMS, same privacy rules)
- [ ] 3.5 Review, CONFIRM or corrections, entry of case note then service, retry from the failed step, receipt with entry IDs, audit without note text, email purge
- [ ] 3.6 Corrections after entry: new version referencing the entry ID, CONFIRM, update operation, audit field names only

## 4. Same-name verification
- [ ] 4.1 Lookup on every new-client draft with a full name and date of birth; say so when the check cannot run
- [ ] 4.2 Grade candidates by the second identifier; verification email; CONFIRM refused until SAME CLIENT <ID> or DIFFERENT PERSON with a reason
- [ ] 4.3 SAME CLIENT turns the draft into an update; DIFFERENT PERSON enters with the confirmed-distinct override
- [ ] 4.4 Audit the verification decision
- [ ] 4.5 Own-records check over open drafts with a keyed hash, if chosen in 1.1
- [ ] 4.6 Staging store retention changes, if chosen in 1.1

## 5. Screens and demo
- [ ] 5.1 Phone: update compose, query compose and replies, verification email and replies, receipt with entry IDs, correction reply
- [ ] 5.2 Staff: queries and verification decisions in the audit view
- [ ] 5.3 Demo Scenarios C, D (both outcomes), and E in `scripts/demo.py` and on the home screen; reset clears and reseeds
- [ ] 5.4 Retake the screenshots

## 6. Tests and checks
- [ ] 6.1 A test for every scenario in `specs/existing-client-updates`, `specs/review-and-submit`, and `specs/encounter-email-intake`
- [ ] 6.2 Update the docs (HANDOFF.md, PROMPTS.md for the new parser output, README)
- [ ] 6.3 `openspec validate add-existing-client-updates --strict`
