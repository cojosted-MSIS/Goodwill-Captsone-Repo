# Design: New-client entry demo

## Context
The demo follows the team's Encounter Workflow Mockups: the worker emails notes, the system parses and stages a record, the worker reviews a draft by email and replies CONFIRM or corrections, and the confirmed record is entered into HMIS with an audit trail. Field names are illustrative. The real field list depends on CHIP and the HMIS administrator.

```text
Worker email -> intake inbox -> parse into draft -> validate
  -> stage record (not sent) -> review email (v1)
  -> worker replies CONFIRM  |  plain-language corrections -> draft v2 -> review email
  -> CONFIRM: enter into mock HMIS in order
       1. create client   2. enroll in program   3. create CE enrollment and triage
  -> receipt email, audit record, email copies deleted
```

## What the HMIS manual says the worker does today
1. Search HMIS first to avoid duplicates (the worker does this, not the system).
2. Add a new client: name, then basic client information (DOB, SSN or a data-quality option, race, ethnicity, gender, disabling condition, veteran status, address).
3. Enroll in a program: choose the project, set the enrollment date, complete the HUD universal data assessment (prior living situation and conditional fields).
4. Coordinated Entry intake: consent, family members, diversion and housing crisis, program enrollment, universal data, triage assessment, VI-SPDAT.

The demo drafts steps 2 and 3 and the triage part of step 4. Everything else in step 4 is out of scope and is shown as "completed in HMIS by the worker" [TBC].

## Mock HMIS (logical operations, entry only)
These are not real HMIS endpoints. Nothing is read back except success or failure and the identifiers HMIS assigns.

| Operation | Inputs | Returns |
|---|---|---|
| `create_client` | Confirmed basic client information | Success with a new client ID, or failure with a reason |
| `enroll_in_program` | Client ID, project, enrollment date, universal data elements, optional case note [TBC] | Success with an enrollment ID, or failure with a reason |
| `create_ce_enrollment` | Client ID, CE project, triage assessment fields | Success with a CE enrollment ID, or failure with a reason |

The mock enforces the order (client, then program enrollment, then CE enrollment), checks the required fields marked with an asterisk in the manual, and can be set to fail on purpose to exercise the failure path, including a "possible duplicate" rejection.

