"""Build the LLM prompt from configuration. Only the email body and sent date are sent."""

from __future__ import annotations

from app.config_loader import AppConfig, FieldDef
from app.email_message import IntakeEmail

RULES = """\
You extract fields for a homeless street outreach intake from an outreach worker's note.
Follow these rules exactly.

1. Use only what the note states. Never infer, guess, or add a value. If a value is not stated, set it to null.
2. Answers about the neighbor (name, birth date, Social Security number, race, ethnicity, gender, disabling condition, veteran status, living situation, homeless history) must be what the note says the neighbor reported. The worker's own description is not an answer: "a man" does not give a gender.
3. Use "client_doesnt_know" or "client_refused" only when the note says the neighbor did not know or refused. Never use "data_not_collected".
4. Location: record only the quadrant in service_area. Never copy camp names, streets, intersections, or landmarks into any value or the case note.
5. Never record anything about a person other than the neighbor (friends, relatives, anyone else present), in any value or in the case note.
6. Social Security number: put only the last four digits in ssn_last4. Never return the full number anywhere.
7. Dates: use YYYY-MM-DD only when the note gives the day, month, and year. If it gives only a month or a year, use null. Never invent a day.
8. Use confidence "medium" when the wording is hedged ("about", "around", "maybe") and "low" when you are unsure. Otherwise "high".
9. A hedged refusal such as "not tonight, maybe next week" is a decline, not an acceptance.
10. Do not record income, benefits, insurance, VI-SPDAT, diversion, domestic violence, consent, or signatures as fields. Consent is completed later in HMIS even if the note says the neighbor agreed or signed.
11. For every value that is not null, "source" must be the sentence from the note that the value came from, copied exactly.
12. Reply with one JSON object only. No markdown, no code fences, no explanation."""

CASE_NOTE_RULES = """\
case_note: two to five short plain sentences built only from statements in the note. Say what happened and what was provided or offered, and any follow-up. Leave out the birth date, Social Security number, health details, precise locations, and anyone other than the neighbor. Refer to the neighbor by first name and last initial."""

SHAPE = """\
Reply with exactly this JSON shape:
{
  "hmis_search_stated": {"value": true or false, "source": "sentence or null", "confidence": "high"},
  "fields": {
    "<field name>": {"value": <value or null>, "source": "<sentence or null>", "confidence": "high" | "medium" | "low" | null}
  },
  "case_note": "<text>",
  "notices": ["<notice id>", ...]
}
Include every field name from the field list in "fields", using {"value": null} for fields the note does not state.
hmis_search_stated is true only when the note says the worker searched HMIS and found no existing record."""


def _describe(name: str, f: FieldDef, config: AppConfig) -> str:
    if name == "project_id":
        options = "; ".join(f'"{p.project_id}" ({p.label}, the note may say {", ".join(p.aliases)})'
                            for p in config.programs.projects.values())
        return f"- {name}: {f.label}. One of: {options}"
    if name == "ce_region":
        return f"- {name}: {f.label}. The region number as a string, for example \"7\""
    if f.type in ("enum", "multi_enum"):
        ids = ", ".join(f'"{o.id}"' for o in config.fields.enums[f.enum])
        kind = f"a list of up to {f.max_items or 'any number of'} values from" if f.type == "multi_enum" else "one of"
        return f"- {name}: {f.label}. {kind}: {ids}"
    kinds = {
        "date": "a date as YYYY-MM-DD",
        "ssn_last4": "exactly four digits as a string",
        "list": "a list of short strings, as stated",
        "boolean": "true or false",
        "string": "text, as stated",
    }
    return f"- {name}: {f.label}. {kinds[f.type]}"


def system_prompt(config: AppConfig) -> str:
    fields = "\n".join(_describe(n, f, config) for n, f in config.parsable_fields().items())
    notices = "\n".join(f'- "{nid}": {n.label}' for nid, n in config.mappings.shared.notices.items())
    return (
        f"{RULES}\n\nField list:\n{fields}\n\n{CASE_NOTE_RULES}\n\n"
        f"notices: zero or more of these ids, when they apply:\n{notices}\n\n{SHAPE}"
    )


def user_prompt(email: IntakeEmail) -> str:
    sent = email.sent_at.strftime("%Y-%m-%d (%A)")
    return f"Email sent: {sent}\n\nWorker's note:\n{email.body}"


def build_messages(email: IntakeEmail, config: AppConfig) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt(config)},
        {"role": "user", "content": user_prompt(email)},
    ]


def retry_message(problems: list[str]) -> str:
    listed = "\n".join(f"- {p}" for p in problems)
    return (
        "Your reply could not be used because of these problems:\n"
        f"{listed}\n"
        "Fix them and reply again with only the corrected JSON object. Follow every rule."
    )
