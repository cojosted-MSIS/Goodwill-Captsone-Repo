"""Checks run on every REALLMS reply (REALLMS_GUIDE.md section 5), then conversion to a ParseResult.

response_format guarantees the shape. These checks look at the content:
- finish_reason is "stop", the content is JSON, and it matches the schema (a backstop);
- every quote and as-written value is an exact substring of the note;
- every definite answer has a quote, and the quote agrees with the label (hint words,
  refusal and don't-know words, negation for yes or no, numbers for counts);
- the full sentence a quote came from has no hedge or hearsay words;
- a length of stay is kept only when its quote states how long, and the duration matches the label.
Problem messages name fields only. They never include note text.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import jsonschema

from app.config_loader import AppConfig
from app.dates import parse_written_date
from app.email_message import IntakeEmail

from .interface import Confidence, ParsedField, ParseResult
from .llm_v2 import AS_WRITTEN, ENUM_FIELDS, LIST_FIELDS, MULTI_FIELDS, TEXT_FIELDS, UNKNOWN
from .shared import split_sentences

# Answers that already express doubt, so a hedged sentence is expected.
HEDGE_EXEMPT = {"client_doesnt_know", "approximate_or_partial_dob_reported"}


def has_word(text: str, words: list[str]) -> set[str]:
    """Words found at a word start (so "Carla" does not count as "car")."""
    lower = text.lower()
    return {w for w in words if re.search(rf"(?<![a-z]){re.escape(w.lower())}", lower)}


def source_sentence(note: str, quote: str, config: AppConfig) -> str:
    for sentence in split_sentences(note, config):
        if quote in sentence:
            return sentence
    return quote  # the quote spans sentences: fall back to the quote itself


def _number_bucket(quote: str, bucket: str, config: AppConfig) -> str | None:
    match = re.search(r"\b(\d+)\b", quote)
    if not match:
        return None
    return _bucket(int(match.group(1)), bucket, config)


def _bucket(number: int, bucket: str, config: AppConfig) -> str | None:
    for b in config.mappings.buckets[bucket]:
        if b.max is None or number <= b.max:
            return b.value
    return None


def stay_days(note: str, quote: str, config: AppConfig) -> list[int]:
    """Durations of a stay stated in a length of stay quote, in days.

    A sentence about the past three years counts homelessness in that window, so its
    durations are not a stay. "last night" says when, not how long, so it is not one either."""
    rule = config.mappings.llm_checks.length_of_stay
    if re.search(rule.lookback, source_sentence(note, quote, config), re.IGNORECASE):
        return []
    days = []
    for match in re.finditer(rule.duration, quote, re.IGNORECASE):
        raw = match.group("number").lower()
        number = int(raw) if raw.isdigit() else rule.number_words.get(raw)
        if number is not None:
            days.append(number * rule.unit_days[match.group("unit").lower()])
    return days


def stay_stated(obj: dict, note: str, config: AppConfig) -> bool:
    """A length of stay answer the note supports: unknown, a refusal or don't know, or a stated duration."""
    if obj["length_of_stay"] in (UNKNOWN, "client_doesnt_know", "client_refused"):
        return True
    return bool(stay_days(note, obj[ENUM_FIELDS["length_of_stay"]], config))