## Decisions
1. **Enter only, never read.** The system never searches HMIS. The worker states in the email that they searched and found no match. This replaces the lookup shown in mockup figure A4 (`hmis_client_id` resolved at submit by an HMIS lookup). For a new client there is nothing to look up, because HMIS assigns the ID on entry.
2. **Worker approval is the main control.** The confirm step exists because the parser will sometimes be wrong (mockup scenario B).
3. **No inferred values.** The manual says never to make up a birth date, SSN, or other answer. A "client doesn't know", "client refused", or "data not collected" value is used only when the email says so.
4. **Draft states:** draft, in review, confirmed, submitted, failed, expired.
5. **One parser interface, two implementations.** A rule-based stub (deterministic, used in tests) and an LLM implementation. Both return the same structured output with a source sentence and a confidence per field. For the demo the LLM implementation calls REALLMS, the IU-hosted LLM service, with synthetic data only, following `docs/reference/reallms/REALLMS_GUIDE.md`: `response_format` json_schema with strict mode (not `guided_json`, which IU's API ignores, and not prompt-only JSON, which fails), temperature 0, one note per request, a flat schema whose categories are enums with "unknown" defined in the prompt, and an exact-quote evidence field per judgment. Every reply is checked (finish reason, schema, exact quotes, quote agrees with label, hedge and hearsay words), retried once, and otherwise flagged for human review; unverified output is never saved. Dates are copied as written and read in code; relative contact dates are resolved from the email's sent date. The model name, prompt version, and parse time are stored with each draft and in the audit record. Default model `gemma-4-31B-it`, with `qwen3.8-27b` as the fallback. `gpt-oss-120b` is marked not recommended after the model comparison and is refused unless explicitly overridden; the comparison script still measures it. Shared rules (name quality, Social Security digits, notices, scrubbing) run on both parsers' output.
6. **Location at quadrant level only.** No camp locations or coordinates, including in the source sentences stored with the draft.
7. **Third-party details are dropped.** Anything about someone other than the neighbor is not recorded, including in stored source sentences and the case note.
8. **Unconfirmed drafts go to a supervisor queue after 48 hours** (from the mockup, proposed).
9. **Signatures are not handled here.** The client consent signature in the CE intake is shown as pending and is completed by the worker in HMIS [TBC].

## Proposed prototype stack (for DeveloperTown to challenge)
Python with FastAPI, SQLite, a simulated inbox (a folder of `.eml` or JSON files, with a small web "phone" view that mimics the mockup screens), and the mock HMIS as a separate local service. Real email is added last. All of this is a suggestion. The specs do not depend on it.

## Risks
- A tired worker confirms a wrong value. Mitigation: show the source sentence beside each value and flag low confidence.
- Field names and required fields differ in the real HMIS. Mitigation: field mapping as configuration.
- The email path carries personal information. Mitigation: synthetic data in the demo, and the production rule (internal inbox, access control) is an open question.

## Signature documents and photos in production
Out of scope for the prototype; options and decisions are in `docs/FUTURE.md`.
- **Why out of scope:** an email cannot carry a valid signature, consent must be informed and given with the neighbor present, CHIP decides which signature and upload methods HMIS accepts through an interface, ID photos are the most sensitive data in the flow and already have an HMIS upload path, and the demo uses synthetic data only.
- **Prototype behavior:** consent and signatures are shown as pending and listed as remaining in HMIS; consent statements in the case note become "[consent pending]"; the compose screen tells workers not to attach ID photos, and attachments are not stored.
- **Production options:** for signatures, keep signing in HMIS, capture on a managed work device through a separate secure channel, or scan a signed paper form as a document; for photos, keep the existing HMIS upload path or upload directly from a work device. Photos as email attachments are not recommended.
- **To decide (DeveloperTown with CHIP, Goodwill and Horizon House):** accepted signature methods and whether signed documents can be uploaded through an interface; whether an attach-document operation exists; whether consent must come before other entries; whether signature documents belong in the product and which first; device availability and offline use; retention outside HMIS; who signs and receives the verification letter.

## Open questions
1. Which project(s) and CE region does a Horizon House outreach worker enroll into, and what are the project IDs? Ask: Hannah, CHIP.
2. Which fields are truly required for a new client in Goodwill's HMIS instance? Ask: CHIP.
3. How is SSN handled over email? The demo captures the last four digits and a data-quality option only. Ask: Dennis, CHIP.
4. How is the client consent signature completed when the worker enters via this path? Ask: Hannah, CHIP.
5. Does the CE intake allow the triage assessment without the VI-SPDAT, or must the VI-SPDAT be completed in the same sitting? Ask: Hannah, CHIP.
6. How does HMIS treat a possible duplicate when entry comes through an API? Ask: CHIP.
7. Where does AI parsing run and what does Goodwill's AI policy allow? Ask: Dennis.
8. Retention period for the intake inbox and who can access it. Ask: Dennis, Goodwill IT.
9. Who is the supervisor for the 48-hour queue? Ask: Hannah.
10. Can the case note be entered as part of the program enrollment through an API, or does HMIS keep case notes in a separate record or service? The demo sends it as an optional field of `enroll_in_program`. Ask: CHIP.

## Source notes
- **Documented:** HMIS User Manual (Jan 2023), new client with program enrollment (pp. 22-35) and Coordinated Entry intake (pp. 94-109). The manual describes ClientTrack screens, which the demo does not copy.
- **Reported:** Encounter Workflow Mockups (October 2026, illustrative, not matched to the real field list).
- **Assumed:** An entry-only interface can be agreed with CHIP.
