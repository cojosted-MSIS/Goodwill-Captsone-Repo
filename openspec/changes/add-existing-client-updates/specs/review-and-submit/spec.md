## MODIFIED Requirements

### Requirement: Enter only after CONFIRM from the author
The system SHALL enter a draft into HMIS only after the worker who wrote the note replies CONFIRM to the current version, SHALL ignore a CONFIRM from anyone else or for an earlier version, SHALL NOT accept a CONFIRM while a required field is missing, and SHALL NOT accept a CONFIRM while a same-name verification is waiting for SAME CLIENT <ID> or DIFFERENT PERSON.

#### Scenario: Confirm while a required field is missing
- **WHEN** the author replies CONFIRM to the current version while a required field is missing
- **THEN** nothing is entered into HMIS
- **AND** the draft stays in review
- **AND** the system replies listing the fields still needed before entry

#### Scenario: Confirm while a same-name verification is open
- **WHEN** the author replies CONFIRM to a new-client draft whose same-name verification has no answer yet
- **THEN** nothing is entered into HMIS
- **AND** the system replies asking for SAME CLIENT <ID> or DIFFERENT PERSON with a reason

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

### Requirement: Send unconfirmed drafts to a supervisor queue
The system SHALL move a draft that is still in review after 48 hours [TBC] to the state "expired", SHALL place every expired draft in the supervisor queue, SHALL notify the worker, and SHALL NOT enter it. Held notes and drafts that never reach submission, with their email copies, SHALL be deleted after a configured period (7 days).

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

#### Scenario: Deleted after seven days
- **WHEN** a held note or an expired or failed draft is 7 days old
- **THEN** it and its email copies are deleted, and its audit record remains without note text

### Requirement: Keep an audit record and delete email copies
The system SHALL record who confirmed each submission, when, the draft versions, and which fields the worker changed, SHALL NOT store the narrative text in the audit record, and SHALL delete the email copies after submission, within a retention limit set by Goodwill [TBC]. In production retention mode, the system SHALL also reduce each submitted draft to a stub of IDs, states, and times. Demo retention mode is the exception: it keeps the synthetic values so the staged record and submitted record screens still work.

#### Scenario: Confirmed submission
- **WHEN** a draft is submitted
- **THEN** the audit record shows the worker, the confirmation time, the versions, and the changed fields
- **AND** the audit record does not contain the email text

#### Scenario: Email copies removed
- **WHEN** a draft is submitted
- **THEN** the intake email and review emails are deleted within the retention limit

#### Scenario: Production mode reduces the draft
- **WHEN** a draft is submitted in production retention mode
- **THEN** only its IDs, states, versions, and times remain in the staging store

#### Scenario: Demo mode keeps the values
- **WHEN** a draft is submitted in demo retention mode
- **THEN** its synthetic values remain so the staff screens can show the submitted record
