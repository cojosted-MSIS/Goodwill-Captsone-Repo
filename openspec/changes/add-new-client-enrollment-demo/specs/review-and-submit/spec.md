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
The system SHALL email the worker a review of the draft showing every field beside its source and any flags, SHALL tell the worker that nothing has been sent to HMIS, and SHALL invite the worker to reply CONFIRM or to reply with changes in plain words.

#### Scenario: Review email content
- **WHEN** a draft enters review
- **THEN** the worker receives an email titled with the draft's subject
- **AND** the email lists the fields, the flags, the assessments that remain for HMIS, and the draft version
- **AND** the email says nothing has been sent to HMIS

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
The system SHALL enter a draft into HMIS only after the worker who wrote the note replies CONFIRM to the current version, and SHALL ignore a CONFIRM from anyone else or for an earlier version.

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
- **AND** the confirmed draft is kept so the worker can retry

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
