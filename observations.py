"""Source-preserving imports for K/L/M neurologic values and I-block weight.

No clinical scores, pressures or Z-scores are calculated. Zero and negative
scores are data. Each source section is stored and replaced independently.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import re
from vitals import validate_vitals
from demographics import separate_dosing_weight

NEURO_SECTIONS = {'k': 'Target Arousal Level', 'y': 'CAPD', 'l': 'WAT Score', 'm': 'ICP Trends'}
MISSING = {'', '-', '--', '---', 'n/a', 'na', 'none', 'not documented', 'not recorded',
           'not assessed', 'no data', 'no data recorded', 'no results found'}
NUMBER = r'[+\-\u2212]?(?:\d+(?:\.\d*)?|\.\d+)'
WEIGHT = re.compile(r'(?P<weight>\d+(?:\.\d+)?)\s*(?P<unit>kg|g|lbs?|oz)\b(?!/)', re.I)
Z_VALUE = re.compile(r'\bZ(?:[- ]?score)?\s*[=:]\s*(?P<z>' + NUMBER + r')(?![\w.])', re.I)
DATE_START = re.compile(r'^\s*(\d{1,2}/\d{1,2}/\d{2,4})(?=\s|$)')


def normalized(text: str) -> str:
    return re.sub(r'\s+', ' ', text.strip()).casefold()


def empty_neuro() -> dict[str, list[dict]]:
    # Y is optional in storage so pre-CAPD handoffs retain their exact fields.
    return {key: [] for key in ("k", "l", "m")}


def validate_neuro(data: dict) -> None:
    if not isinstance(data, dict) or not {"k", "l", "m"}.issubset(data) or set(data) - set(NEURO_SECTIONS):
        raise ValueError('The neurologic observations have an invalid structure.')
    for rows in data.values():
        validate_vitals(rows)
        if any(row['section'] != 'Neurologic' for row in rows):
            raise ValueError('Neurologic observations must remain in the Neurologic section.')
    from capd import validate_capd_rows
    validate_capd_rows(data.get('y', []))
    from icp_cpp import validate_icp_cpp_rows
    validate_icp_cpp_rows(data["m"])


def neuro_rows(data: dict) -> list[dict]:
    """Target arousal, CAPD (always), WAT-1, then ICP/CPP before medications."""
    validate_neuro(data)
    from capd import capd_display_row
    result = []
    for key in NEURO_SECTIONS:
        if key == "y":
            result.append(capd_display_row(data.get("y", [])))
        elif key == "m":
            from icp_cpp import display_icp_cpp_rows
            result.extend(display_icp_cpp_rows(data[key]))
        else:
            result.extend(data[key])
    return result


@dataclass
class ObservationResult:
    rows: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    error: str = ''


def parse_neuro(block: str, source: str) -> ObservationResult:
    out = ObservationResult()
    if source == "y":
        from capd import parse_capd
        return parse_capd(block)
    if source == "m":
        from icp_cpp import is_range_format, parse_icp_cpp
        if is_range_format(block):
            return parse_icp_cpp(block)
    if source not in NEURO_SECTIONS:
        out.error = 'The neurologic source section is unsupported. Nothing was imported.'
        return out
    headings = {
        'k': {'target arousal level', 'target arousal level (sbs)', 'target arousal level (rass)', 'sbs', 'rass'},
        'l': {'wat score', 'wat-1 total score', 'wat-1 score', 'wat-1 total score (0-12)', 'wat-1', 'wat score (0-12)'},
        'm': {'icp trends', 'icp', 'cpp', 'icp mean (mmhg)'},
    }[source]
    labels = {
        'k': re.compile(r'^(?:target arousal level|target\s+(?:sbs|rass)|sbs|rass)\b', re.I),
        'l': re.compile(r'^wat(?:[- ]?1)?\b', re.I),
        'm': re.compile(r'^(?:icp|cpp|intracranial pressure|cerebral perfusion pressure)\b', re.I),
    }[source]
    entries = {}
    for raw in block.replace('\r\n', '\n').replace('\r', '\n').splitlines():
        text = raw.replace('\u00a0', ' ').strip()
        whole = normalized(text.rstrip(':'))
        if whole in headings or whole in MISSING or whole.rstrip('.') in MISSING:
            continue
        if ':' in text:
            label, value = (part.strip() for part in text.split(':', 1))
        elif source == 'k' and re.fullmatch(r'(?:SBS|RASS)\s*' + NUMBER, text, re.I):
            scale = re.match(r'[A-Za-z]+', text).group(0).upper()
            label, value = 'Target Arousal Level (' + scale + ')', text
        elif source == 'l' and re.fullmatch(NUMBER, text):
            label, value = 'WAT-1 total score (0-12)', text
        elif '\t' in raw:
            pieces = [part.strip() for part in raw.split('\t') if part.strip()]
            if len(pieces) != 2:
                out.error = f'A {NEURO_SECTIONS[source]} line could not be separated. Nothing was imported.'
                return out
            label, value = pieces
        else:
            out.error = f'A {NEURO_SECTIONS[source]} line needs a recognizable label and value. Nothing was imported.'
            return out
        if normalized(value) in MISSING or normalized(value).rstrip('.') in MISSING:
            continue
        if not label or not labels.match(label):
            out.error = f'An unrecognized field appears in {NEURO_SECTIONS[source]}. Nothing was imported.'
            return out
        identity = normalized(label)
        if identity in entries:
            if entries[identity] != value:
                out.error = f'Conflicting repeated fields appear in {NEURO_SECTIONS[source]}. Nothing was imported.'
                return out
            continue
        entries[identity] = value
        out.rows.append({'label': label, 'value': value, 'section': 'Neurologic', 'include': True})
    try:
        validate_vitals(out.rows)
    except ValueError as exc:
        out.error = str(exc)
    return out


def validate_nutrition(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != {'weight', 'z_score', 'include'}:
        raise ValueError('The weight and Z-score record has an invalid structure.')
    if type(data['include']) is not bool:
        raise ValueError('The weight display setting is invalid.')
    weight, z = data['weight'], data['z_score']
    if not isinstance(weight, str) or len(weight) > 80 or not isinstance(z, str) or len(z) > 40:
        raise ValueError('The weight or Z-score is invalid.')
    match = WEIGHT.fullmatch(weight.strip())
    if not match:
        raise ValueError('Enter a recorded weight with its unit, for example 15.3 kg.')
    if Decimal(match.group('weight')) <= 0:
        raise ValueError('The recorded weight must be positive.')
    if z and not re.fullmatch(NUMBER, z):
        raise ValueError('Enter only the recorded numerical Z-score, or leave it blank.')


def format_nutrition(data: dict | None) -> str:
    validate_nutrition(data)
    if data is None or not data['include']:
        return ''
    return 'Weight: ' + data['weight'] + ('\nZ-score: ' + data['z_score'] if data['z_score'] else '')


@dataclass
class NutritionResult:
    data: dict | None = None
    dosing_weight: str = ""
    issues: list[str] = field(default_factory=list)
    error: str = ''


def parse_nutrition(block: str) -> NutritionResult:
    out = NutritionResult()
    split = separate_dosing_weight(block)
    if split.error:
        out.error = split.error
        return out
    block = split.measured_block
    out.dosing_weight = split.dosing_weight
    out.issues.extend(split.issues)
    candidates = []
    for raw in block.replace('\r\n', '\n').replace('\r', '\n').splitlines():
        text = raw.replace('\u00a0', ' ').strip()
        if not text or text.startswith('*'):
            continue
        dated = DATE_START.match(text)
        has_label = bool(re.match(r'^(?:weight|wt)\s*:', text, re.I))
        after_prefix = re.sub(r'^(?:weight|wt)\s*:\s*', '', text, flags=re.I)
        if dated:
            after_prefix = text[dated.end():].strip()
        match = WEIGHT.match(after_prefix)
        # Only a dated weight, explicit Weight/Wt field or standalone weight is
        # eligible. Nutrient quantities and medication doses are not weights.
        if not match:
            if has_label and normalized(after_prefix) not in MISSING:
                out.error = 'A Nutrition weight field could not be read. Nothing was imported.'
                return out
            continue
        tail = after_prefix[match.end():].strip()
        if tail and not tail.startswith(('(', 'Z', 'z', '*')):
            continue
        z_match = Z_VALUE.search(tail)
        if re.search(r'\bZ(?:[- ]?score)?\s*[=:]', tail, re.I) and z_match is None:
            out.error = 'A Nutrition Z-score could not be read. Nothing was imported.'
            return out
        data = {'weight': match.group('weight') + ' ' + match.group('unit'),
                'z_score': z_match.group('z') if z_match else '', 'include': True}
        try:
            validate_nutrition(data)
        except ValueError as exc:
            out.error = str(exc)
            return out
        date = None
        if dated:
            for form in ('%m/%d/%Y', '%m/%d/%y'):
                try:
                    date = datetime.strptime(dated.group(1), form)
                    break
                except ValueError:
                    pass
            if date is None:
                out.error = 'A weight row contains an invalid source date. Nothing was imported.'
                return out
        candidates.append((date, data))
    if not candidates:
        substantive = [line.strip() for line in block.splitlines() if line.strip()
                       and normalized(line.strip().rstrip(':')) not in MISSING | {'nutrition'}
                       and not re.match(r'^(?:wt readings|\*)', line.strip(), re.I)]
        if substantive:
            out.issues.append('No recognized weight row was found in Nutrition. No weight or Z-score was invented.')
        return out
    if len(candidates) > 1:
        if all(date is not None for date, _ in candidates):
            candidates.sort(key=lambda pair: pair[0], reverse=True)
            out.issues.append('Multiple weights were supplied. The most recent dated row is shown, with source order retained for a date tie.')
        else:
            out.issues.append('Multiple weights without complete dates were supplied. The first source row is shown.')
    out.data = candidates[0][1]
    if not out.data['z_score']:
        out.issues.append('The weight has no recorded Z-score. It was left blank, not calculated from the percentile.')
    return out
