## ADDED Requirements

### Requirement: Accept update notes for an existing neighbor
The system SHALL treat an email from an authorized worker whose subject starts with "Update:" followed by a name or an HMIS client ID as one visit's note for an existing client, SHALL create one update draft per note, and SHALL allow any number of updates for the same client over time.

#### Scenario: Second visit to the same neighbor
- **WHEN** a worker sends an update note for a client a few days after an earlier update for that client was entered
- **THEN** the system creates a new update draft for the same client
- **AND** the earlier entries are not changed

#### Scenario: Update from an unrecognized sender
- **WHEN** an update note arrives from an address that is not on the authorized worker list
- **THEN** the system drops it without processing it and without replying

### Requirement: Identify the client by a checked HMIS client ID
When an update note or its subject gives an HMIS client ID, the system SHALL check its format [TBC] and SHALL check that the client exists and is visible to the worker's project through the read-only lookup. If the ID fails either check, or the subject and the note give different IDs, the system SHALL draft nothing and SHALL tell the worker in plain words.

#### Scenario: Valid client ID
- **WHEN** the note says "Client ID HMIS-C-000001" and that client exists
- **THEN** the system drafts the update for that client

#### Scenario: Wrong format
- **WHEN** the note gives a client ID that does not match the format
- **THEN** the system drafts nothing and asks the worker to check the ID

#### Scenario: Client not found
- **WHEN** the client ID has the right format but no visible client has it
- **THEN** the system drafts nothing and tells the worker no client with that ID was found

#### Scenario: Subject and note disagree
- **WHEN** the subject and the note give different client IDs
- **THEN** the system drafts nothing and asks the worker which one is right

### Requirement: Offer lookup candidates when no client ID is given
When an update note has no client ID, the system SHALL run the read-only lookup with the name and date of birth from the note, SHALL email the candidates (client ID, first name and last initial, quadrant, last contact date), and SHALL wait for the worker to reply "CLIENT <ID>". The system SHALL NOT pick a client itself, even when there is only one candidate.

#### Scenario: One candidate
- **WHEN** the lookup finds exactly one client
- **THEN** the system still asks the worker to reply "CLIENT <ID>" before drafting

#### Scenario: Worker picks a candidate
- **WHEN** the worker replies "CLIENT HMIS-C-000001" and that ID was one of the candidates
- **THEN** the system drafts the update for that client

#### Scenario: Name without a date of birth
- **WHEN** the update note gives a name but no date of birth or client ID
- **THEN** the system asks for the client ID or the date of birth and runs no lookup

#### Scenario: No candidate
- **WHEN** the lookup finds no client
- **THEN** the system says no client was found and that a new client needs a "New client" note

### Requirement: Draft a case note and a service entry
For an update the system SHALL draft a case note and a service entry with the service date, service type, quadrant, and time spent, filling each only from the note [TBC with Horizon House and CHIP: the exact service fields]. The service date SHALL come from the note or, labelled "email date", from the email. A value not stated SHALL stay blank and be flagged if required.

#### Scenario: Time spent not stated
- **WHEN** the note does not say how long the contact took
- **THEN** time spent stays blank and is not estimated

#### Scenario: Service type not on the list
- **WHEN** the note describes a service that matches no configured service type
- **THEN** the service type stays blank and is flagged for the worker

#### Scenario: Case note privacy
- **WHEN** the note mentions a friend of the neighbor and a camp location
- **THEN** the case note and stored sentences leave out the friend and record only the quadrant

### Requirement: Review and enter updates the same way as new clients
An update draft SHALL go through validation, a review email, CONFIRM or plain-language corrections, entry, a receipt, an audit record without note text, and deletion of the email copies, exactly as a new-client draft does. Entry SHALL add the case note and then the service entry, and a retry SHALL resume at the step that failed.

#### Scenario: Update confirmed
- **WHEN** the worker replies CONFIRM to the current version of an update draft
- **THEN** the system adds the case note and the service entry to the client
- **AND** the receipt lists the new case note ID and service ID

