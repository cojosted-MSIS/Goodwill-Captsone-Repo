## ADDED Requirements

### Requirement: Capture the Form 101 fields
The system SHALL draft a Form 101 (Outreach Observation) entry containing the applicant's name, the form date, how the information was collected, the location and dates the neighbor slept in a place not meant for human habitation, the agency name and address, and the staff member's name, title, and phone or email.

#### Scenario: Complete observation email
- **WHEN** a worker emails that they saw Pat Example sleeping in a bus shelter near Example St and Sample Ave on October 1 and October 2, 2026
- **THEN** the draft contains the applicant name, the location, and both dates
- **AND** the information source is set to outreach worker observation
- **AND** the agency details and staff details come from the worker's profile

### Requirement: Require a location and at least one date
The system SHALL require a location description and at least one date or date range for when the neighbor slept there, because the form must include the location and the date or dates.

#### Scenario: Relative date
- **WHEN** the email says the neighbor slept there "last week"
- **THEN** the draft shows the date range that "last week" resolves to, based on the date the email was sent
- **AND** the system asks the worker to confirm the range

#### Scenario: Location missing
- **WHEN** the email gives dates but no location
- **THEN** the system asks the worker for the location before presenting the draft

### Requirement: Record how the information was collected
The system SHALL set the information source to one of three values (outreach worker observation, written referral from a housing or service provider, or oral referral from a housing or service provider) and SHALL ask the worker when the email does not make it clear.

#### Scenario: First-hand observation
- **WHEN** the email describes something the worker saw themselves
- **THEN** the draft sets the source to outreach worker observation
- **AND** the draft shows the source for the worker to confirm

#### Scenario: Source unclear
- **WHEN** the email does not say how the information was obtained
- **THEN** the system asks the worker which of the three sources applies

### Requirement: Collect oral referral details
The system SHALL require the name, title, and contact number of the person providing the information, and the date and time of the conversation, when the information source is an oral referral.

#### Scenario: Missing provider details
- **WHEN** a worker's email says a housing provider reported by phone that a neighbor slept outside
- **AND** the email does not include the provider's contact number
- **THEN** the system asks the worker for it before presenting the draft

#### Scenario: Details complete
- **WHEN** the email includes the provider's name, title, contact number, and the date and time of the call
- **THEN** the draft records all four values

### Requirement: Handle signatures by a CHIP-accepted method
The system SHALL NOT record the staff signature, the applicant signature, or the release authorization as obtained based on email content, and SHALL present the entry as signatures pending until they are completed by a method CHIP accepts [TBC].

#### Scenario: Email claims consent
- **WHEN** the email says the neighbor agreed to the release of the information
- **THEN** the draft still shows the release authorization as pending a signature

#### Scenario: All fields complete, signatures outstanding
- **WHEN** every required field is filled but no signature has been completed by the accepted method
- **THEN** the draft is marked signatures pending
- **AND** the draft is not described as a complete verification

#### Scenario: Signed copy attached
- **WHEN** the worker attaches a photo or scan of the signed form
- **THEN** the system lists it for confirmation and enters it with the entry through `attach_document`
- **AND** whether it counts as complete depends on the CHIP-accepted method [TBC]

### Requirement: Limit location detail
The system SHALL capture location only as the description the worker writes, SHALL NOT collect device coordinates, including from photo metadata, and SHALL NOT copy location details to any map, shared channel, or report outside the HMIS entry.

#### Scenario: Photo with location data
- **WHEN** an email for this form includes a photograph with embedded location data
- **THEN** the system does not use that location data
- **AND** the location comes only from the worker's written description

#### Scenario: Location stays in the entry
- **WHEN** a Form 101 entry is submitted
- **THEN** the location appears only in the HMIS entry
- **AND** the audit record does not contain it

### Requirement: Enter the approved entry in HMIS
The system SHALL enter an approved Form 101 draft through the HMIS interface operation `record_outreach_observation`, using the neighbor identifier the worker supplied and approved, and SHALL tell the worker whether it was recorded.

#### Scenario: Submission succeeds
- **WHEN** HMIS accepts the entry
- **THEN** the worker receives a submission receipt

#### Scenario: Submission fails
- **WHEN** HMIS rejects the entry or cannot be reached
- **THEN** the draft moves to failed and goes back to the worker
- **AND** the worker receives a failure notice with the reason
