"""Rules applied to every parser's output, so the stub and the LLM behave the same.

- A full Social Security number is reduced to its last four digits, checked against the
  known invalid patterns, and masked in every source sentence and in the case note.
- Name quality follows the configured trigger phrases.
- The HMIS search statement and the review notices are detected from the email text.
"""

from __future__ import annotations

import re

from app.config_loader import AppConfig
from app.email_message import IntakeEmail

from .interface import ParsedField, ParseResult


def split_sentences(text: str, config: AppConfig) -> list[str]:
    return [s.strip() for s in re.split(config.mappings.sentence_split, text.strip()) if s.strip()]


def mask_ssns(text: str, config: AppConfig) -> str:
    def mask(match: re.Match) -> str:
        return "***-**-" + re.sub(r"\D", "", match.group(0))[-4:]

    return re.sub(config.mappings.shared.ssn.any_full_number, mask, text)


def first_sentence_matching(sentences: list[str], pattern: str, flags: int = re.IGNORECASE) -> tuple[str, re.Match] | None:
    for sentence in sentences:
        match = re.search(pattern, sentence, flags)
        if match:
            return sentence, match
    return None


def known_invalid_ssn_label(number: str, config: AppConfig) -> str | None:
    for rule in config.validation.ssn.invalid_full_number_patterns:
        if re.search(rule.pattern, number):
            return rule.label
    return None


def scrub(text: str, config: AppConfig) -> tuple[str, list[str]]:
    """Replace precise locations and third-party details. Returns the text and the notices still detected."""
    leftover = []
    for notice_id, notice in config.mappings.shared.notices.items():
        if not notice.scrub:
            continue
        for pattern in notice.scrub:
            text = re.sub(pattern, notice.replacement, text, flags=re.IGNORECASE)
        cleaned = text.replace(notice.replacement, "")
        if any(re.search(p, cleaned, re.IGNORECASE) for p in notice.patterns):
            leftover.append(notice_id)
    return text, leftover


def clean_source(source: str, config: AppConfig) -> str:
    text, leftover = scrub(mask_ssns(source, config), config)
    if leftover:
        notices = config.mappings.shared.notices
        return " ".join(notices[n].replacement for n in leftover)
    return text


def finalize(result: ParseResult, email: IntakeEmail, config: AppConfig) -> ParseResult:
    """Apply the shared rules to a successful parse."""
    if not result.ok:
        return result
    shared = config.mappings.shared
    sentences = split_sentences(email.body, config)
    fields = dict(result.fields)
    flags = list(result.flags)

    # Social Security number
    found = first_sentence_matching(sentences, shared.ssn.full_number)
    if found:
        sentence, match = found
        digits = re.sub(r"\D", "", match.group("number"))
        fields["ssn_last4"] = ParsedField(value=digits[-4:], source=sentence, confidence="high")
        label = known_invalid_ssn_label(match.group("number"), config)
        if label:
            fields.pop("ssn_quality", None)
            flags.append(f"ssn_known_invalid_pattern: The Social Security number in the note is {label}. "
                         "Check it with the neighbor and choose the data quality yourself.")
        elif "ssn_quality" not in fields:
            fields["ssn_quality"] = ParsedField(value=shared.ssn.full_number_quality, source=sentence, confidence="high")

    # Name quality
    nq = shared.name_quality
    trigger = first_sentence_matching(sentences, "|".join(rf"\b{re.escape(t)}\b" for t in nq.partial_triggers))
    if trigger:
        fields["name_quality"] = ParsedField(value=nq.partial_value, source=trigger[0], confidence="high")
    elif "first_name" in fields and "last_name" in fields:
        fields["name_quality"] = ParsedField(value=nq.full_value, source=fields["last_name"].source, confidence="high")

    # HMIS search statement
    hmis_search = result.hmis_search_stated
    if hmis_search is None or hmis_search.value is not True:
        stated = next((s for p in shared.hmis_search if (s := first_sentence_matching(sentences, p))), None)
        if stated:
            hmis_search = ParsedField(value=True, source=stated[0], confidence="high")

    # Notices
    notices = list(result.notices)
    for notice_id, notice in shared.notices.items():
        if notice_id not in notices and any(first_sentence_matching(sentences, p) for p in notice.patterns):
            notices.append(notice_id)

    # Clean every stored source sentence and the case note
    fields = {name: f.model_copy(update={"source": clean_source(f.source, config)}) for name, f in fields.items()}
    if hmis_search is not None:
        hmis_search = hmis_search.model_copy(update={"source": clean_source(hmis_search.source, config)})
    case_note = result.case_note
    if case_note:
        case_note, leftover = scrub(mask_ssns(case_note, config), config)
        flags += [f"case_note_check: The case note may still contain something from '{n}'. Check the wording."
                  for n in leftover]

    return result.model_copy(
        update={
            "fields": fields,
            "flags": list(dict.fromkeys(flags)),
            "hmis_search_stated": hmis_search,
            "notices": notices,
            "case_note": case_note,
        }
    )
