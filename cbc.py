"""Source-faithful Q-matrix CBC import, separate from P blood-gas parsing.

A dated column stays a column. Standard hemoglobin has priority over explicitly
labelled ISTAT hemoglobin across the snapshot. ANC and ALC are independent
latest absolute counts, never calculated from percentages or borrowed dates.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import re
import uuid
from labs import date_parts, short_date
from import_review import diagnostic, diagnostic_text

CORE = ('WBC', 'HGB', 'HCT', 'PLT', 'MCV')
ALIASES = {
    'WBC': 'WBC', 'WBC AUTO': 'WBC', 'WBC AUTOMATED': 'WBC',
    'HEMOGLOBIN': 'HGB', 'HGB': 'HGB', 'HB': 'HGB',
    'HEMOGLOBIN ISTAT': 'HGB_ISTAT', 'HGB ISTAT': 'HGB_ISTAT',
    'HEMOGLOBIN I-STAT': 'HGB_ISTAT', 'HGB I-STAT': 'HGB_ISTAT',
    'HEMATOCRIT': 'HCT', 'HCT': 'HCT', 'HEMATOCRIT ISTAT': 'HCT_ISTAT',
    'HCT ISTAT': 'HCT_ISTAT', 'MCV': 'MCV',
    'PLATELETS AUTO': 'PLT', 'PLATELETS': 'PLT', 'PLT': 'PLT',
    'NEUTROS ABS': 'ANC', 'NEUTROABS': 'ANC', 'NEUTRO ABS': 'ANC',
    'NEUTROPHILS ABSOLUTE': 'ANC', 'ABSOLUTE NEUTROPHIL COUNT': 'ANC',
    'ANC': 'ANC', 'LYMPHS ABS AUTO': 'ALC', 'LYMPHSABS': 'ALC',
    'LYMPHS ABS': 'ALC', 'LYMPHOCYTES ABSOLUTE': 'ALC',
    'ABSOLUTE LYMPHOCYTE COUNT': 'ALC', 'ALC': 'ALC',
    'MANUAL ABSOLUTE LYMPHOCYTE CV': 'ALC',
    'MANUAL ABSOLUTE LYMPHOCYTE COUNT': 'ALC',
    'MANUAL ABSOLUTE LYMPHOCYTE': 'ALC',
}
DATE_PATTERN = r'\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})'
TOKEN = re.compile(r'(?P<date>' + DATE_PATTERN + r')|(?P<time>\b(?:\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?|\d{4})\b)')
VALUE = re.compile(r'^[<>≤≥]?\s*[+\-−]?\d+(?:\.\d+)?\s*(?:\*+|\((?:H|L|HH|LL|A)\))?$', re.I)
EMPTY = re.compile(r'^(?:|--+|[-—–]|<\s*>|not (?:done|available|reported)|pending|n/?a)$', re.I)
MAX_ROWS = 2000


def multiple_numeric_results(value: str) -> bool:
    """A literal pipe means multiple source results, not a sortable range."""
    parts = value.split('|')
    return 2 <= len(parts) <= 10 and all(VALUE.fullmatch(part.strip()) for part in parts)



def cbc_component(label: str) -> str | None:
    key = re.sub(r'\s+', ' ', label.strip()).upper()
    return ALIASES.get(key)


def empty_cbc() -> dict:
    return {'rows': [], 'notes': []}


def validate_cbc(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != {'rows', 'notes'}:
        raise ValueError('The CBC snapshot has an invalid structure.')
    if not isinstance(data['rows'], list) or len(data['rows']) > MAX_ROWS:
        raise ValueError('The CBC list is invalid or too large.')
    ids, dates, cells, components = set(), {}, {}, {}
    for row in data['rows']:
        if not isinstance(row, dict) or set(row) != {'id', 'component', 'value', 'unit', 'date', 'column', 'include'}:
            raise ValueError('A CBC row has an invalid structure.')
        ident = row['id']
        if not isinstance(ident, str) or not re.fullmatch(r'[0-9a-f]{32}', ident) or ident in ids:
            raise ValueError('CBC row identifiers must be unique.')
        ids.add(ident)
        if not isinstance(row['component'], str) or not cbc_component(row['component']):
            raise ValueError('A CBC source label is not supported.')
        if not isinstance(row['include'], bool):
            raise ValueError('A CBC inclusion setting is invalid.')
        if type(row['column']) is not int or not 0 <= row['column'] < 100:
            raise ValueError('A CBC source column is invalid.')
        for key, limit in (('date', 80), ('unit', 50), ('value', 100)):
            if not isinstance(row[key], str) or len(row[key]) > limit or any(x in row[key] for x in '\r\n\t'):
                raise ValueError('A CBC result, unit or collection date is invalid.')
        if not VALUE.fullmatch(row['value'].strip()) and not (not row['include'] and multiple_numeric_results(row['value'])):
            raise ValueError('Use a recorded numeric CBC result, not a missing-result placeholder.')
        date_parts(row['date'])
        if row['column'] in dates and dates[row['column']] != row['date']:
            raise ValueError('Results in one CBC column must retain the same collection date and time.')
        dates[row['column']] = row['date']
        key = (row['column'], row['component'].strip().upper())
        if key in cells:
            raise ValueError('A CBC source label repeats in the same dated column.')
        cells[key] = True
        component = cbc_component(row['component'])
        if row['include'] and component in CORE + ('HGB_ISTAT', 'HCT_ISTAT'):
            alias_key = (row['column'], component)
            result = (row['value'], row['unit'])
            if alias_key in components and components[alias_key] != result:
                raise ValueError('Conflicting CBC aliases appear in the same dated column. Nothing was imported.')
            components[alias_key] = result
    if not isinstance(data['notes'], list) or len(data['notes']) > 100 or any(not isinstance(v, str) or len(v) > 1000 for v in data['notes']):
        raise ValueError('The CBC source notes are invalid.')


def _headers(text: str) -> list[str]:
    """Read wrapped date/time columns without altering the working gas parser."""
    tokens = [(m.lastgroup, m.group(0)) for m in TOKEN.finditer(text)]
    if not tokens or tokens[0][0] != 'date':
        raise ValueError('No dated CBC columns were found in Q. Copy the complete Lab / Units header.')
    n = sum(kind == 'date' for kind, value in tokens)
    if not 1 <= n <= 100:
        raise ValueError('The CBC table has too many date columns.')
    kinds = [kind for kind, value in tokens]
    if kinds == ['date'] * n + ['time'] * n:
        dates = [tokens[i][1] + ' ' + tokens[i+n][1] for i in range(n)]
    elif kinds == ['date'] * n:
        dates = [value for kind, value in tokens]
    else:
        dates, index = [], 0
        while index < len(tokens):
            if tokens[index][0] != 'date':
                raise ValueError('CBC date/time columns are ambiguous. Copy the complete table header.')
            value = tokens[index][1]
            index += 1
            if index < len(tokens) and tokens[index][0] == 'time':
                value += ' ' + tokens[index][1]
                index += 1
            dates.append(value)
    remainder = TOKEN.sub(' ', text)
    remainder = re.sub(r'\b(?:lab|units|date|time|collection|result)\b', '', remainder, flags=re.I)
    if re.search(r'[^\s:|]', remainder):
        raise ValueError('The CBC header contains an unrecognized date or time. Copy the table with tabs.')
    for date in dates:
        date_parts(date)
    return dates


@dataclass
class CBCResult:
    data: dict = field(default_factory=empty_cbc)
    issues: list[str] = field(default_factory=list)
    error: str = ''
    diagnostics: list[dict] = field(default_factory=list)


def parse_cbc(block: str) -> CBCResult:
    out = CBCResult()
    lines = block.replace('\r\n', '\n').replace('\r', '\n').replace('\u00a0', ' ').splitlines()
    meaningful = [line.strip() for line in lines if line.strip()]
    empty_line = re.compile(r'^(?:cbc:?|complete blood count:?|results? from (?:the )?last .*|none|no results?.*|no lab exists for component:.*)$', re.I)
    if not meaningful or all(empty_line.fullmatch(line) for line in meaningful):
        return out
    start = next((i for i, line in enumerate(lines) if re.match(r'^\s*Lab\s+Units\b', line, re.I)), None)
    if start is None:
        out.error = 'The Q block is missing its Lab / Units header. Nothing was imported.'
        return out
    first = len(lines)
    for i in range(start + 1, len(lines)):
        if re.search(r'[A-Za-z]', TOKEN.sub(' ', lines[i].strip())) and ('\t' in lines[i] or re.search(r' {2,}', lines[i])):
            first = i
            break
    try:
        dates = _headers('\n'.join(lines[start:first]))
    except ValueError as exc:
        out.error = str(exc)
        return out
    n, recognized, skipped = len(dates), 0, 0
    seen, blocked = {}, set()
    def warn(code, number, column=0, component='', action='cell_omitted'):
        item = diagnostic('q', code, line=number, column=column, field=component, action=action)
        out.diagnostics.append(item)
        out.issues.append(diagnostic_text(item))
    for number, raw in enumerate(lines[first:], first+1):
        line = raw.strip()
        if not line or re.match(r'^<\s*>\s*=', line):
            continue
        if '\t' in raw:
            cells = [c.strip() for c in raw.lstrip(' \t').split('\t')]
            while len(cells) > n+2 and not cells[-1]:
                cells.pop()
        else:
            cells = re.split(r' {2,}', line)
        component = cbc_component(cells[0]) if cells else None
        if not component:
            skipped += 1
            continue
        recognized += 1
        if '\t' not in raw and len(cells) == n+1 and all(EMPTY.fullmatch(c) or VALUE.fullmatch(c) for c in cells[1:]):
            cells.insert(1, '')
        if len(cells) != n+2:
            warn('cbc_row_columns', number, component=component, action='row_omitted')
            continue
        if component in ('ANC', 'ALC') and cells[1].casefold() in ('%', 'percent', 'percentage'):
            warn('cbc_percentage', number, component=component, action='row_omitted')
            continue
        for column, value in enumerate(cells[2:]):
            if EMPTY.fullmatch(value):
                continue
            include = True
            if not VALUE.fullmatch(value):
                if multiple_numeric_results(value):
                    # Keep the source cell for manual review, but never choose a value.
                    include = False
                    warn('cbc_multiple_values', number, column + 1, component)
                else:
                    warn('cbc_invalid_cell', number, column + 1, component)
                    continue
            key = (column, cells[0].upper())
            if key in blocked:
                continue
            if key in seen:
                if seen[key] == (value, cells[1]):
                    continue
                # Neither value wins just because it appeared first.
                out.data['rows'] = [r for r in out.data['rows']
                    if (r['column'], r['component'].upper()) != key]
                blocked.add(key)
                warn('cbc_conflict', number, column + 1, component)
                continue
            seen[key] = (value, cells[1])
            out.data['rows'].append({'id': uuid.uuid4().hex, 'component': cells[0],
                'value': value, 'unit': cells[1], 'date': dates[column], 'column': column, 'include': include})
    if not recognized:
        out.error = 'No supported CBC rows were recognized in Q. The previous handoff was not changed.'
        return out
    if skipped:
        out.issues.append('Unrecognized Q-table rows were not used for the CBC. No absolute counts were calculated.')
    aliases = defaultdict(list)
    for row in out.data['rows']:
        key = cbc_component(row['component'])
        if row['include'] and key in CORE + ('HGB_ISTAT', 'HCT_ISTAT'):
            aliases[(row['column'], key)].append(row)
    for (column, component), values in aliases.items():
        if len({(r['value'], r['unit']) for r in values}) > 1:
            for row in values:
                row['include'] = False
            warn('cbc_conflict', 0, column + 1, component)
    try:
        validate_cbc(out.data)
    except ValueError as exc:
        out.error = str(exc)
        return out
    out.issues.extend(cbc_selection_issues(out.data))
    out.data['notes'] = list(dict.fromkeys(out.issues))[:100]
    return out


def _ordered(rows: list[dict]) -> list[dict]:
    days = defaultdict(list)
    for row in rows:
        days[date_parts(row['date'])[0].date()].append(row)
    out = []
    for day in sorted(days, reverse=True):
        values = days[day]
        if all(date_parts(r['date'])[1] for r in values):
            values = sorted(values, key=lambda r: date_parts(r['date'])[0], reverse=True)
        else:
            values = sorted(values, key=lambda r: r.get('column', 0))
        out.extend(values)
    return out


def _eligible(data: dict) -> list[dict]:
    return [r for r in data['rows'] if r['include'] and not (cbc_component(r['component']) in ('ANC', 'ALC') and r.get('unit', '').casefold() in ('%', 'percent', 'percentage'))]


def cbc_selection_issues(data: dict) -> list[str]:
    rows = _eligible(data)
    issues = []
    if any(cbc_component(r['component']) == 'HGB_ISTAT' for r in rows):
        if any(cbc_component(r['component']) == 'HGB' for r in rows):
            issues.append('ISTAT hemoglobin is retained for review but excluded from the handoff because a standard hemoglobin is available in this snapshot.')
        else:
            issues.append('No standard hemoglobin is available in this snapshot. ISTAT hemoglobin may be displayed and is labelled ISTAT.')
    for name in ('ANC', 'ALC'):
        counts = _ordered([r for r in rows if cbc_component(r['component']) == name])
        if len(counts) > 1 and date_parts(counts[0]['date']) == date_parts(counts[1]['date']) and counts[0]['value'] != counts[1]['value']:
            issues.append(name + ' has differing results at the same supplied timestamp. Source order is used. Review the retained rows.')
    if rows and any(not date_parts(r['date'])[1] for r in rows):
        issues.append('Some CBC collection times are absent. Same-date ties use the original column order.')
    return issues


def _display(row: dict, key: str) -> dict:
    out = deepcopy(row)
    out['component'] = ('Hgb (ISTAT)' if cbc_component(row['component']) == 'HGB_ISTAT' else key)
    if key in ('ANC', 'ALC') and row.get('unit'):
        out['value'] = row['value'] + ' ' + row['unit']
    return out


def _counts(rows: list[dict]) -> dict:
    out = {}
    for key in ('ANC', 'ALC'):
        candidates = _ordered([r for r in rows if cbc_component(r['component']) == key])
        out[key] = _display(candidates[0], key) if candidates else {'component': key, 'value': '--', 'date': ''}
    return out


def cbc_cards(labs: dict, snapshot: dict | None = None) -> list[dict]:
    """Q wins, even when empty. Older G data remains a non-destructive fallback."""
    if snapshot is None:
        rows = [r for r in labs['rows'] if r['include'] and cbc_component(r['component'])]
        if not rows:
            return []
        regular = any(cbc_component(r['component']) == 'HGB' for r in rows)
        groups = defaultdict(list)
        for row in rows:
            key = cbc_component(row['component'])
            if key == 'HGB_ISTAT':
                if regular:
                    continue
                key = 'HGB'
            if key in CORE:
                groups[key].append(row)
        groups = {key: _ordered(value) for key, value in groups.items()}
        cards = []
        for index in range(2):
            slots = {key: _display(values[index], key) for key, values in groups.items() if len(values) > index}
            if slots:
                cards.append({'title': 'CBC | ' + ('latest per component' if index == 0 else 'preceding per component'), 'kind': 'cbc', 'rows': slots})
        if not cards and any(cbc_component(r['component']) in ('ANC', 'ALC') for r in rows):
            cards = [{'title': 'CBC | counts only', 'kind': 'cbc', 'rows': {}}]
        if cards:
            cards[0]['rows'].update(_counts(rows))
        return cards
    validate_cbc(snapshot)
    rows = _eligible(snapshot)
    if not rows:
        return []
    regular = any(cbc_component(r['component']) == 'HGB' for r in rows)
    by_column = defaultdict(list)
    for row in rows:
        by_column[row['column']].append(row)
    # A gas-only Hct / ISTAT column is not a regular CBC. Only use ISTAT
    # columns when no standard hemoglobin exists anywhere in the snapshot.
    anchors = {'WBC', 'HGB', 'MCV', 'PLT'} | ({'HGB_ISTAT'} if not regular else set())
    candidates = [dict(date=values[0]['date'], column=column) for column, values in by_column.items()
                  if any(cbc_component(r['component']) in anchors for r in values)]
    if not candidates:
        candidates = [dict(date=values[0]['date'], column=column) for column, values in by_column.items()
                      if any(cbc_component(r['component']) in ('HCT', 'HCT_ISTAT') for r in values)]
    cards = []
    for index, candidate in enumerate(_ordered(candidates)[:2]):
        slots = {}
        column_rows = by_column[candidate['column']]
        for key in CORE:
            choices = [r for r in column_rows if cbc_component(r['component']) == key]
            if key == 'HGB' and not regular and not choices:
                choices = [r for r in column_rows if cbc_component(r['component']) == 'HGB_ISTAT']
            if key == 'HCT' and not choices:
                choices = [r for r in column_rows if cbc_component(r['component']) == 'HCT_ISTAT']
            if choices:
                slots[key] = _display(choices[0], key)
        cards.append({'title': 'CBC | ' + ('latest column' if index == 0 else 'preceding column'), 'kind': 'cbc', 'rows': slots})
    if not cards and any(cbc_component(r['component']) in ('ANC', 'ALC') for r in rows):
        cards = [{'title': 'CBC | counts only', 'kind': 'cbc', 'rows': {}}]
    if cards:
        cards[0]['rows'].update(_counts(rows))
    return cards


def cbc_summary(data: dict) -> str:
    cards = cbc_cards({'rows': [], 'notes': []}, data)
    lines = []
    for card in cards:
        lines.append(card['title'])
        for key, row in card['rows'].items():
            lines.append(row['component'] + ': ' + row['value'] + (' [' + short_date(row['date']) + ']' if row['date'] else ''))
    return '\n'.join(lines)
