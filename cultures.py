"""Epic culture snapshots, with no sensitivity columns or microbiology inference.

Rows are retained individually. The compact output groups identical collection
 date/time + specimen labels, combines their documented organisms/statuses, and
shows two newest display groups per specimen category. Groups are not asserted
 to be distinct cultures: no accession IDs are present in the source.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
import re
import uuid

from labs import date_parts, short_date

MAX_ROWS = 2500
MAX_ORGANISMS = 100
HEADERS = ('collected', 'specimen info', 'organism')
DATE_START = re.compile(r'^\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})(?=\s|$)')


def clean(value: str) -> str:
    return re.sub(r'\s+', ' ', value.replace('\u00a0', ' ')).strip()


def empty_cultures() -> dict:
    return {'rows': [], 'notes': []}


def culture_date(value: str) -> tuple[datetime, bool]:
    try:
        return date_parts(value)
    except ValueError:
        raise ValueError('A culture date could not be read. Use the source collection date and optional time.') from None


def category_for(specimen: str) -> str:
    """Group explicit specimen labels only. An unspecified aspirate is not lung."""
    key = clean(specimen).casefold()
    if re.search(r'\bblood\b', key):
        return 'Blood'
    if re.search(r'\bsputum\b|\btrache\w*|\bbronch\w*|\brespiratory\b|\bbal\b|\blung\b|\bendotrache\w*', key):
        return 'Respiratory'
    if re.search(r'\burine\b', key):
        return 'Urine'
    if re.search(r'\bcsf\b|cerebrospinal', key):
        return 'CSF'
    if re.search(r'\bstool\b|\bfeces\b|\bfaeces\b', key):
        return 'Stool'
    if re.search(r'\bwound\b', key):
        return 'Wound'
    # Keep each other site separate. A pericardial result must not be hidden
    # merely because another unspecified source has more recent results.
    return 'Other: ' + key


def validate_cultures(data: dict) -> None:
    if not isinstance(data, dict) or set(data) != {'rows', 'notes'}:
        raise ValueError('The culture snapshot has an invalid structure.')
    if not isinstance(data['rows'], list) or len(data['rows']) > MAX_ROWS:
        raise ValueError('The culture list is invalid or too large.')
    ids = set()
    for row in data['rows']:
        if not isinstance(row, dict) or set(row) != {'id', 'date', 'specimen', 'organisms', 'include'}:
            raise ValueError('A culture row has an invalid structure.')
        if not isinstance(row['id'], str) or not re.fullmatch(r'[0-9a-f]{32}', row['id']) or row['id'] in ids:
            raise ValueError('Culture row identifiers must be unique.')
        ids.add(row['id'])
        for key, limit in (('date', 80), ('specimen', 500)):
            if (not isinstance(row[key], str) or not row[key].strip()
                    or len(row[key]) > limit or any(c in row[key] for c in '\r\n\t')):
                raise ValueError('A culture date or specimen is missing or invalid.')
        culture_date(row['date'])
        organisms = row['organisms']
        if not isinstance(organisms, list) or not 1 <= len(organisms) <= MAX_ORGANISMS:
            raise ValueError('A culture needs at least one recorded organism or result.')
        if any(not isinstance(x, str) or not x.strip() or len(x) > 2000
               or any(c in x for c in '\r\n\t') for x in organisms):
            raise ValueError('A culture organism or result is empty or invalid.')
        if not isinstance(row['include'], bool):
            raise ValueError('A culture inclusion setting is invalid.')
    if (not isinstance(data['notes'], list) or len(data['notes']) > 20
            or any(not isinstance(x, str) or len(x) > 1000 for x in data['notes'])):
        raise ValueError('The culture source notes are invalid.')


@dataclass
class CultureResult:
    data: dict = field(default_factory=empty_cultures)
    issues: list[str] = field(default_factory=list)
    error: str = ''


def parse_cultures(block: str) -> CultureResult:
    out = CultureResult()
    previous = None
    empty_reported = False
    for number, raw in enumerate(block.replace('\r\n', '\n').replace('\r', '\n').replace('\u00a0', ' ').splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        low = clean(line.rstrip(':')).casefold()
        if low == 'cultures' or low.startswith('susceptibility data from'):
            continue
        if re.match(r'^collected\s+specimen\s+info\s+organism(?:\s|$)', low):
            previous = None  # Do not carry a continuation across a new table.
            continue
        if low.startswith(('no results found', 'no culture results', 'no cultures')) or low == 'none':
            out.data['notes'].append(clean(line))
            empty_reported = True
            previous = None
            continue
        if DATE_START.match(line):
            # Ignore sensitivity columns. Never split specimen/organism names
            # on ordinary single spaces, since those names themselves use them.
            cells = raw.lstrip(' \t').split('\t') if '\t' in raw else re.split(r' {2,}', line)
            if len(cells) < 3 or not all(clean(x) for x in cells[:3]):
                out.error = f'Culture line {number}: collection date, specimen and organism could not be separated. Copy the table with its tabs. Nothing was applied.'
                return out
            date, specimen, organism = (clean(x) for x in cells[:3])
            try:
                culture_date(date)
            except ValueError as exc:
                out.error = str(exc)
                return out
            previous = {'id': uuid.uuid4().hex, 'date': date, 'specimen': specimen,
                        'organisms': [organism], 'include': True}
            out.data['rows'].append(previous)
            continue
        # Epic multi-organism row: the first TWO cells are explicitly blank.
        # Preserve their tabs so organisms cannot be mistaken for specimens.
        cells = raw.lstrip(' ').split('\t')
        if len(cells) >= 3 and not clean(cells[0]) and not clean(cells[1]):
            organism = clean(cells[2])
            if previous is None:
                out.error = f'Culture line {number}: a continuation has no preceding dated specimen. Nothing was applied.'
                return out
            if organism:
                previous['organisms'].append(organism)
            # A row with only extra sensitivity cells adds no requested result.
            continue
        out.error = f'Culture line {number} could not be linked to a dated specimen. Nothing was applied. Keep the collection, specimen and organism columns when copying.'
        return out
    if empty_reported and out.data['rows']:
        out.error = 'The culture section says no results but also contains dated cultures. Check the source. Nothing was applied.'
        return out
    try:
        validate_cultures(out.data)
    except ValueError as exc:
        out.error = str(exc)
    return out


def compact_groups(data: dict, limit: int = 2) -> list[dict]:
    """Latest two distinct date/time + specimen groups in each category.

    Same-date, same-site rows combine their results for display only. Raw rows
    and their inclusion controls remain separate in the snapshot/editor. Ties
    without collection times retain Epic source order, not inferred chronology.
    """
    validate_cultures(data)
    if not isinstance(limit, int) or limit < 1:
        raise ValueError('Choose at least one culture group per category.')
    groups: OrderedDict = OrderedDict()
    for index, row in enumerate(data['rows']):
        if not row['include']:
            continue
        dt, timed = culture_date(row['date'])
        key = (dt, timed, clean(row['specimen']).casefold())
        if key not in groups:
            groups[key] = {'date': row['date'], 'specimen': row['specimen'],
                           'organisms': [], 'row_ids': [], 'category': category_for(row['specimen']),
                           'first_index': index, 'sort_date': dt}
        group = groups[key]
        group['row_ids'].append(row['id'])
        for organism in row['organisms']:
            if clean(organism).casefold() not in {clean(x).casefold() for x in group['organisms']}:
                group['organisms'].append(organism)
    ranked = sorted(groups.values(), key=lambda g: g['sort_date'], reverse=True)
    counts: dict[str, int] = {}
    selected = []
    for group in ranked:
        kind = group['category']
        if counts.get(kind, 0) >= limit:
            continue
        selected.append(group)
        counts[kind] = counts.get(kind, 0) + 1
    order = {'Blood': 0, 'Respiratory': 1, 'Urine': 2, 'CSF': 3, 'Stool': 4, 'Wound': 5}
    return sorted(selected, key=lambda g: (order.get(g['category'], 6),
        '' if g['category'] in order else g['category']))


def culture_display(value: str) -> str:
    """Shorten an unambiguously negative growth result, not a mixed result."""
    if re.fullmatch(r"\s*no growth(?: to date)?(?: after \d+ days?)?(?:\s*\([^)]*\))?\.?\s*", value, re.I):
        return "NGTD"
    return value


def cultures_text(data: dict, empty_none: bool = False) -> str:
    groups = compact_groups(data)
    if not groups:
        return 'Cultures: None' if empty_none and not data['rows'] else ''
    lines = ['Cultures']
    for group in groups:
        lines.append(short_date(group['date']) + ' | ' + group['specimen'] + ' | ' + ' / '.join(dict.fromkeys(culture_display(v) for v in group['organisms'])))
    return '\n'.join(lines)
