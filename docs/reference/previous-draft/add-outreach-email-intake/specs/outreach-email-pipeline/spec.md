## ADDED Requirements

### Requirement: Accept messages only from authorized workers
The system SHALL process only emails sent to the designated secure inbox by authorized outreach staff.

#### Scenario: Message from an unrecognized sender
- **WHEN** an email arrives from an address that is not on the authorized worker list
- **THEN** the system drops the message without processing it
- **AND** the system does not reply with any neighbor information

### Requirement: Identify the form type
The system SHALL determine which supported request an email makes (a Form 101 observation, a verification letter, or a new neighbor profile) and SHALL ask the worker when it cannot tell.

#### Scenario: Clear request
- **WHEN** a worker writes "I need a homeless verification letter for Pat Example, DOB 01/01/1980"
- **THEN** the system classifies the email as a verification letter request

#### Scenario: Unclear message
- **WHEN** an email does not clearly match a supported request
- **THEN** the system replies asking the worker what they mean
- **AND** the system does not create a draft

### Requirement: Fill draft fields only from stated or trusted sources
The system SHALL fill a draft field only with a value stated in the email or taken from the worker's profile, and SHALL leave any other field blank and flagged. The draft SHALL show which source each value came from, and for a value taken from the email, the sentence it came from.

#### Scenario: Value not stated
- **WHEN** an email does not state a value the form needs
- **THEN** the draft leaves that field blank
- **AND** the draft flags the field for the worker

#### Scenario: Source shown
- **WHEN** a draft is sent to the worker for review
- **THEN** each field is shown beside its source
- **AND** each value from the email cites the sentence it came from
- **AND** each other value is labeled as coming from the worker's profile

### Requirement: Identify the neighbor from the worker's email
The system SHALL take the neighbor identifier from the worker's email, either an HMIS client ID or the neighbor's name and date of birth, SHALL show it back to the worker in the review email as the first of three checkpoints (confirm the neighbor, confirm the fields, approve the submission), and SHALL NOT search or read HMIS to find or check it.

#### Scenario: Identifier supplied
- **WHEN** the email includes an HMIS client ID, or a name and date of birth
- **THEN** the draft shows that identifier to the worker for confirmation
- **AND** the system does not query HMIS

#### Scenario: Identifier missing
- **WHEN** the email gives no client ID and not both a name and date of birth
- **THEN** the system asks the worker for the identifier before presenting the draft

### Requirement: Enter information into HMIS only
The system SHALL only enter approved information into HMIS and SHALL NOT retrieve, search, or display any information from HMIS.

#### Scenario: Entry approved
- **WHEN** the worker approves a draft that is entered into HMIS
- **THEN** the system sends the entry
- **AND** the only information it takes back from HMIS is whether the entry succeeded or failed and why

#### Scenario: Worker wants to look someone up
- **WHEN** a worker needs to check whether a neighbor already has a profile
- **THEN** the worker does that in HMIS directly
- **AND** the system does not offer a lookup

### Requirement: Prepare a new neighbor profile for confirmation
The system SHALL draft a new neighbor profile from the email only when the worker states that they searched HMIS and found no existing profile, and SHALL enter it only after the worker approves the draft, with the fields CHIP requires for a new profile [TBC].

#### Scenario: Worker found no existing profile
- **WHEN** the email says the worker searched HMIS and found no match, and gives the details for a new profile
- **THEN** the system drafts a new profile from those details
- **AND** the draft is sent to the worker for review before anything is entered

#### Scenario: Search not stated
- **WHEN** a worker asks for a new profile without saying they searched HMIS
- **THEN** the system asks the worker to confirm they searched and found no match
- **AND** the system does not draft the profile until the worker does

#### Scenario: Profile approved
- **WHEN** the worker approves the new-profile draft
- **THEN** the system enters it through `create_neighbor_profile`
- **AND** the system tells the worker whether it was recorded

### Requirement: Accept photo attachments
The system SHALL accept photographs attached to a worker's email, SHALL attach them to the matching HMIS entry through `attach_document` after the worker approves, and SHALL NOT accept video.

#### Scenario: Photo attached
- **WHEN** an email includes a photograph
- **THEN** the draft lists the photo for the worker to confirm
- **AND** the photo is entered with the entry only after the worker approves

#### Scenario: Video attached
- **WHEN** an email includes a video
- **THEN** the system does not store it
- **AND** the system tells the worker video is not accepted

### Requirement: Validate drafts with rules, not AI
The system SHALL check each draft against required-field, format, and date rules for its document type, SHALL flag every problem in the review email, and SHALL NOT silently correct a value. The rules SHALL be configuration that Goodwill IT can edit without a code change.

#### Scenario: Problem found
- **WHEN** a draft has a missing required field, a badly formatted value, or an impossible date
- **THEN** the review email flags the problem
- **AND** the system does not change the value on its own

#### Scenario: Worker edits a value
- **WHEN** the worker replies with an edit
- **THEN** the system re-runs the rules on the updated draft before presenting it again

#### Scenario: Rules changed
- **WHEN** Goodwill IT edits the rules for a document type
- **THEN** new drafts use the changed rules without a code change

