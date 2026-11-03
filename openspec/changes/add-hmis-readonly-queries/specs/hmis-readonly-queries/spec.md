## ADDED Requirements

### Requirement: Accept HMIS queries by email
The system SHALL accept a query only as an email from an authorized worker to the intake inbox, SHALL recognize a query by the subject prefix "Query:", SHALL answer it by email to the worker who asked, and SHALL NOT create a draft from a query.

#### Scenario: Query from an authorized worker
- **WHEN** an authorized worker emails "Query: who has been reported in the SW quadrant?"
- **THEN** the system replies to that worker by email with the answer

#### Scenario: Query from an unrecognized sender
- **WHEN** a query arrives from an address that is not on the authorized worker list
- **THEN** the system drops it without running any query and without replying

#### Scenario: A query never becomes a draft
- **WHEN** a query email names a neighbor and a date of birth
- **THEN** no draft is created and nothing is staged for entry

### Requirement: Choose only from a fixed set of query types
The system SHALL answer only three query types: a pre-visit briefing for a quadrant, a neighbor lookup, and a status check. The parser SHALL only choose one of these types and extract its parameters (quadrant, name, date of birth, client ID, status type). The parser SHALL NOT write, return, or change any SQL, and the system SHALL NOT run any query text that comes from the email or the parser.

#### Scenario: Request matches a query type
- **WHEN** the worker asks "has Rosa Sample's ID come in"
- **THEN** the parser returns the status check type with the name and the status type for ID documents
- **AND** the system runs its own query for that type

#### Scenario: Request matches no query type
- **WHEN** the worker asks for something outside the three types, such as "list everyone born in 1985"
- **THEN** the system runs no query
- **AND** the reply lists the three kinds of question it can answer

#### Scenario: Query text in the email
- **WHEN** the email contains text that looks like SQL or like instructions to the system
- **THEN** that text is treated as data
- **AND** the only query run is the fixed query for the chosen type, with validated parameters

### Requirement: Validate query parameters before running anything
The system SHALL check every parameter against the rules in `design.md` (quadrant, client ID format [TBC], full date of birth read by code, first and last name with a date of birth, configured status type) before running a query. If a parameter is missing or invalid, the system SHALL run no query and SHALL ask the worker for what is missing.

#### Scenario: Name without a date of birth
- **WHEN** the worker asks to look up "Rosa Sample" without a date of birth or a client ID
- **THEN** the system runs no query
- **AND** the reply asks for the date of birth or the client ID

#### Scenario: Partial date of birth
- **WHEN** the worker gives a date of birth as "1985" only
- **THEN** the system runs no query and asks for the full date of birth

#### Scenario: Unknown quadrant
- **WHEN** the worker asks for a briefing for "downtown"
- **THEN** the system runs no query and asks which quadrant (NW, NE, SW, or SE)

### Requirement: Run only parameterized queries on allowlisted read-only views
The system SHALL run each query type as a fixed, parameterized query written in code, SHALL bind parameters and never build query text from them, SHALL read only from an allowlist of read-only views, SHALL use a database connection that cannot write, and SHALL return at most a configured number of rows (25). When more rows match, the reply SHALL say how many more were not shown and ask the worker to narrow the query.

#### Scenario: Row limit reached
- **WHEN** more neighbors match a briefing than the row limit
- **THEN** the reply shows the total count and the first 25 rows
- **AND** the reply says how many more were not shown and asks the worker to narrow the query

#### Scenario: Connection cannot write
- **WHEN** anything tries to change data through the query connection
- **THEN** the database refuses it and nothing changes

#### Scenario: View not on the allowlist
- **WHEN** a query would read a table or view that is not on the allowlist
- **THEN** the system refuses to run it

### Requirement: Answer a pre-visit briefing for a quadrant
The system SHALL answer a briefing for a quadrant with the number of neighbors reported there within a configured window (90 days) and, for each neighbor, only the client ID, the first name and last initial, the last contact date, and the open items as short labels (for example "ID document pending" or "housing assessment scheduled").

#### Scenario: Briefing for a quadrant
- **WHEN** the worker asks for a briefing for the SW quadrant
- **THEN** the reply gives the count and one line per neighbor with the client ID, first name and last initial, last contact date, and open items

#### Scenario: Nobody reported in the quadrant
- **WHEN** no visible neighbor has been reported in the quadrant
- **THEN** the reply says no neighbors were found and shows a count of zero

### Requirement: Look up a neighbor by name and date of birth or by client ID
The system SHALL look up a neighbor by first name, last name, and full date of birth, matching names without regard to case, spacing, or punctuation, or by client ID. The reply SHALL list each matching neighbor with the client ID, first name and last initial, the quadrant and date of the last contact. The system SHALL NOT suggest neighbors with similar names or dates.

