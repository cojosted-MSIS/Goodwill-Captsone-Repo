## MODIFIED Requirements

### Requirement: Enter only after CONFIRM from the author
The system SHALL enter a draft into HMIS only after the worker who wrote the note presses Confirm on the current version, SHALL refuse a confirmation from anyone else or for an earlier version, SHALL NOT accept one while a required field is missing, and SHALL NOT accept one while a same-name verification is waiting for SAME CLIENT or DIFFERENT PERSON. The Confirm button replaces the CONFIRM reply.

#### Scenario: Worker confirms
- **WHEN** the author presses Confirm on the current version
- **THEN** the draft moves to confirmed and entry begins in the required order

#### Scenario: Confirm while a required field is missing
- **WHEN** a required field is missing
- **THEN** the Confirm button is disabled, the server refuses a confirmation anyway, and nothing is entered

#### Scenario: Confirm while a same-name verification is open
- **WHEN** the author tries to confirm a new-client draft whose same-name verification has no answer
- **THEN** nothing is entered and the screen asks for SAME CLIENT or DIFFERENT PERSON with a reason

#### Scenario: Confirm from someone else
- **WHEN** a signed-in user who is not the author tries to confirm the draft
- **THEN** the system refuses it

#### Scenario: Confirm of an old version
- **WHEN** the author confirms version 1 after version 2 was made
- **THEN** the system asks the author to review version 2 and nothing is entered

### Requirement: Accept plain-language corrections
The system SHALL accept corrections written in plain words in a box on the review screen, SHALL apply them to the same draft, SHALL mark the corrected fields as worker-sourced, SHALL regenerate the case note to match, and SHALL show the new version for review.

#### Scenario: Worker corrects a field
- **WHEN** the worker writes "it was the third time on the street, not the second" in the corrections box
- **THEN** the number of times on the street, in emergency shelter, or in safe haven in the past three years becomes three
- **AND** the field is marked as worker-sourced and the case note is regenerated

#### Scenario: Correction cannot be understood
- **WHEN** the corrections cannot be matched to any field
- **THEN** the screen asks the worker to rephrase
- **AND** the draft is unchanged

### Requirement: Review on phone-style screens
The system SHALL offer phone-sized web screens for the worker to write a note, read the review, correct it, confirm it, and see the HMIS receipt, SHALL call the same core as every other channel, SHALL show each field's value, source quote, origin, and flags, SHALL collapse fields not needed for this neighbor, SHALL disable Confirm while a required field is missing, and SHALL show the receipt after entry.

#### Scenario: Review screen
- **WHEN** the worker opens the current review
- **THEN** each filled or flagged field shows its value, its source quote, where it came from, and any flags
- **AND** the case note is marked as generated for the worker to check
- **AND** the screen says nothing has been sent to HMIS

#### Scenario: CONFIRM disabled while a required field is missing
- **WHEN** the current draft has a required field missing
- **THEN** the Confirm button is disabled and the missing fields are named beside it
- **AND** a confirmation sent to the API anyway is refused as well

#### Scenario: Older version opened
- **WHEN** the worker opens a version that is no longer current
- **THEN** the screen says a newer version exists and offers no Confirm for it

#### Scenario: Receipt shown
- **WHEN** HMIS accepts the entries
- **THEN** the receipt screen shows the identifiers HMIS assigned and the fields the worker corrected

### Requirement: Send unconfirmed drafts to a supervisor queue
The system SHALL move a draft still in review after 48 hours [TBC] to the state "expired", SHALL place it in the supervisor queue of the worker's team, SHALL tell the worker in the app, and SHALL NOT enter it. Held notes and drafts that never reach submission, with their note copies, SHALL be deleted after a configured period (7 days).

#### Scenario: Draft not confirmed in time
- **WHEN** a draft has been in review for 48 hours
- **THEN** it moves to expired, appears in the supervisor queue, the worker sees a notice, and nothing is entered

#### Scenario: Confirm after expiry
- **WHEN** the author tries to confirm a draft that has expired
- **THEN** nothing is entered and the screen says the draft is with their supervisor

#### Scenario: Deleted after seven days
- **WHEN** a held note or an expired or failed draft is 7 days old
- **THEN** it and its note copies are deleted, and its audit record remains without note text

### Requirement: Keep an audit record and delete email copies
The system SHALL record who confirmed each submission, when, the versions, and the fields the worker changed, SHALL NOT store note text in the audit, and SHALL delete the stored note text after submission within a limit set by Goodwill [TBC]. In production retention mode each submitted draft SHALL be reduced to a stub of IDs, states, versions, and times; demo mode keeps the synthetic values.

#### Scenario: Confirmed submission
- **WHEN** a draft is submitted
- **THEN** the audit shows the user, the confirmation time, the versions, and the changed fields, and no note text

#### Scenario: Email copies removed
- **WHEN** a draft is submitted
- **THEN** the stored note and correction text (and any email copies stored before this change) are deleted within the retention limit

#### Scenario: Production mode reduces the draft
- **WHEN** a draft is submitted in production retention mode
- **THEN** only its IDs, states, versions, and times remain in the staging store

#### Scenario: Demo mode keeps the values
- **WHEN** a draft is submitted in demo retention mode
- **THEN** its synthetic values remain so the staff screens can show the submitted record

## REMOVED Requirements

### Requirement: Send a review email
**Reason**: The review is shown on a web screen ("Review on phone-style screens"); the worker no longer receives a review email.
**Migration**: The content of the review email (filled and flagged fields with sources, the "not needed for this neighbor" line, the remaining HMIS items, the version, and "nothing has been sent to HMIS") moves to the review screen, which already shows it. Review emails already stored are deleted under the existing email retention rule. The email version stays available at the tag `v1-email-headless`.
