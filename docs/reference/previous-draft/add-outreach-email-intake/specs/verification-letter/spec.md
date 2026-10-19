## ADDED Requirements

### Requirement: Draft a verification letter on request
The system SHALL produce a draft Homeless Verification Letter when an authorized worker emails a request that includes the neighbor's details, and SHALL send the draft only to that worker.

#### Scenario: Letter requested
- **WHEN** a worker emails a request for a verification letter for Pat Example with the details the neighbor gave them in the field
- **THEN** the system returns a draft letter to the worker

#### Scenario: Delivery limited to the requester
- **WHEN** a draft letter is produced
- **THEN** it is sent only to the requesting worker
- **AND** it is not sent to the neighbor or any third party

### Requirement: Take details from the worker's email, not from HMIS
The system SHALL fill the neighbor's name, date of birth, and last four Social Security digits from the worker's email, which relays what the neighbor told the worker in the field, and SHALL NOT look them up in or read them from HMIS.

#### Scenario: Details supplied in the field
- **WHEN** the email includes the name, date of birth, and last four Social Security digits the neighbor gave the worker
- **THEN** the draft uses those values
- **AND** the system does not query HMIS

#### Scenario: Detail missing
- **WHEN** the email leaves out the name, date of birth, or last four digits
- **THEN** the system asks the worker for it before producing the draft

#### Scenario: Worker confirms the details
- **WHEN** a draft letter is produced
- **THEN** the draft shows the name, date of birth, and masked Social Security number for the worker to check against what the neighbor said
- **AND** the worker approves it with the same APPROVE, EDIT or REJECT commands used for other drafts

### Requirement: Print only the last four Social Security digits
The system SHALL print the Social Security number only as its last four digits (in the form xxx-xx-NNNN) and SHALL NOT include, store, or log a full Social Security number in the letter, any email, the draft, or the audit record.

#### Scenario: Masked output
- **WHEN** a draft letter is produced
- **THEN** the Social Security line shows only the last four digits

#### Scenario: Email contains a full number
- **WHEN** the worker's email includes more than the last four digits
- **THEN** the system keeps only the last four digits and discards the rest before building the draft

### Requirement: Use the approved wording, issue date, and validity period
The system SHALL use Horizon House's approved letter wording without altering its statements, SHALL include the issue date, and SHALL state that the letter is valid for 30 days.

#### Scenario: Letter dated and time-limited
- **WHEN** a draft letter is produced
- **THEN** it shows the issue date
- **AND** it states that it is valid for 30 days

### Requirement: Leave signing to the worker
The system SHALL NOT apply a signature on the worker's behalf, SHALL fill the signature block from the worker's profile (name, title, phone, and email), and SHALL NOT mark the letter as issued until the worker approves it.

#### Scenario: Draft is unsigned
- **WHEN** a draft letter is returned to the worker
- **THEN** it is unsigned
- **AND** it is labeled as needing the worker's review and signature before it goes to the neighbor

#### Scenario: Signer details come from the worker
- **WHEN** the worker's profile has a name, title, and contact details
- **THEN** the signature block uses them instead of fixed values from the template

### Requirement: Drafting a letter does not touch HMIS
The system SHALL NOT read from or write to HMIS as part of drafting or issuing a verification letter.

#### Scenario: Letter drafted
- **WHEN** a letter is drafted and approved
- **THEN** no query is made to HMIS
- **AND** no change is made to the neighbor's HMIS record
