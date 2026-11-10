"""Explicit demographic values. No DOB capture or age/sex inference from prose.

Age is the age at the BMI measurement. A years-only display is not treated as an
exact age in months for a BMI percentile. BMI and BSA are imported, not derived
from weight, medication doses, or inferred height. CDC reference lookup is local.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
import re

FIELDS = ('age', 'sex', 'bmi', 'height', 'bsa')
MISSING = {'', 'none', 'n/a', 'na', '--', 'unknown', 'not recorded', 'not documented'}
NUMBER = r'(?:\d+(?:\.\d+)?|\.\d+)'
HEADER = re.compile(r'^(Age(?:\s+(?:in\s+months|at\s+(?:BMI\s+)?measurement))?|Sex(?:\s+for\s+growth\s+chart)?|BMI|Body\s+mass\s+index|Height|Length|BSA|Body\s+surface\s+area)\s*(?::|\bis\b)\s*(.*)$', re.I)


def empty_anthropometrics() -> dict:
    return {key: '' for key in FIELDS}


def _age_for_math(text: str) -> str:
    """Interpret Epic age abbreviations without changing the displayed wording."""
    text = re.sub(r'\s+', ' ', text.strip().lower())
    for pattern, unit in (
        (r'\b(?:yrs?|y)\.?\s*o\.?(?!\w)', 'years'),
        (r'\b(?:mos?|m)\.?\s*o\.?(?!\w)', 'months'),
        (r'\b(?:wks?|w)\.?\s*o\.?(?!\w)', 'weeks'),
        (r'\bd\.?\s*o\.?(?!\w)', 'days'),
    ):
        text = re.sub(pattern, unit, text)
    return text


def age_months(text: str) -> float | None:
    """Accept documented total months or years AND months. Never guess months."""
    text = _age_for_math(text)
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(?:months?|mos?|m)', text)
    if match:
        return float(match.group(1))
    match = re.fullmatch(r'(\d+)\s*(?:years?|yrs?|y)\s*(?:,|and)?\s*(\d+)\s*(?:months?|mos?|m)', text)
    if match and int(match.group(2)) < 12:
        return 12 * int(match.group(1)) + int(match.group(2))
    return None


def age_bounds(text: str) -> tuple[float, float] | None:
    text = _age_for_math(text)
    value = age_months(text)
    if value is not None:
        return value, value
    match = re.fullmatch(r'(\d+)\s*(?:years?|yrs?|y)', text.strip(), re.I)
    if match:
        return int(match.group(1)) * 12, (int(match.group(1)) + 1) * 12
    # These infant ages are sufficient to identify the under-two restriction,
    # but never used as a decimal-month input to the CDC table.
    match = re.fullmatch(r'(\d+)\s*(?:days?|d|weeks?|wks?|w)', text.strip(), re.I)
    if match:
        days = int(match.group(1)) * (7 if re.search(r'w', text, re.I) else 1)
        return days / 31, days / 28
    match = re.fullmatch(r'(\d+)\s*(months?|mos?|m|weeks?|wks?|w)\s*(?:,|and)?\s*(\d+)\s*(?:days?|d)', text.strip(), re.I)
    if match:
        number, unit, days = int(match[1]), match[2].lower(), int(match[3])
        if unit.startswith('m'):
            return float(number), number + days / 28
        total_days = number * 7 + days
        return total_days / 31, total_days / 28
    return None


def _height_parentheticals(suffix: str) -> list[str]:
    """Split balanced trailing notes without discarding unrecognized content."""
    groups: list[str] = []
    rest = suffix.strip()
    while rest:
        if not rest.startswith('('):
            raise ValueError('Unexpected text follows the recorded height. Verify the height and its annotations.')
        depth = 0
        end = None
        for index, char in enumerate(rest):
            if char == '(':
                depth += 1
                if depth > 8:
                    raise ValueError('The height annotation has too many nested parentheses.')
            elif char == ')':
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end is None:
            raise ValueError('The height annotation has unmatched parentheses.')
        groups.append(rest[1:end].strip())
        rest = rest[end + 1:].strip()
    return groups


def _height_charting_note(note: str) -> bool:
    """Recognize chart-transfer notes only, not alternate measurements.

    This accepts Epic/Cerner migration and recharting provenance. It does not
    ignore unknown annotations, a second height, or language invalidating the
    recorded measurement. No free-text note is copied into error messages.
    """
    provenance = re.search(
        r"\b(?:epic|cerner|go[ -]?live|re[ -]?charted|re[ -]?charting|"
        r"transcribed|transcription|migrated|migration|imported|"
        r"copied (?:from|over)|carried forward)\b", note, re.I)
    if not provenance:
        return False
    if re.search(
        r"\b(?:unknown|unavailable|unable|unreliable|invalid|inaccurate|"
        r"incorrect|wrong|error|erroneous|conflicting|uncertain|corrected|correction|correct|"
        r"remeasur\w*|recheck\w*|verify|unverified|estimated|approximate|"
        r"not measured|not verified|do not use|should be|instead)\b",
        note, re.I,
    ):
        return False
    # Check quantities before stripping dates or years: a four-digit height
    # must never be mistaken for a provenance year.
    if re.search(
        rf"(?<!\w){NUMBER}\s*(?:cm|mm|m(?:et(?:er|re)s?)?|in(?:ch(?:es)?)?|ft|feet|foot|kg|g|lbs?)\b",
        note, re.I,
    ) or re.search(r"\d\s*[\"'′″]", note):
        return False
    # Dates in a provenance note are harmless, but a second quantity is not.
    # Also reject unitless numeric assertions other than dates/clock times.
    numeric_free = re.sub(r"\b\d{1,4}[/-]\d{1,2}[/-]\d{1,4}\b", "", note)
    numeric_free = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", "", numeric_free)
    numeric_free = re.sub(r"\b(?:19|20)\d{2}\b", "", numeric_free)
    if re.search(r"[0-9<>]", numeric_free):
        return False
    return True


def _clean_height(value: str) -> str:
    """Keep primary height, validate an imperial equivalent, omit charting notes.

    Only recognized documentation provenance is omitted. Different heights,
    malformed parentheses and unknown or invalidating annotations still fail.
    No height is calculated from weight or BMI.
    """
    match = re.fullmatch(rf'({NUMBER})\s*(cm|m|in(?:ches)?)(.*)', value, re.I)
    if not match or len(match.group(1)) > 96 or Decimal(match.group(1)) <= 0:
        raise ValueError('Enter recorded height with a unit, for example 100 cm. An Epic feet/inches equivalent in parentheses is also accepted.')
    number, unit, suffix = match.groups()
    unit = unit.lower()
    equivalent_seen = False
    for annotation in _height_parentheticals(suffix):
        alternate = annotation.translate(str.maketrans({
            '\u2032': "'", '\u2018': "'", '\u2019': "'",
            '\u2033': '"', '\u201c': '"', '\u201d': '"',
        }))
        imperial = re.fullmatch(
            rf"\s*(\d+)\s*(?:'|ft\.?|feet|foot)\s*({NUMBER})\s*(?:\"|in\.?|inch(?:es)?)\s*",
            alternate, re.I)
        if imperial:
            if equivalent_seen or not 0 <= Decimal(imperial.group(2)) < 12:
                raise ValueError('The height has a duplicate or invalid feet/inches equivalent. Verify the recorded height.')
            equivalent_seen = True
            feet, inches = imperial.groups()
            factor = Decimal('100') if unit == 'm' else Decimal('2.54') if unit.startswith('in') else Decimal('1')
            primary_cm = Decimal(number) * factor
            alternate_cm = (Decimal(feet) * 12 + Decimal(inches)) * Decimal('2.54')
            primary_rounding = Decimal(1).scaleb(Decimal(number).as_tuple().exponent) * factor / 2
            alternate_rounding = Decimal(1).scaleb(Decimal(inches).as_tuple().exponent) * Decimal('2.54') / 2
            if abs(primary_cm - alternate_cm) > primary_rounding + alternate_rounding:
                raise ValueError('The primary height and its feet/inches equivalent disagree. Verify the recorded height before importing this section.')
        elif not _height_charting_note(annotation):
            raise ValueError('The height annotation is not a recognized charting note or feet/inches equivalent. Verify the primary height and units.')
    return number + ' ' + unit


def clean_field(key: str, value: str) -> str:
    value = re.sub(r'\s+', ' ', value.replace('\u00a0', ' ').strip())
    if value.casefold().rstrip('.') in MISSING:
        return ''
    # A copied charting note can be longer than the normalized measurement.
    if len(value) > (2000 if key == 'height' else 100):
        raise ValueError('A demographic field is too long.')
    if key == 'age':
        if not re.fullmatch(r'\d+(?:\.\d+)?\s*(?:years?|yrs?|y|months?|mos?|m|weeks?|wks?|w|days?|d)(?:\s*(?:,|and)?\s*\d+\s*(?:months?|mos?|m|days?|d))?', _age_for_math(value), re.I):
            raise ValueError('Use an age with units, for example 5 years 2 months, 14 months, or 10 days.')
        if age_months(value) is not None and age_months(value) > 1440:
            raise ValueError('Check the recorded age.')
        return value
    if key == 'sex':
        names = {'m': 'Male', 'male': 'Male', 'boy': 'Male', 'f': 'Female', 'female': 'Female', 'girl': 'Female'}
        if value.casefold() not in names:
            raise ValueError('CDC growth-chart sex must be explicitly Male or Female, or left blank.')
        return names[value.casefold()]
    if key == 'bmi':
        match = re.fullmatch(rf'({NUMBER})(?:\s*kg\s*/\s*m(?:²|\^?2))?\.?', value, re.I)
        if not match or not 0 < Decimal(match.group(1)) <= 200:
            raise ValueError('Enter a positive recorded BMI, such as 17.14 kg/m².')
        return match.group(1) + ' kg/m²'
    if key == 'height':
        return _clean_height(value)
    if key == 'bsa':
        match = re.fullmatch(rf'({NUMBER})\s*(?:m²|m\^?2|sq\.?\s*m|square\s+met(?:er|re)s?|met(?:er|re)s?\s+squared)\.?', value, re.I)
        if not match or not 0 < Decimal(match.group(1)) <= 10:
            raise ValueError('Check BSA and its unit. Use a recorded value such as 0.65 m², not m/kg².')
        return match.group(1) + ' m²'
    raise ValueError('Unknown demographic field.')


def validate_anthropometrics(data: dict) -> None:
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        raise ValueError('The demographic measurements have an invalid structure.')
    for key, value in data.items():
        if not isinstance(value, str) or any(c in value for c in '\n\r\t'):
            raise ValueError('A demographic measurement contains invalid text.')
        if clean_field(key, value) != value:
            raise ValueError('A demographic measurement is not normalized.')


@dataclass
class AnthropometricResult:
    values: dict = field(default_factory=dict)
    remainder: str = ''
    error: str = ''


AGE_SEX_LABEL = re.compile(
    r'(?<!\w)(Age(?:\s+(?:in\s+months|at\s+(?:BMI\s+)?measurement))?'
    r'|Sex(?:\s+for\s+growth\s+chart)?)\s*:[ \t]*', re.I)


def extract_age_sex(block: str, *, allow_inline_suffix: bool = False) -> AnthropometricResult:
    """Extract labeled patient age/sex, including one-line Epic metadata.

    A metadata line may start with either label. In a diagnosis block, a trailing
    Age AND Sex pair is also accepted, so older joined diagnosis text can be
    reimported. A single embedded label (for example Bone age:) stays untouched.
    Errors are static and never include source text.
    """
    out = AnthropometricResult()
    remaining = []
    pending = None

    def record(label: str, raw_value: str) -> bool:
        key = 'age' if label.lower().startswith('age') else 'sex'
        value = raw_value.strip()
        if label.casefold() == 'age in months' and re.fullmatch(NUMBER, value):
            value += ' months'
        try:
            value = clean_field(key, value)
        except ValueError as exc:
            out.error = str(exc)
            return False
        if key in out.values and out.values[key] and value and out.values[key] != value:
            out.error = 'Conflicting demographic measurements were supplied in one section.'
            return False
        if value or key not in out.values:
            out.values[key] = value
        return True

    for raw in block.replace('\r\n', '\n').replace('\r', '\n').splitlines():
        text = raw.strip()
        if not text:
            remaining.append(raw)
            continue
        matches = list(AGE_SEX_LABEL.finditer(raw))
        prefix = raw[:matches[0].start()] if matches else ''
        keys = {m.group(1).split()[0].lower() for m in matches}
        starts_line = bool(matches) and not prefix.strip()
        suffix_pair = (allow_inline_suffix and keys == {'age', 'sex'}
                       and not re.search(r'\b(?:bone|gestational|maternal|paternal|corrected)\s*$', prefix, re.I))
        if matches and (starts_line or suffix_pair):
            pending = None
            if prefix.strip():
                remaining.append(prefix.rstrip())
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
                value = raw[match.end():end].strip()
                if not record(match.group(1), value):
                    return out
                if not value and index == len(matches) - 1:
                    pending = match.group(1)
            continue
        if pending:
            # A new heading does not become a missing demographic value.
            if HEADER.match(text) or re.match(r'^(?:Dosing|Wt|Weight|Date of Admission|NUTRITION|Diagnoses)\b', text, re.I):
                pending = None
            else:
                if not record(pending, text):
                    return out
                pending = None
                continue
        remaining.append(raw)
    out.remainder = '\n'.join(remaining)
    return out


def extract_anthropometrics(block: str) -> AnthropometricResult:
    """Remove explicitly labeled measurements from I/N before weight parsing."""
    age_sex = extract_age_sex(block)
    if age_sex.error:
        return age_sex
    block = age_sex.remainder
    out = AnthropometricResult(values=dict(age_sex.values))
    remaining = []
    pending = None
    for raw in block.replace('\r\n', '\n').replace('\r', '\n').splitlines():
        text = raw.strip()
        match = HEADER.match(text)
        if match:
            label, value = match.groups()
            name = label.casefold()
            key = ('age' if name.startswith('age') else 'sex' if name.startswith('sex') else
                   'bmi' if name in ('bmi', 'body mass index') else 'bsa' if name in ('bsa', 'body surface area') else 'height')
            if name == 'age in months' and re.fullmatch(NUMBER, value):
                value += ' months'
            pending = key if not value else None
        elif pending and text:
            if HEADER.match(text) or re.match(r'^(?:Dosing|Wt|Weight|Date of Admission|NUTRITION)\b', text, re.I):
                remaining.append(raw)
                pending = None
                continue
            key, value, pending = pending, text, None
        else:
            remaining.append(raw)
            continue
        try:
            value = clean_field(key, value)
        except ValueError as exc:
            out.error = str(exc)
            return out
        if key in out.values and out.values[key] and value and out.values[key] != value:
            out.error = 'Conflicting demographic measurements were supplied in one section.'
            return out
        if value or key not in out.values:
            out.values[key] = value
    out.remainder = '\n'.join(remaining)
    return out


def bmi_output_allowed(data: dict) -> bool:
    """Only print BMI when the documented age establishes age >=24 months.

    Missing age is not inferred from a growth-chart footnote or diagnosis.
    Retain imported BMI in the editor/storage even when it is not printed.
    """
    bounds = age_bounds(data.get('age', ''))
    return bounds is not None and bounds[0] >= 24


def measurements_text(data: dict) -> str:
    from bmi_reference import bmi_percentile_summary
    validate_anthropometrics(data)
    rows = []
    for key, label in (('height', 'Height'), ('bsa', 'BSA')):
        if data[key]:
            rows.append(label + ': ' + data[key])
    if data['bmi'] and bmi_output_allowed(data):
        rows.append('BMI: ' + data['bmi'])
        text, _ = bmi_percentile_summary(data)
        # Missing-data messages belong to the editor, not the compact handoff.
        if text.endswith(' (CDC)'):
            rows.append('BMI percentile: ' + text)
    return '\n'.join(rows)
