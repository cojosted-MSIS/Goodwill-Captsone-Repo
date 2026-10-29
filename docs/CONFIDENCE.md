# How confidence labels are produced

Every value in a draft carries a label: **High**, **Medium**, **Worker**, **Review**, or **n/a** (and **Low** exists but is never produced today). This document explains exactly where each label comes from, using the code as it is. All examples are synthetic.

## The short version

- **The model does not report confidence.** The response schema has no confidence field, and the model is never asked how sure it is. No label comes from the model, so there is no model confidence to calibrate.
- **High and Medium come from our own wording check.** A value is Medium when the sentence it came from contains a hedge word such as "about" or "around". Otherwise it is High.
- **Worker and Review come from where the value came from**, not from any measure of certainty: Worker means the worker supplied it in a reply; Review means the text was generated and the worker must check the wording.
- **The quote checks decide whether a value is accepted at all, not its label.** A value that fails them is never saved, so every saved value has passed them.
- **A label describes the wording of the note, not whether the value is correct.** A wrong value can be High. That is why every value is shown beside its source sentence and nothing is entered until the worker replies CONFIRM.

## Step by step

### 1. The model's part (live parser only)

The live parser (`parser/llm.py`) asks the model for a value and an exact quote for each field. Nothing in the request or the response schema mentions confidence. The model's answer feeds steps 2 and 3, and its own certainty is never used.

### 2. Acceptance checks: is the value saved at all?

Before any label is set, `parser/llm_checks.py` checks the reply (the full list is in `docs/PROMPTS.md`). The checks that matter here:

- **Quote match.** Every quote must be copied exactly from the note, and every definite answer needs one.
- **Quote agrees with the label.** For example, a quote saying "shelter" cannot back "place not meant for habitation", and "not a veteran" cannot back "yes".
- **Hedge and hearsay.** If the full sentence a quote comes from contains `might`, `maybe`, `thinks`, `possibly`, `probably`, `not sure`, `heard`, `supposedly`, `apparently`, `rumor`, `i think`, or `guess`, a definite answer fails. The exceptions are "client doesn't know" and "approximate or partial DOB reported", which already express doubt.

A reply that fails is retried once; if it fails again, the note goes to human review and nothing is saved. So these checks never produce a label. They decide whether a value exists.

The rule-based stub has no reply to check. It simply skips any sentence containing a hearsay word (`might`, `thinks`, `heard`, `supposedly`, `apparently`, `not sure`, `rumor`), so such a sentence fills nothing.

### 3. High or Medium: the hedge-word check

For a value that is saved, the label is set by looking for these hedge words (`hedge_words` in `config/mappings.yaml`):

> about, around, roughly, approximately, maybe, probably, i think

Matching ignores case. The stub matches whole words only. The live parser matches a hedge word wherever a word starts with it, so "thoroughly" does not count as "roughly", but "abouts" would count as "about".

| Parser | Where it looks | Label |
|---|---|---|
| Live parser (`parser/llm_checks.py`, `to_result`) | The whole sentence the quote comes from | Medium if any hedge word is in that sentence, otherwise High |
| Rule-based stub (`parser/rule_stub.py`) | The matched words plus the 12 characters before them | Medium if a hedge word is there, otherwise High (a rule in `config/mappings.yaml` may fix the label, but none does today) |
| Scripted demo parser | The stub's labels, plus the one scripted value | The scripted value is set to High on purpose |

Because "maybe", "probably" and "i think" are also on the hedge and hearsay list in step 2, a definite answer from the live parser whose sentence contains them never gets this far. In practice, live parser Medium values come from "about", "around", "roughly" and "approximately", or from the two doubt-expressing answers above.

### 4. Values set by our own code

