# Design: Updates to existing clients, and same-name verification

## Context
Week 10 made case notes and service documentation the core MVP: workers meet the same neighbor repeatedly and add to the same HMIS record each time. Stakeholders also want stronger verification when neighbors share a name and date of birth. This change depends on `add-hmis-readonly-queries` for the lookup. All writes still go through entry operations after CONFIRM; email is still the only channel.

```text
"Update: <name or client ID>"  ->  client ID in the note?  -- yes -->  check format + lookup by ID
                                          | no
                                          v
                                 lookup by name + DOB -> candidates email -> worker replies CLIENT <ID>
  -> draft case note + service entry -> validate -> review email -> CONFIRM | corrections (v2 ...)
  -> add case note, then add service (POST only) -> receipt with entry IDs -> audit (no note text) -> email purge

"New client: ..."  ->  draft  ->  lookup by name + DOB
  -> no match: review as today
  -> match: verification email (candidates, grade)  ->  SAME CLIENT <ID>  ->  becomes an update draft
                                                    ->  DIFFERENT PERSON: <reason>  ->  review, CONFIRM,
                                                        entered with a confirmed-distinct override
```

## Decisions

### 1. Update is the main flow
- Subjects: "Update: <name or client ID>" for a visit to a known neighbor, "New client: ..." as today, "Query: ..." for queries (`add-hmis-readonly-queries`).
- One note per visit, one update draft per note. A client collects any number of entries over time.
- The client ID in the note wins over a name in the subject. Different IDs in the subject and note stop the draft.
- With no client ID, the lookup runs on the name and date of birth in the note and the worker picks with "CLIENT <ID>", even when there is one candidate, because picking is an inference the system must not make.

### 2. Case note and service entry fields [TBC with Horizon House and CHIP]
Based on the HMIS manual excerpt (`docs/reference/hmis-manual-new-client-enrollment-and-ce-intake.md`): the Coordinated Entry triage assessment records a contact with Information Date, Assessment Location, Assessment Contact Type, Current Living Situation, Record Contact, and a Contact Service chosen from a drop-down.

| Field | Source | Required | Basis |
|---|---|---|---|
| Service date | Stated in the note, else the email date (labelled) | Yes | Information Date |
| Service type | From the note, matched to a configured list [TBC: the real Contact Service options] | Yes | Contact Service drop-down |
| Contact type | Program default "in person, street contact" | Yes | Assessment Contact Type |
| Quadrant | From the note | Yes | Assessment Location, kept at quadrant level |
| Current living situation | From the note, only if stated | No [TBC] | Current Living Situation |
| Time spent | From the note, only if stated ("30 minutes") | No | Not in the excerpt |
| Case note | Generated from the note, same privacy rules as today | Yes | Not in the excerpt |

What the excerpt does not cover: a case note screen or its fields, a service record outside the Coordinated Entry triage, the list of Contact Service options, time spent or duration, a quadrant on a service, whether a saved case note or service can be edited, and who can see case notes. The demo service types are a placeholder list (outreach contact, basic needs, transportation, ID document help, housing navigation, referral) [TBC].

### 3. Mock HMIS operations (POST only)
`POST /clients/{id}/case-notes` and `POST /clients/{id}/services` add entries; `POST /case-notes/{id}/updates` and `POST /services/{id}/updates` correct entries made by this system; `POST /clients` accepts an optional `confirmed_distinct: {reason}`. Each returns only success or failure and the assigned or updated ID (demo prefixes HMIS-N- and HMIS-S- [TBC]). An unknown client returns "No client with that ID exists" and nothing else. Entries appear in the read-only views.

### 3a. As built (Stage 2)
- **Fields in config.** `config/fields.yaml` has a `service` section (draft kind `update`) with the service date, service type (the placeholder list), contact type (program default), and time spent; `update_draft` lists the update's fields in review order (adding the existing quadrant, current living situation, and case note) and which are required.
- **Parsing.** An update note goes through the same parser as a new-client note; only the update's own fields are kept, never names, dates of birth, or other client answers. Service type and time spent come from shared rules in `config/mappings.yaml` (`shared.service_type`, `shared.time_spent`) that run for every parser, so the live parser gets them too. Time spent is filled only from a stated duration. A hedged sentence ("about 20 minutes") gives Medium.
- **Client check.** A client ID in the subject or note (`settings.updates.client_id_in_text`) is checked for format and found through the read-only lookup, which is audited like a query. With no ID, the lookup runs on the parsed name and full date of birth and the worker picks with "CLIENT <ID>" from a held note (`UPD-` reference).
- **Quadrant on every contact.** The quadrant is sent with the new-client Coordinated Entry entry (`also_sent_with` on the field) and with each service, and the mock records it on the contact, so briefings list the neighbor right away. Before this, the quadrant was kept only in the draft and the case note. [TBC with CHIP: the real HMIS may have no place for a quadrant on a contact]; if so, briefings would need another source for the quadrant.
- **Corrections after entry** reopen the same draft as a new version marked as a correction to the listed entry IDs, and CONFIRM enters it as an update (or, when the mock is set to forbid edits, as new correcting entries).

