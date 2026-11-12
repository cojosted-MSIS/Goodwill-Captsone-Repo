# Open questions

Every item marked [TBC] in the specs, the design documents, the configuration, the code, and the docs, in one place, grouped by who can answer it. Each says what the question is, why it matters, and what the demo assumes in the meantime. An item with two owners is listed once, under the owner who decides first, and names the other.

The appendix at the end shows where every [TBC] in the repository appears and which question it belongs to. `python scripts/update_questions_doc.py` regenerates it, and a test fails if a new [TBC] has no question.

## The 10 most important

Ordered by how much of a production system depends on the answer.

1. **[CHIP-1] Can this system read the real HMIS at all?** Briefings, look-ups, the watchlist, and the same-name check all depend on it.
2. **[CHIP-2] Will CHIP agree to an entry-only interface, and with which required fields?** Nothing reaches HMIS without one.
3. **[CHIP-4] Does the real HMIS accept an idempotency key?** Without one, a retry after a lost answer could create a second client.
4. **[HH-1] What are the real case note and service fields and service types?** Recurring visit notes are the core of the product, and today's list is a placeholder.
5. **[IT-1] How will people sign in, and where do roles come from?** The demo's synthetic accounts cannot be used with real data.
6. **[IT-5] Where will this be hosted over HTTPS?** Service workers and browser encryption only work over HTTPS, so offline does not work on a real phone without it.
7. **[IT-4] Who holds the private keys that open queued notes?** Whoever holds them can read every note waiting on every device.
8. **[GW-2] May even the last four SSN digits be stored on a device?** It changes what a worker can capture offline.
9. **[GW-16] Where may AI parsing run, and what does Goodwill's AI policy allow?** Note text goes to the model, so this decides whether the parser can be used on real notes.
10. **[GW-1] Does email stay as a fallback, or is it deleted?** Two channels mean two things to secure, test, and audit.

## CHIP

| ID | Question | Why it matters | What the demo assumes |
|---|---|---|---|
| CHIP-1 | Can the system read the real HMIS at all, by SQL or an API, and under what agreement? (With the HMIS administrator.) | The four queries and the same-name check need reads. No access is confirmed. | A mock HMIS with read-only views, a read-only connection, and fixed, audited queries. |
| CHIP-2 | Can an entry-only interface be agreed, what entry method and permissions apply, and which fields are truly required for a new client? | Entry is the whole point, and the required list drives what the review blocks on. | The mock accepts POSTs for client, enrollment, Coordinated Entry enrollment, case note, and service. Required fields follow the manual excerpt (`config/hmis.yaml`). |
| CHIP-3 | Is reading a client ID in the format `HMIS-C-NNNNNN` right? What is the real client ID format, and what prefixes do real IDs use? | Notes and queries are checked against the format. | `HMIS-C-` plus six digits; `HMIS-N-` and `HMIS-S-` for case notes and services. |
| CHIP-4 | Does the real HMIS accept an idempotency key on entry operations? | A retry after a lost answer must not make a second record. | The core makes a key at Confirm and reuses it for every retry; the mock honors it. |
| CHIP-5 | Does the real HMIS have a place for a quadrant (or another location) on a contact or service? | Briefings are by quadrant. If there is no place for it, they cannot be built this way. | The quadrant is entered on the Coordinated Entry contact and every service. |
| CHIP-6 | Does the real HMIS allow a confirmed-distinct override for a possible duplicate? | "Different person" needs some way past the duplicate check. | The mock accepts `confirmed_distinct` only with a non-empty reason. |
| CHIP-7 | How does HMIS treat a possible duplicate when entry comes through an interface, or when a worker's search missed one? | It is the last safety net against duplicate clients. | The mock rejects a possible duplicate and says nothing about the matching record. |
| CHIP-8 | Can saved case notes and services be edited through an interface? | Corrections after entry depend on it. | Edits are allowed; a config flag falls back to a new entry that says it corrects the earlier one. |
| CHIP-9 | Can a case note be entered with the program enrollment, or does HMIS keep it separately? | It changes the order and shape of entry. | It is sent as an optional field of the enrollment. |
| CHIP-10 | How does record visibility work, and which project does an outreach worker belong to? | A worker must never learn about a record they cannot see. | Visibility follows the project in `config/workers.yaml`; a hidden record is answered as if it does not exist. |
| CHIP-11 | Which signature methods does HMIS accept for the Client Informed Consent, and how is it completed when entry comes through this path? | Consent cannot be recorded from a note. | Consent and signatures are always shown as pending, and completed in HMIS by the worker. |
| CHIP-12 | Does the Coordinated Entry intake allow the triage assessment without the VI-SPDAT? | It decides what can be entered in one go. | The triage assessment is entered; the VI-SPDAT is out of scope. |
| CHIP-13 | How should SSNs be handled in this channel, and should any digits beyond the last four be discarded? (With Goodwill.) | A full SSN must not spread. | Only the last four and a data-quality option are kept; further digits are discarded. |
| CHIP-14 | Does an attach-document operation exist or can one be agreed, and must consent be recorded before other entries? | Needed before signatures or photos could be handled here. | Out of scope; see `docs/FUTURE.md`. |
| CHIP-15 | Superseded draft: how should a Form 101 land in HMIS, what minimum fields make a new profile, and how does an entry attach to the right client when the system cannot look anyone up? | Kept from the earlier draft so nothing is lost. The third part is now answered by the read-only lookup, if CHIP-1 allows it. | Form 101 is out of scope. |

