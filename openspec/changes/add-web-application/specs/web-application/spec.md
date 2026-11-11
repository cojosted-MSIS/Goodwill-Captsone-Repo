## ADDED Requirements

### Requirement: Sign in with a role
The system SHALL require every user to sign in before using the web application, SHALL give each user a role (worker, supervisor, or staff), and SHALL check on the server that each action is allowed for that role. Production sign-in SHALL use Goodwill's identity provider [TBC with Goodwill IT]; the demo SHALL use synthetic accounts whose passwords come from the environment and are stored only as hashes.

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
The system SHALL keep sessions on the server, SHALL send the session only in an HttpOnly, SameSite=Strict cookie that is Secure over HTTPS (always in production), SHALL require a CSRF token on every write including sign-in, SHALL end a session after configured idle and absolute times [TBC with Goodwill IT], and SHALL delete the session on the server at sign-out.

#### Scenario: Write without the CSRF token
- **WHEN** a signed-in user's browser sends a write without the CSRF token, or with a wrong one
- **THEN** the system refuses it and changes nothing

#### Scenario: Session expired
- **WHEN** a session has been idle longer than the configured time
- **THEN** the next request asks the user to sign in again

#### Scenario: Absolute limit
- **WHEN** a session reaches the configured absolute time, however active it was
- **THEN** the next request asks the user to sign in again

#### Scenario: Signed out
- **WHEN** a user signs out and someone later sends the old session cookie
- **THEN** the system answers "not signed in"

### Requirement: Limit sign-in attempts
The system SHALL lock a username for a configured time after a configured number of failed sign-ins within a window, SHALL limit sign-in attempts from one client address, and SHALL answer every failed or refused sign-in with the same message whether or not the username exists.

#### Scenario: Repeated failures
- **WHEN** a username has the configured number of failed sign-ins within the window
- **THEN** every sign-in for it is refused until the lockout ends, even with the right password

#### Scenario: Unknown username
- **WHEN** someone signs in with a username that does not exist
- **THEN** the answer is the same as for a wrong password, and repeated tries lock the same way

### Requirement: Audit sign-in events
The system SHALL audit each sign-in, sign-out, failed sign-in, lockout, refused sign-in, and expired session with the time and the known username, and SHALL NOT record a password, a session or CSRF token, or a username that does not exist.

#### Scenario: Failed sign-in audited
- **WHEN** a sign-in fails
- **THEN** the audit shows a failed sign-in with the time, and with the username only if the account exists
- **AND** no password or token appears in the audit or the logs

### Requirement: Use the same core for every use case
The web application SHALL offer the same use cases as the email version (new neighbor entry, case notes and services for existing clients, same-name and date of birth verification, and the four read-only query types including the no-contact watchlist) through the same core logic, so the drafting, validation, verification, entry, audit, and retention rules are unchanged.

#### Scenario: Same draft from the same note
- **WHEN** the same note is submitted in the web app and was earlier sent by email
- **THEN** the draft has the same fields, origins, flags, and case note

#### Scenario: Same rules for HMIS writes
- **WHEN** a worker confirms a draft in the web app
- **THEN** HMIS is written only through entry operations, in the same order, with the same retry from the failed step

#### Scenario: Channel-neutral note
- **WHEN** a channel passes a note to the core
- **THEN** it passes a note with the author, title, time written, and text, and the core never sees an email

### Requirement: Worker screens
The system SHALL offer a signed-in worker screens to write a new-client note, write an update note, ask a read-only query, review a draft with each field's value, source quote, origin, and flags, correct it in plain words, answer a same-name verification, pick a client, confirm the current version with a button, retry a failed entry, see the receipt, and correct an entry from its receipt.

#### Scenario: Review screen
- **WHEN** a worker opens a draft in review
- **THEN** each filled or flagged field shows its value, source quote, where it came from, and any flags, and the screen says nothing has been sent to HMIS

#### Scenario: Only the author's drafts
- **WHEN** a worker opens or acts on another worker's draft
- **THEN** the system answers that there is no such draft and changes nothing

#### Scenario: Confirm shows what will be entered
- **WHEN** a worker looks at a draft they can confirm
- **THEN** a short summary of each entry Confirm will make in HMIS is shown right above the Confirm button

#### Scenario: Confirm while a verification is open
- **WHEN** a same-name verification is open on the draft
- **THEN** the Confirm button is shown disabled, with the reason, until the worker chooses Same person or Different person

#### Scenario: Plain buttons and labels
- **WHEN** any worker screen is shown
- **THEN** every button says what it does, every field has a label, and every error says what to do next

#### Scenario: Pick the client with a button
- **WHEN** an update note matches more than one client
- **THEN** each candidate has its own button naming the client, and nothing is drafted until the worker presses one

