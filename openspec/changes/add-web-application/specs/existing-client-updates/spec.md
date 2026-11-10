## MODIFIED Requirements

### Requirement: Accept update notes for an existing neighbor
The system SHALL treat a note a signed-in worker writes on the "Update a neighbor" screen, with a name or an HMIS client ID, as one visit's note for an existing client, SHALL create one update draft per note, and SHALL allow any number of updates for the same client over time.

#### Scenario: Second visit to the same neighbor
- **WHEN** a worker writes an update for a client a few days after an earlier update for that client was entered
- **THEN** the system creates a new update draft for the same client and the earlier entries are not changed

#### Scenario: Update from an unrecognized sender
- **WHEN** an update is submitted without a valid session, so the sender is not a recognized worker
- **THEN** the system refuses it without processing it

### Requirement: Offer lookup candidates when no client ID is given
When an update note has no client ID, the system SHALL run the read-only lookup with the name and date of birth from the note, SHALL show the candidates (client ID, first name and last initial, quadrant, last contact date), and SHALL wait for the worker to pick one on screen. The system SHALL NOT pick a client itself, even when there is only one candidate.

#### Scenario: One candidate
- **WHEN** the lookup finds exactly one client
- **THEN** the system still asks the worker to pick that client before drafting

#### Scenario: Worker picks a candidate
- **WHEN** the worker picks HMIS-C-000001 from the candidates
- **THEN** the system drafts the update for that client

#### Scenario: Name without a date of birth
- **WHEN** the update note gives a name but no date of birth or client ID
- **THEN** the system asks for the client ID or the date of birth and runs no lookup

#### Scenario: No candidate
- **WHEN** the lookup finds no client
- **THEN** the system says no client was found and that a new client needs a new-client note

### Requirement: Correct an entry this system already made
Only the worker who wrote the original note SHALL be able to correct a case note or service entry this system entered, with "Correct this entry" on its receipt. The system SHALL create a new draft version that references the entry ID, SHALL require Confirm, SHALL enter it as an update to that entry, and SHALL audit field names only. If HMIS forbids edits after save [TBC], it SHALL add a new entry that says it corrects the earlier one.

#### Scenario: Correction after entry
- **WHEN** the worker writes "the service was 45 minutes, not 30" under "Correct this entry" and confirms the new version
- **THEN** the system updates that service entry through the update operation and audits only the changed field name and the entry ID

#### Scenario: Correction from someone else
- **WHEN** a worker who did not write the original note opens "Correct this entry"
- **THEN** the system refuses it

#### Scenario: HMIS forbids edits after save
- **WHEN** the update operation is not allowed for that entry
- **THEN** after Confirm the system adds a new case note or service entry that says it corrects the earlier entry, and the earlier entry is unchanged

#### Scenario: Entry not made by this system
- **WHEN** a correction names an entry ID this system did not enter
- **THEN** the system refuses it and tells the worker to correct the entry in HMIS

### Requirement: Check new-client drafts for the same name and date of birth
Before a new-client draft goes to review, the system SHALL run the read-only lookup with its first name, last name, and date of birth. If any visible client matches, the system SHALL show a verification screen listing each candidate's client ID, quadrant, last contact date, entered date, enrollment status, and last service type, and SHALL NOT accept Confirm until the worker chooses SAME CLIENT for one candidate or DIFFERENT PERSON with a reason.

#### Scenario: Match found
- **WHEN** a new-client draft has the same name and date of birth as a client in HMIS
- **THEN** the worker sees the verification screen with the candidates instead of the review, and Confirm is not offered

#### Scenario: No match
- **WHEN** no visible client has the same name and date of birth
- **THEN** the draft goes to review as before

#### Scenario: Match found for a note written offline
- **WHEN** a note written offline uploads and the lookup finds a match
- **THEN** the worker sees the verification screen the next time they are online, and nothing is entered until they answer it and confirm
