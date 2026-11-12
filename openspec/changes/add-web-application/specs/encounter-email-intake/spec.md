## MODIFIED Requirements

### Requirement: Accept messages only from authorized workers
The system SHALL accept notes only from signed-in users with the worker role, SHALL take the author and the worker's project from the user record instead of an email sender allowlist, and SHALL NOT show or return neighbor information to anyone who is not signed in.

#### Scenario: Note from a signed-in worker
- **WHEN** a signed-in worker submits a new-client note
- **THEN** the system drafts it with that worker as the author

#### Scenario: Message from an unrecognized sender
- **WHEN** a note is submitted without a valid session, so the sender is not a recognized worker
- **THEN** the system refuses it without processing it
- **AND** the system returns no neighbor information

#### Scenario: Signed in without the worker role
- **WHEN** a user with only the staff role submits a note
- **THEN** the system refuses it
