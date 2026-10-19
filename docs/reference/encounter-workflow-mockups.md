**Encounter Note to HMIS: Worker Workflow Concept**

Crimson Consulting Group \| Prepared for Goodwill of Central & Southern Indiana, Horizon House \| Draft for sponsor review, October 2026

Summary

This document shows, screen by screen, how an outreach worker would document an encounter under the concept the team is evaluating. The worker emails plain-language notes to a secure Goodwill intake inbox. An AI model running inside Goodwill’s network turns the notes into structured fields, stages them as a record, and emails the structured draft back to the worker. Nothing is submitted to HMIS until the worker confirms it.

Two scenarios follow. Scenario A is a clean parse confirmed on the first reply. Scenario B shows the AI misreading a declined referral as accepted, the worker correcting it in a plain-language reply, and the corrected draft being confirmed. Scenario B is the more important of the two: the confirmation step exists because the model will sometimes be wrong.

**All neighbor data is fictional.** Screens are illustrative mockups, not a built system. Field names are illustrative and have not been matched to Horizon House’s HMIS instance; the actual field list depends on CHIP and the HMIS administrator.

Workflow at a glance

| **Step**    | **Who**               | **What happens**                                                                         | **Figures**  |
|-------------|-----------------------|------------------------------------------------------------------------------------------|--------------|
| 1\. Capture | Worker                | After the conversation, types or dictates notes into an email to the secure intake inbox | A1, B1       |
| 2\. Parse   | AI (Goodwill network) | Extracts fields using fixed rules; flags anything not stated                             | A2, B2       |
| 3\. Map     | System                | Places values into the HMIS street outreach contact fields                               | A3, B3       |
| 4\. Stage   | System                | Holds the record with per-field source and confidence; not sent to HMIS                  | A4, B4       |
| 5\. Confirm | Worker                | Reviews the draft by email; replies CONFIRM or replies with corrections                  | A5, B5 to B7 |
| 6\. Submit  | System                | Submits the confirmed record to HMIS and logs the audit trail                            | B8           |

Scenario A: Clean parse, confirmed on first reply

Fictional encounter: Wednesday, October 7, 2026. The worker meets Darnell W., who is unsheltered, needs a replacement birth certificate before he can get a state ID, and agrees to a housing assessment the next day.

**Figure A1. Worker emails encounter notes to the secure intake inbox**

Back in the vehicle after the conversation, the worker writes notes the way they would in a notebook or Notes app today: shorthand, no form, no required fields. The phone is not out during the conversation. The banner reminds the worker not to attach ID document photos, which keep their existing upload path into HMIS.

<img src="media/2286a20d65accd2ac55c1adbb9d30627a5d0b08e.png" style="width:2.69792in;height:5.52083in" />

**Figure A2. AI model receives the notes as its prompt**

The worker’s email body is passed to the model unchanged, alongside fixed system instructions the worker never sees. The instructions limit the model to what the note states, require a null and a flag for anything missing, keep location at quadrant level, and exclude information about third parties. The output is structured data, not free text.

<img src="media/414214629472a45eba019b62d9a9279f72cb1ff6.png" style="width:6.5in;height:5.11458in" />

**Figure A3. Parsed data mapped to the fields of the HMIS contact record**

Each value lands in the field it belongs to, with a source line showing which words in the email it came from. The case note narrative is generated from the email and is the one element the worker should read for wording, not just accuracy. Service area is stored at quadrant level; no camp location is recorded.

<img src="media/5af63e9cd4534f22395bf3648e307ee03efad17b.png" style="width:6.5in;height:5.05208in" />

**Figure A4. API view: staged record with column-level data**

The same record as the API sees it: one row per column, with value, data type, source and confidence. The HMIS client ID stays pending until submission, when the system looks up the neighbor by date of birth, which matches the lookup practice observed on both ride-alongs. Status is STAGED: the record cannot be submitted until the worker confirms.

<img src="media/00fb95e335f71e4e32f96ce5f3efdfeee2169593.png" style="width:6.5in;height:3.63542in" />

**Figure A5. Structured draft emailed back to the worker for confirmation**

The worker receives the draft in the same inbox they sent from. Reviewing it takes about as long as reading a short email. In this scenario every field is correct, so the worker replies CONFIRM and the record moves to submission.

<img src="media/8e3f586edde4fb217f4bf3cbd20de494d69a597f.png" style="width:2.69792in;height:6.47917in" />

Scenario B: AI error caught and corrected by the worker

Fictional encounter: Friday, October 9, 2026. The worker meets Rosa M. downtown and offers a shelter bed referral, which she declines for now. The model gets two things wrong and one thing missing, which is a realistic mix for this kind of note.