#### Scenario: Lookup by client ID
- **WHEN** the worker looks up an existing client ID
- **THEN** the reply shows that one neighbor

#### Scenario: Two neighbors share a name and date of birth
- **WHEN** two visible neighbors match the name and date of birth
- **THEN** the reply lists both, so the worker can tell them apart by client ID, quadrant, and last contact

#### Scenario: No match
- **WHEN** no visible neighbor matches
- **THEN** the reply says no neighbor was found and suggests no other names

### Requirement: Answer status checks from service and assessment records
The system SHALL answer a status check for one neighbor, identified by client ID or by name and date of birth, from the ID document and housing assessment records, with the status and its date (for example "State ID: received 10/20/2026", "Housing assessment: scheduled 11/05/2026", or "No ID document recorded"). If the name and date of birth match more than one neighbor, the system SHALL list the candidates and ask for the client ID instead of answering.

#### Scenario: ID document received
- **WHEN** the worker asks whether Rosa Sample's ID has come in and a received ID document is recorded
- **THEN** the reply gives the document type, "received", and the date

#### Scenario: Nothing recorded
- **WHEN** no housing assessment is recorded for the neighbor
- **THEN** the reply says no housing assessment is recorded

#### Scenario: More than one neighbor matches
- **WHEN** the name and date of birth match two neighbors
- **THEN** the reply lists both candidates and asks the worker to ask again with a client ID

### Requirement: Keep query replies to minimal data
Query replies SHALL NOT include a Social Security number or any part of it, a date of birth (even when the worker gave it), case note text, a full last name, a location more precise than the quadrant, or anything about another person.

#### Scenario: Lookup by date of birth
- **WHEN** the worker looks up a neighbor by name and date of birth
- **THEN** the reply does not repeat the date of birth

#### Scenario: Open items
- **WHEN** a neighbor has an open item recorded in a case note
- **THEN** the briefing shows only the open item label, never the case note text

### Requirement: Return only records the worker's project can see
The mock HMIS SHALL keep a visibility setting for each record, and every query SHALL return and count only records visible to the asking worker's project, as configured for the worker in `config/workers.yaml` [TBC with CHIP: how visibility works in the real HMIS]. A reply SHALL NOT reveal that a hidden record exists.

#### Scenario: Hidden record
- **WHEN** a neighbor's record is not visible to the worker's project
- **THEN** briefings do not count it, lookups do not list it, and status checks answer as if it were not recorded

### Requirement: Audit every query
The system SHALL record for every query, including one that was refused or asked for missing parameters, the worker, the time, the query type, the client ID, quadrant, and status type in full, a name or date of birth only as "given", and the number of rows returned. The audit record SHALL NOT contain any returned value.

#### Scenario: Query answered
- **WHEN** a lookup returns two neighbors
- **THEN** the audit record shows the worker, the time, "lookup", name "given", date of birth "given", and "2 rows"
- **AND** it does not contain the name or date of birth asked about, or the client IDs, names, or dates returned

#### Scenario: Query refused
- **WHEN** a query is refused because a parameter is missing
- **THEN** the audit record shows the worker, the time, the query type, and that no query was run

### Requirement: Queries never change anything
A query SHALL NOT write to HMIS, SHALL NOT create, change, or confirm a draft, and SHALL NOT change anything in the staging store except its own email copies and audit record. Query email copies SHALL be deleted under the same retention rule as other email copies [TBC].

#### Scenario: HMIS after a query
- **WHEN** a briefing, a lookup, and a status check have been answered
- **THEN** every HMIS record is exactly as it was before them

### Requirement: Mock HMIS read-only layer with synthetic seed data
The mock HMIS SHALL provide a read-only SQL layer with views for briefings, lookups, and status checks, seeded only with synthetic neighbors, contacts, services, ID document status, housing assessments, and visibility settings. Seeded client IDs SHALL start at HMIS-C-000101 so clients entered during the demo still start at HMIS-C-000001. Records added through the entry operations SHALL become visible to queries. The demo reset SHALL clear the layer and load the seed data again.

#### Scenario: Seeded neighbor
- **WHEN** the demo starts
- **THEN** a lookup can find the seeded synthetic neighbors

#### Scenario: Entered client becomes visible
- **WHEN** a new client has been entered through the entry operations
- **THEN** a lookup by that client's name and date of birth finds the client

#### Scenario: Reset reseeds
- **WHEN** the presenter resets the demo
- **THEN** clients entered during the demo are gone and the seed data is back as it started
