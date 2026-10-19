# Change: Add email-based outreach documentation (Form 101 and Verification Letter)

## Why

Horizon House outreach workers document encounters after the fact, from paper notes or memory, and then re-enter the information in HMIS. Workers already use email, and Goodwill email has encryption and access controls. This change describes an email-driven path: a worker describes an encounter or asks for a document in a plain email, the system drafts the structured entry, and the worker confirms it before anything is entered in HMIS or issued.

The system only enters information. It never searches or reads HMIS. Workers still look up neighbors in HMIS themselves, and they put the identifier they found in their email.

Two documents are specified first because together they show two different kinds of work:

- **CHIP Form 101 (Outreach Observation)** is entry into HMIS. Information goes from an email into an HMIS entry.
- **Horizon House Verification Letter** is document generation with no HMIS involvement. The letter is prepared in the field with the neighbor, so the details come from what the neighbor tells the worker, passed along in the worker's email.

Everything else the pipeline does (identifying the form, confirming with the worker, protecting personal information, reminders, audit) is shared, so it is specified once.

## What Changes

- **ADD** `outreach-email-pipeline`: shared intake, parsing, neighbor identification from the email, new-profile drafts, photo attachments, confirmation, reminders, privacy, retention, and audit behavior.
- **ADD** `form-101-observation`: capture an outreach observation for entry into HMIS.
- **ADD** `verification-letter`: draft a homeless verification letter from details the neighbor gave the worker in the field.

## Impact

- **Affected systems:** the designated secure Goodwill inbox, an AI parsing component, and HMIS (entry only, through an interface to be agreed with CHIP).
- **Not changed:** HMIS configuration, credentialing, login, and data standards. These are owned and administered by CHIP. The system never pulls data out of HMIS.
- **In scope (decided with Goodwill and aligned with DeveloperTown's sample):** photos as attachments (not video), drafting new neighbor profiles after the worker confirms, signatures handled by a CHIP-accepted method, retention of inbox content with an access-controlled audit trail, and a reminder plus supervisor flag for unconfirmed drafts.
- **Architecture:** follows the application architecture notes, with one difference: no HMIS lookup (see `design.md`).
- **Out of scope:** production build, direct-to-client applications, searching or reading HMIS, and any real client data in the team's own work. All examples in these files are made up.
- **Status:** draft for review by the capstone team, Goodwill, and DeveloperTown. Items marked [TBC] are open and listed in `design.md`.
