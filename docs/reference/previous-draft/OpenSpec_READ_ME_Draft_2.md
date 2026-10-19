# OpenSpec Draft Read-Through: add-outreach-email-intake

Read in this order: proposal, design, then the three specs. Items marked [TBC] are open.

---

## File: proposal.md

## Change: Add email-based outreach documentation (Form 101 and Verification Letter)

### Why

Horizon House outreach workers document encounters after the fact, from paper notes or memory, and then re-enter the information in HMIS. Workers already use email, and Goodwill email has encryption and access controls. This change describes an email-driven path: a worker describes an encounter or asks for a document in a plain email, the system drafts the structured entry, and the worker confirms it before anything is entered in HMIS or issued.

The system only enters information. It never searches or reads HMIS. Workers still look up neighbors in HMIS themselves, and they put the identifier they found in their email.

Two documents are specified first because together they show two different kinds of work:

- **CHIP Form 101 (Outreach Observation)** is entry into HMIS. Information goes from an email into an HMIS entry.
- **Horizon House Verification Letter** is document generation with no HMIS involvement. The letter is prepared in the field with the neighbor, so the details come from what the neighbor tells the worker, passed along in the worker's email.

Everything else the pipeline does (identifying the form, confirming with the worker, protecting personal information, reminders, audit) is shared, so it is specified once.

### What Changes

- **ADD** `outreach-email-pipeline`: shared intake, parsing, neighbor identification from the email, new-profile drafts, photo attachments, confirmation, reminders, privacy, retention, and audit behavior.
- **ADD** `form-101-observation`: capture an outreach observation for entry into HMIS.
- **ADD** `verification-letter`: draft a homeless verification letter from details the neighbor gave the worker in the field.

### Impact

