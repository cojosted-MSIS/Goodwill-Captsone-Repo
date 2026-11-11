## ADDED Requirements

### Requirement: Open and write entries offline
The web application SHALL open without a connection through a service worker that caches the app shell, and SHALL let a signed-in worker write a new-client note or an update note while offline, saving it in an IndexedDB queue on the device until it uploads. Corrections need the draft, so they need a connection.

#### Scenario: Note written with no connection
- **WHEN** the connection drops and the worker writes and saves a new-client note
- **THEN** the note is kept on the device with the status "Saved on device"
- **AND** nothing is sent to the server or HMIS until the connection returns

#### Scenario: App opened offline
- **WHEN** the worker opens the app with no connection
- **THEN** the app opens and shows the entries saved on the device and their status

### Requirement: Upload automatically with retries
The system SHALL upload queued entries automatically when the connection returns, when the app opens, and through background sync where supported, SHALL retry a failed upload with exponential backoff and jitter (starting at 5 seconds, capped at 5 minutes), and SHALL never upload the same entry twice at once.

#### Scenario: Connection returns
- **WHEN** the connection returns while entries are saved on the device
- **THEN** the app uploads them without the worker doing anything

#### Scenario: Server not reachable
- **WHEN** an upload fails because the server cannot be reached
- **THEN** the entry stays on the device and is retried later with a longer wait each time

### Requirement: Idempotency key per submission
Every write SHALL carry an idempotency key created when the entry is first saved. The server SHALL keep a hash of each key per user with a hash of the request and the result, never note text; SHALL answer a repeat with the original result and create nothing; SHALL refuse the same key with a different request; SHALL give two simultaneous repeats one result; and SHALL forget keys after a configured time longer than the device queue's expiry.

#### Scenario: Response lost, upload retried
- **WHEN** an upload reaches the server but the response is lost and the app retries with the same key
- **THEN** the server returns the same draft ID and no second draft is created

#### Scenario: HMIS response lost, entry retried
- **WHEN** an entry operation reaches HMIS but its response is lost and the step is retried with the same key
- **THEN** HMIS records the client once and returns the same ID

#### Scenario: Key reused for a different entry
- **WHEN** a request arrives with a known key but a different body
- **THEN** the server refuses it and the entry shows "Needs attention"

#### Scenario: Two repeats at once
- **WHEN** two requests with the same key and body arrive at the same time
- **THEN** the action runs once and both get the same result

#### Scenario: Keys belong to one user
- **WHEN** another user sends a request with a key someone else already used
- **THEN** it is treated as a new request

#### Scenario: Replay audited
- **WHEN** the server answers a repeat with the original result
- **THEN** the audit records the replay with the action type and the draft ID only, never the key or any neighbor information

### Requirement: Visible status per entry
The app SHALL show every entry written on the device with one status: "Saved on device", "Uploading", "Uploaded" (the server has it; it is not in HMIS until the worker confirms), or "Needs attention" with the reason in plain words.

#### Scenario: Upload accepted
- **WHEN** the server accepts an uploaded entry
- **THEN** its status becomes "Uploaded" and the app links to its review or verification screen

#### Scenario: Upload refused
- **WHEN** the server refuses an entry, for example because the client ID is not in HMIS
- **THEN** its status becomes "Needs attention" with the same plain-words reason the email version gave

### Requirement: Handle conflicts with the existing checks
An uploaded entry SHALL go through every check an emailed note did: the client ID check, the same-name and date of birth lookup, the open-draft keyed hash, and validation. At entry, the HMIS possible-duplicate rejection SHALL stay as the backstop. No check SHALL be skipped because the entry was written offline.

#### Scenario: Same neighbor drafted on two devices offline
- **WHEN** two workers write new-client notes for the same name and date of birth while offline and both upload
- **THEN** the second draft is flagged with the first draft's ID only, as for emailed notes

#### Scenario: Duplicate rejected at entry
- **WHEN** HMIS rejects a confirmed entry as a possible duplicate
- **THEN** the worker sees the existing plain-words failure and nothing more is entered

### Requirement: Verify and confirm only online
An entry written offline SHALL be parsed, verified, and reviewed only on the server after it uploads. The device SHALL NOT confirm, choose SAME CLIENT or DIFFERENT PERSON, or enter anything on the worker's behalf. The Confirm button SHALL be disabled while offline, and a Confirm SHALL never be queued.

#### Scenario: Same-name match for an offline entry
- **WHEN** an entry written offline uploads and the lookup finds a client with the same name and date of birth
- **THEN** the worker sees the verification screen the next time they are online, and Confirm stays refused until they answer it

#### Scenario: Confirm pressed offline
- **WHEN** the worker is offline on a review screen
- **THEN** the Confirm button is disabled and says a connection is needed

### Requirement: Store as little as possible on the device
The device SHALL store only queued entries (note type, client ID for updates, note text, time written, idempotency key, status) and the app shell, SHALL encrypt queued entries, SHALL delete an entry once uploaded, and SHALL expire entries not uploaded within 72 hours. Whether the last four SSN digits may be on the device, and shared devices, are [TBC with Goodwill and CHIP].

#### Scenario: Entry stored encrypted
- **WHEN** an entry is saved on the device
- **THEN** its note text is stored only in encrypted form

### Requirement: Keep full SSNs out of the device queue
Because the queue holds raw note text, the app SHALL, before saving: mask each full SSN matching the server's pattern to its last four digits and show the worker; refuse to save a note in which a looser detector still finds an SSN word followed by seven or more digits, asking for the last four only; and warn on the form. The server SHALL mask again on upload. Numbers in words are not detected [TBC with Goodwill and CHIP].

