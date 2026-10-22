## ADDED Requirements

### Requirement: Stage the record before anything is entered
The system SHALL hold every parsed record as a staged draft that has not been entered into HMIS, and SHALL make the staged record viewable field by field with its value, type, source, and confidence.

#### Scenario: Draft staged
- **WHEN** the parser returns a draft
- **THEN** the draft is staged in the state "in review" after validation
- **AND** nothing is entered into HMIS

#### Scenario: Staged view
- **WHEN** a reviewer opens the staged record
- **THEN** each field is shown with its value, type, source, and confidence
- **AND** the view states that submission is blocked until the worker confirms

### Requirement: Validate drafts without silent correction
The system SHALL check each draft against required-field, format, and date rules, SHALL flag every problem in the review email, and SHALL NOT change a value on its own.

#### Scenario: Impossible date
- **WHEN** a draft has a date of birth in the future
- **THEN** the review email flags it
- **AND** the system does not change it

#### Scenario: Edit re-runs validation
- **WHEN** the worker corrects a value
- **THEN** the system re-runs validation before sending the next draft

### Requirement: Send a review email
The system SHALL email the worker a review of the draft showing every filled or flagged field beside its source and any flags, SHALL name on one line per section the blank fields that are not needed for this neighbor, SHALL tell the worker that nothing has been sent to HMIS, and SHALL invite the worker to reply CONFIRM or to reply with changes in plain words.

#### Scenario: Review email content
- **WHEN** a draft enters review
- **THEN** the worker receives an email titled with the draft's subject
- **AND** the email lists the filled and flagged fields, the flags, the assessments that remain for HMIS, and the draft version
- **AND** the email says nothing has been sent to HMIS

#### Scenario: Fields not needed for this neighbor
- **WHEN** a field is blank and not flagged, because the neighbor's answers make it unnecessary
- **THEN** the review email does not list it as its own line
- **AND** the email names it in that section's "not needed for this neighbor, left blank" line

### Requirement: Accept plain-language corrections
The system SHALL accept a reply that describes corrections in plain words, SHALL apply them to the same draft, SHALL mark the corrected fields as worker-sourced, and SHALL send a new version for review.

#### Scenario: Worker corrects a field
- **WHEN** the worker replies "it was the third time on the street, not the second"
- **THEN** the system changes the number of times on the street, in emergency shelter, or in safe haven in the past three years to three
- **AND** the field is marked as worker-sourced
- **AND** the system regenerates the case note to match
- **AND** the system sends draft version 2 for review

#### Scenario: Correction cannot be understood
- **WHEN** the reply cannot be matched to any field
- **THEN** the system asks the worker to rephrase
- **AND** the draft is unchanged

### Requirement: Enter only after CONFIRM from the author
The system SHALL enter a draft into HMIS only after the worker who wrote the note replies CONFIRM to the current version, SHALL ignore a CONFIRM from anyone else or for an earlier version, and SHALL NOT accept a CONFIRM while a required field is missing.

#### Scenario: Confirm while a required field is missing
- **WHEN** the author replies CONFIRM to the current version while a required field is missing
- **THEN** nothing is entered into HMIS
- **AND** the draft stays in review
- **AND** the system replies listing the fields still needed before entry

#### Scenario: Worker confirms
- **WHEN** the author replies CONFIRM to the current version
- **THEN** the draft moves to confirmed
- **AND** the system begins entry in the required order

#### Scenario: Confirm from someone else
- **WHEN** a CONFIRM arrives from an address other than the note's author
- **THEN** the system ignores it

#### Scenario: Confirm of an old version
- **WHEN** the author replies CONFIRM to version 1 after version 2 was sent
- **THEN** the system tells the author to review version 2
- **AND** nothing is entered

### Requirement: Enter into HMIS without reading from it
The system SHALL enter confirmed records into HMIS only through entry operations, SHALL NOT search, list, or read any HMIS record, and SHALL take back only success or failure and the identifiers HMIS assigns.

#### Scenario: Entry succeeds
- **WHEN** HMIS accepts the entries
- **THEN** the draft moves to submitted
- **AND** the worker receives a receipt listing the identifiers HMIS assigned

#### Scenario: Entry fails
- **WHEN** HMIS rejects an entry or cannot be reached
- **THEN** the draft moves to failed
- **AND** the worker receives a failure notice with the reason
- **AND** the notice and the failure screen say in plain words which step failed and why, for example "The mock HMIS did not answer", without note text or keys
- **AND** the confirmed draft is kept so the worker can retry

### Requirement: Review on phone-style screens
The system SHALL offer phone-style screens for the worker to send a note, read the review, reply, and see the HMIS receipt, SHALL send every worker action on these screens as an email through the same workflow as the intake inbox, SHALL show each field's value, source quote, origin, and flags, SHALL collapse the fields not needed for this neighbor as the review email does, SHALL disable CONFIRM while a required field is missing, and SHALL show the HMIS receipt after entry.

#### Scenario: Review screen
- **WHEN** the worker opens the current review on the phone screen
- **THEN** each filled or flagged field shows its value, its source quote, where it came from, and any flags
- **AND** the case note is marked as generated for the worker to check
- **AND** the screen says nothing has been sent to HMIS

#### Scenario: CONFIRM disabled while a required field is missing
- **WHEN** the current draft has a required field missing
- **THEN** the CONFIRM button is disabled and the missing fields are named beside it
- **AND** a CONFIRM typed in a reply is refused by the workflow as well

#### Scenario: Older version opened
- **WHEN** the worker opens the review email for a version that is no longer current
- **THEN** the screen says a newer version was sent and offers no CONFIRM for it

