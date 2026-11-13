"""Route E-block vitals and show explicit oxygenation and pressure ranges.

No endpoint or clinical value is calculated. Ordinary labeled vital lines stay
verbatim. Summary Min/Max fields are kept as documented, with no clipping of
extremes and no substitution of a mean or blood-gas result. Missing-data markers
are ignored rather than becoming patient values or invalidating the E block.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from arterial_pressure import parse_arterial_line, arterial_display_rows
import re


_ETCO2_NAME = r'(?:et\s*co[2₂]|end[ -]?tidal\s+(?:co[2₂]|carbon dioxide))'
_CVP_NAME = r'(?:cvp|central venous pressure)'
_MONITOR_NAME = rf'(?:{_ETCO2_NAME}|{_CVP_NAME})'
_PRESSURE_UNIT = r'(?:mm\s*hg|cm\s*h[2₂]o|kpa)'
_MONITOR_PREFIX = re.compile(
    rf'^(?P<name>{_MONITOR_NAME})(?=$|[\s:(])'
    rf'(?P<qualifiers>(?:\s*\(\s*(?:mean|{_PRESSURE_UNIT})\s*\))*)'
    r'\s*:?\s*(?P<body>.*)$', re.IGNORECASE,
)
_SUMMARY_START = re.compile(r'^(?:avg|average|min|minimum|max|maximum)\s*:', re.IGNORECASE)
_PRESSURE_VALUE = re.compile(
    rf'(?P<number>[+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(?P<unit>{_PRESSURE_UNIT})?',
    re.IGNORECASE,
)
_NO_DATA = {'no data recorded', 'not recorded', 'not documented', 'none', 'n/a', '--'}


def route(label: str) -> str:
    key = re.sub(r'\s+', ' ', label.strip().casefold().replace('₂', '2'))
    if re.match(r'^last\s+', key):
        return route(re.sub(r'^last\s+', '', key))
    if re.match(r'^(?:pulse ox(?:imetry)?|pulse oxygen)\b', key):
        return 'Respiratory'
    if re.match(r'^(?:icp|cpp|intracranial pressure|cerebral perfusion pressure|wat(?:[- ]?1)?|target arousal level|sbs|rass)\b', key):
        return 'Neurologic'
    if re.match(r'^(?:temp(?:erature)?|tmax|t min|t max)\b', key):
        return 'Infectious Disease'
    if re.match(rf'^{_ETCO2_NAME}(?=$|[\s:(])', key, re.IGNORECASE):
        return 'Respiratory'
    if re.match(r'^(?:resp(?:iratory)?(?: rate)?|respirations|rr|spo2|sao2|oxygen saturation|o2 sat(?:uration)?|fio2)\b', key):
        return 'Respiratory'
    if re.match(r'^(?:heart rate|hr|pulse(?: rate)?|bp|blood pressure|systolic|diastolic|sbp|dbp|map|mean arterial pressure|abp|art(?:erial)?(?: line)?(?: bp| blood pressure| pressure)?|cvp|central venous pressure|pap|pulmonary artery pressure)\b', key):
        return 'Cardiovascular'
    return 'Other'


def validate_vitals(rows: list[dict]) -> None:
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError('The vital-sign list is invalid or too large.')
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'label', 'value', 'section', 'include'}:
            raise ValueError('A vital-sign row has an invalid structure.')
        if row['section'] not in ('Neurologic', 'Respiratory', 'Cardiovascular', 'Infectious Disease', 'Other') or not isinstance(row['include'], bool):
            raise ValueError('A vital-sign destination or inclusion setting is invalid.')
        for key in ('label', 'value'):
            if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > 1500 or '\n' in row[key] or '\r' in row[key]:
                raise ValueError('A vital-sign field is empty or invalid.')


@dataclass
class VitalsResult:
    rows: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    error: str = ''



_SPO2_SUMMARY = re.compile(
    r'^(?:spo[2₂]|pulse ox(?:imetry)?)(?P<units>\s*\(\s*%\s*\))?\s*:?\s*'
    r'(?=(?:avg|average|min|minimum|max|maximum)\s*:)', re.IGNORECASE,
)
_SUMMARY_STAT = re.compile(r'\b(avg|average|min|minimum|max|maximum)\s*:', re.IGNORECASE)
_PERCENT_VALUE = re.compile(r'(?P<number>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>%?)')


def spo2_summary_range(text: str) -> str | None:
    """Return explicit Min/Max only, or None for an ordinary vital-sign line.

    Handle an optional colon after SpO2, tabs, nonbreaking spaces, subscript 2,
    decimals and reordered statistics. An incomplete/conflicting summary raises
    an actionable error instead of inventing endpoints or substituting Avg.
    """
    text = text.strip()
    prefix = _SPO2_SUMMARY.match(text)
    if prefix is None:
        return None
    stats_text = text[prefix.end():]
    markers = list(_SUMMARY_STAT.finditer(stats_text))
    limits: dict[str, str] = {}
    for index, marker in enumerate(markers):
        stat = marker.group(1).casefold()
        if stat in ('avg', 'average'):
            continue
        stat = 'min' if stat.startswith('min') else 'max'
        end = markers[index + 1].start() if index + 1 < len(markers) else len(stats_text)
        source = stats_text[marker.end():end].strip()
        value = _PERCENT_VALUE.fullmatch(source)
        if value is None or (not value.group('unit') and not prefix.group('units')):
            raise ValueError('SpO2 Min and Max need numeric percentage values. Nothing was imported.')
        number = value.group('number')
        if not Decimal('0') <= Decimal(number) <= Decimal('100'):
            raise ValueError('SpO2 Min and Max must be between 0% and 100%. Check the source. Nothing was imported.')
        if stat in limits and Decimal(limits[stat]) != Decimal(number):
            raise ValueError('The SpO2 summary has conflicting repeated Min or Max values. Nothing was imported.')
        limits.setdefault(stat, number)
    if set(limits) != {'min', 'max'}:
        raise ValueError('The SpO2 summary needs both Min and Max. The average cannot supply a missing limit. Nothing was imported.')
    if Decimal(limits['min']) > Decimal(limits['max']):
        raise ValueError('SpO2 Min is greater than Max. Check the source. Nothing was imported.')
    return limits['min'] + '% to ' + limits['max'] + '%'


def _unit_name(value: str) -> str:
    """Normalize unit typography only. Never convert values or infer a unit."""
    key = re.sub(r'\s+', '', value.casefold().replace('₂', '2'))
    return {'mmhg': 'mmHg', 'cmh2o': 'cmH2O', 'kpa': 'kPa', '': ''}[key]


def _no_monitor_data(text: str) -> bool:
    """Only discard explicit absence for a recognized monitor, not free text."""
    prefix = _MONITOR_PREFIX.match(text)
    if prefix is None:
        return False
    body = prefix.group('body').strip().rstrip('.:').casefold()
    return not body or body in _NO_DATA


def monitor_summary_range(text: str) -> tuple[str, str] | None:
    """Read the recorded ETCO2/CVP Min and Max, independent of the average.

    ETCO2 and CVP are pressures, not percentages. No 0-100 bound is applied.
    Units must agree, or be supplied by the field label. Absent units are left
    absent. Missing/conflicting limits are never sorted, filled or averaged.
    Ordinary label:value lines are deliberately returned to the original parser.
    """
    prefix = _MONITOR_PREFIX.match(text.strip())
    if prefix is None or _SUMMARY_START.match(prefix.group('body')) is None:
        return None
    is_etco2 = re.fullmatch(_ETCO2_NAME, prefix.group('name'), re.IGNORECASE) is not None
    qualifiers = prefix.group('qualifiers')
    label = 'ETCO2' if is_etco2 else ('CVP (mean)' if re.search(r'\(\s*mean\s*\)', qualifiers, re.IGNORECASE) else 'CVP')
    hints = [_unit_name(m.group(0)) for m in re.finditer(_PRESSURE_UNIT, qualifiers, re.IGNORECASE)]
    if len(set(hints)) > 1:
        raise ValueError(label + ' has conflicting pressure units in its label. Check the source.')
    hint = hints[0] if hints else ''
    text = prefix.group('body')
    markers = list(_SUMMARY_STAT.finditer(text))
    limits: dict[str, tuple[str, str]] = {}
    for index, marker in enumerate(markers):
        stat = marker.group(1).casefold()
        if stat in ('avg', 'average'):
            continue
        stat = 'min' if stat.startswith('min') else 'max'
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        value = _PRESSURE_VALUE.fullmatch(text[marker.end():end].strip())
        if value is None:
            raise ValueError(label + ' Min and Max need numeric values with consistent pressure units. Check the source.')
        number = value.group('number')
        unit = _unit_name(value.group('unit') or '') or hint
        if hint and unit != hint:
            raise ValueError(label + ' has conflicting pressure units. Check the source.')
        if stat in limits and (Decimal(limits[stat][0]) != Decimal(number) or limits[stat][1] != unit):
            raise ValueError(label + ' has conflicting repeated Min or Max values. Check the source.')
        limits.setdefault(stat, (number, unit))
    if set(limits) != {'min', 'max'}:
        raise ValueError(label + ' needs both Min and Max. The average cannot supply a missing limit.')
    if limits['min'][1] != limits['max'][1]:
        raise ValueError(label + ' Min and Max use different or incomplete units. Check the source.')
    if Decimal(limits['min'][0]) > Decimal(limits['max'][0]):
        raise ValueError(label + ' Min is greater than Max. Check the source.')
    unit = limits['min'][1]
    return label, limits['min'][0] + ' to ' + limits['max'][0] + (' ' + unit if unit else '')


def parse_vitals(block: str) -> VitalsResult:
    out = VitalsResult()
    for number, raw in enumerate(block.splitlines(), 1):
        text = raw.strip()
        if not text or text.rstrip(':').casefold() in ('vitals', 'vital signs', 'none', 'not documented'):
            continue
        try:
            arterial = parse_arterial_line(text)
        except ValueError as exc:
            out.error = f'Vital-sign line {number}: {exc}'
            return out
        if arterial is not None:
            label, value = arterial
            if label:
                out.rows.append({'label': label, 'value': value,
                                 'section': 'Cardiovascular', 'include': True})
            continue
        last = re.match(r'(?i)^Last\s+(SpO[2₂]|Pulse Ox(?:imetry)?|ET\s*CO[2₂]|CVP)\s*:\s*(.*)$', text)
        if last:
            kind = monitor_kind(last.group(1))
            value = last.group(2).strip()
            value = re.sub(r'(?i)^(?:SpO[2₂]|Pulse Ox(?:imetry)?|ET\s*CO[2₂]|CVP)(?:\s*\([^)]*\))*\s*:\s*', '', value)
            if not value or value.casefold().rstrip('.:') in _NO_DATA:
                continue
            if not re.fullmatch(r'(?:\(!\)\s*)?[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*(?:%|mm\s*Hg|cm\s*H[2₂]O|kPa)?', value, re.I):
                out.issues.append('A latest monitor value could not be read. Its range was retained without a bracketed last value.')
                continue
            out.rows.append({'label': 'Last ' + kind, 'value': value,
                             'section': 'Cardiovascular' if kind == 'CVP' else 'Respiratory', 'include': True})
            continue
        if text.rstrip('.:').casefold() == 'no data recorded'  or _no_monitor_data(text):
            continue
        try:
            summary = monitor_summary_range(text)
        except ValueError as exc:
            out.error = f'Vital-sign line {number}: {exc}'
            return out
        if summary is not None:
            label, value = summary
            out.rows.append({'label': label, 'value': value,
                             'section': route(label), 'include': True})
            continue
        try:
            saturation_range = spo2_summary_range(text)
        except ValueError as exc:
            out.error = f'Vital-sign line {number}: {exc}'
            return out
        if saturation_range is not None:
            out.rows.append({'label': 'SpO2', 'value': saturation_range,
                             'section': 'Respiratory', 'include': True})
            continue
        if ':' not in text:
            out.error = f'Vital-sign line {number} needs a label followed by a colon. Nothing was imported.'
            return out
        label, value = (x.strip() for x in text.split(':', 1))
        if not value:
            out.issues.append('A blank vital-sign field was left out.')
            continue
        section = route(label)
        out.rows.append({'label': label, 'value': value, 'section': section, 'include': True})
        if section == 'Other':
            out.issues.append('An unrecognized vital-sign label was retained in Other for review.')
    try:
        validate_vitals(out.rows)
    except ValueError as exc:
        out.error = str(exc)
    return out


def monitor_kind(label: str) -> str:
    key = re.sub(r'\s+', ' ', label.strip().casefold().replace('₂', '2'))
    key = re.sub(r'^last\s+', '', key)
    if re.match(r'^(?:spo2|pulse ox(?:imetry)?)(?=$|[\s:(])', key):
        return 'SpO2'
    if re.match(rf'^{_ETCO2_NAME}(?=$|[\s:(])', key, re.I):
        return 'ETCO2'
    if re.match(rf'^{_CVP_NAME}(?=$|[\s:(])', key, re.I):
        return 'CVP'
    return ''


def _latest_parts(value: str) -> tuple[str, str] | None:
    # Also understands last-value rows saved by earlier releases in Other.
    value = re.sub(r'(?i)^(?:SpO[2₂]|Pulse Ox(?:imetry)?|ET\s*CO[2₂]|CVP)(?:\s*\([^)]*\))*\s*:\s*', '', value.strip())
    m = re.fullmatch(r'(?P<flag>\(!\)\s*)?(?P<number>[+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(?P<unit>%|mm\s*Hg|cm\s*H[2₂]O|kPa)?', value, re.I)
    if not m:
        return None
    unit = m.group('unit') or ''
    unit = '%' if unit == '%' else _unit_name(unit)
    return (('(!) ' if m.group('flag') else '') + m.group('number'), unit)


def text_by_system(rows: list[dict]) -> dict[str, str]:
    result = {}
    active = arterial_display_rows(rows)
    consumed = set()
    def add(section, text):
        result[section] = (result.get(section, '') + '\n' + text).strip()
    for index, row in enumerate(active):
        kind = monitor_kind(row['label'])
        is_last = row['label'].strip().lower().startswith('last ')
        if is_last and kind:
            continue
        value = row['value']
        if kind and ' to ' in value:
            candidates = [(i, _latest_parts(r['value'])) for i, r in enumerate(active)
                          if monitor_kind(r['label']) == kind and r['label'].strip().lower().startswith('last ')]
            parts = {parts for _, parts in candidates if parts is not None}
            if len(parts) == 1:
                last_value, unit = next(iter(parts))
                range_unit = '%' if '%' in value else next((_unit_name(m.group(0)) for m in re.finditer(_PRESSURE_UNIT, value, re.I)), '')
                if (unit == range_unit) or not unit:
                    value += ' [' + last_value + ']'
                    consumed.update(i for i, parts in candidates if parts is not None)
        add(row['section'], row['label'] + ': ' + value)
    for index, row in enumerate(active):
        kind = monitor_kind(row['label'])
        if index in consumed or not kind or not row['label'].strip().lower().startswith('last '):
            continue
        if not row['value'].strip() or row['value'].strip().casefold() in _NO_DATA:
            continue
        has_range = any(monitor_kind(r['label']) == kind and ' to ' in r['value'] for r in active)
        parts = _latest_parts(row['value'])
        value = (parts[0] + (' ' + parts[1] if parts[1] else '')) if parts else row['value']
        add('Cardiovascular' if kind == 'CVP' else 'Respiratory', ('Last ' if has_range else '') + kind + ': ' + value)
    return result
