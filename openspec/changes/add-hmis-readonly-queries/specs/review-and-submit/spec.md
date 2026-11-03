## RENAMED Requirements
- FROM: `### Requirement: Enter into HMIS without reading from it`
- TO: `### Requirement: Write to HMIS only through entry operations`

## MODIFIED Requirements

### Requirement: Write to HMIS only through entry operations
The system SHALL write to HMIS only through entry operations, each only after the worker's CONFIRM, and SHALL take back from an entry operation only success or failure and the identifiers HMIS assigns. The system SHALL read HMIS only through the read-only queries of `hmis-readonly-queries` [TBC with CHIP and the HMIS administrator: the real HMIS has no confirmed API or SQL access], and a read SHALL never write.

#### Scenario: Entry succeeds
- **WHEN** HMIS accepts the entries
- **THEN** the draft moves to submitted
- **AND** the worker receives a receipt listing the identifiers HMIS assigned

#### Scenario: Entry fails
- **WHEN** HMIS rejects an entry or cannot be reached
- **THEN** the draft moves to failed
- **AND** the worker receives a failure notice with the reason
- **AND** the notice and the failure screen say in plain words which step failed and why, for example "The mock HMIS did not answer", without note text or keys
- **AND** the confirmed draft is kept so the worker can retry

#### Scenario: Reading does not write
- **WHEN** the system reads HMIS to answer a query or to check a draft
- **THEN** it uses only the read-only query connection
- **AND** no HMIS record is created or changed

### Requirement: Reset the demo between runs (demo only)
The demo SHALL offer a reset, labelled "demo only", that clears the mock HMIS records and its identifier counters, reloads the synthetic seed data of the mock HMIS read-only layer, and clears the local staging store (drafts, held notes, emails, audit records, and identifier counters). The reset SHALL act only when the configured HMIS address is on this machine and the HMIS answers as the mock HMIS, SHALL change nothing otherwise, SHALL require an explicit confirmation, and SHALL NOT be reachable through any email or reply.

#### Scenario: Reset before a second run
- **WHEN** the presenter resets the demo after Scenarios A and B were submitted
- **THEN** the home screen shows no drafts and the inbox is empty
- **AND** running Scenario A again is accepted, with the first identifiers HMIS-C-000001, HMIS-E-000002, and HMIS-CE-000003

#### Scenario: Reset reseeds the read-only layer
- **WHEN** the presenter resets the demo after clients were entered and queried
- **THEN** queries see exactly the synthetic seed data again

#### Scenario: HMIS is not a local mock
- **WHEN** the configured HMIS address is not on this machine
- **THEN** the reset is refused before any request is sent
- **AND** nothing in the staging store is cleared

#### Scenario: HMIS does not answer as the mock
- **WHEN** the HMIS at the configured address does not answer the reset as the mock HMIS
- **THEN** the reset is refused and nothing in the staging store is cleared

#### Scenario: Email cannot reset
- **WHEN** a worker emails a note, a reply, or a query that says "reset demo"
- **THEN** nothing is reset and the email is handled as an ordinary note, reply, or query
