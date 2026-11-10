"""Latest documented gas from Epic's P matrix. No cross-column backfilling.

A matrix column is one documented date/time. Specimen-qualified rows are
kept together within that column. Missing/hidden values are not numbers.
Raw pasted source, unrelated analytes and patient identifiers are not stored.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime
from copy import deepcopy
import re
import uuid

SPECIMENS = ('VEN', 'ART', 'CAP')
FIELDS = ('pH', 'PCO2', 'PO2', 'HCO3', 'Base excess', 'O2 saturation')
MAX_SAMPLES = 300
DATE_PATTERN = r'\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})'
TOKEN = re.compile(r'(?P<date>' + DATE_PATTERN + r')|(?P<time>\b(?:\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?|\d{4})\b)')
VALUE = re.compile(r'^[<>≤≥]?\s*[+\-−]?\d+(?:\.\d+)?\s*(?:\*+|\((?:H|L|HH|LL|A)\))?$', re.I)
EMPTY = re.compile(r'^(?:|--+|[-—–]|<\s*>|not (?:done|available|reported)|pending|n/?a)$', re.I)


def _date(value: str) -> tuple[datetime, bool]:
    # Local import prevents cycles when the lab renderer uses the legacy adapter.
    from labs import date_parts
    return date_parts(value)


def empty_gases() -> dict:
    return {'samples': [], 'notes': []}


def gas_label(label: str) -> tuple[str, str] | None:
    """Only explicit specimen labels. Never infer type from value or unit."""
    # Existing labels may include a quoted alternate name after the first label.
    # POCT rows instead use a comma to separate analyte from specimen type.
    first = label.split(',', 1)[0].strip(" '\"")
    whole = label.strip(" '\"")
    match = None
    for candidate in (first, whole):
        key = re.sub(r'\s+', ' ', candidate.replace('₂', '2').replace('₃', '3')).upper()
        key = re.sub(r'^POCT\s+', '', key)
        key = re.sub(r',\s*', ' ', key)
        match = re.fullmatch(r'(PH|PCO2|PO2|HCO3|BICARBONATE|BASE EXC|BASE EXCESS|O2 SAT|O2 SATURATION|SO2) (VEN|VENOUS|ART|ARTERIAL|CAP|CAPILLARY)', key)
        if match:
            break
    if not match:
        return None
    field_name, specimen = match.groups()
    specimen = {'VENOUS': 'VEN', 'ARTERIAL': 'ART', 'CAPILLARY': 'CAP'}.get(specimen, specimen)
    field_name = {'PH': 'pH', 'BICARBONATE': 'HCO3', 'BASE EXC': 'Base excess',
                  'BASE EXCESS': 'Base excess', 'O2 SAT': 'O2 saturation',
                  'O2 SATURATION': 'O2 saturation', 'SO2': 'O2 saturation'}.get(field_name, field_name)
    return specimen, field_name


def _row_label(raw: str) -> str:
    if '\t' in raw:
        return raw.lstrip(' \t').split('\t', 1)[0]
    return re.split(r' {2,}', raw.strip(), maxsplit=1)[0]


def _headers(text: str) -> list[str]:
    tokens = [(m.lastgroup, m.group(0)) for m in TOKEN.finditer(text)]
    if not tokens or tokens[0][0] != 'date':
        raise ValueError('No dated blood-gas columns were found in P. Copy the dates and times with the table.')
    n = sum(kind == 'date' for kind, value in tokens)
    if not 1 <= n <= 100:
        raise ValueError('The blood-gas table has too many date columns.')
    kinds = [kind for kind, value in tokens]
    dates = []
    # Also accept a horizontal date-header row followed by a time-header row.
    if kinds == ['date'] * n + ['time'] * n:
        dates = [tokens[i][1] + ' ' + tokens[i + n][1] for i in range(n)]
    elif kinds == ['date'] * n:
        dates = [value for kind, value in tokens]
    else:
        index = 0
        while index < len(tokens):
            if tokens[index][0] != 'date':
                raise ValueError('Blood-gas date/time columns are ambiguous. Copy the complete table header.')
            value = tokens[index][1]
            index += 1
            if index < len(tokens) and tokens[index][0] == 'time':
                value += ' ' + tokens[index][1]
                index += 1
            dates.append(value)
    # Reject stray text/numbers between dates rather than accidentally accepting
    # malformed times such as 99:99 or a missing leading zero in 804.
    header = re.sub(r'(?im)^\s*(?:results? from (?:the )?last .*|blood gases?:?|latest blood gas:?)\s*$', '', text)
    remainder = TOKEN.sub(' ', header)
    remainder = re.sub(r'\b(?:lab|units|date|time|collection|result)\b', '', remainder, flags=re.I)
    if re.search(r'[^\s:|]', remainder):
        raise ValueError('The blood-gas header contains an unrecognized date or time. Copy the complete table with tabs.')
    for date in dates:
        _date(date)
    return dates


def validate_gases(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != {'samples', 'notes'}:
        raise ValueError('The blood-gas snapshot is invalid.')
    if not isinstance(data['samples'], list) or len(data['samples']) > MAX_SAMPLES:
        raise ValueError('The blood-gas sample list is invalid or too large.')
    ids = set()
    for sample in data['samples']:
        if not isinstance(sample, dict) or set(sample) != {'id', 'specimen', 'date', 'values', 'include'}:
            raise ValueError('A blood-gas sample has an invalid structure.')
        ident = sample['id']
        if not isinstance(ident, str) or not re.fullmatch(r'[0-9a-f]{32}', ident) or ident in ids:
            raise ValueError('Blood-gas sample identifiers must be unique.')
        ids.add(ident)
        if sample['specimen'] not in SPECIMENS or not isinstance(sample['include'], bool):
            raise ValueError('A blood-gas specimen or inclusion setting is invalid.')
        if not isinstance(sample['date'], str) or len(sample['date']) > 80 or '\n' in sample['date'] or '\r' in sample['date']:
            raise ValueError('A blood-gas collection date is invalid.')
        _date(sample['date'])
        values = sample['values']
        if not isinstance(values, dict) or not values or not set(values).issubset(FIELDS):
            raise ValueError('A blood gas must contain at least one supported result.')
        for result in values.values():
            if not isinstance(result, dict) or set(result) != {'value', 'unit'}:
                raise ValueError('A blood-gas result has an invalid structure.')
            if not isinstance(result['value'], str) or len(result['value']) > 100 or not VALUE.fullmatch(result['value'].strip()):
                raise ValueError('Use the recorded numeric gas result, with its source flag if present. Do not enter a placeholder as a result.')
            if not isinstance(result['unit'], str) or len(result['unit']) > 50 or '\n' in result['unit'] or '\r' in result['unit']:
                raise ValueError('A blood-gas unit is invalid.')
    if not isinstance(data['notes'], list) or len(data['notes']) > 100 or any(not isinstance(note, str) or len(note) > 1000 for note in data['notes']):
        raise ValueError('The blood-gas source notes are invalid.')


@dataclass
class GasResult:
    data: dict = field(default_factory=empty_gases)
    issues: list[str] = field(default_factory=list)
    error: str = ''


def parse_gases(block: str) -> GasResult:
    out = GasResult()
    lines = block.replace('\r\n', '\n').replace('\r', '\n').replace('\u00a0', ' ').splitlines()
    meaningful = [line.strip() for line in lines if line.strip()]
    empty_lines = re.compile(r'^(?:blood gases?:?|latest blood gas:?|results? from (?:the )?last .*|none|no results?(?: found)?.*|no lab exists for component:.*)$', re.I)
    if not meaningful or all(empty_lines.fullmatch(line) for line in meaningful):
        return out
    # The first data row can be an unsupported analyte. The Lab/Units header is
    # the boundary, followed by dates/times on as many lines as Epic emits.
    header_start = next((i for i, line in enumerate(lines) if re.match(r'^\s*Lab\s+Units\b', line, re.I)), None)
    if header_start is None:
        out.error = 'The P block is missing its Lab / Units header. Nothing was imported.'
        return out
    first_row = None
    for i in range(header_start + 1, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        # A row is not a pure sequence of date/time tokens. A table row whose
        # label is unsupported is still used to terminate the header.
        remainder = TOKEN.sub(' ', line)
        if re.search(r'[A-Za-z]', remainder) and ('\t' in lines[i] or re.search(r' {2,}', lines[i])):
            first_row = i
            break
    if first_row is None:
        first_row = len(lines)
    try:
        dates = _headers('\n'.join(lines[header_start:first_row]))
    except ValueError as exc:
        out.error = str(exc)
        return out
    n = len(dates)
    by_column = [dict() for _ in dates]
    ignored = 0
    recognized = 0
    generic_ph_rows = []
    for number, raw in enumerate(lines[first_row:], first_row + 1):
        line = raw.strip()
        if not line or re.match(r'^<\s*>\s*=', line) or re.match(r'^results? from (?:the )?last ', line, re.I):
            continue
        raw_label = _row_label(raw)
        generic_ph = raw_label.strip().upper() in ("PH", "POCT PH")
        typed = gas_label(raw_label)
        if generic_ph:
            typed = ("", "pH")
        if not typed:
            ignored += 1
            continue
        recognized += 1
        # Preserve empty units and empty trailing values, which have positions.
        if '\t' in raw:
            cells = [cell.strip() for cell in raw.lstrip(' \t').split('\t')]
            while len(cells) > n + 2 and not cells[-1]:
                cells.pop()
        else:
            cells = re.split(r' {2,}', line)
            # A pH-only row has no unit and may lose the empty cell when tabs
            # become spaces. This case has an unambiguous known dimensionless label.
            if typed[1] == 'pH' and len(cells) == n + 1:
                cells.insert(1, '')
        if len(cells) != n + 2:
            out.error = f'Blood-gas row {number} does not match the dated columns. Copy the table with tabs. Nothing was imported.'
            return out
        specimen, label = typed
        unit = cells[1]
        if generic_ph:
            if unit:
                out.error = 'An untyped pH row has unexpected units. Nothing was imported.'
                return out
            generic_ph_rows.append((number, cells))
            continue
        for index, value in enumerate(cells[2:]):
            if EMPTY.fullmatch(value):
                continue
            if not VALUE.fullmatch(value):
                out.error = f'Blood-gas row {number} has an unrecognized result. Nothing was imported.'
                return out
            if specimen not in by_column[index]:
                by_column[index][specimen] = {'id': uuid.uuid4().hex, 'specimen': specimen,
                    'date': dates[index], 'values': {}, 'include': True}
            sample = by_column[index][specimen]
            result = {'value': value, 'unit': unit}
            if label in sample['values'] and sample['values'][label] != result:
                out.error = 'Two blood-gas rows disagree for the same specimen, column and component. Nothing was imported.'
                return out
            sample['values'][label] = result
    # Generic PH is used only where this exact column has one explicit specimen
    # type established by another requested gas analyte. Never use older columns.
    for number, cells in generic_ph_rows:
        for index, value in enumerate(cells[2:]):
            if EMPTY.fullmatch(value):
                continue
            if not VALUE.fullmatch(value):
                out.error = 'An untyped pH row has an unrecognized result. Nothing was imported.'
                return out
            if len(by_column[index]) != 1:
                out.issues.append('An untyped pH result could not be assigned to one explicit specimen in its own column and was omitted.')
                continue
            sample = next(iter(by_column[index].values()))
            result = {'value': value, 'unit': ''}
            if 'pH' in sample['values'] and sample['values']['pH'] != result:
                out.error = 'Typed and untyped pH disagree within the same specimen column. Nothing was imported.'
                return out
            sample['values']['pH'] = result
            out.issues.append('An untyped pH was associated with the only explicitly identified specimen in its own date/time column.')
    if not recognized and first_row < len(lines):
        out.error = 'No supported specimen-labeled blood-gas rows were found in P. Nothing was imported.'
        return out
    out.data['samples'] = [sample for column in by_column for sample in column.values()]
    if ignored:
        out.issues.append('P-block rows without a supported specimen-qualified gas label were not used. Corrected PO2 and ISTAT deficit rows are not substituted for PO2 or base excess.')
    try:
        validate_gases(out.data)
    except ValueError as exc:
        out.error = str(exc)
        return out
    _, warnings = latest_sample(out.data)
    out.issues.extend(warnings)
    return out


def latest_sample(data: dict | None) -> tuple[dict | None, list[str]]:
    if data is None:
        return None, []
    rows = [row for row in data['samples'] if row['include'] and row['values']]
    if not rows:
        return None, []
    # Preserve source order for unresolved date-only ties, never prioritize ART.
    newest_day = max(_date(row['date'])[0].date() for row in rows)
    candidates = [row for row in rows if _date(row['date'])[0].date() == newest_day]
    issues = []
    if all(_date(row['date'])[1] for row in candidates):
        newest = max(_date(row['date'])[0] for row in candidates)
        candidates = [row for row in candidates if _date(row['date'])[0] == newest]
        if len(candidates) > 1:
            issues.append('More than one gas has the same latest timestamp. The first source column/specimen is displayed. Review the retained gases to resolve the tie.')
    else:
        issues.append('Collection time is absent for at least one gas on the latest date. Source order breaks the tie, not a guessed time or specimen priority.')
    return candidates[0], issues


def legacy_gases(labs: dict) -> dict:
    """Date-matched fallback for pre-P G blocks. No cross-date filling."""
    from labs import canonical, ARTERIAL, VENOUS, CAPILLARY
    maps = {}
    for specimen, keys in (('ART', ARTERIAL), ('VEN', VENOUS), ('CAP', CAPILLARY)):
        for component, label in zip(keys, FIELDS):
            maps[component] = (specimen, label)
    groups = {}
    repeated = False
    for row in labs['rows']:
        typed = maps.get(canonical(row['component']))
        if not row['include'] or not typed or not VALUE.fullmatch(row['value'].strip()):
            continue
        specimen, label = typed
        key = (specimen, _date(row['date']))
        if key not in groups:
            groups[key] = {'id': row['id'], 'specimen': specimen, 'date': row['date'], 'values': {}, 'include': True}
        if label not in groups[key]['values']:
            groups[key]['values'][label] = {'value': row['value'], 'unit': ''}
        else:
            repeated = True
    data = {'samples': list(groups.values()), 'notes': []}
    if repeated:
        data['notes'].append('Legacy rows repeat a component at the same supplied date/time. The first source row is used, without asserting a common collection.')
    return data


def gas_card(labs: dict, snapshot: dict | None = None) -> dict | None:
    """One compact card. P, including an empty P, overrides old G gas rows."""
    data = legacy_gases(labs) if snapshot is None else snapshot
    sample, issues = latest_sample(data)
    if sample is None:
        return None
    qualifier = ''
    if snapshot is None:
        qualifier = ' | legacy G, same-draw unverified'
    elif issues:
        qualifier = ' | source-order tie' if len([r for r in data['samples'] if r['include']]) > 1 else ' | time not supplied'
    rows = {label: {'component': label, 'value': sample['values'][label]['value'] +
                    (' ' + sample['values'][label]['unit'] if sample['values'][label]['unit'] else ''),
                    'date': sample['date']} for label in FIELDS if label in sample['values']}
    return {'title': 'Gas ' + sample['specimen'] + ' | latest' + qualifier, 'kind': 'branch', 'rows': rows}


def gas_summary(data: dict | None) -> str:
    sample, issues = latest_sample(data)
    if sample is None:
        return ''
    from labs import short_date
    values = [label + ': ' + sample['values'][label]['value'] +
              (' ' + sample['values'][label]['unit'] if sample['values'][label]['unit'] else '')
              for label in FIELDS if label in sample['values']]
    return 'Gas ' + sample['specimen'] + ' [' + short_date(sample['date']) + '] | ' + ' | '.join(values)
