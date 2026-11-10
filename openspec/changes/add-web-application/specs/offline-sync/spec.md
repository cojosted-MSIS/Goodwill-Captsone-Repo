## ADDED Requirements

### Requirement: Open and write entries offline
The web application SHALL open without a connection through a service worker that caches the app shell, and SHALL let a signed-in worker write a new-client note, an update note, or a correction while offline, saving it in an IndexedDB queue on the device until it uploads.

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

#### Scenario: Entry never uploaded
- **WHEN** an entry has not uploaded within 72 hours [TBC]
- **THEN** it shows "Needs attention", and it is deleted from the device after 7 days

### Requirement: Wipe the device at sign-out
Signing out SHALL delete the offline queue and its encryption key from the device. If entries are still waiting to upload, the app SHALL warn the worker first and offer to upload them.

#### Scenario: Sign out with entries waiting
- **WHEN** a worker signs out while two entries are saved on the device
- **THEN** the app warns that they have not uploaded and offers to upload them first
- **AND** after sign-out the queue and key are gone from the device

### Requirement: Read-only queries while offline
No read-only query SHALL run while offline. The Ask HMIS screen SHALL say a connection is needed, and no query result SHALL ever be stored on the device.

#### Scenario: Briefing asked offline
- **WHEN** a worker asks for a briefing with no connection
- **THEN** the app says queries need a connection, runs nothing, and stores nothing
