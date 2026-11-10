## ADDED Requirements

### Requirement: Sign in with a role
The system SHALL require every user to sign in before using the web application, SHALL give each user one or more roles (worker, supervisor, staff), and SHALL allow each action only for the roles that may take it. Production sign-in SHALL use Goodwill's identity provider [TBC with Goodwill IT]; the demo SHALL use synthetic accounts whose passwords come from the environment and are stored only as hashes.

#### Scenario: Not signed in
- **WHEN** someone opens a worker screen or calls the API without signing in
- **THEN** the system shows the sign-in screen or answers "not signed in"
- **AND** no neighbor information is shown

#### Scenario: Worker opens a staff view
- **WHEN** a user with only the worker role opens the staff audit view
- **THEN** the system refuses it and shows no audit data

#### Scenario: Demo passwords
- **WHEN** the repository is searched for demo passwords
- **THEN** only placeholders appear in `.env.example` and no password or hash of a real password is committed

### Requirement: Protect sessions
The system SHALL keep sessions on the server, SHALL send the session only in an HttpOnly, Secure, SameSite=Strict cookie, SHALL require a CSRF token on every write, and SHALL end a session after a configured idle time [TBC with Goodwill IT].

#### Scenario: Write without the CSRF token
- **WHEN** a signed-in user's browser sends a write without the CSRF token
- **THEN** the system refuses it and changes nothing

#### Scenario: Session expired
- **WHEN** a session has been idle longer than the configured time
- **THEN** the next request asks the user to sign in again

### Requirement: Use the same core for every use case
The web application SHALL offer the same use cases as the email version (new neighbor entry, case notes and services for existing clients, same-name and date of birth verification, and the four read-only query types including the no-contact watchlist) through the same core logic, so the drafting, validation, verification, entry, audit, and retention rules are unchanged.

#### Scenario: Same draft from the same note
- **WHEN** the same note is submitted in the web app and was earlier sent by email
- **THEN** the draft has the same fields, origins, flags, and case note

#### Scenario: Same rules for HMIS writes
- **WHEN** a worker confirms a draft in the web app
- **THEN** HMIS is written only through entry operations, in the same order, with the same retry from the failed step

### Requirement: Worker screens
The system SHALL offer a signed-in worker screens to write a new-client note, write an update note, ask a read-only query, review a draft with each field's value, source quote, origin, and flags, correct it in plain words, answer a same-name verification, pick a client, confirm the current version with a button, retry a failed entry, see the receipt, and correct an entry from its receipt.

#### Scenario: Review screen
- **WHEN** a worker opens a draft in review
- **THEN** each filled or flagged field shows its value, source quote, where it came from, and any flags, and the screen says nothing has been sent to HMIS

#### Scenario: Only the author's drafts
- **WHEN** a worker opens another worker's draft
- **THEN** the system refuses it

### Requirement: Supervisor queue screen
The system SHALL show users with the supervisor role the drafts of their team that expired after 48 hours in review [TBC], SHALL show each draft's ID, worker, version, and time in review, and SHALL NOT let a supervisor confirm a draft on a worker's behalf.

#### Scenario: Expired draft
- **WHEN** a draft has been in review for 48 hours
- **THEN** it appears on the supervisor queue screen and the worker sees a notice in the app

#### Scenario: Supervisor tries to confirm
- **WHEN** a supervisor tries to confirm a draft in the queue
- **THEN** the system refuses it and nothing is entered into HMIS

### Requirement: Web API over the core
The system SHALL offer a versioned JSON API for every worker, supervisor, and staff action, SHALL check the user's role and the draft's author on every call, and SHALL return only the data the screen shows, with the same minimal-data rules as the email replies.

#### Scenario: Query through the API
- **WHEN** a worker asks for a briefing through the API
- **THEN** the response holds only the minimal fields of the email reply, as structured data

#### Scenario: Draft through the API
- **WHEN** a worker fetches their draft's review data
- **THEN** the response holds the same fields as the review screen and nothing else

### Requirement: Keep email as an optional channel, off by default
The final email-based version SHALL stay available at the tag `v1-email-headless`. The email channel SHALL stay in the code as an optional channel over the same core, off by default behind a config flag, until the sponsors decide whether to keep it as a fallback [TBC with the sponsors]. When it is off, no email is read or sent.

#### Scenario: Running the email demo
- **WHEN** a developer checks out `v1-email-headless`
- **THEN** the email demo and its tests run as before

#### Scenario: Email channel off
- **WHEN** the email channel flag is off and a note arrives by email
- **THEN** the system neither processes it nor replies

#### Scenario: Email channel on
- **WHEN** the email channel flag is on
- **THEN** an emailed note goes through the same core and rules as a note written in the app

### Requirement: Label entered drafts "Entered in HMIS"
The worker and supervisor screens SHALL show a draft that HMIS has accepted as "Entered in HMIS", so it is never confused with an entry on the device that has only been uploaded to the server.

#### Scenario: Draft entered
- **WHEN** HMIS accepts every entry for a draft
- **THEN** the draft shows "Entered in HMIS" with the identifiers HMIS assigned