### 4. Corrections after entry [TBC: the real HMIS may not allow edits after save]
The worker replies to the receipt with the change, naming the entry if the receipt lists more than one ("Service HMIS-S-000014: 45 minutes, not 30"). The system creates a new draft version that references the entry ID, sends a review, needs CONFIRM, and calls the update operation. Only the worker who wrote the original note can correct it. If HMIS forbids edits after save, the fallback is a new case note or service entry that says it corrects the earlier one, after the same CONFIRM. The audit keeps the entry ID and changed field names, never values or note text. Entries not made by this system are refused with "correct it in HMIS". Corrections before entry work as today.

### 5. Same name and date of birth
- **Main check:** the read-only lookup, run on every new-client draft with a full name and full date of birth. A draft without a full date of birth cannot be checked; its review says so and relies on the backstop.
- **Match:** first and last name without regard to case, spacing, or punctuation, and the exact date of birth.
- **Grade by the last four SSN digits (decided):**
  - *Matching digits:* "likely the same person"; the email recommends SAME CLIENT. DIFFERENT PERSON needs a longer written reason (at least 40 characters, a config value) and is flagged in the audit for supervisor review afterward. It does not block on a supervisor's approval; whether production should block is [TBC with Goodwill].
  - *Digits missing on either side:* a hard stop; the email asks the worker to get the digits from the neighbor if they can.
  - *Different digits:* a warning.
  - Every grade needs SAME CLIENT <ID> or DIFFERENT PERSON with a reason; CONFIRM alone is never enough.
- **Limits of the rule:** nicknames, misspellings, hyphenated surnames, and swapped day and month are not matched. The lookup must not suggest similar names (change 1), so these fall to the backstop and to the worker's own HMIS search.
- **Backstop:** the mock's possible-duplicate rejection stays and gives no details. It accepts `confirmed_distinct` only with a non-empty reason. Whether the real HMIS allows an override is [TBC with CHIP].
- **SAME CLIENT:** the new-client fields are not entered. The note's case note and service entry become an update draft. Demographic answers in the note are listed as "update in HMIS yourself" and never written.

### 6. Screens and demo
- **Phone:** "Update a neighbor" compose; "Ask HMIS" compose with the three query types; query replies shown as emails; the verification email with a SAME CLIENT button per candidate and DIFFERENT PERSON with a reason field (no CONFIRM button); a receipt listing the case note and service IDs; a "correct this entry" reply from the receipt.
- **Staff:** the audit trail shows queries (type, parameters, row count) and verification decisions (candidates, grade, decision, reason).
- **Demo seed and scenarios:** a seeded pair sharing a name and date of birth with matching digits, and another with different digits. Scenario C: after Scenario A, an "Update:" note for Pat Example with a case note and service. Scenario D: a new-client note matching the seeded pair, run once to SAME CLIENT and once to DIFFERENT PERSON with a reason. Scenario E: a briefing for SW, then "has <neighbor>'s ID come in". The reset clears everything and reseeds.

### 5a. Candidate details and possible duplicates (review of 2026-11-03)
Two candidates that match on name, date of birth, SSN digits, and quadrant cannot be told apart, and recommending one would be a guess. So each candidate card also shows the date the record was entered, its enrollment status (active or exited), and its last service type, read through two more read-only views (`v_enrollments`, `v_services`). Nothing else is added: no SSN digits, date of birth, or case note text, and the quadrant only. When two or more candidates are strong matches, the email and the phone say they may be duplicates of each other in HMIS, ask the worker to check HMIS and pick the current record, and recommend none; the audit records "possible duplicate pair in HMIS" with the client IDs only, for follow-up. The demo seed now has Robin Demo once as a recent, active strong match (HMIS-C-000113) and once as an older, exited record with different digits (HMIS-C-000114), and a separate pair, Dana Placeholder (HMIS-C-000115 and 116), for the possible-duplicates case (Scenario D3).

