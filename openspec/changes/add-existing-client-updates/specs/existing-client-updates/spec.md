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
- **WHEN** the note describes a service that matches no configured service type (a placeholder list [TBC with Horizon House and CHIP])
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

### Requirement: Record the quadrant with every contact
Every contact the system enters SHALL carry its quadrant: the new-client Coordinated Entry entry SHALL send the draft's quadrant with the contact, and each service entry SHALL carry its quadrant, so a neighbor entered or visited through this system appears in quadrant briefings right away.

#### Scenario: New client appears in the briefing
- **WHEN** a new client noted in the SW quadrant has been entered and the worker asks for a briefing for the SW quadrant
- **THEN** the briefing lists that client with the contact date

#### Scenario: Visit appears in the briefing
- **WHEN** an update for a client is entered with a service in the NE quadrant
- **THEN** a briefing for the NE quadrant lists that client with the service date as the last contact

### Requirement: Correct an entry this system already made
Only the worker who wrote the original note SHALL be able to correct a case note or service entry this system entered, by replying to its receipt. The system SHALL create a new draft version that references the entry ID, SHALL require CONFIRM, SHALL enter it as an update to that entry, and SHALL audit field names only. If HMIS forbids edits after save [TBC], the system SHALL instead add a new entry that says it corrects the earlier one.

#### Scenario: Correction after entry
- **WHEN** the worker replies to a receipt "the service was 45 minutes, not 30" and then confirms the new version
- **THEN** the system updates that service entry through the update operation
- **AND** the audit record lists the changed field name and the entry ID, not the values or the note text

#### Scenario: Correction from someone else
- **WHEN** a correction to an entry arrives from a worker other than the one who wrote the original note
- **THEN** the system ignores it

#### Scenario: HMIS forbids edits after save
- **WHEN** the update operation is not allowed for that entry
- **THEN** after CONFIRM the system adds a new case note or service entry that says it corrects the earlier entry, and the earlier entry is unchanged

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
The system SHALL grade each candidate by the last four Social Security digits: matching digits are "likely the same person" and the email recommends SAME CLIENT; digits missing on either side are a hard stop and the email asks the worker to get the digits if they can; different digits are a warning. Every grade SHALL need SAME CLIENT <ID> or DIFFERENT PERSON with a reason.

#### Scenario: Matching digits
- **WHEN** the draft and the candidate have the same last four SSN digits
- **THEN** the verification email marks the candidate as likely the same person and recommends SAME CLIENT

#### Scenario: Different digits
- **WHEN** the draft and the candidate have different last four SSN digits
- **THEN** the verification email shows a warning and still needs SAME CLIENT <ID> or DIFFERENT PERSON

#### Scenario: Digits missing
- **WHEN** either the draft or the candidate has no SSN digits
- **THEN** the candidate is a hard stop and the email asks the worker to get the digits if they can

### Requirement: SAME CLIENT turns the draft into an update
When the worker replies SAME CLIENT <ID> with an ID from the candidate list, the system SHALL turn the draft into an update draft for that client with a case note and a service entry from the note, SHALL NOT enter the new-client fields, SHALL show any demographic answers as "update in HMIS yourself", and SHALL send it for review and CONFIRM.

#### Scenario: Same client
- **WHEN** the worker replies "SAME CLIENT HMIS-C-000101"
- **THEN** the worker receives an update review for that client and no new client is created

#### Scenario: Demographics that differ
- **WHEN** the note gives a gender or veteran status for the neighbor
- **THEN** the update review lists them under "update in HMIS yourself" and they are never written to HMIS

#### Scenario: ID not among the candidates
- **WHEN** the worker replies SAME CLIENT with an ID that was not a candidate
- **THEN** the system refuses it and lists the candidates again

### Requirement: DIFFERENT PERSON needs a reason and is entered as confirmed distinct
When the worker replies DIFFERENT PERSON with a reason, the system SHALL continue the new-client review, accept CONFIRM, and enter the client with a confirmed-distinct override carrying the reason. A reply without a reason SHALL be refused. When the SSN digits match, the reason SHALL meet a configured minimum length (40 characters) and the decision SHALL be flagged for supervisor review afterward, without blocking [TBC with Goodwill].

#### Scenario: Different person with a reason
- **WHEN** the worker replies "DIFFERENT PERSON: she is 20 years younger than the person in HMIS" and then CONFIRM
- **THEN** the client is entered as new with the confirmed-distinct override and the reason

#### Scenario: Different person without a reason
- **WHEN** the worker replies "DIFFERENT PERSON" with no reason
- **THEN** the system asks for the reason and does not accept CONFIRM yet

#### Scenario: Different person when the SSN digits match
- **WHEN** the candidate's SSN digits match and the worker's reason is shorter than the minimum
- **THEN** the system asks for a fuller reason
- **AND** once a long enough reason is given and the client is entered, the audit flags the decision for supervisor review

### Requirement: Keep the possible-duplicate rejection as a backstop
The mock HMIS SHALL keep rejecting a new client that matches an existing one, answering only with a failure and no details about the matching record, and SHALL accept a confirmed-distinct override only when it carries a reason [TBC with CHIP: whether the real HMIS allows an override].

#### Scenario: Duplicate without an override
- **WHEN** a new client matching an existing record is posted without an override
- **THEN** the mock HMIS rejects it as a possible duplicate and says nothing about the existing record

#### Scenario: Override without a reason
- **WHEN** a confirmed-distinct override is posted with an empty reason
- **THEN** the mock HMIS rejects it

### Requirement: Audit verification decisions
The audit record SHALL show, for each same-name verification, the worker, the time, the number of candidates, the grade, the decision (same client or different person), the chosen client ID, the reason for a different person after the shared privacy cleaning, and a supervisor review flag when the SSN digits matched. It SHALL NOT contain note text.

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
- **AND** the briefing includes a neighbor entered earlier in the demo, because the contact recorded its quadrant

### Requirement: Check open drafts against each other with a keyed hash
To catch two open drafts for the same neighbor, which the HMIS lookup cannot see, the system SHALL keep for each open new-client draft only a keyed hash (HMAC-SHA256) of the normalized first name, last name, and date of birth, SHALL compare new drafts against these hashes, and SHALL delete the hash when the draft is entered, expires, or fails.

#### Scenario: Two open drafts for the same neighbor
- **WHEN** a second new-client draft has the same name and date of birth as an open draft
- **THEN** the second worker is told another draft for the same name and date of birth is open, with its draft ID only
- **AND** no name or date of birth is stored for the comparison

#### Scenario: Hash deleted at entry
- **WHEN** an open draft is entered into HMIS
- **THEN** its hash is deleted

### Requirement: Hash key from the environment
The hash key SHALL come from the environment (`.env`, never the repo). In production retention mode the system SHALL refuse to start without it. In demo retention mode, when no key is set, the system SHALL generate a random key in memory for that run. `.env.example` SHALL hold only a placeholder.

#### Scenario: Production mode without a key
- **WHEN** the system starts in production retention mode and no hash key is set
- **THEN** it refuses to start with a clear message

#### Scenario: Demo mode without a key
- **WHEN** the system starts in demo retention mode and no hash key is set
- **THEN** it generates a random key in memory and does not write it anywhere