## Goodwill

| ID | Question | Why it matters | What the demo assumes |
|---|---|---|---|
| GW-1 | Does email stay as a fallback channel, or is the code deleted? (The sponsors: Goodwill and DeveloperTown.) | Two channels mean two surfaces to secure and a second way for personal information to arrive. | Kept, off by default behind `channels.email.enabled`. |
| GW-2 | May even the last four SSN digits be stored on a device? (With CHIP.) | They are in the sealed note until upload. | Allowed. If not, the device would mask all nine digits and the worker adds the last four after upload. |
| GW-3 | Are the SSN layers enough, given a number written in words or split across sentences cannot be detected? (With CHIP.) | A missed number would be sealed on the device and sent. | Pattern masking, a looser detector, a warning on the form, and masking again on the server. |
| GW-4 | Are shared devices allowed? (With CHIP.) | Notes from two workers could sit on one device. | One worker per device recommended. If shared, each note belongs to its owner; others see only a count; the server refuses a mismatch. |
| GW-5 | How long may a device keep accepting notes without reaching the server? | It limits how stale an unverified note can be. | 12 hours (`web.offline_write_hours`), enforced on the device and by the server when the note arrives. |
| GW-6 | May the worker's profile (username, display name, role, last contact) be stored on the device? | It is the only readable personal data kept there, and the app needs it to open offline. | Accepted for now, kept to that minimum, and removed at sign-out. |
| GW-7 | May the same-name screen show that the last four SSN digits match, differ, or are missing (never the digits)? (With CHIP.) | It helps the decision but reveals something about the record. | The chip is shown, with a note saying this is open. |
| GW-8 | What may supervisors see of a draft? | Supervisors have no need for most neighbor information. | States, times, and the audit; never note text, titles, or field values. |
| GW-9 | Who is the supervisor for the 48-hour queue, and how are teams defined? | It decides who is told about stuck drafts. | One demo supervisor sees every draft. |
| GW-10 | Should supervisor and staff views themselves be audited? | Viewing records may need a trail. | Not audited; only HMIS reads, actions, and sign-ins are. |
| GW-11 | Who needs the parser-run and staged-record views outside the demo? | They show draft contents. | Demo only, off by default. |
| GW-12 | Should a "different person" decision on matching SSN digits wait for a supervisor's approval? | A wrong decision creates a duplicate client. | It needs a 40-character reason and is flagged afterward, without blocking. |
| GW-13 | Is 48 hours the right limit before a draft goes to the supervisor? | It sets how long a note can sit unconfirmed. | 48 hours. |
| GW-14 | What is the production retention limit for stored note text and stubs, and who can see them? (With Goodwill IT.) | Note text is the most sensitive thing kept. | Reduced to a stub at submission in production mode; unsubmitted drafts deleted after 7 days. |
| GW-15 | How long should query emails be kept, if the email channel stays? | Replies hold neighbor information. | 24 hours. |
| GW-16 | Where does AI parsing run, and what does Goodwill's written AI policy allow? | Note text goes to the model. | A rule-based stub by default; REALLMS for synthetic text only. |
| GW-17 | Do signature documents belong in this product, and if so which first? Do workers have managed devices? | It decides whether a capture screen is ever built. | Out of scope; see `docs/FUTURE.md`. |
| GW-18 | Superseded draft: the reminder window, who is flagged, after how many days an unapproved draft is deleted, and the retention rule for the Goodwill mailbox. | Kept from the earlier draft so nothing is lost. Mostly replaced by GW-13 and GW-14. | 48-hour queue; 7-day deletion. |