### Requirement: Supervisor queue screen
The system SHALL show users with the supervisor role the drafts of their team that expired after 48 hours in review [TBC], SHALL show each draft's ID, worker, version, and time in review, and SHALL NOT let a supervisor confirm a draft on a worker's behalf.

#### Scenario: Expired draft
- **WHEN** a draft has been in review for 48 hours
- **THEN** it appears on the supervisor queue screen and the worker sees a notice in the app

#### Scenario: Supervisor tries to confirm
- **WHEN** a supervisor tries to confirm a draft in the queue
- **THEN** the system refuses it and nothing is entered into HMIS

### Requirement: Supervisor views without neighbor information
The system SHALL show a supervisor each draft's state, times, and audit trail in plain words, and each decision flagged because the last four SSN digits matched, showing only that the flag exists, the draft ID, and the worker's written reason with any digits or dates hidden. It SHALL NOT show SSN digits, a date of birth, a title, field values, or note text [TBC with Goodwill: what supervisors may see], and SHALL NOT let a supervisor run a worker action.

#### Scenario: Flagged decision
- **WHEN** a worker chooses Different person although the last four SSN digits matched
- **THEN** the supervisor sees the flag, the draft ID, and the reason, and never the digits, even if the worker wrote them in the reason

#### Scenario: Draft's audit trail
- **WHEN** a supervisor opens a draft
- **THEN** it shows the state, times, HMIS identifiers, and what happened in plain words, and no name, date of birth, or note text

#### Scenario: Worker action refused
- **WHEN** a supervisor tries to confirm, correct, retry, write a note, or run a query
- **THEN** the system refuses it and changes nothing

#### Scenario: Limit applied without a job
- **WHEN** a draft passes the limit and any signed-in request arrives
- **THEN** the draft moves to the supervisor queue, and Confirm is refused from then on

### Requirement: Run the retention jobs without the email channel
The system SHALL run the same retention jobs whether or not the email channel is on: deleting stored copies after their retention time, and deleting held notes and unsubmitted drafts after the configured days. They SHALL run before each signed-in request and on a timer in the server, so they hold with nobody signed in. The audit of a deletion SHALL record its type and count only, never content.

#### Scenario: Copies past their retention time
- **WHEN** stored copies pass their retention time and the jobs run
- **THEN** the copies are deleted and the audit records "stored_copies" and how many

#### Scenario: Seven days old with the email channel off
- **WHEN** a held note or an unsubmitted draft is 7 days old and the email channel is off
- **THEN** it is deleted with its copies, and the audit records whether it was a held note or an unsubmitted draft and a count, with no state, title, or note text

#### Scenario: Nobody signed in
- **WHEN** a retention time passes and nobody is signed in
- **THEN** the timer still runs the jobs

### Requirement: Web API over the core
The system SHALL offer a versioned JSON API for every worker, supervisor, and staff action, SHALL check the user's role and the draft's author on every call, and SHALL return only the data the screen shows, with the same minimal-data rules as the email replies.

#### Scenario: Query through the API
- **WHEN** a worker asks for a briefing through the API
- **THEN** the response holds only the minimal fields of the email reply, as structured data

#### Scenario: Draft through the API
- **WHEN** a worker fetches their draft's review data
- **THEN** the response holds the same fields as the review screen and nothing else

#### Scenario: Author and project from the session
- **WHEN** a request names an author or a project
- **THEN** the system refuses it, because both always come from the signed-in user

### Requirement: Keep email as an optional channel, off by default
The final email-based version SHALL stay available at the tag `v1-email-headless`. The email channel SHALL stay in the code as an optional channel over the same core, off by default behind a config flag, until the sponsors decide whether to keep it as a fallback [TBC with the sponsors]. When it is off, no email is read or sent.

#### Scenario: Running the email demo
- **WHEN** a developer checks out `v1-email-headless`
- **THEN** the email demo and its tests run as before

#### Scenario: Email channel off
- **WHEN** the email channel flag is off and a note arrives by email
- **THEN** the system neither processes it nor replies
- **AND** the email demo's routes, which have no sign-in, are not served

#### Scenario: Email channel on
- **WHEN** the email channel flag is on
- **THEN** an emailed note goes through the same core and rules as a note written in the app

#### Scenario: Draft made in the web app
- **WHEN** the email channel flag is on and a worker writes a note in the web app
- **THEN** its draft gets no review or verification email, and only drafts from emailed notes get emails

### Requirement: Ask HMIS with fixed forms
The web app SHALL offer the four read-only query types (briefing, lookup, status check, no-contact watchlist) only as forms with fixed fields, never free text and never through a parser, with the same checks, limits, minimal results, project visibility, and audit as an email query. Results SHALL be shown once and not stored, and the forms SHALL say they are unavailable while offline.

