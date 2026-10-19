"""Rule-based stub parser. Deterministic, driven by config/mappings.yaml, used in tests."""

from __future__ import annotations

import re
from datetime import date

from app.config_loader import AppConfig, SetSpec
from app.email_message import IntakeEmail

from .interface import Confidence, ParsedField, ParseResult
from .shared import finalize, first_sentence_matching, split_sentences

HEDGE_WINDOW = 12  # characters before a match checked for hedge words


def _words(words: list[str]) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)


class RuleStubParser:
    name = "rule_stub"
    prompt_version = "rule_stub"

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._hedge = _words(config.mappings.hedge_words)
        self._hearsay = _words(config.mappings.stub_hearsay_words)

    def parse(self, email: IntakeEmail) -> ParseResult:
        config = self._config
        all_sentences = split_sentences(email.body, config)
        # Hearsay or a guess ("his friend thinks he might be...") fills nothing.
        sentences = [s for s in all_sentences if not self._hearsay.search(s)]
        fields: dict[str, ParsedField] = {}

        for rule in config.mappings.stub_rules:
            flags = 0 if rule.case_sensitive else re.IGNORECASE
            found = first_sentence_matching(sentences, rule.pattern, flags)
            if not found:
                continue
            sentence, match = found
            hedged = bool(self._hedge.search(sentence[max(0, match.start() - HEDGE_WINDOW): match.end()]))
            for name, spec in rule.sets.items():
                multi = config.fields.fields[name].type == "multi_enum"
                if name in fields and not multi:
                    continue
                value = self._value(spec, match)
                if value is None:
                    continue
                confidence: Confidence = spec.confidence or ("medium" if hedged else "high")
                if multi:
                    previous = fields.get(name)
                    values = list(previous.value) if previous else []
                    if value not in values:
                        values.append(value)
                    source = previous.source if previous else sentence
                    fields[name] = ParsedField(value=values, source=source, confidence=confidence)
                else:
                    fields[name] = ParsedField(value=value, source=sentence, confidence=confidence)

        project = self._project(sentences)
        if project:
            fields["project_id"] = project

        contact = None
        for pattern in config.mappings.stub_contact_date:
            if found := first_sentence_matching(sentences, pattern):
                contact = ParsedField(value=found[1].group("phrase"), source=found[0], confidence="high")
                break

        result = ParseResult(
            parser=self.name, prompt_version=self.prompt_version, fields=fields, contact_date_phrase=contact
        )
        result = finalize(result, email, config)
        return result.model_copy(update={"case_note": self._case_note(result.fields, sentences)})

    def regenerate_case_note(self, note: str, corrections: str, fields: dict[str, ParsedField]) -> str | None:
        sentences = split_sentences(note, self._config) + split_sentences(corrections, self._config)
        return self._case_note(fields, [s for s in sentences if not self._hearsay.search(s)])

    def _value(self, spec: SetSpec, match: re.Match):
        if spec.value is not None:
            return spec.value
        raw = match.group(spec.group)
        if raw is None:
            return None
        if spec.map:
            return spec.map.get(raw.lower())
        convert = spec.convert or ""
        if convert == "date_mdy":
            month, day, year = (int(p) for p in raw.split("/"))
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                return None  # an impossible date is left blank, never corrected
        if convert == "lower":
            return raw.lower()
        if convert == "list_items":
            items = re.split(r",\s*|\s+and\s+", raw)
            return [re.sub(r"^(?:a|an|the|\d+)\s+", "", i.strip(), flags=re.IGNORECASE) for i in items if i.strip()]
        if convert.startswith("bucket:"):
            number = int(raw)
            for bucket in self._config.mappings.buckets[convert[7:]]:
                if bucket.max is None or number <= bucket.max:
                    return bucket.value
        return raw.strip()

    def _project(self, sentences: list[str]) -> ParsedField | None:
        for project in self._config.programs.projects.values():
            pattern = "|".join(rf"\b{re.escape(a)}\b" for a in project.aliases)
            found = first_sentence_matching(sentences, pattern)
            if found:
                return ParsedField(value=project.project_id, source=found[0], confidence="high")
        return None

    def _case_note(self, f: dict[str, ParsedField], sentences: list[str]) -> str:
        config = self._config
        parts = []
        if "first_name" in f:
            initial = f" {f['last_name'].value[0]}." if "last_name" in f else ""
            where = ""
            if "service_area" in f:
                label = _label(config, "service_area", f["service_area"].value)
                where = f" in the {label.split()[0]} quadrant"
            parts.append(f"Met {f['first_name'].value}{initial}{where}.")
        if "current_living_situation" in f:
            parts.append(f"Current living situation: {_label(config, 'current_living_situation', f['current_living_situation'].value).lower()}.")
        if "times_homeless_past_three_years" in f:
            times = _label(config, "times_homeless_past_three_years", f["times_homeless_past_three_years"].value)
            parts.append(f"Times on the street, in shelter, or in a safe haven in the past three years: {times.lower()}.")
        if "contact_service" in f:
            parts.append(f"Provided {', '.join(f['contact_service'].value)}.")
        for rule in config.mappings.stub_case_note:
            found = first_sentence_matching(sentences, rule.pattern)
            if found:
                parts.append(rule.text.format(**{k: v.strip() for k, v in found[1].groupdict().items() if v}))
        return " ".join(parts)


def _label(config: AppConfig, field: str, option_id: str) -> str:
    enum = config.fields.fields[field].enum
    return next(o.label for o in config.fields.enums[enum] if o.id == option_id)