#### Scenario: Correction before entry
- **WHEN** the worker replies to an update review with a correction such as "it was 30 minutes"
- **THEN** the system sends version 2 with the field marked as worker-sourced

#### Scenario: Service step fails after the case note was added
- **WHEN** the case note was added, the service step failed, and the worker replies RETRY
- **THEN** the system adds only the service entry and does not add the case note again

### Requirement: Mock HMIS operations for existing clients
The mock HMIS SHALL offer POST-only operations to add a case note to a client, add a service to a client, and update a case note or service entry, each returning only success or failure and the assigned or updated entry ID. An unknown client ID SHALL fail with a plain-words reason and no other data.

#### Scenario: Unknown client
- **WHEN** a case note is posted for a client ID the mock HMIS does not have
- **THEN** the mock HMIS answers with a failure saying no client with that ID exists
- **AND** the answer contains nothing about any other client

#### Scenario: Case note added
- **WHEN** a case note is posted for an existing client
- **THEN** the mock HMIS answers with success and the new case note ID only

### Requirement: Correct an entry this system already made
The worker SHALL be able to correct a case note or service entry this system entered by replying to its receipt with the change. The system SHALL create a new draft version that references the entry ID, SHALL require CONFIRM, SHALL enter it as an update to that entry [TBC: the real HMIS may not allow edits after save], and SHALL audit field names only. Corrections before entry stay as they are.

#### Scenario: Correction after entry
- **WHEN** the worker replies to a receipt "the service was 45 minutes, not 30" and then confirms the new version
- **THEN** the system updates that service entry through the update operation
- **AND** the audit record lists the changed field name and the entry ID, not the values or the note text

#### Scenario: Correction from someone else
- **WHEN** a correction to an entry arrives from a worker other than the one who entered it
- **THEN** the system ignores it [TBC: whether a supervisor may correct]

#### Scenario: Entry not made by this system
- **WHEN** a correction references an entry ID this system did not enter
- **THEN** the system refuses it and tells the worker to correct the entry in HMIS

### Requirement: Check new-client drafts for the same name and date of birth
Before a new-client draft goes to review, the system SHALL run the read-only lookup with its first name, last name, and date of birth. If any visible client matches, the system SHALL send a verification email listing each candidate's client ID, quadrant, and last contact date, and SHALL NOT accept CONFIRM until the worker replies SAME CLIENT <ID> or DIFFERENT PERSON with a reason.

#### Scenario: Match found
- **WHEN** a new-client draft has the same name and date of birth as a client in HMIS
- **THEN** the worker receives a verification email with the candidates
- **AND** a CONFIRM reply is refused with a message asking for SAME CLIENT <ID> or DIFFERENT PERSON

#### Scenario: No match
- **WHEN** no visible client has the same name and date of birth
- **THEN** the draft goes to review as before

### Requirement: Grade a same-name match by the second identifier
The system SHALL grade each candidate by the last four digits of the Social Security number [TBC: proposed rule]: a matching or missing second identifier on either side is a hard stop, labelled "likely the same person"; a different second identifier is a warning, labelled "same name and date of birth, different SSN digits". Both SHALL need the explicit reply.

#### Scenario: Matching digits
- **WHEN** the draft and the candidate have the same last four SSN digits
- **THEN** the verification email marks the candidate as likely the same person

#### Scenario: Different digits
- **WHEN** the draft and the candidate have different last four SSN digits
- **THEN** the verification email shows a warning and still needs SAME CLIENT <ID> or DIFFERENT PERSON

#### Scenario: Digits missing
- **WHEN** either the draft or the candidate has no SSN digits
- **THEN** the candidate is treated as a hard stop

### Requirement: SAME CLIENT turns the draft into an update
When the worker replies SAME CLIENT <ID> with an ID from the candidate list, the system SHALL turn the draft into an update draft for that client with a case note and a service entry from the note, SHALL NOT enter the new-client fields, and SHALL send it for review and CONFIRM.

