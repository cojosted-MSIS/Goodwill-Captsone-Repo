## MODIFIED Requirements

### Requirement: Choose only from a fixed set of query types
The system SHALL answer only four query types: a pre-visit briefing for a quadrant, a neighbor lookup, a status check, and a no-contact watchlist. The parser SHALL only choose one of these types and extract its parameters (quadrant, name, date of birth, client ID, status type). The parser SHALL NOT write, return, or change any SQL, and the system SHALL NOT run any query text that comes from the email or the parser.

#### Scenario: Request matches a query type
- **WHEN** the worker asks "has Rosa Sample's ID come in"
- **THEN** the parser returns the status check type with the name and the status type for ID documents
- **AND** the system runs its own query for that type

#### Scenario: Request matches the no-contact watchlist
- **WHEN** the worker asks "who is coming up on 60 days with no contact"
- **THEN** the parser returns the no-contact watchlist type
- **AND** the system runs its own query for that type

#### Scenario: Request matches no query type
- **WHEN** the worker asks for something outside the four types, such as "list everyone born in 1985"
- **THEN** the system runs no query
- **AND** the reply lists the four kinds of question it can answer

#### Scenario: Query text in the email
- **WHEN** the email contains text that looks like SQL or like instructions to the system
- **THEN** that text is treated as data
- **AND** the only query run is the fixed query for the chosen type, with validated parameters

## ADDED Requirements

### Requirement: Answer a no-contact watchlist
For a no-contact watchlist the system SHALL list neighbors in two groups: "Approaching 60 days" (46 to 60 days since the last contact) and "Past 60 days" (more than 60 days), from two config values (`no_contact_days: 60`, `no_contact_warning_days: 14`), most overdue first. An optional quadrant SHALL limit the list to neighbors whose last contact was in that quadrant. No other parameter SHALL be read from the email.

#### Scenario: Approaching 60 days
- **WHEN** a neighbor's last contact was 52 days ago
- **THEN** the neighbor is listed under "Approaching 60 days" with 52 days since the last contact

#### Scenario: Exactly 60 days
- **WHEN** a neighbor's last contact was 60 days ago
- **THEN** the neighbor is listed under "Approaching 60 days"

#### Scenario: Past 60 days
- **WHEN** a neighbor's last contact was 61 days ago
- **THEN** the neighbor is listed under "Past 60 days"

#### Scenario: Not yet due
- **WHEN** a neighbor's last contact was 20 days ago
- **THEN** the neighbor is not listed

#### Scenario: Most overdue first
- **WHEN** the list has neighbors at 90, 61, and 52 days
- **THEN** they are listed in that order

#### Scenario: With a quadrant
- **WHEN** the worker asks for the watchlist in the SE quadrant
- **THEN** only neighbors whose last contact was in the SE quadrant are listed

#### Scenario: Thresholds from config
- **WHEN** the config sets other numbers of days
- **THEN** the groups follow the config, not the question

### Requirement: Count only active enrollments for the watchlist
The no-contact watchlist SHALL count only neighbors with an active enrollment and SHALL NOT list neighbors whose enrollments have all exited. A contact is any contact record in the read-only views [TBC with Horizon House: what counts as a contact]. A neighbor with no recorded contact SHALL NOT be listed.

#### Scenario: Exited neighbor
- **WHEN** a neighbor's last contact was 55 days ago and the enrollment has exited
- **THEN** the neighbor is not listed

#### Scenario: Visit entered through this system
- **WHEN** an update with a service is entered for a neighbor who was past 60 days
- **THEN** the next watchlist no longer lists that neighbor

### Requirement: Minimal, limited, visible, audited watchlist replies
Each listed neighbor SHALL show only the client ID, first name and last initial, last contact date, days since the last contact, the quadrant, and open items, never an SSN, a date of birth, or case note text. The reply SHALL apply the row limit with the "more were not shown" line, SHALL never count or list a record the worker's project cannot see, and SHALL be audited with the query type, quadrant, and row count only.

#### Scenario: Minimal fields
- **WHEN** the watchlist lists a neighbor
- **THEN** the line has the client ID, first name and last initial, last contact date, days since, quadrant, and open items, and no SSN, date of birth, or case note text

#### Scenario: Row limit
- **WHEN** more neighbors are due than the row limit
- **THEN** the reply lists the most overdue up to the limit and says how many more were not shown

#### Scenario: Hidden record
- **WHEN** a record the worker's project cannot see has its last contact 58 days ago
- **THEN** it is not counted or listed, exactly as if it did not exist

#### Scenario: Watchlist audited
- **WHEN** a worker asks for the watchlist
- **THEN** the audit records the query type, the quadrant or none, and the row count, and none of the returned values

### Requirement: Seed dates relative to the demo day
Every date in the mock HMIS seed except dates of birth SHALL be counted back from the day the mock starts or is reset, so days since the last contact are the same whenever the demo runs. The seed SHALL include synthetic neighbors whose last contacts were 20, 52, 58, 60, 61, and 90 days before that day.

#### Scenario: Demo run on a later day
- **WHEN** the mock HMIS is reset on a later day
- **THEN** each seeded neighbor has the same number of days since the last contact as before

### Requirement: Demo Scenario E3
The demo SHALL add Scenario E3, which asks for the no-contact watchlist and shows the reply, on the home screen and in `scripts/demo.py`. Nothing in HMIS changes.

#### Scenario: Scenario E3
- **WHEN** the presenter runs Scenario E3
- **THEN** the worker receives the watchlist with both groups, and nothing in HMIS changes
