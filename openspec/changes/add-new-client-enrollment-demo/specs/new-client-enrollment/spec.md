## ADDED Requirements

### Requirement: Draft the basic client information
The system SHALL draft the new client's basic information containing first name, last name, name quality, date of birth with its data quality, Social Security digits with their data quality, race, ethnicity, gender, disabling condition, and veteran status, using the values the neighbor gave the worker.

#### Scenario: Complete basic information
- **WHEN** the email gives Pat Example's name, date of birth, race, ethnicity, gender, disabling condition, and veteran status
- **THEN** the draft contains each value
- **AND** each value cites its source sentence

#### Scenario: Neighbor gave a street name
- **WHEN** the email says the neighbor only gave a street name
- **THEN** the draft sets the name quality to "partial, street name, or code name reported"

#### Scenario: Full name given
- **WHEN** the email gives a first and a last name and contains none of the configured street-name phrases (such as "goes by", "street name", or "nickname")
- **THEN** the draft sets the name quality to "full name reported"
- **AND** the review email shows the name quality with its source sentence for the worker to check

### Requirement: Capture only the last four Social Security digits
The system SHALL capture only the last four digits of a Social Security number in the demo, SHALL show them masked in the review email, and SHALL discard any further digits [TBC]. When the email gives a full number, the system SHALL check it against the known invalid patterns kept in configuration (such as 123-45-6789, 999-99-9999, and all digits the same) before discarding it, and SHALL flag a match without showing the full number.

#### Scenario: Full number in the email
- **WHEN** the email includes a full Social Security number
- **THEN** the draft keeps only the last four digits
- **AND** the full number is not stored, shown, or logged

#### Scenario: Known invalid number
- **WHEN** the email includes the number 123-45-6789
- **THEN** the draft flags the Social Security number as a known invalid pattern
- **AND** the flag and the review email do not show the full number
- **AND** the system does not choose a data-quality option on its own

### Requirement: Draft the program enrollment
The system SHALL draft a program enrollment containing the project, the enrollment date, and a household of one with the relationship to head of household set to "self".

#### Scenario: Enrollment date defaults to the encounter date
- **WHEN** the email does not give an enrollment date
- **THEN** the draft uses the date of the encounter
- **AND** the review email shows the date for the worker to check

#### Scenario: Back-dated enrollment
- **WHEN** the email says the encounter happened on an earlier date
- **THEN** the draft uses that date as the enrollment date

#### Scenario: Project not stated
- **WHEN** the email does not name the project
- **THEN** the system asks the worker which project to enroll the neighbor in
- **AND** the system does not choose one

### Requirement: Draft the universal data elements for the enrollment
The system SHALL draft the prior living situation and, depending on the answer, the length of stay, the approximate date homelessness started, the number of times on the street, in emergency shelter, or in safe haven in the past three years, and the total months homeless in that period.

#### Scenario: Prior living situation is a place not meant for habitation
- **WHEN** the email says the neighbor stayed outside the night before
- **THEN** the draft sets the prior living situation to place not meant for habitation
- **AND** the system asks for any conditional field the email does not give

#### Scenario: Neighbor does not remember
- **WHEN** the email says the neighbor does not remember how many times they have been on the street
- **THEN** the draft uses "client doesn't know" for that field

### Requirement: Keep unsupported assessments out of the draft
The system SHALL NOT draft income and benefits, veteran assessment details, domestic violence assessment, health insurance, or additional household members, and SHALL list them in the review email as completed in HMIS by the worker.

#### Scenario: Email mentions income
- **WHEN** the email says the neighbor receives disability income
- **THEN** the draft does not record it
- **AND** the review email lists the income assessment as remaining to be completed in HMIS

### Requirement: Draft a case note narrative
The system SHALL generate a short case note from the email, limited to what the email states, SHALL mark it for the worker to read for wording, and SHALL send the confirmed case note with the program enrollment as an optional field [TBC].

#### Scenario: Case note sent with the program enrollment
- **WHEN** a confirmed draft is entered into HMIS
- **THEN** the case note is sent as an optional field of the program enrollment
- **AND** the audit record does not contain the case note text

#### Scenario: Case note generated
- **WHEN** a draft is staged
- **THEN** it includes a case note built only from statements in the email
- **AND** the case note is marked as generated

#### Scenario: Hedged refusal in the case note
- **WHEN** the email says a shelter bed was offered and the neighbor said "not tonight, maybe next week"
- **THEN** the case note says the bed was offered and declined
- **AND** the case note does not say the neighbor accepted it