| **Field**        | **What the worker meant**                                    | **What the AI produced**            | **Why this happens**                                                                       |
|------------------|--------------------------------------------------------------|-------------------------------------|--------------------------------------------------------------------------------------------|
| Referrals        | Shelter referral offered and declined; may revisit next week | Emergency shelter referral accepted | Hedged refusals ("not tonight, maybe next week") are a known weak spot for language models |
| Follow-up        | Monday or Tuesday                                            | Monday only                         | The model collapsed a range to a single date                                               |
| Living situation | Unsheltered (known to the worker)                            | Not stated, flagged                 | Correct behavior: the note never said it, so the model asked rather than guessed           |

The referral error is the one that matters. Left uncorrected, the record would show a neighbor in a shelter pipeline she declined, and the follow-up could go to the wrong place. The design depends on the worker catching it.

**Figure B1. Worker emails encounter notes**

Same capture step as Scenario A. The note mentions a friend; under the fixed rules that detail should not be recorded.

<img src="media/fc4a1e67d956e4a0a0ee7d0b2fee75818337114e.png" style="width:2.69792in;height:5.52083in" />

**Figure B2. AI model output with an error and a flag**

The model correctly flags the missing living situation and correctly drops the friend. It records the shelter referral as accepted. The red highlight is added for this document only; the system has no way to know its own output is wrong, which is why it reports this field at high confidence.

<img src="media/ee34ed4830867b2316296332a638458fae5ce9cf.png" style="width:6.5in;height:3.53125in" />

**Figure B3. Mapped fields carry the error forward**

The wrong referral status and the single follow-up date are mapped into the record exactly as the model produced them. The missing living situation is held open for the worker to supply.

<img src="media/502b4dd1057179eb1d6a7777a7b9beb6898498e9.png" style="width:6.5in;height:4in" />

**Figure B4. API view: staged record containing the error**

The staged record is still blocked from HMIS. Rows shaded red are the ones that are wrong in this draft; the shading is for this document only.

<img src="media/53e0cfcefd2bc6a0f01d23808558f340e7c2da68.png" style="width:6.5in;height:3.27083in" />

**Figure B5. Draft emailed back to the worker**

The worker sees the draft with a banner for the missing field. Reading the Referrals row and the case note, the worker sees "referral accepted," which is not what happened.

<img src="media/392f399e87e2acab33df0a4eb7438cb2c5b544ce.png" style="width:2.69792in;height:6.39583in" />

**Figure B6. Worker replies with corrections in plain words**

The worker does not edit a form or log into a system. They reply in the same plain language they used for the original note, fixing the referral and the follow-up window and supplying the missing living situation.

<img src="media/e2f2e5149a2dedf94d9f2c18dd26801a0d30200f.png" style="width:2.69792in;height:5.52083in" />

**Figure B7. Revised draft sent back for confirmation**

The system applies the corrections and sends draft v2. The referral now reads as offered and declined, the follow-up shows Monday or Tuesday, and the case note is regenerated to match. The worker replies CONFIRM.

<img src="media/9a3bedb88b8938999b671854382f2396f600cafc.png" style="width:2.69792in;height:6.60417in" />

**Figure B8. API view: confirmed record submitted, with audit trail**

Corrected fields are marked as worker-sourced rather than AI-sourced, so anyone reviewing the record later can see which values a person supplied. The audit trail records each draft, the correction, the confirmation time and the deletion of the email copies. Live submission to HMIS depends on CHIP approving API access, which Goodwill is pursuing.

<img src="media/32495c6305234c02607462743df9c75c421c84d5.png" style="width:6.5in;height:4.32292in" />

Design choices shown, and what they rely on

Several behaviors in these screens are proposed design rules, not decisions. Each needs a sponsor answer before the concept moves to a prototype.

| **Shown in mockup**                                | **Status**                                                              | **Needs to be confirmed with**        |
|----------------------------------------------------|-------------------------------------------------------------------------|---------------------------------------|
| HMIS field list and names                          | Illustrative only                                                       | CHIP / HMIS administrator             |
| HMIS API submission                                | Depends on CHIP approval (Goodwill handling, per Oct 7 sponsor meeting) | Goodwill IT, CHIP                     |
| Model hosted inside Goodwill network               | Sponsor-stated Oct 7; hosting and owner not yet named                   | Goodwill IT                           |
| Secure intake inbox and encryption                 | Assumed; mechanism not specified                                        | Goodwill IT                           |
| Email copies deleted after submission              | Proposed retention rule                                                 | Goodwill IT, Horizon House leadership |
| Unconfirmed drafts go to supervisor after 48 hours | Proposed; prevents silent loss of records                               | Horizon House leadership              |
| Location kept at quadrant level only               | Proposed data minimization rule                                         | Horizon House leadership              |
| ID document photos stay out of email               | Proposed; keeps existing HMIS upload path                               | Horizon House leadership              |
