## MODIFIED Requirements

### Requirement: Accept HMIS queries by email
The system SHALL accept a query only from a signed-in worker on the Ask HMIS screen, SHALL answer it on screen to that worker, and SHALL NOT create a draft from a query. The parser SHALL still only pick one of the four fixed query types and copy its parameters; it SHALL never write SQL.

#### Scenario: Query from an authorized worker
- **WHEN** a signed-in worker asks "who has been reported in the SW quadrant?"
- **THEN** the answer is shown to that worker on screen

#### Scenario: Query from an unrecognized sender
- **WHEN** a query is sent without a valid session, so the sender is not a recognized worker
- **THEN** no query runs and nothing is returned

#### Scenario: A query never becomes a draft
- **WHEN** a query names a neighbor and a date of birth
- **THEN** no draft is created and nothing is staged for entry

### Requirement: Queries never change anything
A query SHALL NOT write to HMIS, SHALL NOT create, change, or confirm a draft, and SHALL NOT change anything in the staging store except its own audit record. The answer SHALL be shown to the worker and not stored by the server; the query email retention period no longer applies.

#### Scenario: HMIS after a query
- **WHEN** a briefing, a lookup, a status check, and a no-contact watchlist have been answered
- **THEN** every HMIS record is exactly as it was before them

#### Scenario: Query emails deleted after the retention period
- **WHEN** query email copies stored before this change are 24 hours old
- **THEN** they are deleted under the old rule and their audit records remain; queries asked in the app create no copies to delete

#### Scenario: Answer not stored
- **WHEN** a query has been answered
- **THEN** the staging store holds only its audit record (type, parameters as audited, row count), not the answer
