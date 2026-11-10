"""U/V device snapshots. Identify the device, not Epic's surrounding heading.

No clinical inference or cross-section lookup. Removed devices are discarded,
except ETT entries retained explicitly as airway history. Assessment prose is
not used to infer device removal or placement. Values never cross devices.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape
import re
import uuid

from feeds import feeding_method
from import_review import diagnostic
from lab_windows import clock

KINDS = ('ETT', 'Trach', 'PIV', 'PICC', 'CVC', 'Arterial line',
         'Urinary catheter', 'Feeding tube', 'Drain', 'EVD', 'ICP monitor', 'Other')
ROW_KEYS = {'id', 'kind', 'label', 'date', 'size', 'secured', 'status', 'removed', 'include'}
EDIT_FIELDS = ('label', 'date', 'size', 'secured', 'status', 'include')
VASCULAR_KINDS = frozenset(('PIV', 'PICC', 'CVC', 'Arterial line'))
REMOVED = re.compile(r'\[\s*removed\s*\]', re.I)
DATE = re.compile(r'(?<!\d)(?:\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))(?!\d)')
PROPERTY = re.compile(r'\s*[-\u2013\u2014]\s*(?P<field>Site\s+Assessment|Secured\s+at\s*\(cm\)|'
                      r'Secured\s+(?:at|location)|Secure\s*Site|Secured\s+at\s+site|'
                      r'Drain\s+Status|Status)\s*:\s*(?P<value>.*)$', re.I)
HEADINGS = {'lines', 'lines / devices', 'devices', 'lines and devices', 'endotracheal tube',
            'urinary catheter', 'tracheostomy tube', 'intracranial pressure monitor',
            'neuro devices', 'devices / airway', 'none', 'no data', 'no data recorded',
            'not documented', 'n/a', '--', 'no devices', 'no lines'}


@dataclass
class DevicesResult:
    data: dict | None = None
    issues: list[str] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    error: str = ''


def _clean(value: str) -> str:
    return re.sub(r'\s+', ' ', value.replace('\u00a0', ' ')).strip()


def _missing(value: str) -> bool:
    return _clean(value).rstrip('.:').casefold() in ('', '--', '-', 'none', 'n/a', 'unknown', 'not documented', 'no data recorded')


def _value(value: str) -> str:
    value = _clean(value)
    value = re.sub(r'^\(S\)\s*', '', value, flags=re.I)
    return '' if _missing(value) else value


def _kind(label: str, section: str) -> str:
    """A named gastric tube under 'Endotracheal Tube' is still a feeding tube."""
    if re.match(r'^(?:ETT\b|Endotracheal\s+Tube\b)', label, re.I):
        return 'ETT'
    if re.match(r'^(?:Surgical\s+Airway|Tracheostomy(?:\s+Tube)?|Trach(?:eal)?\s+tube)\b', label, re.I):
        return 'Trach'
    for kind, pat in (('PIV', r'^(?:Peripheral\s+IV|PIV)\b'),
                      ('PICC', r'^(?:PICC|Peripherally\s+inserted\s+central\s+catheter)\b'),
                      ('CVC', r'^(?:CVC|CVL|Central\s+(?:Venous\s+)?(?:Line|Catheter)|Port[- ]?a[- ]?cath|Implanted\s+Port|Hemodialysis\s+Catheter)\b'),
                      ('Arterial line', r'^(?:Arterial\s+(?:Line|Catheter)|A[- ]line)\b'),
                      ('Urinary catheter', r'^(?:Urethral\s+Catheter|Urinary\s+Catheter|Foley|Suprapubic\s+Catheter)\b')):
        if re.search(pat, label, re.I):
            return kind
    # A shared Epic category prefix alone is not enough to call a bolt an EVD.
    specific = re.sub(r'^Intracranial\s+Pressure\s*/\s*Ventriculostomy\b', '', label, flags=re.I).strip()
    if re.search(r'\b(?:EVD|external\s+ventricular\s+drain(?:age)?|ventricular\s+drain(?:age)?\s+catheter|ventriculostomy(?:\s+(?:drain|catheter))?)\b', specific, re.I):
        return 'EVD'
    if re.search(r'\b(?:intracranial\s+pressure|ICP\s+(?:monitor|bolt|microsensor)|intraparenchymal|Camino|Codman)\b', label, re.I):
        return 'ICP monitor'
    if re.match(r'^(?:Gastric\s+Tube|Gastrostomy/Enterostomy|Gastrostomy|Gastrojejunostomy|Jejunostomy|Naso(?:gastric|jejunal)|Orogastric|PEG(?:-J)?\b|NG\b|NJ\b|GT\b|GJ\b)', label, re.I):
        return 'Feeding tube'
    if re.match(r'^(?:Chest\s+Tube|Drain|Closed\s+Suction\s+Drain|Surgical\s+Drain)\b', label, re.I):
        return 'Drain'
    return 'Other'


def _short_label(label: str, kind: str) -> str:
    text = _clean(label.replace(';', ', '))
    replacements = {
        'PIV': (r'^(?:Peripheral\s+IV|PIV)\b', 'PIV'),
        'Arterial line': (r'^(?:Arterial\s+(?:Line|Catheter)|A[- ]line)\b', 'Arterial line'),
        'Urinary catheter': (r'^(?:Urethral\s+Catheter|Urinary\s+Catheter)\b', 'Urinary catheter'),
        'Trach': (r'^(?:Surgical\s+Airway|Tracheostomy(?:\s+Tube)?|Trach(?:eal)?\s+tube)\b', 'Trach'),
    }
    if kind in replacements:
        pattern, replacement = replacements[kind]
        text = re.sub(pattern, replacement, text, count=1, flags=re.I)
    if kind == 'Feeding tube':
        method = feeding_method(text)
        if method != 'UNK':
            text = re.sub(r'^(?:Gastric\s+Tube|Gastrostomy/Enterostomy)\s*', '', text, flags=re.I)
            text = re.sub(r'^(?:Percutaneous\s+endoscopic\s+gastrostomy\s*\(PEG\)|Gastrojejunostomy|Gastrostomy|Jejunostomy|Nasojejunal|Nasogastric|Orogastric|Nasoduodenal|PEG-J|PEG|NG|NJ|GT|GJ)\b\s*', '', text, flags=re.I)
            # Closing parenthesis is a non-word boundary in the PEG expression.
            text = re.sub(r'^Percutaneous\s+endoscopic\s+gastrostomy\s*\(PEG\)\s*', '', text, flags=re.I)
            text = method + (' ' + text if text else '')
    return _clean(text)


def validate_devices(data: dict | None, section: str = 'u') -> None:
    if data is None:
        return
    if section not in ('u', 'v') or not isinstance(data, dict) or set(data) != {'rows'} or not isinstance(data['rows'], list) or len(data['rows']) > 100:
        raise ValueError('The device snapshot has an invalid structure.')
    ids = set()
    for row in data['rows']:
        if not isinstance(row, dict) or set(row) != ROW_KEYS:
            raise ValueError('A device entry has an invalid structure.')
        if not isinstance(row['id'], str) or not re.fullmatch(r'[0-9a-f]{32}', row['id']) or row['id'] in ids:
            raise ValueError('A device entry identifier is invalid or repeated.')
        ids.add(row['id'])
        if row['kind'] not in KINDS or type(row['include']) is not bool or type(row['removed']) is not bool:
            raise ValueError('A device entry has an invalid display choice.')
        if row['removed'] and row['kind'] != 'ETT':
            raise ValueError('Removed non-ETT devices must not be retained.')
        for name, limit in (('label', 600), ('date', 40), ('size', 120), ('secured', 250), ('status', 250)):
            if not isinstance(row[name], str) or len(row[name]) > limit or any(c in row[name] for c in '\n\r\t'):
                raise ValueError('A device field is invalid or too long.')
        if not row['label'].strip():
            raise ValueError('Enter a device description or exclude the entry.')
        if row['date']:
            if not DATE.fullmatch(row['date']):
                raise ValueError('Use the documented device date in MM/DD/YY or MM/DD/YYYY format.')
            try:
                datetime.strptime(row['date'], '%m/%d/%Y' if len(row['date'].split('/')[-1]) == 4 else '%m/%d/%y')
            except ValueError:
                raise ValueError('The device date is not a valid calendar date.') from None


def parse_devices(block: str, section: str = 'u') -> DevicesResult:
    out = DevicesResult()
    if section not in ('u', 'v') or not isinstance(block, str) or len(block) > 30000:
        out.error = 'The device section is invalid or too long.'
        return out
    groups = {}
    def warn(code, line=0, field=''):
        item = diagnostic(section, code, line=line, field=field, action='row_omitted' if code == 'device_unrecognized' else 'field_unknown')
        if item not in out.diagnostics:
            out.diagnostics.append(item)
    for number, raw in enumerate(block.replace('\r\n', '\n').replace('\r', '\n').splitlines(), 1):
        text = _clean(raw)
        if not text or text.rstrip(':.').casefold() in HEADINGS:
            continue
        if ':' in text:
            head, tail = text.split(':', 1)
            if head.strip().casefold() in HEADINGS and _missing(tail):
                continue
        if re.fullmatch(r'No (?:ETT|EVD|ICP monitor|devices?|lines?)(?: present| documented| recorded)?\.?', text, re.I):
            continue
        removed = bool(REMOVED.search(text))
        text = REMOVED.sub('', text).strip()
        prop = PROPERTY.search(text)
        label = text[:prop.start()].strip() if prop else text
        kind = _kind(label, section)
        # Ignore the entire removed row, including any values that follow it.
        if removed and kind != 'ETT':
            continue
        if kind == 'Other' and not prop:
            warn('device_unrecognized', number)
            continue
        if len(label) > 600:
            warn('device_unrecognized', number)
            continue
        key = (label.casefold(), removed)
        if key not in groups:
            dates = DATE.findall(label)
            date = dates[0] if len(dates) == 1 else ''
            if len(dates) > 1:
                warn('device_conflict', number, 'device_date')
            if date:
                try:
                    datetime.strptime(date, '%m/%d/%Y' if len(date.split('/')[-1]) == 4 else '%m/%d/%y')
                except ValueError:
                    date = ''
                    warn('device_conflict', number, 'device_date')
            short = label
            if date:
                short = DATE.sub('', short, count=1)
            size = ''
            if kind == 'ETT':
                sizes = re.findall(r'(?<![\w.])\d+(?:\.\d+)?\s*mm\b', short, re.I)
                if len(set(sizes)) == 1:
                    size = sizes[0]
                elif len(set(sizes)) > 1:
                    warn('device_conflict', number, 'device_size')
            groups[key] = {'row': dict(id=uuid.uuid4().hex, kind=kind, label=_short_label(short, kind),
                                      date=date, size=size, secured='', status='', removed=removed, include=True),
                           'values': {'secured': [], 'location': [], 'status': []}, 'lines': {'secured': number, 'location': number, 'status': number}}
        group = groups[key]
        if kind == 'Other':
            warn('device_unclassified', number)
        if prop:
            label_key = _clean(prop['field']).casefold()
            if label_key == 'site assessment':
                continue  # Dressing/site condition is not part of this compact inventory.
            target = ('status' if label_key in ('status', 'drain status') else 'secured' if '(cm)' in label_key or label_key == 'secured at' else 'location')
            value = _value(prop['value'])
            if value:
                group['values'][target].append(value)
                group['lines'][target] = number
    rows = []
    for group in groups.values():
        row = group['row']
        location = ''
        for target in ('secured', 'status', 'location'):
            values = list(dict.fromkeys(group['values'][target]))
            if len(values) == 1 and len(values[0]) <= 250:
                if target == 'location':
                    location = values[0]
                else:
                    row[target] = values[0]
            elif values:
                warn('device_conflict', group['lines'][target], 'device_secured' if target == 'location' else 'device_' + target)
                if target == 'location':
                    location = 'UNK'
                else:
                    row[target] = 'UNK'
        if location:
            row['secured'] = ', '.join(v for v in (row['secured'], location) if v)
        if row['kind'] == 'EVD' and not row['status']:
            row['status'] = 'UNK'
            warn('device_missing_status', group['lines']['status'], 'device_status')
        rows.append(row)
    if len(rows) > 100 or len(out.diagnostics) > 100:
        out.error = 'The device section contains too many entries or review issues.'
        return out
    out.data = {'rows': rows} if rows else None
    try:
        validate_devices(out.data, section)
    except ValueError as exc:
        out.error = str(exc)
        out.data = None
    if out.diagnostics:
        out.issues.append('Some device details need review. Unreadable values are not guessed, and other sections can still update.')
    return out


def devices_for_output(sheet: dict, section: str = 'u') -> dict | None:
    action = 'devices_hidden' if section == 'u' else 'neuro_devices_hidden'
    if any(item['action'] == action for item in sheet.get('import_warnings', {}).get(section, [])):
        return None
    return sheet.get('devices' if section == 'u' else 'neuro_devices')


def _rows(sheet: dict, section: str):
    data = devices_for_output(sheet, section)
    return [row for row in (data or {}).get('rows', []) if row['include'] and (not row['removed'] or row['kind'] == 'ETT')]


def insertion_date(value: str) -> date | None:
    """Read a complete documented date without inventing missing components."""
    if not isinstance(value, str) or not DATE.fullmatch(value):
        return None
    try:
        return datetime.strptime(value, '%m/%d/%Y' if len(value.split('/')[-1]) == 4 else '%m/%d/%y').date()
    except ValueError:
        return None


def line_day_number(value: str, as_of: datetime | None = None) -> int | None:
    """Calendar days in Eastern time. Insertion is Day 1, not elapsed 24 hours."""
    inserted = insertion_date(value)
    if inserted is None:
        return None
    elapsed = (clock(as_of).date() - inserted).days
    return elapsed + 1 if elapsed >= 0 else None


def _output_kind(row: dict) -> str:
    """Recognize old saved CVL rows without rewriting their stored category."""
    if row['kind'] == 'Other':
        detected = _kind(row['label'], 'u')
        if detected in VASCULAR_KINDS:
            return detected
    return row['kind']


def _date_label(row: dict, as_of: datetime | None = None) -> str:
    label = row['date']
    day = line_day_number(label, as_of) if _output_kind(row) in VASCULAR_KINDS and not row['removed'] else None
    return label + (', Day ' + str(day) if day is not None else '')


def device_line(row: dict, as_of: datetime | None = None) -> str:
    if row['kind'] == 'ETT':
        label = 'ETT history (removed)' if row['removed'] else 'ETT'
        return label + ' | Last Airway Size: ' + (row['size'] or 'UNK') + ' | Last Secure Site: ' + (row['secured'] or 'UNK') + (' | ' + row['date'] if row['date'] else '')
    text = row['label']
    if row['date']:
        text += ' (' + _date_label(row, as_of) + ')'
    if row['secured']:
        text += ' | Secured: ' + row['secured']
    if row['kind'] == 'EVD':
        text += ' | ' + (row['status'] or 'UNK')
    elif row['status']:
        text += ' | ' + row['status']
    return text


def evd_text(sheet: dict) -> str:
    """V EVD status stays in Neurologic, not inferred from ICP or U headings."""
    rows = [r for r in _rows(sheet, 'v') if r['kind'] == 'EVD']
    if len(rows) == 1:
        return 'EVD: ' + (rows[0]['status'] or 'UNK')
    return '\n'.join('EVD ' + str(i) + ': ' + (r['status'] or 'UNK') + ' | ' + r['label'] for i, r in enumerate(rows, 1))


def _device_groups(sheet: dict, render) -> list[tuple[str, list[str]]]:
    groups = {name: [] for name in ('Airway', 'Vascular access', 'Tubes / drains', 'Other devices')}
    rows = _rows(sheet, 'u') + [r for r in _rows(sheet, 'v') if r['kind'] != 'EVD']
    # Stable source ordering within each category. Active ETTs/trachs before history.
    rows.sort(key=lambda r: r['removed'])
    for row in rows:
        kind = _output_kind(row)
        category = ('Airway' if kind in ('ETT', 'Trach') else
                    'Vascular access' if kind in ('PIV', 'PICC', 'CVC', 'Arterial line') else
                    'Tubes / drains' if kind in ('Urinary catheter', 'Feeding tube', 'Drain') else 'Other devices')
        line = render(row)
        if line not in groups[category]:
            groups[category].append(line)
    return [(name, lines) for name, lines in groups.items() if lines]


def device_groups(sheet: dict, as_of: datetime | None = None) -> list[tuple[str, list[str]]]:
    return _device_groups(sheet, lambda row: device_line(row, as_of))


def devices_text(sheet: dict, as_of: datetime | None = None) -> str:
    return '\n'.join(name + ': ' + ' / '.join(lines) for name, lines in device_groups(sheet, as_of))


def devices_markup(sheet: dict, esc=escape, as_of: datetime | None = None, *, live_days: bool = False) -> str:
    def render(row):
        markup = esc(device_line(row, as_of))
        inserted = insertion_date(row['date'])
        if live_days and inserted is not None and _output_kind(row) in VASCULAR_KINDS and not row['removed']:
            label = _date_label(row, as_of)
            span = ('<span data-line-insertion="' + inserted.isoformat() + '" data-line-date="' + escape(row['date'], quote=True) + '">'
                    + esc(label) + '</span>')
            markup = markup.replace(esc('(' + label + ')'), '(' + span + ')', 1)
        return markup
    return '\n'.join('<b>' + esc(name) + ':</b> ' + ' / '.join(lines)
                     for name, lines in _device_groups(sheet, render))