#### Scenario: Receipt shown
- **WHEN** HMIS accepts the entries
- **THEN** the receipt screen shows the identifiers HMIS assigned and the fields the worker corrected

### Requirement: Screen routes read only the staging store
The routes the screens use SHALL read only the intake system's own staging store and SHALL NOT search, list, or read HMIS. The phone screens SHALL open only emails the system sent, never the stored copy of a worker's note. The staff parser run screen SHALL show the worker's note only with a full Social Security number cut to its last four digits and precise locations and other people's details removed, and SHALL NOT show it once the email copies are deleted.

#### Scenario: Screens load a draft, inbox, or receipt
- **WHEN** a screen loads the worker's inbox, a review, a receipt, or a staff view
- **THEN** the data comes from the staging store
- **AND** the system makes no request to HMIS

#### Scenario: Stored note requested
- **WHEN** a phone screen asks for the stored copy of an email the worker sent
- **THEN** the system does not return it

#### Scenario: Note on the parser run screen
- **WHEN** the parser run screen shows a note that names a camp, another person, and a full Social Security number
- **THEN** the note is shown with the number cut to its last four digits and the location and the other person's details removed
- **AND** after the email copies are deleted, the screen says the note was deleted under the retention rule

### Requirement: Staff screens for the parser run, mapped draft, staged record, and audit
The system SHALL offer staff screens that show, for each draft, the parser run (the fixed instructions, the note, the verified structured output with each quote and confidence, and which parser and model produced it), the mapped draft by section, the staged record field by field, and after entry the submitted record with the identifiers HMIS assigned and the audit trail. The parser output shown SHALL be the verified output kept with the draft, never the raw model reply.

#### Scenario: Parser run
- **WHEN** a reviewer opens the parser run for a draft
- **THEN** the screen shows the parser and model that produced it and the instructions it follows
- **AND** each extracted value is shown with its quote and confidence as the parser produced it, even after the worker corrected the field

#### Scenario: Scripted draft on the parser run screen
- **WHEN** the draft came from the scripted demo parser
- **THEN** the screen labels it as a scripted demo example and marks the scripted value

#### Scenario: Submitted record with audit trail
- **WHEN** a reviewer opens a submitted draft
- **THEN** the screen shows the identifiers HMIS assigned and marks the fields the worker corrected as worker-sourced
- **AND** the audit trail lists each version, the corrections, the confirmation, each entry step, the submission, and the deletion of the email copies, without note text

### Requirement: Reset the demo between runs (demo only)
The demo SHALL offer a reset, labelled "demo only", that clears the mock HMIS records and its identifier counters and the local staging store (drafts, held notes, emails, audit records, and identifier counters). The reset SHALL act only when the configured HMIS address is on this machine and the HMIS answers as the mock HMIS, SHALL change nothing otherwise, SHALL require an explicit confirmation, and SHALL NOT be reachable through any email or reply.

#### Scenario: Reset before a second run
- **WHEN** the presenter resets the demo after Scenarios A and B were submitted
- **THEN** the home screen shows no drafts and the inbox is empty
- **AND** running Scenario A again is accepted, with the first identifiers HMIS-C-000001, HMIS-E-000002, and HMIS-CE-000003

#### Scenario: HMIS is not a local mock
- **WHEN** the configured HMIS address is not on this machine
- **THEN** the reset is refused before any request is sent
- **AND** nothing in the staging store is cleared

#### Scenario: HMIS does not answer as the mock
- **WHEN** the HMIS at the configured address does not answer the reset as the mock HMIS
- **THEN** the reset is refused and nothing in the staging store is cleared

#### Scenario: Email cannot reset
- **WHEN** a worker emails a note or a reply that says "reset demo"
- **THEN** nothing is reset and the email is handled as an ordinary note or reply

### Requirement: Resume a failed entry from the failed step
The system SHALL resume a retried entry at the step that failed, SHALL reuse the identifiers HMIS already assigned for the steps that succeeded, and SHALL NOT repeat a step that HMIS accepted.

#### Scenario: Retry after a partial failure
- **WHEN** the client record was accepted, a later step failed, and the worker retries the draft
- **THEN** the system starts at the step that failed
- **AND** the system uses the client ID HMIS assigned on the first attempt
- **AND** the system does not create the client again

### Requirement: Send unconfirmed drafts to a supervisor queue
The system SHALL move a draft that is still in review after 48 hours [TBC] to the state "expired", SHALL place every expired draft in the supervisor queue, SHALL notify the worker, and SHALL NOT enter it.

#### Scenario: Draft not confirmed in time
- **WHEN** a draft has been in review for 48 hours
- **THEN** the draft moves to expired
- **AND** the draft appears in the supervisor queue
- **AND** the worker is notified
- **AND** nothing is entered into HMIS

#### Scenario: Confirm after expiry
- **WHEN** the author replies CONFIRM to a draft that has expired
- **THEN** the system does not enter it
- **AND** the system tells the author the draft is with their supervisor

### Requirement: Keep an audit record and delete email copies
The system SHALL record who confirmed each submission, when, the draft versions, and which fields the worker changed, SHALL NOT store the narrative text in the audit record, and SHALL delete the email copies after submission, within a retention limit set by Goodwill [TBC].

#### Scenario: Confirmed submission
- **WHEN** a draft is submitted
- **THEN** the audit record shows the worker, the confirmation time, the versions, and the changed fields
- **AND** the audit record does not contain the email text

#### Scenario: Email copies removed
- **WHEN** a draft is submitted
- **THEN** the intake email and review emails are deleted within the retention limit