#### Scenario: Watchlist in plain language
- **WHEN** a worker opens the no-contact watchlist
- **THEN** it lists "Past 60 days" and "Approaching 60 days", each row with the client ID, first name and last initial, last contact date, and quadrant

#### Scenario: Hidden record
- **WHEN** a worker looks up a client their project cannot see
- **THEN** the answer is exactly the answer for a client who does not exist

#### Scenario: Same audit as email
- **WHEN** a worker runs a query from a form
- **THEN** the audit records the type, the quadrant or client ID, the status type, and the row count, with a name or date of birth only as "given", exactly as for an email query

#### Scenario: Offline
- **WHEN** the device is offline
- **THEN** the query screens say that looking things up needs a connection, and no query can be sent

#### Scenario: Only workers
- **WHEN** a supervisor or staff user asks for a query
- **THEN** the system refuses it

### Requirement: Word messages for each channel
The core SHALL name each message to a worker or supervisor with a neutral key and its parameters, and each channel SHALL supply the words: the web screens name buttons (Confirm, Try again, Same client, Different person, Make a correction) and never ask the worker to reply, and email keeps its reply commands and reference tokens. Audit events SHALL have neutral names, and events recorded under an old name SHALL still be read under the new one.

#### Scenario: Web message
- **WHEN** a worker using the web app gets any message, flag, or screen text
- **THEN** it names the buttons on the screen and contains no email wording such as "reply CONFIRM"

#### Scenario: Email message
- **WHEN** a worker using the email channel gets the same message
- **THEN** it keeps the email wording and the reference token the email channel reads

#### Scenario: Old audit history
- **WHEN** an audit record written before the rename is read (for example "review_sent")
- **THEN** it is shown under the neutral name ("ready_for_review") and still says what it was called

### Requirement: Demo-only views of draft contents
The parser-run, mapped-draft, and staged-record views SHALL be served only when a demo configuration flag is on, off by default, because they show draft contents. Who needs them outside the demo is [TBC with Goodwill].

#### Scenario: Flag off
- **WHEN** the flag is off and someone opens one of these views
- **THEN** the system answers that it does not exist

### Requirement: Staff audit views without neighbor information
The system SHALL give users with the staff role read-only views of the audit (draft IDs, kinds, states, workers, versions, times, entry identifiers, and the query log with types and row counts) and SHALL NOT show staff note text, draft titles, field values, or the worker's written reasons.

#### Scenario: Staff opens a draft's audit
- **WHEN** a staff user opens a draft's audit
- **THEN** it shows who confirmed it, when, the versions, and the HMIS identifiers, and no name, date of birth, SSN digits, note text, or reason

#### Scenario: Staff tries to change something
- **WHEN** a staff user tries to write a note, open a worker's draft, or open the supervisor queue
- **THEN** the system refuses it and changes nothing

### Requirement: Idempotency keys on HMIS entry operations
When the author confirms a version, the system SHALL make an HMIS idempotency key and store it with the draft before the first HMIS call, SHALL send it with each entry step, SHALL reuse it on every retry, and SHALL never take it from a request. A retry SHALL NOT reopen the same-name verification, and the possible-duplicate backstop SHALL still apply. Whether the real HMIS accepts the key is [TBC with CHIP]; the mock HMIS does.

#### Scenario: HMIS saved the entry but the answer was lost
- **WHEN** HMIS records a client but its answer is lost, and the worker retries
- **THEN** HMIS returns the same client ID, exactly one client exists, and the replay is audited with the step and draft ID only

#### Scenario: Retry after a timeout that saved nothing
- **WHEN** HMIS did not answer and saved nothing, and the worker retries
- **THEN** the entry is made once

#### Scenario: Key cannot be changed
- **WHEN** a retry or a confirm request tries to send its own HMIS key
- **THEN** the system refuses the request, and the stored key is used

#### Scenario: New version, new key
- **WHEN** the worker confirms a corrected version
- **THEN** a new key is made for it

#### Scenario: Same-name check still applies
- **WHEN** a second draft names a client already entered
- **THEN** the same-name verification opens as before, and HMIS still refuses a possible duplicate sent with a new key

### Requirement: Label entered drafts "Entered in HMIS"
The worker and supervisor screens SHALL show a draft that HMIS has accepted as "Entered in HMIS", so it is never confused with an entry on the device that has only been uploaded to the server.

#### Scenario: Draft entered
- **WHEN** HMIS accepts every entry for a draft
- **THEN** the draft shows "Entered in HMIS" with the identifiers HMIS assigned
