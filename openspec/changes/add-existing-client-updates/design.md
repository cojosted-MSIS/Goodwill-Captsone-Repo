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

### 4. Corrections after entry [TBC: the real HMIS may not allow edits after save]
The worker replies to the receipt with the change, naming the entry if the receipt lists more than one ("Service HMIS-S-000014: 45 minutes, not 30"). The system creates a new draft version that references the entry ID, sends a review, needs CONFIRM, and calls the update operation. Only the author of the original entry can correct it [TBC: supervisors]. The audit keeps the entry ID and changed field names, never values or note text. Entries not made by this system are refused with "correct it in HMIS". Corrections before entry work as today.

### 5. Same name and date of birth
- **Main check:** the read-only lookup, run on every new-client draft with a full name and full date of birth. A draft without a full date of birth cannot be checked; its review says so and relies on the backstop.
- **Match:** first and last name without regard to case, spacing, or punctuation, and the exact date of birth.
- **Grade (your proposed rule, kept):** a matching or missing second identifier (last four SSN digits) on either side is a hard stop; a different one is a warning. Both need SAME CLIENT <ID> or DIFFERENT PERSON with a reason.
- **Suggested refinement (for your decision):** treat "matching" and "missing" differently, because a match on name, date of birth, and SSN digits is much stronger evidence than a missing digit. With matching digits, the verification email recommends SAME CLIENT, and DIFFERENT PERSON also needs a supervisor's reply [TBC]. With missing digits, keep the hard stop as proposed and ask the worker to get the digits from the neighbor if they can. With different digits, keep the warning.
- **Limits of the rule:** nicknames, misspellings, hyphenated surnames, and swapped day and month are not matched. The lookup must not suggest similar names (change 1), so these fall to the backstop and to the worker's own HMIS search.
- **Backstop:** the mock's possible-duplicate rejection stays and gives no details. It accepts `confirmed_distinct` only with a non-empty reason. Whether the real HMIS allows an override is [TBC with CHIP].
- **SAME CLIENT:** the new-client fields are not entered. The note's case note and service entry become an update draft. Demographics in the note that differ from HMIS are shown to the worker but never written [TBC: whether to flag them].

### 6. Screens and demo
- **Phone:** "Update a neighbor" compose; "Ask HMIS" compose with the three query types; query replies shown as emails; the verification email with a SAME CLIENT button per candidate and DIFFERENT PERSON with a reason field (no CONFIRM button); a receipt listing the case note and service IDs; a "correct this entry" reply from the receipt.
- **Staff:** the audit trail shows queries (type, parameters, row count) and verification decisions (candidates, grade, decision, reason).
- **Demo seed and scenarios:** a seeded pair sharing a name and date of birth with matching digits, and another with different digits. Scenario C: after Scenario A, an "Update:" note for Pat Example with a case note and service. Scenario D: a new-client note matching the seeded pair, run once to SAME CLIENT and once to DIFFERENT PERSON with a reason. Scenario E: a briefing for SW, then "has <neighbor>'s ID come in". The reset clears everything and reseeds.

## Privacy: what the staging store keeps
**Today (measured from the code):**

| Data | Kept | For how long |
|---|---|---|
| Drafts (`drafts` table) | Every field value, including first and last name, date of birth, SSN last four digits, and answers; the cleaned source sentences; the case note; the parser's verified version 1 output with its sentences; HMIS IDs | Forever. Nothing deletes drafts, including submitted, failed, and expired ones. The store is `data/intake.db` unless run with `--db :memory:`; only the demo reset clears it. |
| Held notes (`pending` table) | The parsed note while the worker confirms the HMIS search | Until the worker confirms; forever if they never do |
| Email copies | Notes, replies, review emails | Deleted at submission (retention 0 hours). Drafts that never reach submission keep their emails forever. Receipts are kept but hold only IDs. |
| Audit | Times, workers, versions, field names, HMIS IDs; never note text | Forever |

**Proposals (for decision):**
1. After submission, reduce each draft to a stub (ID, worker, state, versions, HMIS IDs, times, parser and model) and delete its field values, sentences, case note, and parser output [TBC: retention period, proposed at submission].
2. Delete held notes and the emails of drafts that never reach submission after a set period (proposed 7 days after expiry or failure) [TBC with Goodwill IT].
3. **Do we still need a check against our own records?** The lookup covers clients already in HMIS. It cannot see drafts still in review or failed, so two workers drafting the same neighbor the same day would both pass. Recommendation: keep a narrow check over open drafts only, using a keyed hash (HMAC-SHA256 with a secret from `.env`) of the normalized first name, last name, and date of birth, stored only while the draft is open and deleted at entry, expiry, or failure. Names and dates of birth are never kept for matching. **Flagged for your decision:** the alternative is no own-records check, relying on the lookup and the backstop.

## Risks
- **Worker picks the wrong client.** Mitigation: candidates show client ID, quadrant, and last contact; SAME CLIENT must name an ID from the list; the receipt names the client.
- **Over-trusting "different person".** Mitigation: a reason is required and audited; the refinement in decision 5 adds a supervisor for matching digits.
- **Edits after save may not exist in HMIS.** Mitigation: corrections after entry are [TBC]; they can fall back to a new case note that says it corrects an earlier one.

## Open questions [TBC]
1. The real case note and service fields, and the Contact Service options. Ask: Hannah, Horizon House, CHIP.
2. Can saved case notes and services be edited through an interface? Ask: CHIP.
3. Does the real HMIS allow a confirmed-distinct override for a possible duplicate? Ask: CHIP.
4. The match rule and the supervisor refinement for matching SSN digits. Ask: the team, Hannah.
5. Retention for drafts, held notes, and unsubmitted emails. Ask: Dennis, Goodwill IT.
6. The own-records check with a keyed hash, or none. Ask: the team.
7. Can a supervisor correct another worker's entry? Ask: Hannah.
8. Should differing demographics found by SAME CLIENT be flagged for the worker to fix in HMIS? Ask: Hannah.
