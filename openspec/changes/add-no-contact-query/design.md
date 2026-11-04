# Design: No-contact watchlist query

## Context
`add-hmis-readonly-queries` gives workers three fixed read-only queries by email. This change adds a fourth, the no-contact watchlist, through the same path: "Query:" email, parser picks a type and copies parameters, code validates, a fixed parameterized read over allowlisted views, a minimal reply, an audit record without the returned values.

## Decisions

### 1. One more fixed query type, `no_contact`
- **Question:** for example "Query: who is coming up on 60 days with no contact", optionally naming a quadrant ("in the SE quadrant").
- **Parameters:** an optional quadrant (nw, ne, sw, se). Nothing else is read from the email, including any number of days: the thresholds are config values, so "who is coming up on 30 days" still answers for the configured 60 [assumption].
- **Parser:** the live prompt adds `no_contact` to the query type enum (prompt version `query-v2`); the rule-based stub matches phrases in `config/mappings.yaml` (`stub_query.no_contact_words`) before the other types. Neither writes SQL.

### 2. Two groups from two config values
`config/settings.yaml`, `hmis_queries`: `no_contact_days: 60` and `no_contact_warning_days: 14`.
- **Approaching 60 days:** 46 to 60 days since the last contact (60 - 14 to 60, both ends included).
- **Past 60 days:** more than 60 days.
- Days are whole days from the last contact date to today's date. A neighbor with fewer than 46 days is not listed.

### 3. Who is counted [TBC with Horizon House: what counts as a contact]
- Only neighbors with an active enrollment (an enrollment with no exit date, `v_enrollments`). Exited neighbors are never listed.
- A contact is any record in `v_contacts`: seeded contacts, the Coordinated Entry contact of a new client entered here, and every service entered here. Whether case notes, phone calls, or attempted contacts count is [TBC with Horizon House].
- A neighbor with no contact recorded at all is not listed (there is no date to count from) [assumption].
- With a quadrant, only neighbors whose last contact was in that quadrant are listed.

### 4. The reply
One line per neighbor, minimal fields only: client ID, first name and last initial, last contact date, days since the last contact, the quadrant of the last contact, and open items (an ID document pending, a housing assessment scheduled). No SSN, date of birth, or case note text. Sorted most overdue first, so "Past 60 days" comes before "Approaching 60 days". The existing row limit (25) applies to the whole reply, with the "N more were not shown" line; the group headings give the full counts. Records the worker's project cannot see are never counted or listed, exactly as if they did not exist.

### 5. Fixed queries
Two fixed, parameterized reads in `app/hmis_reader.py` (a count by group and the rows), over `v_clients`, `v_contacts`, and `v_enrollments`, with the date cutoffs, the optional quadrant, the project, and the row limit bound as parameters. No new view is needed.

### 6. Audit
Like the other queries: query type, quadrant (or none), and the row count, never the returned values.

### 7. Seed dates relative to the demo day
Every seed date is written as days before the day the mock HMIS starts or is reset (`days_ago`, `entered_days_ago`, `exited_days_ago`), so days since the last contact stay the same whenever the demo runs. Dates of birth are the only fixed dates in the seed, and they do not drift. New synthetic neighbors (SE and NE quadrants, active enrollments) have their last contact 20, 52, 58, 60, 61, and 90 days before the demo day; one exited neighbor at 55 days and one record hidden from the demo project at 58 days show that neither is listed.

### 8. Screens and demo
The staff queries view names the new type "no-contact watchlist". The phone "Ask HMIS" hint lists four kinds of question. Demo Scenario E3 asks the question and shows the reply.

## Risks
- **A gap in contacts that is really a gap in data entry.** Mitigation: the reply says what counts as a contact is [TBC], and lists only the last recorded contact.
- **A long list.** Mitigation: the row limit and the optional quadrant.

## Open questions [TBC]
1. What counts as a contact (services, case notes, phone calls, attempts). Ask: Horizon House.
2. Whether 60 days and a 14-day warning are the right numbers, and whether exits after 60 days are a policy. Ask: Horizon House.
3. Archiving: the modified requirement lives in `add-hmis-readonly-queries`, which is not archived yet, so that change must be archived before this one.