## Goodwill IT

| ID | Question | Why it matters | What the demo assumes |
|---|---|---|---|
| IT-1 | How will people sign in (single sign-on), and where do roles come from? | The demo's accounts cannot be used with real data. | Synthetic accounts in `config/users.yaml`, passwords in `.env`, stored only as scrypt hashes. |
| IT-2 | What should the session idle and absolute timeouts be? | They balance security against a worker outdoors. | 30 minutes idle, 12 hours absolute. |
| IT-3 | Where should sign-in lockout counts live with more than one app process? | Each process would count separately. | In memory, one process. |
| IT-4 | Who holds the private keys that open queued notes, and how are they rotated? | Whoever holds them can read every waiting note. | Environment variable, several keys at once, newest first. A key vault is expected. |
| IT-5 | Where is it hosted over HTTPS, and will a reverse proxy keep the Host header? | Service workers and browser encryption need HTTPS. The offline sign-out checks Origin against Host. | Localhost. |
| IT-6 | What runs the time-based rules in production? | The 48-hour rule and retention must hold with nobody signed in. | A timer in the app, plus a check before each signed-in request. |
| IT-7 | Superseded draft: who owns and can access the mailbox and audit trail, and how are authorized workers identified? | Kept from the earlier draft so nothing is lost. Mostly replaced by IT-1. | Accounts in configuration. |

## Horizon House

| ID | Question | Why it matters | What the demo assumes |
|---|---|---|---|
| HH-1 | What are the real case note and service fields, and the Contact Service options? Is time spent recorded? (With CHIP.) | Recurring visit notes are the core of the product. | A placeholder list (outreach contact, basic needs, transportation, ID document help, housing navigation, referral). |
| HH-2 | What counts as a contact (services, case notes, phone calls, attempts)? | The watchlist is only as good as this definition. | Any contact record in the read-only views; the result says this is open. |
| HH-3 | Are 60 days and a 14-day warning the right numbers, and are exits after 60 days a policy? | It sets who appears on the watchlist. | 60 days, with a 14-day warning. |
| HH-4 | Which ID document and housing assessment statuses matter to workers, and what are the labels? | They are what a status check answers. | `id_document` and `housing_assessment`, with State ID and birth certificate as labels. |
| HH-5 | Which projects and Coordinated Entry region does an outreach worker enroll into, and what are the IDs? (With CHIP.) | Enrollments need real IDs. | Placeholder IDs in `config/programs.yaml`. |
| HH-6 | Which parts of the intake steps stay "completed in HMIS by the worker"? Is current living situation required on a visit? | It decides how much is left to do by hand. | Everything else in the step is listed for the worker to finish in HMIS; living situation is optional on a visit. |
| HH-7 | Superseded draft: how often Form 101 and the verification letter are completed, who receives the letter, whether issuing it is logged, and what a written referral needs. | Kept from the earlier draft so nothing is lost. | Out of scope. |

## DeveloperTown

