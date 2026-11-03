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