- **Affected systems:** the designated secure Goodwill inbox, an AI parsing component, and HMIS (entry only, through an interface to be agreed with CHIP).
- **Not changed:** HMIS configuration, credentialing, login, and data standards. These are owned and administered by CHIP. The system never pulls data out of HMIS.
- **In scope (decided with Goodwill and aligned with DeveloperTown's sample):** photos as attachments (not video), drafting new neighbor profiles after the worker confirms, signatures handled by a CHIP-accepted method, retention of inbox content with an access-controlled audit trail, and a reminder plus supervisor flag for unconfirmed drafts.
- **Architecture:** follows the application architecture notes, with one difference: no HMIS lookup (see `design.md`).
- **Out of scope:** production build, direct-to-client applications, searching or reading HMIS, and any real client data in the team's own work. All examples in these files are made up.
- **Status:** draft for review by the capstone team, Goodwill, and DeveloperTown. Items marked [TBC] are open and listed in `design.md`.

---

## File: design.md

## Design: Email-based outreach documentation

### Context

The team is specifying this change, not building it. These notes record the decisions and open questions behind the specs so DeveloperTown can evaluate and estimate the work. The specs describe behavior at the edges (email in, HMIS entry, worker confirmation), so they stay valid whichever HMIS access method CHIP approves.

The flow, as reviewed with Horizon House on the team's process diagram (no major gaps were identified):

```text
Worker email -> secure inbox -> identify form -> parse into draft
  -> validate with rules -> review email (neighbor, fields, approval)
  -> worker replies APPROVE, EDIT or REJECT
  -> Form 101 or new profile: enter into HMIS, then receipt  |  Letter: return draft letter to worker
```

The worker looks neighbors up in HMIS on their own. The system does not search or read HMIS at any step.

### Alignment with the application architecture

This change follows the "Outreach notes to HMIS: application architecture" (October 2026). The mapping:

| Architecture element | Where it is specified |
|---|---|
| Mail gateway, allow-listed senders, drop all others | `outreach-email-pipeline`: accept messages only from authorized workers |
| AI field extraction, each field cites its source sentence | `outreach-email-pipeline`: fill draft fields only from stated or trusted sources |
| Validation rules (not AI), configuration | `outreach-email-pipeline`: validate drafts with rules; define document fields as configuration |
| Approval workflow, three checkpoints, APPROVE / EDIT / REJECT | `outreach-email-pipeline`: worker approval before any entry or issue |
| Submit and reconcile, receipt, failure notice | `outreach-email-pipeline`: send receipts and failure notices |
| Draft store, mailbox, audit log | `outreach-email-pipeline`: retention, reminder and expiry, audit trail |
| Field mapping as configuration | `outreach-email-pipeline`: define document fields as configuration |

**One deliberate difference:** the architecture's "Client match (1)" proposes candidate clients by looking them up in HMIS. This change does not. The system only enters information and never reads HMIS (Decision 9). Checkpoint 1 is therefore "confirm the neighbor identifier the worker supplied," not "confirm a client the system found." If the team later decides lookups are allowed, the architecture and this change would both need to change together, and the entry-only rule would be revisited with CHIP.

### Why these two documents

| Document | Direction | What it exercises |
|---|---|---|
| CHIP Form 101 (Outreach Observation) | Enter: email to HMIS entry | Free-text parsing, a conditional required-field rule, signatures that email cannot carry, photos, location privacy |
| Horizon House Verification Letter | None: email to generated document | Details supplied by the neighbor in the field, masking, a validity rule, document generation |

Both share identifying the neighbor from the email, missing-field handling, and worker confirmation, which is why those live in `outreach-email-pipeline`.

For estimating: Form 101 is a medium-sized form (a handful of fields, one conditional rule, one free-text field). The letter is small and needs no HMIS access. A large form such as the Head of Household CES Assessment can be added later as the upper bound.

### HMIS interface (logical operations)

These are not HMIS endpoints. They describe what the system needs to enter into HMIS, so DeveloperTown and CHIP can map them to whatever access method is available. All operations are entry only. Nothing is read back out.

| Operation | Direction | Inputs | Returns | Used by |
|---|---|---|---|---|
| `create_neighbor_profile` | Enter | Confirmed new-profile draft | Success, or failure with a reason | `outreach-email-pipeline` |
| `record_outreach_observation` | Enter | Confirmed Form 101 draft, the worker-supplied neighbor identifier | Success, or failure with a reason | `form-101-observation` |
| `attach_document` | Enter | Photo or scan, the worker-supplied neighbor identifier | Success, or failure with a reason | `outreach-email-pipeline` |

The verification letter uses none of these.

### Decisions

1. **The worker approves before anything is entered.** It happens in one review email with three checkpoints: confirm the neighbor, confirm the fields, approve the submission. Nothing reaches HMIS and no document is marked issued on the system's own judgment. This is the main control against a wrong parse. Drafts move through five states: draft, in review, approved, submitted, failed.
2. **No inferred values.** A field is filled only from the email or the worker's profile. Anything else is left blank and flagged, and relative dates are shown resolved for confirmation.
3. **Signatures follow a CHIP-accepted method.** Form 101 needs staff and applicant signatures and a release authorization. An email cannot carry those, so the system shows them as pending until they are completed by whichever method CHIP accepts [TBC], and never records them as obtained from email content.
4. **Personal information stays inside a Goodwill-approved environment.** Where the AI parsing runs is an open question. The specs state the rule, not the hosting.
5. **Location is minimized.** Only the worker's written description is captured. No device coordinates, no copies to maps or shared channels.
6. **Behavior, not model choice.** The specs do not name a model or vendor. They state inputs, outputs, and what happens when the system is unsure.
7. **Photos yes, video no.** Photo attachments are accepted and stored with the entry. Video is not accepted.
8. **New profiles are drafted, then confirmed.** If the worker says they searched HMIS and found no match, the system drafts a new profile from the email and enters it only after the worker confirms.
9. **Enter only, never read.** The system never searches or reads HMIS. The neighbor identifier (HMIS client ID, or name and date of birth) comes from the worker's email and is shown back to the worker for confirmation. Duplicate prevention depends on the worker's own HMIS search and on whatever duplicate handling HMIS has [TBC].

### AI parsing: failure modes

The charter requires a named failure mode, owner, running cost, and governance answer for every AI capability. Owner and cost are not yet known and are marked as such.

| Capability | Failure mode | Consequence | Mitigation | Owner | Running cost |
|---|---|---|---|---|---|
| Field extraction | Misread or invented value (wrong date, wrong place) | Inaccurate verification record | Values must come from the email text; every draft is confirmed by the worker; unstated fields stay blank and flagged | Goodwill to name | Not yet estimated |
| Relative dates | "Last week" resolved to the wrong range | Wrong dates on a federal verification | Show the resolved range and ask for confirmation | Goodwill to name | Not yet estimated |
| Form identification | Wrong form chosen | Wrong fields requested | Ask when unsure; show the form type in the draft | Goodwill to name | Not yet estimated |
| Neighbor identification | Worker mistypes or the system misreads the identifier, so an entry attaches to the wrong person | Another person's record changes | Show the identifier back to the worker; require confirmation; never guess or search | Goodwill to name | Not yet estimated |

### Alternative considered: structured email template

A fill-in email template with labeled lines ("Applicant:", "Location:", "Dates:", "Source:"), read by simple rules with no AI, would capture most Form 101 fields cheaply. AI adds value mainly for the free-text location and dates, relative dates, and detecting an oral referral. The letter needs AI only to read the details in the email; filling the letter is template work. The charter asks that each AI capability be tested against a cheaper alternative, so the team and Goodwill should decide whether to start with the template and add AI only where it falls short.

### Risks and trade-offs

- Email is asynchronous. A draft can sit unconfirmed, so a reminder and supervisor flag rule is specified.
- Uncredentialed workers depend on colleagues to enter notes. Whose identity the system enters under affects the audit trail and CHIP's participation agreement.
- Because the system cannot look anyone up, a mistyped identifier is the main way an entry could land on the wrong person. Showing it back for confirmation is the control.
- Retaining inbox content is useful for audit but increases exposure of personal information, so access control on the inbox and audit trail matters.

### Open questions

1. How should a Form 101 entry land in HMIS: as structured fields, or as the signed form uploaded as a document (for example through the "Document Collected" tool in CHIP's CES knowledge base)? Ask: Hannah, CHIP.
2. Which signature method does CHIP accept for the staff signature, applicant signature, and release authorization (for example a scanned signed copy)? Ask: Hannah, CHIP.
3. How often do outreach workers complete Form 101 and the verification letter? Ask: Hannah.
4. Who receives the verification letter and what is it used for? The team has not confirmed this. The letter has no addressee. Ask: Hannah, Horizon House.
5. Should issuing a letter be logged in HMIS as a service? If yes, that becomes a later change to `verification-letter`. Ask: Hannah.
6. What does a written referral need attached, if anything? The form lists no extra fields for it. Ask: Hannah.
7. Where does AI parsing run, and what does Goodwill's written AI policy allow? Ask: Dennis.
8. What retention period applies to the mailbox, and who owns and can access the mailbox and audit trail? Ask: Dennis, Goodwill IT.
9. Where are photos stored, and are there size or count limits? Ask: Dennis, CHIP.
10. How long before the reminder, who is the supervisor who gets flagged, and after how many days [N] is an unapproved draft deleted? Ask: Hannah, Dennis.
11. What HMIS entry method and permissions apply, given the system only enters information? Ask: CHIP.
12. How are authorized workers identified (sender address, or tied to an HMIS user)? Ask: Dennis, CHIP.
13. What is the minimum set of fields CHIP requires to create a new profile? Ask: CHIP.
14. How does an entry attach to the right client when the system cannot look anyone up (client ID supplied by the worker, or name and date of birth matched on the HMIS side)? Ask: CHIP.
15. How does HMIS handle a duplicate profile if a worker's search missed an existing one? Ask: CHIP.

### Source notes

- **Documented:** The Form 101 field list comes from the text of the CHIP PDF in the CES Knowledge Base (chipindy.org). The text extraction scrambled the order of some fields, so confirm the layout against the PDF. The verification letter fields come from the Horizon House template the team holds.
- **Reported:** Goodwill email has encryption and security controls (client meeting). Workers collect name, date of birth, and last four Social Security digits from a new neighbor and search HMIS themselves, by date of birth first (ride-alongs). The verification letter is prepared in the field with the neighbor (Ankush, Oct 8).
- **Assumed:** That outreach regularly completes both documents (question 3), and that an entry-only HMIS interface can be agreed with CHIP (question 11).

---

## File: specs/outreach-email-pipeline/spec.md

### ADDED Requirements

#### Requirement: Accept messages only from authorized workers
The system SHALL process only emails sent to the designated secure inbox by authorized outreach staff.

##### Scenario: Message from an unrecognized sender
- **WHEN** an email arrives from an address that is not on the authorized worker list
- **THEN** the system drops the message without processing it
- **AND** the system does not reply with any neighbor information

#### Requirement: Identify the form type
The system SHALL determine which supported request an email makes (a Form 101 observation, a verification letter, or a new neighbor profile) and SHALL ask the worker when it cannot tell.

##### Scenario: Clear request
- **WHEN** a worker writes "I need a homeless verification letter for Pat Example, DOB 01/01/1980"
- **THEN** the system classifies the email as a verification letter request

##### Scenario: Unclear message
- **WHEN** an email does not clearly match a supported request
- **THEN** the system replies asking the worker what they mean
- **AND** the system does not create a draft

#### Requirement: Fill draft fields only from stated or trusted sources
The system SHALL fill a draft field only with a value stated in the email or taken from the worker's profile, and SHALL leave any other field blank and flagged. The draft SHALL show which source each value came from, and for a value taken from the email, the sentence it came from.

##### Scenario: Value not stated
- **WHEN** an email does not state a value the form needs
- **THEN** the draft leaves that field blank
- **AND** the draft flags the field for the worker

##### Scenario: Source shown
- **WHEN** a draft is sent to the worker for review
- **THEN** each field is shown beside its source
- **AND** each value from the email cites the sentence it came from
- **AND** each other value is labeled as coming from the worker's profile

#### Requirement: Identify the neighbor from the worker's email
The system SHALL take the neighbor identifier from the worker's email, either an HMIS client ID or the neighbor's name and date of birth, SHALL show it back to the worker in the review email as the first of three checkpoints (confirm the neighbor, confirm the fields, approve the submission), and SHALL NOT search or read HMIS to find or check it.

##### Scenario: Identifier supplied
- **WHEN** the email includes an HMIS client ID, or a name and date of birth
- **THEN** the draft shows that identifier to the worker for confirmation
- **AND** the system does not query HMIS

##### Scenario: Identifier missing
- **WHEN** the email gives no client ID and not both a name and date of birth
- **THEN** the system asks the worker for the identifier before presenting the draft

#### Requirement: Enter information into HMIS only
The system SHALL only enter approved information into HMIS and SHALL NOT retrieve, search, or display any information from HMIS.

##### Scenario: Entry approved
- **WHEN** the worker approves a draft that is entered into HMIS
- **THEN** the system sends the entry
- **AND** the only information it takes back from HMIS is whether the entry succeeded or failed and why

##### Scenario: Worker wants to look someone up
- **WHEN** a worker needs to check whether a neighbor already has a profile
- **THEN** the worker does that in HMIS directly
- **AND** the system does not offer a lookup

#### Requirement: Prepare a new neighbor profile for confirmation
The system SHALL draft a new neighbor profile from the email only when the worker states that they searched HMIS and found no existing profile, and SHALL enter it only after the worker approves the draft, with the fields CHIP requires for a new profile [TBC].

##### Scenario: Worker found no existing profile
- **WHEN** the email says the worker searched HMIS and found no match, and gives the details for a new profile
- **THEN** the system drafts a new profile from those details
- **AND** the draft is sent to the worker for review before anything is entered

##### Scenario: Search not stated
- **WHEN** a worker asks for a new profile without saying they searched HMIS
- **THEN** the system asks the worker to confirm they searched and found no match
- **AND** the system does not draft the profile until the worker does

##### Scenario: Profile approved
- **WHEN** the worker approves the new-profile draft
- **THEN** the system enters it through `create_neighbor_profile`
- **AND** the system tells the worker whether it was recorded

#### Requirement: Accept photo attachments
The system SHALL accept photographs attached to a worker's email, SHALL attach them to the matching HMIS entry through `attach_document` after the worker approves, and SHALL NOT accept video.

##### Scenario: Photo attached
- **WHEN** an email includes a photograph
- **THEN** the draft lists the photo for the worker to confirm
- **AND** the photo is entered with the entry only after the worker approves

##### Scenario: Video attached
- **WHEN** an email includes a video
- **THEN** the system does not store it
- **AND** the system tells the worker video is not accepted

#### Requirement: Validate drafts with rules, not AI
The system SHALL check each draft against required-field, format, and date rules for its document type, SHALL flag every problem in the review email, and SHALL NOT silently correct a value. The rules SHALL be configuration that Goodwill IT can edit without a code change.

##### Scenario: Problem found
- **WHEN** a draft has a missing required field, a badly formatted value, or an impossible date
- **THEN** the review email flags the problem
- **AND** the system does not change the value on its own

##### Scenario: Worker edits a value
- **WHEN** the worker replies with an edit
- **THEN** the system re-runs the rules on the updated draft before presenting it again

##### Scenario: Rules changed
- **WHEN** Goodwill IT edits the rules for a document type
- **THEN** new drafts use the changed rules without a code change

#### Requirement: Define document fields as configuration
The system SHALL define the HMIS documents it supports and their field mappings as configuration, so that adding a form, or supporting another continuum of care, means adding configuration and not new software.

##### Scenario: New form added
- **WHEN** a new form is added to the configuration
- **THEN** the system can draft and enter it using the same pipeline

#### Requirement: Ask for missing required fields
The system SHALL ask the worker for any required field that is missing or unclear before presenting the draft for review.

##### Scenario: Required field missing
- **WHEN** a required field cannot be filled from the email or the worker's profile
- **THEN** the system replies listing the missing fields

##### Scenario: Worker supplies the missing detail
- **WHEN** the worker replies with the missing detail
- **THEN** the system updates the same draft rather than starting a new one

#### Requirement: Worker approval before any entry or issue
The system SHALL send the worker a review email showing the neighbor identifier and every field beside its source, SHALL accept three reply commands (APPROVE, EDIT with corrected values, REJECT) tied to that draft's ID, SHALL accept them only from the worker who wrote the note, and SHALL NOT enter anything into HMIS, or mark any document as issued, without an explicit APPROVE.

##### Scenario: Worker approves
- **WHEN** the author replies APPROVE to a draft
- **THEN** the draft moves from in review to approved
- **AND** the system proceeds to the next step defined for that form

##### Scenario: Worker edits
- **WHEN** the author replies EDIT with corrected values
- **THEN** the system updates the draft and re-runs validation
- **AND** the system sends the updated draft for review again

##### Scenario: Worker rejects
- **WHEN** the author replies REJECT
- **THEN** the draft is discarded
- **AND** nothing is entered into HMIS

##### Scenario: Reply from someone else
- **WHEN** a reply command arrives from anyone other than the note's author
- **THEN** the system ignores it

##### Scenario: Draft states
- **WHEN** a draft moves through the workflow
- **THEN** it is always in one of five states: draft, in review, approved, submitted, or failed

##### Scenario: No response
- **WHEN** the worker does not respond
- **THEN** the draft stays in review
- **AND** nothing is entered into HMIS

#### Requirement: Remind the worker, flag a supervisor, then expire the draft
The system SHALL send one reminder when a draft stays in review for the set window [TBC], SHALL flag the draft to the worker's supervisor [TBC] if it is still in review after the reminder, and SHALL delete the draft after [N] days [TBC] if it is never approved.

##### Scenario: Reminder sent
- **WHEN** a draft has been in review for the reminder window
- **THEN** the system sends the worker one reminder

##### Scenario: Still in review
- **WHEN** the draft is still in review after the reminder
- **THEN** the system flags it to the supervisor
- **AND** nothing is entered into HMIS

##### Scenario: Draft expires
- **WHEN** a draft has gone unapproved for [N] days
- **THEN** the draft is deleted

#### Requirement: Keep personal information out of external AI systems
The system SHALL NOT send personally identifiable information to any AI system outside an environment approved under Goodwill's AI policy.

##### Scenario: Email contains identifying details
- **WHEN** an email containing a name and a date of birth is processed
- **THEN** no request leaves the approved environment with that name or date of birth in it

#### Requirement: Retain inbox content under access controls
The system SHALL keep original email content in the Goodwill mailbox under its own retention rule set by Goodwill [TBC], SHALL restrict access to it to authorized staff, and SHALL delete it when that period ends. The system SHALL keep only pending drafts in a draft store, SHALL delete a draft on submission or when it expires, and SHALL NOT keep any standing copy of HMIS client data outside HMIS.

##### Scenario: Entry submitted
- **WHEN** an entry is successfully submitted
- **THEN** its draft is deleted from the draft store
- **AND** the original email stays in the mailbox only for the retention period, visible only to authorized staff

##### Scenario: Retention period ends
- **WHEN** the mailbox retention period ends
- **THEN** the email content is deleted

##### Scenario: No copy of client data
- **WHEN** an entry has been submitted
- **THEN** no copy of the neighbor's HMIS data is kept outside HMIS, apart from the audit record

#### Requirement: Keep an access-controlled audit trail
The system SHALL record who approved each submission, when, which form type it was, the neighbor identifier the worker supplied, and which fields the worker changed from the AI's proposal, SHALL restrict access to that record to authorized staff, and SHALL record change flags and not the narrative content of the email.

##### Scenario: Approved submission
- **WHEN** a worker approves a draft
- **THEN** the audit record shows the worker, the time, the form type, and the neighbor identifier
- **AND** the audit record does not contain the email text

##### Scenario: Worker changed a field
- **WHEN** the worker edited a field the AI had proposed
- **THEN** the audit record flags that field as changed
- **AND** the audit record does not contain the old or new narrative text

#### Requirement: Send receipts and failure notices
The system SHALL email the worker a submission receipt when HMIS accepts an entry, and a failure notice with the reason when it does not, and SHALL return a failed submission to the worker rather than retrying silently.

##### Scenario: Receipt
- **WHEN** HMIS accepts an entry
- **THEN** the worker receives a receipt
- **AND** the draft moves to submitted

##### Scenario: Failure
- **WHEN** HMIS rejects an entry or cannot be reached
- **THEN** the draft moves to failed
- **AND** the worker receives a failure notice with the reason

---

## File: specs/form-101-observation/spec.md

### ADDED Requirements

#### Requirement: Capture the Form 101 fields
The system SHALL draft a Form 101 (Outreach Observation) entry containing the applicant's name, the form date, how the information was collected, the location and dates the neighbor slept in a place not meant for human habitation, the agency name and address, and the staff member's name, title, and phone or email.

##### Scenario: Complete observation email
- **WHEN** a worker emails that they saw Pat Example sleeping in a bus shelter near Example St and Sample Ave on October 1 and October 2, 2026
- **THEN** the draft contains the applicant name, the location, and both dates
- **AND** the information source is set to outreach worker observation
- **AND** the agency details and staff details come from the worker's profile

#### Requirement: Require a location and at least one date
The system SHALL require a location description and at least one date or date range for when the neighbor slept there, because the form must include the location and the date or dates.

##### Scenario: Relative date
- **WHEN** the email says the neighbor slept there "last week"
- **THEN** the draft shows the date range that "last week" resolves to, based on the date the email was sent
- **AND** the system asks the worker to confirm the range

##### Scenario: Location missing
- **WHEN** the email gives dates but no location
- **THEN** the system asks the worker for the location before presenting the draft

#### Requirement: Record how the information was collected
The system SHALL set the information source to one of three values (outreach worker observation, written referral from a housing or service provider, or oral referral from a housing or service provider) and SHALL ask the worker when the email does not make it clear.

##### Scenario: First-hand observation
- **WHEN** the email describes something the worker saw themselves
- **THEN** the draft sets the source to outreach worker observation
- **AND** the draft shows the source for the worker to confirm

##### Scenario: Source unclear
- **WHEN** the email does not say how the information was obtained
- **THEN** the system asks the worker which of the three sources applies

#### Requirement: Collect oral referral details
The system SHALL require the name, title, and contact number of the person providing the information, and the date and time of the conversation, when the information source is an oral referral.

##### Scenario: Missing provider details
- **WHEN** a worker's email says a housing provider reported by phone that a neighbor slept outside
- **AND** the email does not include the provider's contact number
- **THEN** the system asks the worker for it before presenting the draft

##### Scenario: Details complete
- **WHEN** the email includes the provider's name, title, contact number, and the date and time of the call
- **THEN** the draft records all four values

#### Requirement: Handle signatures by a CHIP-accepted method
The system SHALL NOT record the staff signature, the applicant signature, or the release authorization as obtained based on email content, and SHALL present the entry as signatures pending until they are completed by a method CHIP accepts [TBC].

##### Scenario: Email claims consent
- **WHEN** the email says the neighbor agreed to the release of the information
- **THEN** the draft still shows the release authorization as pending a signature

##### Scenario: All fields complete, signatures outstanding
- **WHEN** every required field is filled but no signature has been completed by the accepted method
- **THEN** the draft is marked signatures pending
- **AND** the draft is not described as a complete verification

##### Scenario: Signed copy attached
- **WHEN** the worker attaches a photo or scan of the signed form
- **THEN** the system lists it for confirmation and enters it with the entry through `attach_document`
- **AND** whether it counts as complete depends on the CHIP-accepted method [TBC]

#### Requirement: Limit location detail
The system SHALL capture location only as the description the worker writes, SHALL NOT collect device coordinates, including from photo metadata, and SHALL NOT copy location details to any map, shared channel, or report outside the HMIS entry.

##### Scenario: Photo with location data
- **WHEN** an email for this form includes a photograph with embedded location data
- **THEN** the system does not use that location data
- **AND** the location comes only from the worker's written description

##### Scenario: Location stays in the entry
- **WHEN** a Form 101 entry is submitted
- **THEN** the location appears only in the HMIS entry
- **AND** the audit record does not contain it

#### Requirement: Enter the approved entry in HMIS
The system SHALL enter an approved Form 101 draft through the HMIS interface operation `record_outreach_observation`, using the neighbor identifier the worker supplied and approved, and SHALL tell the worker whether it was recorded.

##### Scenario: Submission succeeds
- **WHEN** HMIS accepts the entry
- **THEN** the worker receives a submission receipt

##### Scenario: Submission fails
- **WHEN** HMIS rejects the entry or cannot be reached
- **THEN** the draft moves to failed and goes back to the worker
- **AND** the worker receives a failure notice with the reason

---

## File: specs/verification-letter/spec.md

### ADDED Requirements

#### Requirement: Draft a verification letter on request
The system SHALL produce a draft Homeless Verification Letter when an authorized worker emails a request that includes the neighbor's details, and SHALL send the draft only to that worker.

##### Scenario: Letter requested
- **WHEN** a worker emails a request for a verification letter for Pat Example with the details the neighbor gave them in the field
- **THEN** the system returns a draft letter to the worker

##### Scenario: Delivery limited to the requester
- **WHEN** a draft letter is produced
- **THEN** it is sent only to the requesting worker
- **AND** it is not sent to the neighbor or any third party

#### Requirement: Take details from the worker's email, not from HMIS
The system SHALL fill the neighbor's name, date of birth, and last four Social Security digits from the worker's email, which relays what the neighbor told the worker in the field, and SHALL NOT look them up in or read them from HMIS.

##### Scenario: Details supplied in the field
- **WHEN** the email includes the name, date of birth, and last four Social Security digits the neighbor gave the worker
- **THEN** the draft uses those values
- **AND** the system does not query HMIS

##### Scenario: Detail missing
- **WHEN** the email leaves out the name, date of birth, or last four digits
- **THEN** the system asks the worker for it before producing the draft

##### Scenario: Worker confirms the details
- **WHEN** a draft letter is produced
- **THEN** the draft shows the name, date of birth, and masked Social Security number for the worker to check against what the neighbor said
- **AND** the worker approves it with the same APPROVE, EDIT or REJECT commands used for other drafts

#### Requirement: Print only the last four Social Security digits
The system SHALL print the Social Security number only as its last four digits (in the form xxx-xx-NNNN) and SHALL NOT include, store, or log a full Social Security number in the letter, any email, the draft, or the audit record.

##### Scenario: Masked output
- **WHEN** a draft letter is produced
- **THEN** the Social Security line shows only the last four digits

##### Scenario: Email contains a full number
- **WHEN** the worker's email includes more than the last four digits
- **THEN** the system keeps only the last four digits and discards the rest before building the draft

#### Requirement: Use the approved wording, issue date, and validity period
The system SHALL use Horizon House's approved letter wording without altering its statements, SHALL include the issue date, and SHALL state that the letter is valid for 30 days.

##### Scenario: Letter dated and time-limited
- **WHEN** a draft letter is produced
- **THEN** it shows the issue date
- **AND** it states that it is valid for 30 days

#### Requirement: Leave signing to the worker
The system SHALL NOT apply a signature on the worker's behalf, SHALL fill the signature block from the worker's profile (name, title, phone, and email), and SHALL NOT mark the letter as issued until the worker approves it.

##### Scenario: Draft is unsigned
- **WHEN** a draft letter is returned to the worker
- **THEN** it is unsigned
- **AND** it is labeled as needing the worker's review and signature before it goes to the neighbor

##### Scenario: Signer details come from the worker
- **WHEN** the worker's profile has a name, title, and contact details
- **THEN** the signature block uses them instead of fixed values from the template

#### Requirement: Drafting a letter does not touch HMIS
The system SHALL NOT read from or write to HMIS as part of drafting or issuing a verification letter.

##### Scenario: Letter drafted
- **WHEN** a letter is drafted and approved
- **THEN** no query is made to HMIS
- **AND** no change is made to the neighbor's HMIS record
