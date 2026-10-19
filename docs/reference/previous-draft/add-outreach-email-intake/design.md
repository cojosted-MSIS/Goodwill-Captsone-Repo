# Design: Email-based outreach documentation

## Context

The team is specifying this change, not building it. These notes record the decisions and open questions behind the specs so DeveloperTown can evaluate and estimate the work. The specs describe behavior at the edges (email in, HMIS entry, worker confirmation), so they stay valid whichever HMIS access method CHIP approves.

The flow, as reviewed with Horizon House on the team's process diagram (no major gaps were identified):

```text
Worker email -> secure inbox -> identify form -> parse into draft
  -> validate with rules -> review email (neighbor, fields, approval)
  -> worker replies APPROVE, EDIT or REJECT
  -> Form 101 or new profile: enter into HMIS, then receipt  |  Letter: return draft letter to worker
```

The worker looks neighbors up in HMIS on their own. The system does not search or read HMIS at any step.

## Alignment with the application architecture

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

## Why these two documents

| Document | Direction | What it exercises |
|---|---|---|
| CHIP Form 101 (Outreach Observation) | Enter: email to HMIS entry | Free-text parsing, a conditional required-field rule, signatures that email cannot carry, photos, location privacy |
| Horizon House Verification Letter | None: email to generated document | Details supplied by the neighbor in the field, masking, a validity rule, document generation |

Both share identifying the neighbor from the email, missing-field handling, and worker confirmation, which is why those live in `outreach-email-pipeline`.

For estimating: Form 101 is a medium-sized form (a handful of fields, one conditional rule, one free-text field). The letter is small and needs no HMIS access. A large form such as the Head of Household CES Assessment can be added later as the upper bound.

## HMIS interface (logical operations)

These are not HMIS endpoints. They describe what the system needs to enter into HMIS, so DeveloperTown and CHIP can map them to whatever access method is available. All operations are entry only. Nothing is read back out.

| Operation | Direction | Inputs | Returns | Used by |
|---|---|---|---|---|
| `create_neighbor_profile` | Enter | Confirmed new-profile draft | Success, or failure with a reason | `outreach-email-pipeline` |
| `record_outreach_observation` | Enter | Confirmed Form 101 draft, the worker-supplied neighbor identifier | Success, or failure with a reason | `form-101-observation` |
| `attach_document` | Enter | Photo or scan, the worker-supplied neighbor identifier | Success, or failure with a reason | `outreach-email-pipeline` |

The verification letter uses none of these.

## Decisions

1. **The worker approves before anything is entered.** It happens in one review email with three checkpoints: confirm the neighbor, confirm the fields, approve the submission. Nothing reaches HMIS and no document is marked issued on the system's own judgment. This is the main control against a wrong parse. Drafts move through five states: draft, in review, approved, submitted, failed.
2. **No inferred values.** A field is filled only from the email or the worker's profile. Anything else is left blank and flagged, and relative dates are shown resolved for confirmation.
3. **Signatures follow a CHIP-accepted method.** Form 101 needs staff and applicant signatures and a release authorization. An email cannot carry those, so the system shows them as pending until they are completed by whichever method CHIP accepts [TBC], and never records them as obtained from email content.
4. **Personal information stays inside a Goodwill-approved environment.** Where the AI parsing runs is an open question. The specs state the rule, not the hosting.
5. **Location is minimized.** Only the worker's written description is captured. No device coordinates, no copies to maps or shared channels.
6. **Behavior, not model choice.** The specs do not name a model or vendor. They state inputs, outputs, and what happens when the system is unsure.
7. **Photos yes, video no.** Photo attachments are accepted and stored with the entry. Video is not accepted.
8. **New profiles are drafted, then confirmed.** If the worker says they searched HMIS and found no match, the system drafts a new profile from the email and enters it only after the worker confirms.
9. **Enter only, never read.** The system never searches or reads HMIS. The neighbor identifier (HMIS client ID, or name and date of birth) comes from the worker's email and is shown back to the worker for confirmation. Duplicate prevention depends on the worker's own HMIS search and on whatever duplicate handling HMIS has [TBC].

## AI parsing: failure modes

The charter requires a named failure mode, owner, running cost, and governance answer for every AI capability. Owner and cost are not yet known and are marked as such.

| Capability | Failure mode | Consequence | Mitigation | Owner | Running cost |
|---|---|---|---|---|---|
| Field extraction | Misread or invented value (wrong date, wrong place) | Inaccurate verification record | Values must come from the email text; every draft is confirmed by the worker; unstated fields stay blank and flagged | Goodwill to name | Not yet estimated |
| Relative dates | "Last week" resolved to the wrong range | Wrong dates on a federal verification | Show the resolved range and ask for confirmation | Goodwill to name | Not yet estimated |
| Form identification | Wrong form chosen | Wrong fields requested | Ask when unsure; show the form type in the draft | Goodwill to name | Not yet estimated |
| Neighbor identification | Worker mistypes or the system misreads the identifier, so an entry attaches to the wrong person | Another person's record changes | Show the identifier back to the worker; require confirmation; never guess or search | Goodwill to name | Not yet estimated |

## Alternative considered: structured email template

A fill-in email template with labeled lines ("Applicant:", "Location:", "Dates:", "Source:"), read by simple rules with no AI, would capture most Form 101 fields cheaply. AI adds value mainly for the free-text location and dates, relative dates, and detecting an oral referral. The letter needs AI only to read the details in the email; filling the letter is template work. The charter asks that each AI capability be tested against a cheaper alternative, so the team and Goodwill should decide whether to start with the template and add AI only where it falls short.

## Risks and trade-offs

- Email is asynchronous. A draft can sit unconfirmed, so a reminder and supervisor flag rule is specified.
- Uncredentialed workers depend on colleagues to enter notes. Whose identity the system enters under affects the audit trail and CHIP's participation agreement.
- Because the system cannot look anyone up, a mistyped identifier is the main way an entry could land on the wrong person. Showing it back for confirmation is the control.
- Retaining inbox content is useful for audit but increases exposure of personal information, so access control on the inbox and audit trail matters.

## Open questions

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

## Source notes

- **Documented:** The Form 101 field list comes from the text of the CHIP PDF in the CES Knowledge Base (chipindy.org). The text extraction scrambled the order of some fields, so confirm the layout against the PDF. The verification letter fields come from the Horizon House template the team holds.
- **Reported:** Goodwill email has encryption and security controls (client meeting). Workers collect name, date of birth, and last four Social Security digits from a new neighbor and search HMIS themselves, by date of birth first (ride-alongs). The verification letter is prepared in the field with the neighbor (Ankush, Oct 8).
- **Assumed:** That outreach regularly completes both documents (question 3), and that an entry-only HMIS interface can be agreed with CHIP (question 11).