def check_reply(content: str | None, finish_reason: str | None, note: str, schema: dict, config: AppConfig,
                reference: date | None = None) -> tuple[dict | None, list[str]]:
    """The parsed reply and a list of problems (empty when it passed)."""
    if finish_reason != "stop":
        return None, [f"the reply was cut off (finish_reason {finish_reason!r}); answer more briefly"]
    try:
        obj = json.loads(content or "")
        jsonschema.validate(obj, schema)
    except json.JSONDecodeError as exc:
        return None, [f"the reply was not valid JSON ({exc.msg})"]
    except jsonschema.ValidationError as exc:
        return None, [f"the reply did not match the schema at {'/'.join(map(str, exc.absolute_path)) or 'top level'}: {exc.validator}"]

    checks = config.mappings.llm_checks
    problems: list[str] = []

    def quote_ok(name: str, quote: str, definite: bool) -> bool:
        if quote and quote not in note:
            problems.append(f"{name}: the quote is not copied exactly from the note")
            return False
        if definite and not quote.strip():
            problems.append(f"{name}: an answer needs an evidence quote")
            return False
        return True

    def hedged(name: str, quote: str, label: str) -> None:
        if label in HEDGE_EXEMPT:
            return
        if has_word(source_sentence(note, quote, config), checks.hedges):
            problems.append(f"{name}: the evidence is hedged or hearsay, so the answer must be unknown")

    def answer_words(name: str, quote: str, label: str) -> None:
        words = checks.answer_words.get(label)
        if words and not has_word(quote, words):
            problems.append(f"{name}: {label} needs a quote that says so")

    # hmis search
    search, search_quote = obj["hmis_search_stated"], obj["hmis_search_quote"]
    if quote_ok("hmis_search_stated", search_quote, search != UNKNOWN) and search != UNKNOWN:
        if "hmis" not in search_quote.lower():
            problems.append("hmis_search_stated: the quote does not mention HMIS")

    # contact date phrase and as-written dates
    for key in ("contact_date_phrase", *AS_WRITTEN.values()):
        if obj[key] and obj[key] not in note:
            problems.append(f"{key}: not copied exactly from the note")

    # enum fields
    for field, quote_key in ENUM_FIELDS.items():
        label, quote = obj[field], obj[quote_key]
        definite = label != UNKNOWN
        if not quote_ok(field, quote, definite) or not definite:
            continue
        hedged(field, quote, label)
        answer_words(field, quote, label)
        if field.endswith("living_situation"):
            hinted = {cat for cat, words in checks.living_hints.items() if has_word(quote, words)}
            if hinted and label not in hinted:
                problems.append(f"{field}: the quote suggests {sorted(hinted)} but the label is {label}")
        if field in ("disabling_condition", "veteran_status") and label in ("yes", "no"):
            negated = bool(has_word(quote, checks.negation_words)) or "n't" in quote.lower()
            if (label == "no") != negated:
                problems.append(f"{field}: the quote does not agree with {label!r}")
        if field in checks.label_words and label in checks.label_words[field]:
            if not has_word(quote, checks.label_words[field][label]):
                problems.append(f"{field}: the quote does not say {label}")
        if field == "ethnicity" and label == "hispanic_latino":
            if has_word(quote, checks.label_words["ethnicity"].get("non_hispanic_latino", [])):
                problems.append("ethnicity: the quote says not Hispanic")
        if field == "times_homeless_past_three_years" and label not in ("client_doesnt_know", "client_refused"):
            bucket = _number_bucket(quote, "times_homeless", config)
            if bucket and bucket != label:
                problems.append(f"{field}: the number in the quote does not match {label}")
        if field == "months_homeless_past_three_years" and label not in ("client_doesnt_know", "client_refused"):
            bucket = _number_bucket(quote, "months_homeless", config)
            if bucket and bucket != label:
                problems.append(f"{field}: the number in the quote does not match {label}")
        if field == "length_of_stay" and label not in ("client_doesnt_know", "client_refused"):
            buckets = {_bucket(d, "length_of_stay_days", config) for d in stay_days(note, quote, config)}
            if buckets and label not in buckets:
                problems.append(f"{field}: the duration in the quote does not match {label}")
        if field == "project_id":
            project = next(p for p in config.programs.projects.values() if p.project_id == label)
            if not has_word(quote, project.aliases):
                problems.append("project_id: the quote does not name the program")

    # date of birth agrees with its quality
    dob_quality, dob_written = obj["dob_quality"], obj["date_of_birth_as_written"]
    if dob_quality == "full_dob_reported" and not dob_written:
        problems.append("date_of_birth_as_written: a full DOB needs the date as written")
    elif dob_quality == "full_dob_reported" and parse_written_date(dob_written, reference or date.today()) is None:
        problems.append("dob_quality: the date as written is not a full date, so the DOB is approximate or partial")
    if dob_quality == UNKNOWN and dob_written:
        problems.append("dob_quality: a date of birth is written but the quality is unknown")

    # multi-select fields
    for field, quote_key in MULTI_FIELDS.items():
        labels = [v for v in obj[field] if v != UNKNOWN]
        quote = obj[quote_key]
        if not quote_ok(field, quote, bool(labels)) or not labels:
            continue
        hedged(field, quote, "")
        for label in labels:
            words = checks.label_words.get(field, {}).get(label)
            if words and not has_word(quote, words):
                problems.append(f"{field}: the quote does not say {label}")

    # text fields
    for field, quote_key in TEXT_FIELDS.items():
        value, quote = obj[field].strip(), obj[quote_key]
        if not quote_ok(field, quote, bool(value)) or not value:
            continue
        hedged(field, quote, "")
        if value not in quote:
            problems.append(f"{field}: the value does not appear in its quote")
    if obj["ssn_last4"].strip() and not re.fullmatch(r"\d{4}", obj["ssn_last4"].strip()):
        problems.append("ssn_last4: give exactly the last four digits")
    if obj["ce_region"].strip() and not obj["ce_region"].strip().isdigit():
        problems.append("ce_region: give the region number only")

    # lists
    for field, quote_key in LIST_FIELDS.items():
        items = [i for i in obj[field] if i.strip()]
        quote_ok(field, obj[quote_key], bool(items))

    if not obj["case_note"].strip():
        problems.append("case_note: must not be empty")
    return obj, problems