### Requirement: Define document fields as configuration
The system SHALL define the HMIS documents it supports and their field mappings as configuration, so that adding a form, or supporting another continuum of care, means adding configuration and not new software.

#### Scenario: New form added
- **WHEN** a new form is added to the configuration
- **THEN** the system can draft and enter it using the same pipeline

### Requirement: Ask for missing required fields
The system SHALL ask the worker for any required field that is missing or unclear before presenting the draft for review.

#### Scenario: Required field missing
- **WHEN** a required field cannot be filled from the email or the worker's profile
- **THEN** the system replies listing the missing fields

#### Scenario: Worker supplies the missing detail
- **WHEN** the worker replies with the missing detail
- **THEN** the system updates the same draft rather than starting a new one

### Requirement: Worker approval before any entry or issue
The system SHALL send the worker a review email showing the neighbor identifier and every field beside its source, SHALL accept three reply commands (APPROVE, EDIT with corrected values, REJECT) tied to that draft's ID, SHALL accept them only from the worker who wrote the note, and SHALL NOT enter anything into HMIS, or mark any document as issued, without an explicit APPROVE.

#### Scenario: Worker approves
- **WHEN** the author replies APPROVE to a draft
- **THEN** the draft moves from in review to approved
- **AND** the system proceeds to the next step defined for that form

#### Scenario: Worker edits
- **WHEN** the author replies EDIT with corrected values
- **THEN** the system updates the draft and re-runs validation
- **AND** the system sends the updated draft for review again

#### Scenario: Worker rejects
- **WHEN** the author replies REJECT
- **THEN** the draft is discarded
- **AND** nothing is entered into HMIS

#### Scenario: Reply from someone else
- **WHEN** a reply command arrives from anyone other than the note's author
- **THEN** the system ignores it

#### Scenario: Draft states
- **WHEN** a draft moves through the workflow
- **THEN** it is always in one of five states: draft, in review, approved, submitted, or failed

#### Scenario: No response
- **WHEN** the worker does not respond
- **THEN** the draft stays in review
- **AND** nothing is entered into HMIS

### Requirement: Remind the worker, flag a supervisor, then expire the draft
The system SHALL send one reminder when a draft stays in review for the set window [TBC], SHALL flag the draft to the worker's supervisor [TBC] if it is still in review after the reminder, and SHALL delete the draft after [N] days [TBC] if it is never approved.

#### Scenario: Reminder sent
- **WHEN** a draft has been in review for the reminder window
- **THEN** the system sends the worker one reminder

#### Scenario: Still in review
- **WHEN** the draft is still in review after the reminder
- **THEN** the system flags it to the supervisor
- **AND** nothing is entered into HMIS

#### Scenario: Draft expires
- **WHEN** a draft has gone unapproved for [N] days
- **THEN** the draft is deleted

### Requirement: Keep personal information out of external AI systems
The system SHALL NOT send personally identifiable information to any AI system outside an environment approved under Goodwill's AI policy.

#### Scenario: Email contains identifying details
- **WHEN** an email containing a name and a date of birth is processed
- **THEN** no request leaves the approved environment with that name or date of birth in it

### Requirement: Retain inbox content under access controls
The system SHALL keep original email content in the Goodwill mailbox under its own retention rule set by Goodwill [TBC], SHALL restrict access to it to authorized staff, and SHALL delete it when that period ends. The system SHALL keep only pending drafts in a draft store, SHALL delete a draft on submission or when it expires, and SHALL NOT keep any standing copy of HMIS client data outside HMIS.

#### Scenario: Entry submitted
- **WHEN** an entry is successfully submitted
- **THEN** its draft is deleted from the draft store
- **AND** the original email stays in the mailbox only for the retention period, visible only to authorized staff

#### Scenario: Retention period ends
- **WHEN** the mailbox retention period ends
- **THEN** the email content is deleted

#### Scenario: No copy of client data
- **WHEN** an entry has been submitted
- **THEN** no copy of the neighbor's HMIS data is kept outside HMIS, apart from the audit record

### Requirement: Keep an access-controlled audit trail
The system SHALL record who approved each submission, when, which form type it was, the neighbor identifier the worker supplied, and which fields the worker changed from the AI's proposal, SHALL restrict access to that record to authorized staff, and SHALL record change flags and not the narrative content of the email.

#### Scenario: Approved submission
- **WHEN** a worker approves a draft
- **THEN** the audit record shows the worker, the time, the form type, and the neighbor identifier
- **AND** the audit record does not contain the email text

#### Scenario: Worker changed a field
- **WHEN** the worker edited a field the AI had proposed
- **THEN** the audit record flags that field as changed
- **AND** the audit record does not contain the old or new narrative text

### Requirement: Send receipts and failure notices
The system SHALL email the worker a submission receipt when HMIS accepts an entry, and a failure notice with the reason when it does not, and SHALL return a failed submission to the worker rather than retrying silently.

#### Scenario: Receipt
- **WHEN** HMIS accepts an entry
- **THEN** the worker receives a receipt
- **AND** the draft moves to submitted

#### Scenario: Failure
- **WHEN** HMIS rejects an entry or cannot be reached
- **THEN** the draft moves to failed
- **AND** the worker receives a failure notice with the reason