| Value | Label | Code |
|---|---|---|
| SSN last four and SSN quality from a full nine-digit number, name quality, "data not collected" from "didn't ask", the HMIS search statement | High | `parser/shared.py` |
| Enrollment date and information date (from the stated contact date, or the email's sent date) | High | `app/workflow.py`, `_set_contact_date` |
| A value the worker supplied in a reply | Stored as High, shown as **Worker** | `app/workflow.py`, `_corrections` |
| The generated case note | No label, shown as **Review** | origin "generated" |
| Program defaults (for example the CE project) and fixed values (for example relationship to head of household) | No label, shown as **n/a** | `_apply_defaults` |

### 5. How the label is shown

The staged record and the staff screens (`app/review.py`, `staged_view`) show one label per field:

1. If the worker supplied the value: **Worker**.
2. Else if the text was generated (the case note): **Review**.
3. Else the stored label: **High** or **Medium** (or Low).
4. Else **n/a**.

### 6. What the labels change

- **Medium** is shown but not flagged. It does not block CONFIRM.
- **Low** would add the flag "the parser was not sure. Check it." (`config/validation.yaml`, `confidence.flag`). The label type allows Low, but no code path produces it today, so this flag never appears.
- **Review** marks the case note as generated: the review email and screens tell the worker to read it for wording, not just accuracy.
- What blocks CONFIRM is a missing required field or another blocking flag, never a confidence label.

## Examples

Real labels produced by the code. The first two groups come from running the demo scenarios with the default rule-based stub and the scripted demo parser. The live parser rows come from the live parser's conversion and checks run on a fixed reply in the test harness, not from a call to the service.

| Field | Value | Source sentence | Label | Why |
|---|---|---|---|---|
| Date of birth (stub, Scenario A) | 03/04/1975 | "Met Pat Example, DOB 3/4/1975, SW quadrant around 10:15am." | High | "around" is not within 12 characters before the match |
| Length of stay (stub, Scenario A) | One year or longer | "Has been staying outside for over a year." | High | No hedge word |
| Times homeless (stub, Scenario A) | Three times | "Been on the street about 3 times in the last 3 years, around 14 months total." | Medium | "about" just before "3 times" |
| Months homeless (stub, Scenario A) | More than 12 months | same sentence | Medium | "around" just before "14 months" |
| Length of stay (stub, Scenario B) | One month to under 90 days | "Has been staying outside for about a month." | Medium | "about" in the match |
| Times homeless (stub, Scenario B) | One time | "First time on the street in the last 3 years, about 1 month total." | High | "about" is not near "First time" |
| Current living situation (scripted, Scenario B v1) | Emergency shelter | "Offered her a bed at the women's shelter, she said not tonight, maybe next week." | High | Set by the script on purpose; the sentence even says "maybe". A wrong value can be High. |
| Current living situation (Scenario B v2) | Place not meant for habitation | "Current living situation: staying outside, she declined the shelter." (worker's reply) | Worker | Supplied by the worker |
| Veteran status (Scenario B v2) | No | "Not a veteran." (worker's reply) | Worker | Supplied by the worker |
| Enrollment date (both) | The email's sent date | (email date) | High | Set by the workflow |
| Coordinated Entry project (both) | PRJ-CE-R7-DEMO | (program default) | n/a | Configuration, not the note |
| Case note (both) | Generated text | (generated) | Review | Generated; the worker checks the wording |
| Length of stay (live parser) | One month to under 90 days | "Has been staying outside for about a month." | Medium | "about" in the sentence |
| First name, date of birth, quadrant (live parser) | Pat, 03/04/1975, SW | "Met Pat Example, DOB 3/4/1975, SW quadrant around 10:15am." | Medium | "around" anywhere in the sentence lowers every value from it |
| Veteran status (live parser) | Yes | "She might be a veteran, maybe." | Not saved | Fails the hedge check; retried, then sent to human review |

## Limits to keep in mind

- **Wording, not truth.** The label measures whether the note's wording hedges, not whether the value is right. The scripted Scenario B error is High. The known wrong-person risk in the README (a correct-looking quote about a different person) would also be High.
- **The live parser is coarse.** It checks the whole sentence, so a time like "around 10:15am" turns a plainly stated name and date of birth into Medium. The stub is narrower but only knows its own phrase rules.
- **Fixed word lists.** Hedges the lists do not include ("roughly" is there, "like" and "or so" are not) leave a value High. The lists are in `config/mappings.yaml` and can be changed without code changes.
- **No Low.** Nothing produces Low today, so the low-confidence flag never fires.
- **Not calibrated.** Because the labels are rule-based, there is no probability behind them and no evaluation of how often High values are right. The model evaluation (`scripts/eval_parser.py`) measures correct answers and wrong answers that passed the checks, not the labels.

If production needs a calibrated confidence, it would have to be designed and measured separately. The worker's review and CONFIRM remain the control either way.