def to_result(obj: dict, email: IntakeEmail, config: AppConfig, *, parser: str, model: str, prompt_version: str) -> ParseResult:
    """Convert a reply that passed every check."""
    note = email.body
    hedge = config.mappings.hedge_words

    def parsed(value: Any, quote: str) -> ParsedField:
        sentence = source_sentence(note, quote, config)
        confidence: Confidence = "medium" if has_word(sentence, hedge) else "high"
        return ParsedField(value=value, source=sentence, confidence=confidence)

    fields: dict[str, ParsedField] = {}
    flags: list[str] = []
    for field, quote_key in ENUM_FIELDS.items():
        if obj[field] != UNKNOWN:
            fields[field] = parsed(obj[field], obj[quote_key])
    if not stay_stated(obj, note, config):
        fields.pop("length_of_stay")
        flags.append("length_of_stay_unstated: Length of stay: the note does not say how long the neighbor "
                     "stayed there, so it was left blank. Ask and add it.")
    for field, quote_key in MULTI_FIELDS.items():
        labels = [v for v in obj[field] if v != UNKNOWN]
        if labels:
            fields[field] = parsed(labels, obj[quote_key])
    for field, quote_key in TEXT_FIELDS.items():
        if obj[field].strip():
            fields[field] = parsed(obj[field].strip(), obj[quote_key])
    reference = email.sent_at.date()
    for field, key in AS_WRITTEN.items():
        written = obj[key]
        value = parse_written_date(written, reference) if written else None
        if value is not None:  # a partial date ("around March 2025") stays blank
            fields[field] = parsed(value.isoformat(), written)
    for field, quote_key in LIST_FIELDS.items():
        items = [i.strip() for i in obj[field] if i.strip()]
        if items:
            fields[field] = parsed(items, obj[quote_key])

    search = None
    if obj["hmis_search_stated"] == "searched_no_match":
        search = parsed(True, obj["hmis_search_quote"])
    contact = parsed(obj["contact_date_phrase"], obj["contact_date_phrase"]) if obj["contact_date_phrase"] else None
    return ParseResult(
        parser=parser,
        model=model,
        prompt_version=prompt_version,
        fields=fields,
        hmis_search_stated=search,
        contact_date_phrase=contact,
        case_note=obj["case_note"].strip(),
        flags=flags,
    )
