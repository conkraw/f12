"""Choose a supplied FEN/GI template from the documented current patient age.

This reads the current Age field, with a narrow fallback for legacy demographic
text. It never uses a measurement age, dates, the clock, or patient weight.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path
import re

from anthropometrics import AGE_SEX_LABEL, _age_for_math, age_bounds, clean_field


FENGI_TEMPLATE_FILES = {
    "under_2": Path(__file__).parent / "templates" / "fengi_under_2.docx",
    "age_2_plus": Path(__file__).parent / "templates" / "fengi_age_2_plus.docx",
}

_AGE_WARNING = "Enter or verify the current patient age and regenerate to select the FEN/GI template."
_CURRENT_LABEL = re.compile(r"age(?:\s+in\s+months)?", re.I)
_NUMBER = r"\d+(?:\.\d+)?"
_OLD_AGE_CONTEXT = re.compile(
    r"\b(?:previous|prior|historical|history|past|old|measurements?|"
    r"gestational|corrected|maternal|paternal|bone)\b", re.I,
)
_CURRENT_CONTEXT = re.compile(r"(?:current\s+)?(?:patient\s+)?demographics(?:\s*/\s*weight)?", re.I)


@dataclass(frozen=True)
class _AgeSource:
    text: str
    parse_text: str


@dataclass(frozen=True)
class _AgeInterval:
    lower: Decimal
    upper: Decimal
    upper_exclusive: bool = False

    def variant(self) -> str | None:
        if self.lower >= 24:
            return "age_2_plus"
        if self.upper < 24 or (self.upper == 24 and self.upper_exclusive):
            return "under_2"
        return None


def _interval(text: str) -> _AgeInterval | None:
    try:
        value = clean_field("age", text)
    except ValueError:
        return None
    if not value:
        return None
    normalized = _age_for_math(value)
    # Reuse the app's unit and Epic abbreviation parsing. Whole-year ages have
    # an exclusive next-birthday bound, unlike its uncertain week/day ranges.
    bounds = age_bounds(value)
    years = re.fullmatch(rf"({_NUMBER})\s*(?:years?|yrs?|y)", normalized)
    if years:
        number = Decimal(years[1])
        if "." in years[1]:
            with localcontext() as context:
                context.prec = max(28, len(years[1]) + 4)
                months = number * 12
            return _AgeInterval(months, months)
        return _AgeInterval(Decimal(bounds[0]), Decimal(bounds[1]), True)
    months = re.fullmatch(rf"({_NUMBER})\s*(?:months?|mos?|m)", normalized)
    if months:
        # Preserve the exact recorded decimal at the 24-month boundary.
        number = Decimal(months[1])
        return _AgeInterval(number, number)
    compound = re.fullmatch(
        r"\d+\s*(months?|mos?|m|weeks?|wks?|w)\s*(?:,|and)?\s*(\d+)\s*(?:days?|d)",
        normalized,
    )
    if compound and int(compound[2]) >= (7 if compound[1].startswith("w") else 31):
        return None
    if bounds is None:
        return None
    return _AgeInterval(Decimal(str(bounds[0])), Decimal(str(bounds[1])))


def _demographic_sources(text: str) -> list[_AgeSource]:
    """Read only standalone current Age labels, including inline Age/Sex pairs.

    The importer also accepts Age at measurement. That label is deliberately
    excluded here, along with BMI/HC ages, corrected ages, and age in prose.
    """
    sources: list[_AgeSource] = []
    pending: str | None = None
    excluded_context = False

    def record(label: str, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            return
        parse_text = raw
        if "in months" in " ".join(label.lower().split()) and re.fullmatch(_NUMBER, raw):
            parse_text += " months"
        sources.append(_AgeSource(raw, parse_text))

    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        if not line.strip():
            continue
        heading = re.fullmatch(r"([^:]+):\s*", line.strip())
        if heading:
            label = heading[1].strip()
            if _OLD_AGE_CONTEXT.search(label) or re.fullmatch(r"BMI|HC|head\s+circumference", label, re.I):
                excluded_context, pending = True, None
                continue
            if _CURRENT_CONTEXT.fullmatch(label):
                excluded_context, pending = False, None
                continue
        if excluded_context:
            continue
        matches = list(AGE_SEX_LABEL.finditer(line))
        if matches and not line[:matches[0].start()].strip():
            pending = None
            for index, match in enumerate(matches):
                label = match[1]
                if not _CURRENT_LABEL.fullmatch(label):
                    continue
                end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
                raw = line[match.end():end].strip()
                if raw:
                    record(label, raw)
                elif index == len(matches) - 1:
                    pending = label
            continue
        if pending:
            # A following heading never supplies the missing Age value.
            if not re.match(r"^[^:]{1,100}:\s*", line.strip()):
                record(pending, line)
            pending = None
    return sources


def _compatible(intervals: list[_AgeInterval]) -> bool:
    lower = max(item.lower for item in intervals)
    upper = min(item.upper for item in intervals)
    if lower < upper:
        return True
    if lower > upper:
        return False
    return not any(item.upper == upper and item.upper_exclusive for item in intervals)


def select_fengi_variant(sheet: dict) -> dict:
    """Return JSON-friendly ``variant``, ``age_text``, and ``warning`` values.

    ``variant`` is ``under_2``, ``age_2_plus``, or None. ``age_text`` preserves
    the selected source's value, preferring anthropometrics['age']. Explicit
    conflicting current Age labels prevent selection, even when a primary Age
    exists. A missing or malformed primary Age never falls back to BMI/HC ages
    or birth dates. No source values are modified or advanced over time.
    """
    sheet = sheet if isinstance(sheet, dict) else {}
    attrs = sheet.get("anthropometrics", {})
    raw_age = attrs.get("age", "") if isinstance(attrs, dict) else ""
    age_text = raw_age.strip() if isinstance(raw_age, str) else ""
    unresolved = {"variant": None, "age_text": age_text, "warning": _AGE_WARNING}
    if not isinstance(raw_age, str):
        return unresolved

    sources = [_AgeSource(age_text, age_text)] if age_text else []
    fields = sheet.get("fields", {})
    demographics = fields.get("Demographics / Weight", "") if isinstance(fields, dict) else ""
    if isinstance(demographics, str):
        sources.extend(_demographic_sources(demographics))
    if not sources:
        return unresolved
    unresolved["age_text"] = sources[0].text
    intervals = [_interval(source.parse_text) for source in sources]
    if any(item is None or item.variant() is None for item in intervals):
        return unresolved
    if not _compatible(intervals):
        return unresolved
    return {"variant": intervals[0].variant(), "age_text": sources[0].text, "warning": ""}