#### Scenario: Same client
- **WHEN** the worker replies "SAME CLIENT HMIS-C-000101"
- **THEN** the worker receives an update review for that client and no new client is created

#### Scenario: ID not among the candidates
- **WHEN** the worker replies SAME CLIENT with an ID that was not a candidate
- **THEN** the system refuses it and lists the candidates again

### Requirement: DIFFERENT PERSON needs a reason and is entered as confirmed distinct
When the worker replies DIFFERENT PERSON with a reason, the system SHALL continue the new-client review, SHALL accept CONFIRM, and SHALL enter the client with a confirmed-distinct override carrying the reason. DIFFERENT PERSON without a reason SHALL be refused.

#### Scenario: Different person with a reason
- **WHEN** the worker replies "DIFFERENT PERSON: she is 20 years younger than the person in HMIS" and then CONFIRM
- **THEN** the client is entered as new with the confirmed-distinct override and the reason

#### Scenario: Different person without a reason
- **WHEN** the worker replies "DIFFERENT PERSON" with no reason
- **THEN** the system asks for the reason and does not accept CONFIRM yet

### Requirement: Keep the possible-duplicate rejection as a backstop
The mock HMIS SHALL keep rejecting a new client that matches an existing one, answering only with a failure and no details about the matching record, and SHALL accept a confirmed-distinct override only when it carries a reason [TBC with CHIP: whether the real HMIS allows an override].

#### Scenario: Duplicate without an override
- **WHEN** a new client matching an existing record is posted without an override
- **THEN** the mock HMIS rejects it as a possible duplicate and says nothing about the existing record

#### Scenario: Override without a reason
- **WHEN** a confirmed-distinct override is posted with an empty reason
- **THEN** the mock HMIS rejects it

### Requirement: Audit verification decisions
The audit record SHALL show, for each same-name verification, the worker, the time, the number of candidates, the grade, the decision (same client or different person), the chosen client ID, and the reason for a different person [TBC: keep the reason in full or cleaned], and SHALL NOT contain note text.

#### Scenario: Decision recorded
- **WHEN** the worker replies DIFFERENT PERSON with a reason and the client is entered
- **THEN** the audit trail shows the verification, the decision, the reason, and the override

### Requirement: Screens for updates, queries, and verification
The phone screens SHALL offer composing an update note and a query, SHALL show briefing, lookup, and status replies, SHALL show the verification email with SAME CLIENT and DIFFERENT PERSON replies (with a reason field), and SHALL show a receipt with the new entry IDs. The staff audit view SHALL show verification decisions and queries.

#### Scenario: Verification on the phone
- **WHEN** the worker opens a verification email
- **THEN** the screen shows the candidates and offers SAME CLIENT for each and DIFFERENT PERSON with a reason, and CONFIRM is not offered

#### Scenario: Queries in the staff audit
- **WHEN** a reviewer opens the staff audit view
- **THEN** it lists the worker's queries with type, parameters, and row counts, and no returned values

### Requirement: Demo scenarios for updates, verification, and queries
The demo SHALL add Scenario C (a second visit to a neighbor entered earlier, with a case note and service update), Scenario D (a same-name verification, run once ending SAME CLIENT and once ending DIFFERENT PERSON), and Scenario E (a pre-visit briefing for a quadrant, then a status check). The demo reset SHALL clear all of it and reseed the read-only layer.

#### Scenario: Scenario C
- **WHEN** the presenter runs Scenario C after Scenario A
- **THEN** the receipt shows a case note ID and a service ID for Scenario A's client

#### Scenario: Scenario D, both outcomes
- **WHEN** the presenter runs Scenario D
- **THEN** one run ends as an update of the existing client and one as a new client entered as confirmed distinct

#### Scenario: Scenario E
- **WHEN** the presenter runs Scenario E
- **THEN** the worker receives a briefing for the quadrant and then a status answer, and nothing in HMIS changes
