## MODIFIED Requirements

### Requirement: Require a statement that the worker searched HMIS
The system SHALL draft a new client only when the worker's email states that they searched HMIS and found no existing record. The system SHALL read HMIS only through the read-only queries of `hmis-readonly-queries` and SHALL NOT write to HMIS before CONFIRM.

#### Scenario: Worker states no match
- **WHEN** the email says the worker searched HMIS and found no match
- **THEN** the system drafts a new client from the details in the email
- **AND** the system writes nothing to HMIS before the worker confirms

#### Scenario: Search not stated
- **WHEN** the email gives new client details but does not say the worker searched HMIS
- **THEN** the system asks the worker to confirm they searched and found no match
- **AND** the system does not create a draft until the worker does
