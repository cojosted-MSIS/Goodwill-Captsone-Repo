## ADDED Requirements

### Requirement: Draft the Coordinated Entry enrollment
The system SHALL draft a Coordinated Entry enrollment for the new client in the Coordinated Entry project for the worker's region, and SHALL ask the worker for the region when the email does not give it.

#### Scenario: Region stated
- **WHEN** the email names the Coordinated Entry region
- **THEN** the draft records the region for the CE enrollment

#### Scenario: Region missing
- **WHEN** the email does not name the region
- **THEN** the system asks the worker for it
- **AND** the system does not choose one

### Requirement: Draft the triage assessment fields
The system SHALL draft the triage assessment containing assessment location, assessment contact type, current living situation, household type, information date, verified-by-project, and the contact service, and SHALL set the record-contact indicator to true.

#### Scenario: Triage from a street encounter
- **WHEN** the email describes meeting the neighbor in person outside
- **THEN** the draft sets the assessment contact type to an in-person street contact
- **AND** the draft sets the current living situation from what the email states
- **AND** the draft sets the record-contact indicator to true

#### Scenario: Household type
- **WHEN** the email describes a single adult
- **THEN** the draft sets the household type to single adult

### Requirement: Show consent as pending
The system SHALL show the Coordinated Entry client consent and signatures as pending and SHALL NOT record them as obtained from email content [TBC].

#### Scenario: Email says the neighbor agreed
- **WHEN** the email says the neighbor agreed to share their information
- **THEN** the draft still shows the consent as pending
- **AND** the review email says the worker completes the consent with the neighbor in HMIS

#### Scenario: Generated case note mentions consent
- **WHEN** the email says the neighbor "agreed to share his info, signed already"
- **THEN** the generated case note does not say that consent was given or signed
- **AND** each consent statement in the case note, including a case note rewritten after the worker's corrections, is replaced with "[consent pending]"

### Requirement: Leave scored and diversion assessments to the worker
The system SHALL NOT draft the VI-SPDAT, the diversion assessment, or the domestic violence and lethality questions, and SHALL list them in the review email as remaining to be completed in HMIS.

#### Scenario: Assessment outstanding
- **WHEN** a CE enrollment draft is staged
- **THEN** the review email lists the VI-SPDAT and the diversion assessment as remaining

### Requirement: Enter in the required order
The system SHALL enter the client record first, then the program enrollment, then the Coordinated Entry enrollment, and SHALL stop at the first failure.

#### Scenario: Client entry fails
- **WHEN** the client record is rejected
- **THEN** the system does not attempt the enrollments
- **AND** the draft moves to failed

#### Scenario: Enrollment fails after client entry
- **WHEN** the client record is accepted and the program enrollment is rejected
- **THEN** the system does not attempt the CE enrollment
- **AND** the worker is told which steps were recorded and which were not

#### Scenario: Retry resumes after the recorded steps
- **WHEN** the client record and program enrollment were accepted, the CE enrollment was rejected, and the worker retries the draft
- **THEN** the system attempts only the CE enrollment
- **AND** the system uses the client ID HMIS assigned on the first attempt
