# Signature documents and photos: options for production

The prototype leaves out two things on purpose: documents that need a signature, and photos. This document explains why, describes how each could be handled in a production system, and lists what DeveloperTown would need to decide with Goodwill, Horizon House, and CHIP. It proposes no code.

## What is affected

| Item | Where it appears | Signatures | Source |
|---|---|---|---|
| Client Informed Consent (Coordinated Entry intake) | The CE intake in HMIS. The client reads the consent, chooses one of three options, and signs; the case manager also signs. Today this is done in HMIS with a mouse or a signature pad. | Client and case manager | HMIS User Manual, CE intake steps 11 and 12 (`docs/reference/`) |
| CHIP Form 101 (Outreach Observation) | An outreach record CHIP accepts | Staff and applicant signatures, plus a release authorization | Earlier draft, `docs/reference/previous-draft/` |
| Horizon House verification letter | A letter for the neighbor, generated from details the worker supplies | Not yet confirmed who signs or receives it | Earlier draft, `docs/reference/previous-draft/` |
| Photos of ID documents | Uploaded to HMIS today through its existing upload path | None | Encounter Workflow Mockups, figure A1 and the design choices table |

## How the prototype handles them today

- **Consent.** The draft shows "Client consent and signatures: PENDING. You complete the consent with the neighbor in HMIS." Consent is never recorded as obtained from email text. If a note says "he agreed to share his info, signed already", the review email adds a consent notice, and the generated case note replaces that statement with "[consent pending]".
- **Remaining work.** The review email and the receipt list "Client consent and signatures (pending, completed with the neighbor in HMIS)" among the items the worker still completes in HMIS.
- **Photos.** The compose screen tells the worker not to attach photos of ID documents. The intake does not accept or store attachments.

## Why they are out of scope for the prototype

1. **An email cannot carry a valid signature.** A typed name or "signed already" in a note is not a signature. Consent must also be informed: the neighbor reads it and chooses an option, which happens with the neighbor present, not in a note written afterwards.
2. **The question is open.** The team has not received an answer on whether documents that need signatures belong in a headless application (proposal, "Why").
3. **CHIP decides what counts.** Which signature methods and document uploads HMIS accepts through an interface is CHIP's decision, and the prototype only enters three records through a mock.
4. **Photos are the most sensitive data in the flow.** ID images carry full names, dates of birth, ID numbers, faces, and often location data inside the file. Putting them in a mailbox spreads them across inboxes, devices, and backups, and the prototype keeps location at quadrant level and deletes email copies after entry.
5. **There is already a path.** ID photos have an existing upload path into HMIS, which works and is understood by staff.
6. **Synthetic data only.** The prototype cannot be tested with real signatures or ID images, and fake ones would prove little.

## Options for production

### Signatures

| Option | How it would work | Strengths | Concerns |
|---|---|---|---|
| A. Keep signing in HMIS (the prototype's assumption) | The email intake drafts and enters the record. The worker completes consent with the neighbor in HMIS, using the signature pad or mouse as today. | No new signature system. Matches the manual. | The worker has a second step, and consent may lag the encounter. If HMIS needs consent before other data is shared, the entry order would have to change (question 3 below). |
| B. Capture on the worker's device at the encounter | A small consent screen on a work phone or tablet shows the consent text, records the neighbor's choice and signature, and sends it through a separate secure channel, never email. It is stored as a document or consent record in HMIS by a method CHIP accepts. | Consent at the moment of contact. One trip. | New software to build, secure, and support. Needs CHIP acceptance, legal review of electronic signatures, device management, and offline use in places without signal. |
| C. Paper form, then a scan | The neighbor signs a paper form in the field. The worker scans it later and it is uploaded as a document (for example through the "Document Collected" tool noted in CHIP's CES knowledge base). | Works anywhere. Familiar. | Paper can be lost or damaged. Scans are images with the same sensitivity as ID photos. The structured consent choice still has to be entered. |

The email intake can work with any of these. It never records consent as given, and it can keep listing consent as pending until HMIS says otherwise.

### Photos

| Option | How it would work | Strengths | Concerns |
|---|---|---|---|
| A. Keep the existing HMIS upload path (the prototype's assumption) | Photos go into HMIS the way they do today. The email intake ignores them. | Nothing new. No images in email. | Separate step for the worker. |
| B. Direct upload from a work device | A capture screen sends the image straight to HMIS (or to secure storage linked to the record) over an authenticated channel, removes location data from the file, and keeps no copy on the device. | One flow. Images never touch email. | Needs an attach-document interface that CHIP accepts, device management, and a retention rule. |
| C. Email attachments | The worker attaches photos to the intake email. | Easy for the worker. | Not recommended. Images would sit in mailboxes and backups, could be forwarded, and carry location data. It would undo the location and retention rules the prototype follows. |

## What DeveloperTown would need to decide

With CHIP:

1. Which signature methods HMIS accepts for the Client Informed Consent and for Form 101 when entry comes through an interface, and whether a signed document can be uploaded through an interface at all.
2. Whether an attach-document operation exists or can be agreed, what file types and sizes it accepts, and what it returns.
3. Whether HMIS needs consent recorded before the other entries, which would change the order the prototype uses (client, program enrollment, Coordinated Entry enrollment).

With Goodwill and Horizon House:

4. Whether signature documents belong in this product at all (the open question in the proposal), and if so which ones first: consent, Form 101, or the verification letter.
5. Whether workers have managed work devices that could capture signatures or photos, and what happens where there is no signal.
6. Retention: how long any image or signed document may be kept outside HMIS (ideally not at all), and who can see it.
7. Who signs and who receives the verification letter, and whether it is needed.

For the build:

8. Where consent state is shown to the worker, so the review email can stop listing consent as pending once it is done.
9. How signatures and images are kept out of logs, notifications, and error reports.
10. How each choice is tested without real neighbor data.

The open questions in `openspec/changes/add-new-client-enrollment-demo/design.md` (consent signature, retention, AI policy) name who to ask at Goodwill, Horizon House, and CHIP.
