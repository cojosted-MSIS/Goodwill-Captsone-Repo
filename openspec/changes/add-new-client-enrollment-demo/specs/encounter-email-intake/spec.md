## ADDED Requirements

### Requirement: Accept messages only from authorized workers
The system SHALL process only emails sent to the designated intake inbox by senders on the authorized worker list.

#### Scenario: Message from an unrecognized sender
- **WHEN** an email arrives from an address that is not on the authorized worker list
- **THEN** the system drops the message without processing it
- **AND** the system does not reply with any neighbor information

### Requirement: Require a statement that the worker searched HMIS
The system SHALL draft a new client only when the worker's email states that they searched HMIS and found no existing record, and SHALL NOT search or read HMIS itself.

#### Scenario: Worker states no match
- **WHEN** the email says the worker searched HMIS and found no match
- **THEN** the system drafts a new client from the details in the email
- **AND** the system does not query HMIS

#### Scenario: Search not stated
- **WHEN** the email gives new client details but does not say the worker searched HMIS
- **THEN** the system asks the worker to confirm they searched and found no match
- **AND** the system does not create a draft until the worker does

### Requirement: Fill draft fields only from the email
The system SHALL fill a draft field only with a value stated in the email, SHALL leave every other field blank and flagged, and SHALL record for each filled field the sentence it came from and a confidence level.

#### Scenario: Value not stated
- **WHEN** the email does not state a value the HMIS entry needs
- **THEN** the draft leaves that field blank
- **AND** the draft flags the field for the worker

#### Scenario: Source and confidence recorded
- **WHEN** the system fills a field from the email
- **THEN** the draft stores the source sentence and a confidence level for that field

#### Scenario: Generated text marked for review
- **WHEN** the system generates a case note narrative from the email
- **THEN** the draft marks the narrative as generated and needing the worker's review

### Requirement: Label values that come from program defaults or email metadata
The system SHALL fill a field from configuration or email metadata only for program facts (verified-by-project, assessment location for the CE region, and the street outreach assessment contact type) and for the encounter date when the email body does not state one, SHALL label each such value with the source "program default" or "email date", SHALL show those values with their labels in the review email, and SHALL NOT fill any answer the neighbor gives from configuration or metadata.

#### Scenario: Program default shown
- **WHEN** the draft fills verified-by-project from configuration
- **THEN** the review email shows the value with the source "program default"

#### Scenario: Encounter date taken from the email date
- **WHEN** the email body does not state the date of the encounter
- **THEN** the draft uses the date the email was sent as the encounter date
- **AND** the review email shows that date with the source "email date"

#### Scenario: Client answers never defaulted
- **WHEN** the email does not state a value the neighbor would give, such as race or veteran status
- **THEN** the system does not fill it from configuration or email metadata
- **AND** the field stays blank and flagged

### Requirement: Never make up answers for the client
The system SHALL use "client doesn't know", "client refused", or "data not collected" only when the email says so, and SHALL NOT supply a placeholder birth date, Social Security number, or other answer.

#### Scenario: Client did not know their birth date
- **WHEN** the email says the neighbor does not know their date of birth
- **THEN** the draft sets the birth date quality to "client doesn't know"
- **AND** the draft leaves the birth date blank

#### Scenario: Worker says a question was not asked
- **WHEN** the email or a reply says the worker did not ask a question, such as "didn't ask about race" or "Veteran: didn't ask"
- **THEN** the draft sets that field to "data not collected", citing the sentence
- **AND** "data not collected" is set only by that statement and is never chosen by the parser on its own
- **AND** a reply that says "didn't ask" without naming a question makes the system ask which question was not asked

#### Scenario: Silent on a required value
- **WHEN** the email says nothing about the neighbor's Social Security number
- **THEN** the draft leaves it blank and flagged
- **AND** the system does not choose a data-quality option on its own

### Requirement: Minimize location and exclude third parties
The system SHALL record location only at quadrant level, SHALL NOT record camp locations or coordinates, and SHALL NOT record information about people other than the neighbor.

#### Scenario: Precise location in the email
- **WHEN** the email names an intersection or camp
- **THEN** the draft records only the quadrant
- **AND** the source sentences stored with the draft do not contain the precise location
- **AND** the review email tells the worker the precise location was not recorded

#### Scenario: Third party mentioned
- **WHEN** the email mentions a friend or relative of the neighbor
- **THEN** the draft does not record that person's details
- **AND** the source sentences and case note stored with the draft do not contain them

### Requirement: Ask for missing required fields
The system SHALL ask the worker for every required field that is missing or unclear before the draft is submitted, and SHALL update the same draft when the worker replies.

#### Scenario: Required field missing
- **WHEN** a required field cannot be filled from the email
- **THEN** the review email lists the missing fields as flagged

#### Scenario: Worker supplies the detail
- **WHEN** the worker replies with the missing detail
- **THEN** the system updates the same draft and increments its version

### Requirement: Keep personal information inside the approved environment
The system SHALL send email text only to a parser approved for use, and in the demo SHALL accept only synthetic data.

#### Scenario: Swappable parser
- **WHEN** the parser implementation is changed from the rule-based stub to a language model
- **THEN** the rest of the system behaves the same, because both return the same structured output

### Requirement: Use the rule-based stub unless REALLMS is chosen
The system SHALL use the rule-based stub parser by default so the demo runs offline without a key, SHALL use REALLMS only when a setting chooses it for that run, SHALL record which parser and model produced each draft, and SHALL NOT send the REALLMS key to the browser or write it to the logs.

#### Scenario: Default parser
- **WHEN** the system starts with no parser chosen
- **THEN** drafts are parsed by the rule-based stub
- **AND** no key is needed and no note text leaves the machine

#### Scenario: REALLMS chosen
- **WHEN** the run is started with REALLMS chosen by a flag or an environment setting
- **THEN** drafts are parsed by REALLMS with the configured model (gemma-4-31B-it by default)
- **AND** each draft records the parser and model that produced it

#### Scenario: Key stays on the server
- **WHEN** the screens or any route respond
- **THEN** no response contains the REALLMS key
- **AND** the logs do not contain the key or the note text

### Requirement: Label scripted demo drafts
The demo SHALL produce a scripted error only for the exact scripted scenario note, SHALL label every such draft on screen as a scripted demo example and not a live model result, and SHALL parse every other email, including the worker's replies and an edited scenario note, with the configured parser.

#### Scenario: Scripted scenario note
- **WHEN** the worker sends the Scenario B note unchanged
- **THEN** the draft reads the declined shelter bed as the current living situation and leaves veteran status missing
- **AND** the review screen labels the draft as a scripted demo example, not a live model result

#### Scenario: Edited scenario note
- **WHEN** the worker changes the Scenario B note before sending it
- **THEN** the configured parser parses it and no scripted error is applied

#### Scenario: Correcting a scripted draft
- **WHEN** the worker replies to a scripted draft with corrections
- **THEN** the configured parser reads the reply and the corrected fields are marked as worker-sourced