#### Scenario: Full SSN in an offline note
- **WHEN** a worker writes "SSN 123-45-6789" in a note while offline
- **THEN** the text saved on the device has "***-**-6789" and the worker sees the masked text and a notice

#### Scenario: SSN in another form
- **WHEN** a worker writes "social 123 45 6789" in a note while offline
- **THEN** the entry is not saved and the app asks the worker to write only the last four digits

#### Scenario: Last four only
- **WHEN** a worker writes "SSN ends 6789"
- **THEN** the note is saved unchanged

#### Scenario: Entry uploaded
- **WHEN** the server confirms it has an uploaded entry
- **THEN** the entry is deleted from the device

#### Scenario: Entry about to expire
- **WHEN** an entry has waited 60 hours without uploading
- **THEN** it shows a warning that it will be deleted

#### Scenario: Entry never uploaded
- **WHEN** an entry has not uploaded within 72 hours
- **THEN** its envelope is deleted and a notice with no content stays until the worker dismisses it

### Requirement: Cache only the static app shell
The service worker SHALL cache only the static app shell, from a fixed list, and SHALL NOT store any `/api` response, draft, or query result. Every `/api` response, including errors, SHALL carry `Cache-Control: no-store`. A new version SHALL wait until no note is being typed before it takes over.

#### Scenario: After using the app online
- **WHEN** a worker has used the app and the cache is inspected
- **THEN** it holds exactly the shell's files and no API response

#### Scenario: New version while typing
- **WHEN** a new version arrives while a worker is typing a note
- **THEN** the note stays as typed and the new version takes over at the next screen

#### Scenario: Offline is capture only
- **WHEN** the connection goes while a draft is on screen
- **THEN** Confirm and the other actions are disabled, and the screen says notes can be written and reviewed when back online

### Requirement: Never keep refused SSN text
When the app refuses a note because it still looks like it holds a full SSN, the refused text SHALL stay only in the open form so the worker can rewrite it, and SHALL NOT be written to the device queue, browser storage (local storage, IndexedDB, or caches), any saved or auto-saved draft, a log, or the server. Leaving the screen discards it.

#### Scenario: Note refused for an SSN
- **WHEN** a worker's note is refused because it looks like it holds a full SSN
- **THEN** the text stays in the form for the worker to rewrite, and nothing with it is saved on the device or sent

#### Scenario: Worker leaves the refused note
- **WHEN** the worker leaves the screen without rewriting the note
- **THEN** the refused text is gone and nothing of it can be found on the device

### Requirement: Wipe the device at sign-out
Signing out SHALL delete the offline queue and its encryption key from the device. If entries are still waiting to upload, the app SHALL warn the worker first and offer to upload them.

#### Scenario: Sign out with entries waiting
- **WHEN** a worker signs out while two entries are saved on the device
- **THEN** the app warns that they have not uploaded and offers to upload them first
- **AND** after sign-out the queue and key are gone from the device

### Requirement: Finish an offline sign-out first
A sign-out made while offline SHALL wipe the device at once and record a pending flag. On reconnection the sign-out request SHALL be sent before any other request that carries the session, and no one SHALL be able to sign in on that device until it completes.

#### Scenario: Sign out with no connection
- **WHEN** a worker signs out while offline
- **THEN** their envelopes, the cached public key, and their profile are deleted immediately

#### Scenario: Connection returns
- **WHEN** the connection returns after an offline sign-out
- **THEN** the sign-out request is sent first and the old session ends

#### Scenario: Another worker on the same device
- **WHEN** another worker tries to sign in before the sign-out has completed
- **THEN** no sign-in form is offered until it has

### Requirement: Seal queued notes to the server
Each queued note SHALL be encrypted so the device cannot read it back, with a key wrapped to a server public key named by key ID. The envelope SHALL be bound to the user ID and the Idempotency-Key as authenticated data. The server SHALL hold several private keys, read from the environment, so a rotation never strands a note.

#### Scenario: Envelope moved to another user
- **WHEN** a signed-in worker uploads an envelope sealed for another worker
- **THEN** the server refuses it and nothing is drafted

#### Scenario: Envelope replayed under another key
- **WHEN** an envelope is uploaded with a different Idempotency-Key
- **THEN** the server refuses it and nothing is drafted

#### Scenario: Key rotated
- **WHEN** the server has a new key and an envelope names an older key it still holds
- **THEN** the envelope opens

### Requirement: Enforce offline limits on the server
When an envelope arrives the server SHALL check its times against its own clock: refuse a note written more than `web.offline_write_hours` after a server-signed contact stamp, a forged stamp, a future date, or a note older than the queue limit. A repeat of an accepted note SHALL still get its first answer. The limit is [TBC with Goodwill].

#### Scenario: Written past the limit
- **WHEN** an envelope arrives for a note written more than 12 hours after the device last reached the server
- **THEN** the server refuses it with a plain reason and nothing is drafted

### Requirement: Keep each account's notes apart on a shared device
A note SHALL belong to the worker who wrote it. Another account on the same device SHALL see only a count of waiting notes, with no time or kind, and SHALL NOT be able to upload them. Shared devices are [TBC with Goodwill].

#### Scenario: Another worker signs in
- **WHEN** a different worker signs in on a device holding a note from another account
- **THEN** they see only "1 note from another account is waiting on this device"

#### Scenario: A timed-out session
- **WHEN** a worker's session times out with notes on the device
- **THEN** the envelopes stay, unreadable, until that worker signs in or they reach the 72-hour limit

### Requirement: Read-only queries while offline
No read-only query SHALL run while offline. The Ask HMIS screen SHALL say a connection is needed, and no query result SHALL ever be stored on the device.

#### Scenario: Briefing asked offline
- **WHEN** a worker asks for a briefing with no connection
- **THEN** the app says queries need a connection, runs nothing, and stores nothing