| ID | Question | Why it matters | What the demo assumes |
|---|---|---|---|
| DT-1 | Should the `encounter-email-intake` capability be renamed now that notes come from the web? | The name is misleading. | Kept, so the spec history stays readable. |
| DT-2 | Is 96 hours the right time to remember an Idempotency-Key? | It must outlast the 72-hour device queue. | 96 hours, checked at startup to be longer than the queue. |
| DT-3 | When the open notes above are answered, remove the [TBC] hints shown on screen. | Workers should not see working notes in production. | The web shows short headings with the note as a small hint; email keeps its labels. |

<!-- BEGIN GENERATED: where each [TBC] appears -->

## Appendix: where each [TBC] appears (237 in all)

Generated. Each line is a question, then each file that mentions it, with how many times.

- **CHIP-1:** `CLAUDE.md` (1), `README.md` (1), `app/core.py` (1), `app/hmis_reader.py` (1), `config/settings.yaml` (1), `docs/HANDOFF.md` (1), `mock_hmis/__init__.py` (1), `mock_hmis/store.py` (1), `openspec/changes/archive/2026-11-10-add-hmis-readonly-queries/design.md` (5), `openspec/changes/archive/2026-11-10-add-hmis-readonly-queries/proposal.md` (1), `openspec/changes/archive/2026-11-10-add-hmis-readonly-queries/specs/review-and-submit/spec.md` (1), `openspec/project.md` (1), `openspec/specs/hmis-readonly-queries/spec.md` (1), `openspec/specs/review-and-submit/spec.md` (1)
- **CHIP-2:** `config/hmis.yaml` (1), `docs/reference/previous-draft/OpenSpec_READ_ME_Draft_2.md` (1), `docs/reference/previous-draft/add-outreach-email-intake/specs/outreach-email-pipeline/spec.md` (1)
- **CHIP-3:** `app/config_loader.py` (1), `config/settings.yaml` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/design.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/specs/existing-client-updates/spec.md` (1), `openspec/changes/archive/2026-11-10-add-hmis-readonly-queries/design.md` (1), `openspec/changes/archive/2026-11-10-add-hmis-readonly-queries/specs/hmis-readonly-queries/spec.md` (1), `openspec/specs/existing-client-updates/spec.md` (1), `openspec/specs/hmis-readonly-queries/spec.md` (1)
- **CHIP-4:** `app/core.py` (1), `app/drafts.py` (1), `app/hmis_gateway.py` (1), `mock_hmis/service.py` (1), `openspec/changes/add-web-application/design.md` (1), `openspec/changes/add-web-application/proposal.md` (1), `openspec/changes/add-web-application/specs/web-application/spec.md` (1)
- **CHIP-5:** `README.md` (1), `app/web_wording.py` (1), `config/fields.yaml` (2), `config/hmis.yaml` (1), `docs/HANDOFF.md` (1), `docs/PROMPTS.md` (1), `mock_hmis/store.py` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/design.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/specs/existing-client-updates/spec.md` (1), `openspec/specs/existing-client-updates/spec.md` (1)
- **CHIP-6:** `README.md` (1), `mock_hmis/service.py` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/design.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/proposal.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/specs/existing-client-updates/spec.md` (1), `openspec/specs/existing-client-updates/spec.md` (1)
- **CHIP-7:** `docs/reference/previous-draft/OpenSpec_READ_ME_Draft_2.md` (1), `docs/reference/previous-draft/add-outreach-email-intake/design.md` (1)
- **CHIP-8:** `config/hmis.yaml` (1), `mock_hmis/rules.py` (1), `openspec/changes/add-web-application/specs/existing-client-updates/spec.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/design.md` (2), `openspec/changes/archive/2026-11-10-add-existing-client-updates/proposal.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/specs/existing-client-updates/spec.md` (1), `openspec/specs/existing-client-updates/spec.md` (1)
- **CHIP-9:** `config/fields.yaml` (1), `config/hmis.yaml` (1), `openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/design.md` (1), `openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/specs/new-client-enrollment/spec.md` (1), `openspec/specs/new-client-enrollment/spec.md` (1)
- **CHIP-10:** `app/config_loader.py` (1), `config/workers.yaml` (1), `openspec/changes/archive/2026-11-10-add-hmis-readonly-queries/design.md` (1), `openspec/changes/archive/2026-11-10-add-hmis-readonly-queries/specs/hmis-readonly-queries/spec.md` (1), `openspec/specs/hmis-readonly-queries/spec.md` (1)
- **CHIP-11:** `docs/reference/previous-draft/OpenSpec_READ_ME_Draft_2.md` (3), `docs/reference/previous-draft/add-outreach-email-intake/design.md` (1), `docs/reference/previous-draft/add-outreach-email-intake/specs/form-101-observation/spec.md` (2), `openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/design.md` (1), `openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/specs/coordinated-entry-intake/spec.md` (1), `openspec/specs/coordinated-entry-intake/spec.md` (1)
- **CHIP-13:** `openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/specs/new-client-enrollment/spec.md` (1), `openspec/specs/new-client-enrollment/spec.md` (1)
- **DT-1:** `openspec/changes/add-web-application/design.md` (1), `openspec/changes/add-web-application/proposal.md` (1)
- **DT-2:** `config/settings.yaml` (1)
- **DT-3:** `app/web_wording.py` (1), `openspec/changes/add-web-application/design.md` (2)
- **GW-1:** `README.md` (1), `app/email_channel.py` (1), `config/settings.yaml` (1), `openspec/changes/add-web-application/design.md` (2), `openspec/changes/add-web-application/proposal.md` (3), `openspec/changes/add-web-application/specs/web-application/spec.md` (1), `openspec/changes/add-web-application/tasks.md` (1)
- **GW-2:** `openspec/changes/add-web-application/design.md` (1)
- **GW-2/GW-3/GW-4:** `openspec/changes/add-web-application/design.md` (1)
- **GW-2/GW-4:** `openspec/changes/add-web-application/proposal.md` (2), `openspec/changes/add-web-application/specs/offline-sync/spec.md` (1)
- **GW-3:** `app/ssn_guard.py` (1), `openspec/changes/add-web-application/design.md` (1), `openspec/changes/add-web-application/specs/offline-sync/spec.md` (1), `ui/web/ssn.js` (1)
- **GW-4:** `openspec/changes/add-web-application/design.md` (2), `openspec/changes/add-web-application/specs/offline-sync/spec.md` (1)
- **GW-5:** `config/settings.yaml` (1), `openspec/changes/add-web-application/design.md` (2), `openspec/changes/add-web-application/specs/offline-sync/spec.md` (1)
- **GW-6:** `openspec/changes/add-web-application/design.md` (1), `ui/web/device.js` (1)
- **GW-7:** `openspec/changes/add-web-application/design.md` (1), `ui/web/screens.js` (1)
- **GW-8:** `app/web_api.py` (1), `openspec/changes/add-web-application/design.md` (1), `openspec/changes/add-web-application/specs/web-application/spec.md` (1), `ui/web/screens.js` (1)
- **GW-9:** `app/web_api.py` (1), `config/workers.yaml` (1), `openspec/changes/add-web-application/design.md` (1)
- **GW-10:** `app/web_api.py` (1), `openspec/changes/add-web-application/design.md` (1)
- **GW-11:** `app/config_loader.py` (1), `config/settings.yaml` (1), `openspec/changes/add-web-application/design.md` (2), `openspec/changes/add-web-application/specs/web-application/spec.md` (1), `openspec/changes/add-web-application/tasks.md` (1)
- **GW-12:** `README.md` (1), `config/settings.yaml` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/design.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/specs/existing-client-updates/spec.md` (1), `openspec/specs/existing-client-updates/spec.md` (1)
- **GW-13:** `config/settings.yaml` (1), `openspec/changes/add-web-application/specs/review-and-submit/spec.md` (1), `openspec/changes/add-web-application/specs/web-application/spec.md` (1), `openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/specs/review-and-submit/spec.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/specs/review-and-submit/spec.md` (1), `openspec/specs/review-and-submit/spec.md` (1)
- **GW-14:** `config/settings.yaml` (1), `openspec/changes/add-web-application/specs/review-and-submit/spec.md` (1), `openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/specs/review-and-submit/spec.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/specs/review-and-submit/spec.md` (1), `openspec/specs/review-and-submit/spec.md` (1)
- **GW-15:** `config/settings.yaml` (1), `openspec/changes/archive/2026-11-10-add-hmis-readonly-queries/specs/hmis-readonly-queries/spec.md` (1), `openspec/specs/hmis-readonly-queries/spec.md` (1)
- **GW-18:** `docs/reference/previous-draft/OpenSpec_READ_ME_Draft_2.md` (4), `docs/reference/previous-draft/add-outreach-email-intake/specs/outreach-email-pipeline/spec.md` (4)
- **HH-1:** `README.md` (1), `app/web_wording.py` (1), `config/fields.yaml` (3), `config/hmis.yaml` (1), `config/mappings.yaml` (1), `docs/PROMPTS.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/design.md` (4), `openspec/changes/archive/2026-11-10-add-existing-client-updates/proposal.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/specs/existing-client-updates/spec.md` (2), `openspec/specs/existing-client-updates/spec.md` (2)
- **HH-1/CHIP-8/CHIP-6/GW-12:** `openspec/changes/archive/2026-11-10-add-existing-client-updates/tasks.md` (1)
- **HH-2:** `app/queries.py` (2), `openspec/changes/archive/2026-11-10-add-no-contact-query/design.md` (3), `openspec/changes/archive/2026-11-10-add-no-contact-query/proposal.md` (1), `openspec/changes/archive/2026-11-10-add-no-contact-query/specs/hmis-readonly-queries/spec.md` (1), `openspec/specs/hmis-readonly-queries/spec.md` (1)
- **HH-3:** `app/config_loader.py` (1), `config/settings.yaml` (1), `openspec/changes/archive/2026-11-10-add-no-contact-query/proposal.md` (2)
- **HH-4:** `app/config_loader.py` (1), `app/queries.py` (1), `config/settings.yaml` (1), `openspec/changes/archive/2026-11-10-add-hmis-readonly-queries/design.md` (1), `sample-data/hmis_seed.yaml` (1)
- **HH-5:** `config/programs.yaml` (1)
- **HH-6:** `openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/design.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/design.md` (1)
- **IT-1:** `app/auth.py` (1), `config/users.yaml` (1), `openspec/changes/add-web-application/design.md` (1), `openspec/changes/add-web-application/proposal.md` (1), `openspec/changes/add-web-application/specs/web-application/spec.md` (1)
- **IT-2:** `config/settings.yaml` (1), `openspec/changes/add-web-application/specs/web-application/spec.md` (1)
- **IT-3:** `app/auth.py` (1), `openspec/changes/add-web-application/design.md` (1)
- **IT-4:** `README.md` (1), `app/sealing.py` (1), `openspec/changes/add-web-application/design.md` (1)
- **IT-5:** `README.md` (1), `openspec/changes/add-web-application/design.md` (2)
- **IT-6:** `openspec/changes/add-web-application/design.md` (1)
- **Says only that open items are marked, or a test checks an item's wording:** `CLAUDE.md` (1), `docs/HANDOFF.md` (1), `docs/reference/previous-draft/OpenSpec_READ_ME_Draft_2.md` (2), `docs/reference/previous-draft/add-outreach-email-intake/proposal.md` (1), `openspec/changes/add-web-application/design.md` (2), `openspec/changes/add-web-application/tasks.md` (1), `openspec/changes/archive/2026-11-02-add-new-client-enrollment-demo/proposal.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/design.md` (1), `openspec/changes/archive/2026-11-10-add-existing-client-updates/proposal.md` (1), `openspec/changes/archive/2026-11-10-add-hmis-readonly-queries/design.md` (1), `openspec/changes/archive/2026-11-10-add-hmis-readonly-queries/proposal.md` (1), `openspec/changes/archive/2026-11-10-add-no-contact-query/design.md` (1), `openspec/project.md` (1), `tests/test_existing_client_updates.py` (1), `tests/test_web_screens.py` (3), `tests/test_web_style.py` (1), `tests/test_web_supervisor_staff.py` (1)

<!-- END GENERATED -->
