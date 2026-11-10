"""Source-faithful Epic lab rows and dated per-component result slots.

The paste has no specimen IDs and often no collection times. A tree is never
claimed to be a same-draw panel. Same-date ties retain the supplied row order.
No lab value, unit, reference range, missing result or lactate is calculated.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import re
import uuid

CBC = ('WBC', 'HGB', 'HCT', 'PLT', 'MCV', 'NEUTROABS', 'LYMPHSABS')
BMP = ('NA', 'K', 'CL', 'CO2', 'BUN', 'CREATININE', 'GLUCOSE', 'CALCIUM', 'MG', 'PHOS')
HEPATIC = ('AST', 'ALT', 'ALKPHOS', 'BILITOT', 'BILIDIR', 'ALBUMIN', 'PROTEIN')
COAG = ('PT', 'INR', 'PTT', 'FIB', 'HEPLMW', 'ANTI-XA')
ARTERIAL = ('PHA', 'PCO2A', 'PO2ART', 'HCO3A', 'BEART', 'O2SATA')
VENOUS = ('PHV', 'PCO2V', 'PO2VEN', 'HCO3V', 'BEV', 'O2SATV')
CAPILLARY = ('PHC', 'PCO2C', 'PO2CAP', 'HCO3C', 'BEC')
INFLAMMATORY = ('CRP', 'PROCAL', 'ESR')
MRSA_COMPONENTS = frozenset(('MRSADNA', 'MRSANPADM'))
PANELS = {'CBC': CBC, 'BMP': BMP, 'Hepatic': HEPATIC, 'Coagulation': COAG,
          'Arterial gas': ARTERIAL, 'Venous gas': VENOUS,
          'Capillary gas': CAPILLARY, 'Inflammatory': INFLAMMATORY}
PANEL_HEADINGS = {
    'complete blood count': 'CBC', 'cbc': 'CBC',
    'basic metabolic panel': 'BMP', 'bmp': 'BMP',
    'hepatic function panel': 'Hepatic', 'liver function panel': 'Hepatic',
    'coagulation profile': 'Coagulation', 'coagulation': 'Coagulation',
    'blood gas': 'Blood gas', 'blood gases': 'Blood gas',
    'inflammatory markers': 'Inflammatory', 'lactic acid': 'Lactate',
    'lactate': 'Lactate', 'other labs': 'Other labs',
}
ALIASES = {
    'MRSADNA:': 'MRSADNA', 'MRSANPADM:': 'MRSANPADM',
    'HEMOGLOBIN': 'HGB', 'HB': 'HGB', 'HEMATOCRIT': 'HCT', 'PLATELETS': 'PLT',
    'SODIUM': 'NA', 'POTASSIUM': 'K', 'CHLORIDE': 'CL', 'BICARBONATE': 'CO2',
    'CARBON DIOXIDE': 'CO2', 'CREAT': 'CREATININE', 'CR': 'CREATININE',
    'GLU': 'GLUCOSE', 'GLUC': 'GLUCOSE', 'CA': 'CALCIUM',
    'MAGNESIUM': 'MG', 'PHOSPHORUS': 'PHOS', 'PHOSPHATE': 'PHOS',
    'ANTI XA': 'ANTI-XA', 'ANTI_XA': 'ANTI-XA',
    'C-REACTIVE PROTEIN': 'CRP', 'C REACTIVE PROTEIN': 'CRP',
    'ALB': 'ALBUMIN', 'TOTAL PROTEIN': 'PROTEIN', 'TP': 'PROTEIN',
    'ALK PHOS': 'ALKPHOS', 'ALKALINE PHOSPHATASE': 'ALKPHOS',
    'TBILI': 'BILITOT', 'TOTAL BILIRUBIN': 'BILITOT',
    'DIRECT BILIRUBIN': 'BILIDIR', 'DBILI': 'BILIDIR',
    'APTT': 'PTT', 'FIBRINOGEN': 'FIB', 'PROCALCITONIN': 'PROCAL',
    'VANCOMYCIN TROUGH': 'VANCOTROUGH', 'VANCOMYCIN, TROUGH': 'VANCOTROUGH',
    'VANCO TROUGH': 'VANCOTROUGH', 'VANCOMYCIN TROUGH LEVEL': 'VANCOTROUGH',
    'THEOPHYLLINE': 'THEOPH', 'THEOPHYLLINE LEVEL': 'THEOPH',
    'PHART': 'PHA', 'PHARTERIAL': 'PHA', 'PCO2ART': 'PCO2A',
    'PO2A': 'PO2ART', 'HCO3ART': 'HCO3A', 'BICARBART': 'HCO3A',
    'PHVEN': 'PHV', 'PCO2VEN': 'PCO2V', 'PO2V': 'PO2VEN',
    'HCO3VEN': 'HCO3V', 'BICARBVEN': 'HCO3V',
    'LACTIC ACID': 'LACTATE', 'LACTICACID': 'LACTATE', 'LACT': 'LACTATE',
    'LACTIC': 'LACTATE', 'LACTIC ACID, PLASMA': 'LACTATE',
    'LACTATEART': 'LACTATE ARTERIAL', 'LACTATE ART': 'LACTATE ARTERIAL',
    'LACTATEVEN': 'LACTATE VENOUS', 'LACTATE VEN': 'LACTATE VENOUS',
}
DATE_TAIL = re.compile(r'(?P<date>\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})(?:\s+(?:\d{1,2}:\d{2}(?::\d{2})?|\d{4})(?:\s*[APap][Mm])?)?)\s*$')
DATE_FORMATS = ('%m/%d/%Y', '%m/%d/%y')
MAX_ROWS = 2000


def canonical(component: str) -> str:
    key = re.sub(r'\s+', ' ', component.strip()).upper()
    return ALIASES.get(key, key)


def is_lactate(component: str) -> bool:
    key = canonical(component)
    return key in ('LACWB', 'LAC') or bool(re.fullmatch(r'(?:LACTATE|LACTIC(?: ACID)?)(?:[ _,-]+(?:ARTERIAL|VENOUS|PLASMA|BLOOD|WHOLE BLOOD|POC))*', key))


def date_parts(value: str) -> tuple[datetime, bool]:
    text = value.strip()
    for base in DATE_FORMATS:
        for timepart in ('', ' %H:%M', ' %H:%M:%S', ' %H%M', ' %I:%M %p', ' %I:%M%p'):
            try:
                return datetime.strptime(text, base + timepart), bool(timepart)
            except ValueError:
                pass
    raise ValueError('A laboratory date could not be read. Use the date from the source, with an optional collection time.')


def short_date(value: str) -> str:
    dt, timed = date_parts(value)
    return dt.strftime('%m/%d/%y %H:%M' if timed else '%m/%d/%y')


def empty_labs() -> dict:
    return {'rows': [], 'notes': []}


def validate_labs(data: dict) -> None:
    if not isinstance(data, dict) or set(data) != {'rows', 'notes'}:
        raise ValueError('The laboratory snapshot has an invalid structure.')
    if not isinstance(data['rows'], list) or len(data['rows']) > MAX_ROWS:
        raise ValueError('The laboratory list is invalid or too large.')
    ids = set()
    for row in data['rows']:
        if not isinstance(row, dict) or set(row) != {'id', 'component', 'value', 'date', 'panel', 'include'}:
            raise ValueError('A laboratory row has an invalid structure.')
        if not isinstance(row['id'], str) or not re.fullmatch(r'[0-9a-f]{32}', row['id']) or row['id'] in ids:
            raise ValueError('Laboratory row identifiers must be unique.')
        ids.add(row['id'])
        for key, limit in (('component', 120), ('value', 1000), ('date', 80), ('panel', 120)):
            if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > limit or '\n' in row[key] or '\r' in row[key]:
                raise ValueError('A laboratory field is empty or invalid.')
        date_parts(row['date'])
        if not isinstance(row['include'], bool):
            raise ValueError('A laboratory inclusion setting is invalid.')
    if not isinstance(data['notes'], list) or len(data['notes']) > 100 or any(not isinstance(x, str) or len(x) > 1000 for x in data['notes']):
        raise ValueError('The laboratory source notes are invalid.')


def panel_for(component: str, source_panel: str = 'Other labs') -> str:
    key = canonical(component)
    if is_lactate(component):
        return 'Lactate'
    if key == 'VANCOTROUGH':
        return 'ID drug levels'
    if key == 'THEOPH':
        return 'Respiratory drug levels'
    for group, components in PANELS.items():
        if key in components:
            return group
    return source_panel


@dataclass
class LabResult:
    data: dict = field(default_factory=empty_labs)
    issues: list[str] = field(default_factory=list)
    error: str = ''


def parse_labs(block: str) -> LabResult:
    out = LabResult()
    group = 'Other labs'
    for number, raw in enumerate(block.replace('\r\n', '\n').replace('\r', '\n').splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        low = re.sub(r'\s+', ' ', line.rstrip(':')).casefold()
        if low in ('labs', 'lab results') or re.fullmatch(r'component\s+value\s+date(?:/time)?', low):
            continue
        if low in PANEL_HEADINGS:
            group = PANEL_HEADINGS[low]
            continue
        if low.startswith(('no results found', 'no labs', 'no laboratory results')) or low == 'none':
            out.data['notes'].append(line)
            continue
        if line.endswith(':') and '\t' not in line and len(line) <= 120:
            group = line[:-1].strip()
            continue
        cols = [c.strip() for c in raw.split('\t')]
        while cols and not cols[0]:
            cols.pop(0)
        while cols and not cols[-1]:
            cols.pop()
        if len(cols) == 3:
            component, value, date = cols
        else:
            # Copy/paste may replace tabs. The date tail and a numeric result
            # boundary allow deterministic parsing without medication-like guessing.
            # The requested MRSA codes provide an exact component boundary
            # for text results, including negative and pending results.
            tail = DATE_TAIL.search(line)
            body = line[:tail.start()].rstrip() if tail else ''
            match = (re.match(r'^(MRSADNA|MRSANPADM)(?:\s*:\s*|\s+)(.+)$', body, re.I)
                     or re.match(r'^(.*?)\s+([<>≤≥]?\s*[-+]?\d.*)$', body)) if tail else None
            if not match:
                out.error = f'Lab block line {number} could not be separated into component, value and date. Nothing was imported.'
                return out
            component, value, date = match.group(1), match.group(2), tail.group('date')
        try:
            date_parts(date)
            if not component or not value:
                raise ValueError
            row = {'id': uuid.uuid4().hex, 'component': component, 'value': value,
                   'date': date, 'panel': panel_for(component, group), 'include': True}
            out.data['rows'].append(row)
        except ValueError:
            out.error = f'Lab block line {number} has a missing value or unrecognized date. Nothing was imported.'
            return out
    try:
        validate_labs(out.data)
    except ValueError as exc:
        out.error = str(exc)
        return out
    if out.data['rows']:
        out.issues.append('Lab trees show latest/preceding results per component, not verified same-draw panels. Same-date results without times keep the order supplied by Epic.')
    return out


def ordered_components(data: dict) -> dict[str, list[dict]]:
    """Latest dates first. Order within a date is timed only when all rows are timed."""
    buckets = defaultdict(list)
    for row in data['rows']:
        if row['include']:
            buckets[canonical(row['component'])].append(row)
    result = {}
    for component, rows in buckets.items():
        days = defaultdict(list)
        for row in rows:
            days[date_parts(row['date'])[0].date()].append(row)
        ordered = []
        for day in sorted(days, reverse=True):
            same_day = days[day]
            if all(date_parts(row['date'])[1] for row in same_day):
                same_day = sorted(same_day, key=lambda r: date_parts(r['date'])[0], reverse=True)
            ordered.extend(same_day)
        result[component] = ordered
    return result


def result_cards(data: dict, include_id_panels: bool = True, blood_gas: dict | None = None, cbc: dict | None = None) -> list[dict]:
    """Structured lab cards shared by PDF, HTML and plain-text exports.

    Coagulation stays immediately below Hepatic in the laboratory area.
    Only inflammatory markers are routed to ID when include_id_panels is False.
    """
    groups = ordered_components(data)
    from cbc import cbc_cards, cbc_component
    cards = cbc_cards(data, cbc)
    consumed = {key for key in groups if cbc_component(key)}
    # Theophylline is displayed once in RESP, not again in the bottom lab area.
    consumed.add('THEOPH')
    consumed.add('VANCOTROUGH')
    consumed.update(MRSA_COMPONENTS)  # latest combined screen is in demographics
    for name, components, count, kind in (('BMP', BMP, 2, 'bmp'),):
        if not any(key in groups for key in components):
            continue
        for index in range(count):
            rows = {k: groups[k][index] for k in components if len(groups.get(k, [])) > index}
            if rows:
                cards.append({'title': name + (' | latest per component' if index == 0 else ' | preceding per component'),
                              'kind': kind, 'rows': rows})
        consumed.update(components)
    for name, components in PANELS.items():
        if name in ('CBC', 'BMP'):
            continue
        if name in ('Arterial gas', 'Venous gas', 'Capillary gas'):
            consumed.update(components)
            continue
        rows = {k: groups[k][0] for k in components if k in groups}
        if rows and (include_id_panels or name != 'Inflammatory'):
            cards.append({'title': name + ' | latest', 'kind': 'branch', 'rows': rows})
        consumed.update(components)
    from blood_gases import gas_card
    gas = gas_card(data, blood_gas)
    if gas:
        # After hepatic/coagulation, before any other ancillary results.
        insert_at = next((i for i, card in enumerate(cards) if card["title"].startswith("Inflammatory")), len(cards))
        cards.insert(insert_at, gas)
    # Unknown analytes stay visible, without assigning guessed units or a panel.
    other = defaultdict(dict)
    for key, rows in groups.items():
        if key not in consumed and not is_lactate(key):
            other[rows[0]['panel']][key] = rows[0]
    for name, rows in other.items():
        cards.append({'title': name + ' | latest', 'kind': 'branch', 'rows': rows})
    return cards


def is_numeric_lactate(value: str) -> bool:
    """Select measured results only, not specimen rejection or pending messages.

    Preserve the source value verbatim. Units are neither assumed nor converted.
    """
    return bool(re.fullmatch(
        r"[<>≤≥]?\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
        r"(?:\s*(?:mmol/L|mEq/L|mg/dL|mg/L|mmol/l|umol/L|µmol/L))?"
        r"(?:\s*(?:\*|\((?:H|L|HH|LL|A|C|CRIT|HIGH|LOW)\)))*",
        value.strip(), re.I))


def lactate_endpoints(data: dict) -> tuple[dict | None, dict | None, bool]:
    """Earliest/latest usable result ACROSS all documented lactate aliases.

    Dates are compared before source order. Within a day use times only when
    all candidate rows have them, otherwise retain Epic's newest-first order.
    No claim is made about the entire hospital course outside the pasted data.
    """
    candidates = [r for r in data['rows']
                  if r['include'] and is_lactate(r['component'])
                  and is_numeric_lactate(r['value'])]
    days = defaultdict(list)
    for row in candidates:
        days[date_parts(row['date'])[0].date()].append(row)
    ordered = []
    uncertain_days = set()
    for day in sorted(days, reverse=True):
        same_day = days[day]
        if all(date_parts(r['date'])[1] for r in same_day):
            same_day = sorted(same_day, key=lambda r: date_parts(r['date'])[0], reverse=True)
            # A tie can still contain different simultaneous specimen values.
            keys = [date_parts(r['date'])[0] for r in same_day]
            if len(keys) != len(set(keys)) and len({(r['component'], r['value']) for r in same_day}) > 1:
                uncertain_days.add(day)
        elif len(same_day) > 1:
            uncertain_days.add(day)
        ordered.extend(same_day)
    if not ordered:
        return None, None, False
    latest, earliest = ordered[0], ordered[-1]
    uncertain = any(date_parts(r['date'])[0].date() in uncertain_days for r in (earliest, latest))
    return earliest, latest, uncertain


def lactate_text(data: dict) -> str:
    earliest, latest, uncertain = lactate_endpoints(data)
    if latest is None:
        return ''
    def line(label: str, row: dict) -> str:
        # Source code is retained because different assays may use different units.
        return label + ': ' + row['value'] + ' [' + row['date'] + '; ' + row['component'] + ']'
    if earliest['id'] == latest['id']:
        return line('Lactate (only result)', latest)
    lines = [line('Lactate earliest', earliest), line('Lactate latest', latest)]
    if uncertain:
        lines.append('Same-date order follows source; timing unverified.')
    return '\n'.join(lines)


def theophylline_text(data: dict) -> str:
    """Latest included THEOPH result for RESP, without changing source records.

    Use the existing laboratory date/time and same-day ordering rules. Do not
    infer units, a therapeutic range, a missing result, or a medication dose.
    Original rows remain available for editing and exclusion in Labs / Vitals.
    """
    rows = ordered_components(data).get('THEOPH', [])
    if not rows:
        return ''
    row = rows[0]
    return 'Theophylline level: ' + row['value'] + ' [' + row['date'] + ']'


def display_component(component: str) -> str:
    """Clarify the documented anti-Xa code without changing its stored value."""
    return 'Anti-Xa (HEPLMW)' if canonical(component) == 'HEPLMW' else component


def printable_source_notes(notes: list[str]) -> list[str]:
    return [text for text in notes if not re.match(
        r"^\s*(?:Source:\s*)?(?:No results? found|No lab exists|No data recorded)\b", text, re.I)]


def labs_text(data: dict, include_id_panels: bool = True, blood_gas: dict | None = None, cbc: dict | None = None) -> str:
    lines = []
    for card in result_cards(data, include_id_panels=include_id_panels, blood_gas=blood_gas, cbc=cbc):
        if card['kind'] not in ('cbc', 'bmp'):
            lines.append(card['title'].split(' | ', 1)[0])
        for row in card['rows'].values():
            lines.append(display_component(row['component']) + ': ' + row['value'] + (' [' + row['date'] + ']' if row['date'] else ''))
    notes = printable_source_notes(data['notes'])
    if notes:
        lines.extend(['Source notes:'] + notes)
    return '\n'.join(lines)


def id_labs_text(data: dict) -> str:
    """Latest inflammatory results, including CRP and procalcitonin, for ID.

    Coagulation and anti-Xa stay in the bottom lab area below the hepatic panel.
    Matching dates can be shared in a group heading. Mixed dates stay attached
    to their own results. No units, ranges, or collection dates are inferred.
    """
    groups=ordered_components(data)
    lines=[]
    for title,components in (("Inflammatory markers", INFLAMMATORY),):
        rows=[groups[key][0] for key in components if key in groups]
        if not rows:
            continue
        dates={short_date(row["date"]) for row in rows}
        same=len(dates)==1
        heading=title+(" ["+next(iter(dates))+"]" if same else "")
        values=[]
        for row in rows:
            label=display_component(row["component"])
            text=label+": "+row["value"]
            if not same:
                text+=" ["+short_date(row["date"])+"]"
            values.append(text)
        lines.append(heading+": "+" | ".join(values))
    return "\n".join(lines)
