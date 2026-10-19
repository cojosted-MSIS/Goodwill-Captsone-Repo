# Synthetic sample emails

All names, dates, and numbers are made up. Do not add real neighbor data.

| File | What it tests |
|---|---|
| 01_clean_new_client | Near-clean parse. Length of stay is not stated and "around March 2025" is not a full date, so both are flagged and asked for |
| 01b_clean_new_client_complete | 01 with the length of stay and a full start date added. Clean parse, confirmed on the first reply (mockup Scenario A demo) |
| 02_hedged_referral_trap | A hedged refusal ("not tonight, maybe next week") that a parser may record as accepted, a date range ("Monday or Tuesday"), and a declined SSN (mockup Scenario B) |
| 03_search_not_stated | Worker did not say they searched HMIS, so the system must ask |
| 04_unknown_dob_and_street_name | Unknown birth date, name quality, "doesn't remember" fields, no invented values |
| 05_privacy_traps | Precise location (quadrant only), third party dropped, full SSN reduced to last four, income not drafted, consent shown as pending |