## Privacy: what the staging store keeps
**Today (measured from the code):**

| Data | Kept | For how long |
|---|---|---|
| Drafts (`drafts` table) | Every field value, including first and last name, date of birth, SSN last four digits, and answers; the cleaned source sentences; the case note; the parser's verified version 1 output with its sentences; HMIS IDs | Forever. Nothing deletes drafts, including submitted, failed, and expired ones. The store is `data/intake.db` unless run with `--db :memory:`; only the demo reset clears it. |
| Held notes (`pending` table) | The parsed note while the worker confirms the HMIS search | Until the worker confirms; forever if they never do |
| Email copies | Notes, replies, review emails | Deleted at submission (retention 0 hours). Drafts that never reach submission keep their emails forever. Receipts are kept but hold only IDs. |
| Audit | Times, workers, versions, field names, HMIS IDs; never note text | Forever |

**Decisions (2026-11-02):**
1. **Retention mode** (`config/settings.yaml`). In production mode each submitted draft is reduced to a stub of IDs, states, versions, and times at submission. Demo mode is the stated exception: it keeps the synthetic values so the staged record and submitted record screens still work.
2. **Seven-day deletion.** Held notes and drafts that never reach submission, with their emails, are deleted after 7 days (a config value). This lines up with the supervisor queue: a draft goes to the queue at 48 hours and is deleted at 7 days. The audit record, which has no note text, stays.
3. **Own-records check over open drafts only.** The lookup covers clients already in HMIS but cannot see drafts still open, so two workers drafting the same neighbor the same day would both pass. Each open new-client draft keeps only an HMAC-SHA256 of the normalized first name, last name, and date of birth; new drafts are compared against these hashes; the hash is deleted at entry, expiry, or failure. Names and dates of birth are never kept for matching.
4. **Hash key.** From the environment (`INTAKE_MATCH_KEY` in `.env`, never the repo). Required in production mode; in demo mode, when none is set, a random key is generated in memory for that run. `.env.example` gets only a placeholder.

## Risks
- **Worker picks the wrong client.** Mitigation: candidates show client ID, quadrant, and last contact; SAME CLIENT must name an ID from the list; the receipt names the client.
- **Over-trusting "different person".** Mitigation: a reason is required and audited; the refinement in decision 5 adds a supervisor for matching digits.
- **Edits after save may not exist in HMIS.** Mitigation: corrections after entry are [TBC]; they can fall back to a new case note that says it corrects an earlier one.

## Known limitations (as built)
- **Production retention blocks corrections after entry.** In production mode a submitted draft is reduced to a stub of IDs, states, versions, and times, so its fields and note are gone. A reply to an update's receipt is then refused with "correct it in HMIS" instead of becoming a correction draft. Demo mode keeps the values, so corrections work there.
- **A failed entry deletes the match hash.** The open-draft hash is deleted at entry, expiry, or failure, as decided. A draft whose entry failed and is then retried with RETRY is therefore no longer compared against other open drafts, and a second draft for the same neighbor opened after the failure is not flagged against it. The HMIS lookup and the possible-duplicate backstop still apply once the first client is in HMIS.

## Decisions taken (answers of 2026-11-02)
Service types are a placeholder list marked [TBC] until Horizon House and CHIP confirm. Only the original author may correct an entry, with a "corrects earlier note" entry as the fallback if HMIS forbids edits. Demographics that differ on SAME CLIENT are shown as "update in HMIS yourself" and never written. The match rule, retention mode, seven-day deletion, own-records hash check, and hash key are as described above.

## Open questions [TBC]
0. Does the real HMIS have a place for a quadrant (or another location) on a contact or service? The prototype enters it on both. Ask: CHIP.
1. The real case note and service fields, and the Contact Service options. Ask: Hannah, Horizon House, CHIP.
2. Can saved case notes and services be edited through an interface? Ask: CHIP.
3. Does the real HMIS allow a confirmed-distinct override for a possible duplicate? Ask: CHIP.
4. Should production block a DIFFERENT PERSON decision on matching SSN digits until a supervisor approves? Ask: Goodwill.
5. The production retention limit for email copies and stubs. Ask: Dennis, Goodwill IT.
