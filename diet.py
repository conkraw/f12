"""Dietary orders with separate oral, enteral and parenteral source records.

Legacy compact X snapshots remain readable. Detailed dietary orders retain
explicit route, formula, rate and feeding hours without estimating delivery.
Dates do not silently cancel another listed order, and medication exceptions
or milk-label printing are never interpreted as permission to feed.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html import escape
import re
import uuid
from import_review import diagnostic
from feeds import feeding_method, METHODS

MAX_ROWS = 100
MAX_SOURCE = 6000
EMPTY = re.compile(r'^(?:none|no (?:active )?(?:diet(?:ary)? )?orders?(?: found)?|no data(?: recorded)?|not documented)\.?$', re.I)
IGNORE = re.compile(
    r'\b(?:parenteral nutrition|TPN|PPN|PN)\b|'
    r'\b(?:print(?:ing)? labels?|labels? only|breast\s*milk labels?|breastmilk labels?)\b|'
    r'^\s*(?:fat emulsion|SMOFlipid|Intralipid|nutrition consult|dietitian consult|calorie count)\b', re.I)
REMOVED = re.compile(r'^\s*(?:\[(?:REMOVED|DISCONTINUED|CANCELLED|CANCELED)\]|(?:Discontinued|Canceled|Cancelled)\s*:)', re.I)
STARTS = re.compile(r'\s+starting\s+(?:at|on)\s+.+$', re.I)
ENTERAL_KEYS = {'id', 'source', 'method', 'route', 'formula', 'feeding_type',
                'rate', 'hours', 'daily_volume', 'caloric_density', 'additives',
                'comments', 'status', 'include'}
PARENTERAL_KEYS = {'id', 'source', 'name', 'rate', 'status', 'include'}
NUTRITION_STATUSES = ('active', 'held', 'future')
MAX_NUMERIC_LENGTH = 20
_NUTRITION_NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
_CANONICAL_NUMBER = re.compile(r'\d+(?:\.\d+)?')
_NUTRITION_RATE = re.compile(rf'(?P<number>{_NUTRITION_NUMBER})\s*mL\s*(?:/\s*(?:h|hr|hrs|hour|hours)|per\s+hour)\b', re.I)
_TUBE_ORDER = re.compile(r'^(?:Diet,?\s*tube\s*feeding|(?:(?:Infant|Pediatric|Peds|Adult)\s+)?tube\s*feeding)\b', re.I)
_PN_ORDER = re.compile(r'\b(?:parenteral nutrition|TPN|PPN|PN)\b', re.I)
_ANNOTATION = re.compile(r'^\s*\[(?P<kind>START ON|HELD BY PROVIDER)[^\]]*\]\s*', re.I)
_ORDER_TIMESTAMP = re.compile(r'^\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})\s+\d{4}\s*$')
_QA_LABELS = {
    'diet': 'diet', 'formula': 'formula', 'type': 'feeding_type', 'route': 'route',
    'infusion time (hours)': 'hours',
    'tube feeding continuous rate (ml/hr)': 'rate',
    'total volume (ml/day)': 'daily_volume',
    'additives?': 'additives_flag', 'select additive': 'additives',
    'caloric density (kcal per ounce)': 'caloric_density',
    'caloric density (kcal/oz)': 'caloric_density',
    'caloric density (kcal per ml)': 'caloric_density',
    'caloric density (kcal/ml)': 'caloric_density',
    'caloric density (kcal per milliliter)': 'caloric_density',
    'caloric density (kcal per l)': 'caloric_density',
    'caloric density (kcal/l)': 'caloric_density',
    'caloric density (kcal per liter)': 'caloric_density',
    'caloric density': 'caloric_density',
    'diet type': 'oral_type', 'npo except': 'npo_except',
    'explanatory comment': 'npo_comment',
}
_DENSITY_LABEL_UNITS = {
    'caloric density (kcal per ounce)': 'kcal/oz',
    'caloric density (kcal/oz)': 'kcal/oz',
    'caloric density (kcal per ml)': 'kcal/mL',
    'caloric density (kcal/ml)': 'kcal/mL',
    'caloric density (kcal per milliliter)': 'kcal/mL',
    'caloric density (kcal per l)': 'kcal/L',
    'caloric density (kcal/l)': 'kcal/L',
    'caloric density (kcal per liter)': 'kcal/L',
}
_DENSITY_VALUE = re.compile(
    rf'(?P<number>{_NUTRITION_NUMBER})\s*kcal\s*(?:/\s*|per\s+)'
    r'(?P<unit>mL|millilit(?:er|re)s?|L|lit(?:er|re)s?|oz|ounces?)', re.I)
_QA_START = re.compile(r'^(' + '|'.join(re.escape(k) for k in sorted(_QA_LABELS, key=len, reverse=True)) + r')\s*(?::\s*|\s+|$)(.*)$', re.I)


@dataclass
class DietResult:
    data: dict = field(default_factory=lambda: {"rows": []})
    issues: list[str] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    error: str = ''


def validate_diet(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) not in ({'rows'}, {'rows', 'enteral', 'parenteral'}, {'rows', 'enteral', 'parenteral', 'recorded_feed_ids'}) or not isinstance(data['rows'], list) or len(data['rows']) > MAX_ROWS:
        raise ValueError('The dietary snapshot has an invalid structure or is too large.')
    if 'recorded_feed_ids' in data:
        values = data['recorded_feed_ids']
        if (not isinstance(values, list) or len(values) > 50
                or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}', value) for value in values)
                or len(set(values)) != len(values)):
            raise ValueError('The dietary snapshot feeding references are invalid.')
    ids = set()
    for row in data['rows']:
        if not isinstance(row, dict) or set(row) != {'id', 'source', 'text', 'include'}:
            raise ValueError('A dietary row has an invalid structure.')
        if not isinstance(row['id'], str) or not re.fullmatch(r'[0-9a-f]{32}', row['id']) or row['id'] in ids:
            raise ValueError('Dietary row identifiers must be unique.')
        ids.add(row['id'])
        for key, limit in (('source', MAX_SOURCE), ('text', 500)):
            value = row[key]
            if not isinstance(value, str) or not value.strip() or len(value) > limit or any(c in value for c in '\n\r\t'):
                raise ValueError('A dietary field is empty or invalid.')
        if not isinstance(row['include'], bool):
            raise ValueError('A dietary inclusion setting is invalid.')
    for kind, keys in (('enteral', ENTERAL_KEYS), ('parenteral', PARENTERAL_KEYS)):
        rows = data.get(kind, [])
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            raise ValueError('The nutrition order list is invalid or too large.')
        for row in rows:
            if not isinstance(row, dict) or set(row) != keys:
                raise ValueError('A nutrition order has an invalid structure.')
            if not isinstance(row['id'], str) or not re.fullmatch(r'[0-9a-f]{32}', row['id']) or row['id'] in ids:
                raise ValueError('Nutrition order identifiers must be unique.')
            ids.add(row['id'])
            if not isinstance(row['include'], bool) or row['status'] not in NUTRITION_STATUSES:
                raise ValueError('A nutrition order display setting is invalid.')
            for key in keys - {'id', 'include', 'status'}:
                limit = MAX_SOURCE if key == 'source' else 4000 if key == 'comments' else 1200 if key == 'additives' else 80 if key == 'rate' else 600
                value = row[key]
                if not isinstance(value, str) or len(value) > limit or any(c in value for c in '\n\r\t'):
                    raise ValueError('A nutrition order field is invalid or too long.')
            if not row['source'].strip():
                raise ValueError('A nutrition order source is empty.')
            if row['rate'] and (not _NUTRITION_RATE.fullmatch(row['rate']) or not row['rate'].endswith(' mL/hr')):
                raise ValueError('Use a documented nutrition rate in mL/hr, or leave it blank.')
            if row['rate'] and len(_NUTRITION_RATE.fullmatch(row['rate'])['number'].replace(',', '')) > MAX_NUMERIC_LENGTH:
                raise ValueError('The nutrition rate has too many numeric characters.')
            if kind == 'enteral':
                if row['method'] not in METHODS:
                    raise ValueError('The enteral feeding method is invalid.')
                for key in ('hours', 'daily_volume'):
                    if row[key] and (not _CANONICAL_NUMBER.fullmatch(row[key]) or len(row[key]) > MAX_NUMERIC_LENGTH):
                        raise ValueError('Use a nonnegative numeric nutrition value, or leave it blank.')
                if row['hours'] and not 0 < Decimal(row['hours']) <= 24:
                    raise ValueError('Feeding hours per day must be greater than zero and no more than 24.')
            elif not row['name'].strip():
                raise ValueError('A parenteral nutrition order name is empty.')


def _label(value: str) -> str:
    """Normalize only explicitly supported common labels, not clinical content."""
    value = re.sub(r'\s+', ' ', value.strip())
    common = {
        'regular': 'Regular', 'general': 'Regular', 'clear liquid': 'Clear Liquid',
        'clear liquids': 'Clear Liquid', 'full liquid': 'Full Liquid', 'full liquids': 'Full Liquid',
        'pureed': 'Pureed', 'puree': 'Pureed', 'soft': 'Soft', 'soft and bite-sized': 'Soft and Bite-Sized',
        'minced and moist': 'Minced and Moist', 'mechanical soft': 'Mechanical Soft',
        'heart healthy': 'Heart Healthy', 'cardiac': 'Cardiac', 'renal': 'Renal',
    }
    return common.get(value.casefold(), value)


def _strip_duplicate_type(value: str) -> str:
    """Remove Epic's trailing category, not restrictions or consistency text."""
    return re.sub(r':\s*(?:General|NPO|Tube Feeding)\s*$', '', value, flags=re.I).strip(' :;')


def summarize_order(source: str) -> str | None:
    dietary = re.match(r'^(?:\[[^\]]+\]\s*)?(?:(?:Adult|Pediatric|Peds|Infant)\s+)?(?:diet\b|NPO\b|tube\s*feeding\b)', source, re.I)
    if REMOVED.search(source) or (IGNORE.search(source) and not dietary):
        return None
    text = STARTS.sub('', source).strip()
    # Future start annotations and held labels are not silently converted to active diets.
    annotation = ''
    pref = re.match(r'^(\[(?:START ON|HELD BY PROVIDER)[^\]]*\])\s*(.*)$', text, re.I)
    if pref:
        annotation, text = pref.group(1) + ' ', pref.group(2)
    text = _strip_duplicate_type(text)
    if re.match(r'^(?:NPO(?:\s+diet)?|Diet\s*:?\s*NPO)\b', text, re.I):
        exception = ''
        found = re.search(r'\bNPO\s+except\s*:\s*(.*)$', text, re.I)
        if found:
            exception = found.group(1).strip()
            comment = re.search(r'\bExplanatory comment\s*:\s*(.+)$', exception, re.I)
            if comment:
                exception = comment.group(1).strip()
            if re.fullmatch(r'Other\s*\(specify\)', _strip_duplicate_type(exception), re.I):
                return annotation + 'NPO (exception unspecified)'
            exception = re.sub(r'^Other\s*\(specify\)\s*[;:]?\s*', '', exception, flags=re.I)
            exception = re.sub(r'\s*\[\d+\]', '', exception)
            exception = _strip_duplicate_type(exception)
            if re.fullmatch(r'(?:No Exceptions|None|NPO)', exception, re.I):
                exception = ''
            elif re.fullmatch(r'Other\s*\(specify\)', exception, re.I):
                exception = 'exception unspecified'
            else:
                exception = re.sub(r'^except\s+(?:for\s+)?', '', exception, flags=re.I)
                exception = re.sub(r'\bmedications?\b', 'meds', exception, flags=re.I)
        return annotation + 'NPO' + (' except ' + exception if exception else '')
    if re.match(r'^(?:Diet,?\s*tube\s*feeding|(?:Infant|Pediatric|Adult)\s+tube\s*feeding|Tube\s*feeding)\b', text, re.I):
        prefix = 'Infant ' if re.match(r'^Infant\b', text, re.I) else 'Peds ' if re.match(r'^Pediatric\b', text, re.I) else 'Adult ' if re.match(r'^Adult\b', text, re.I) else ''
        return annotation + prefix + 'Tube Feeding' + (' (no tray)' if re.search(r'\bno tray\b', text, re.I) else '')
    match = re.match(r'^(?:(Adult|Pediatric|Peds|Infant)\s+)?diet\s*:?\s*(.+)$', text, re.I)
    if match:
        age, value = match.groups()
        # Only the administrative suffix is dropped. Real diet modifications stay.
        value = _strip_duplicate_type(value)
        if not value or value.casefold() in ('orders', 'effective now', 'unknown'):
            return ''
        prefix = {'pediatric': 'Peds ', 'peds': 'Peds ', 'adult': 'Adult ', 'infant': 'Infant '}.get((age or '').casefold(), '')
        return annotation + prefix + _label(value)
    # Direct short descriptions may be supplied after the X-section heading.
    if re.fullmatch(r'(?:Adult |Peds |Pediatric )?(?:Regular|Clear Liquids?|Full Liquids?|Pureed|Soft|Mechanical Soft)', text, re.I):
        text = re.sub(r'^Pediatric\s+', 'Peds ', text, flags=re.I)
        return annotation + _label(text)
    return ''  # Unknown content is not treated as an order.


def _parse_legacy_diet(block: str) -> DietResult:
    out = DietResult()
    if not isinstance(block, str):
        out.error = 'The dietary section is not text.'
        return out
    if len(block) > 60000:
        out.error = 'The dietary section is too large.'
        return out
    lines = block.replace('\r\n', '\n').replace('\r', '\n').replace('\u00a0', ' ').splitlines()
    seen = set()
    for number, raw in enumerate(lines, 1):
        source = re.sub(r'\s+', ' ', re.sub(r'^\s*[•\-]\s*', '', raw)).strip()
        if not source or source.rstrip(':').casefold() in ('diet', 'dietary', 'diet orders', 'dietary orders') or EMPTY.fullmatch(source):
            continue
        if len(source) > MAX_SOURCE:
            out.error = 'Diet line ' + str(number) + ' is too long.'
            return out
        summary = summarize_order(source)
        if summary is None:
            continue
        if not summary:
            out.diagnostics.append(diagnostic('x', 'diet_unrecognized', line=number, action='row_omitted'))
            continue
        if len(summary) > 500:
            out.error = 'Diet line ' + str(number) + ' has an unusually long summary. Review it in Epic.'
            return out
        # Repeated identical summaries do not create duplicate diet labels.
        key = summary.casefold()
        if key not in seen:
            out.data['rows'].append({'id': uuid.uuid4().hex, 'source': source, 'text': summary, 'include': True})
            seen.add(key)
    if len(out.data['rows']) > 1:
        out.diagnostics.append(diagnostic('x', 'diet_multiple', action='field_unknown'))
        out.issues.append('More than one distinct diet order was listed in X. All are shown. Verify which orders apply rather than assuming the newest start time cancels another order.')
    if any(d['code'] == 'diet_unrecognized' for d in out.diagnostics):
        out.issues.append('Unrecognized X-section content was omitted. Review the diet summary against Epic.')
    out.diagnostics = out.diagnostics[:100]
    try:
        validate_diet(out.data)
    except ValueError as exc:
        out.error = str(exc)
    return out


def _compact(value: str) -> str:
    return re.sub(r'\s+', ' ', value.replace('\u00a0', ' ').replace('：', ':')).strip()


def _clean_order_header(value: str) -> str:
    value = re.sub(r'^\s*[•\-]\s*', '', value)
    value = STARTS.sub('', _compact(value))
    value = re.sub(r'\s+Diet\s+effective\s+now\s*$', '', value, flags=re.I)
    return _strip_duplicate_type(value)


def _status_and_body(value: str) -> tuple[str, str]:
    match = _ANNOTATION.match(value)
    if match:
        return ('held' if match['kind'].casefold() == 'held by provider' else 'future'), value[match.end():]
    return 'active', value


def _order_kind(value: str) -> str:
    if REMOVED.search(value):
        return 'ignored'
    _, body = _status_and_body(value)
    if _TUBE_ORDER.match(body):
        return 'enteral'
    if re.match(r'^(?:(?:Adult|Pediatric|Peds|Infant)\s+)?diet\b|^NPO\b', body, re.I):
        return 'oral'
    if re.match(r'^(?:nutrition consult|dietitian consult|calorie count)\b', body, re.I):
        return 'ignored'
    if _PN_ORDER.search(body):
        return 'parenteral'
    if IGNORE.search(body):
        return 'ignored'
    if summarize_order(value):
        return 'oral'
    return ''


def _qa_label(value: str) -> str:
    value = _compact(value).rstrip(':').casefold()
    value = re.sub(r'\s*\(\s*', ' (', value)
    value = re.sub(r'\s*\)', ')', value)
    return re.sub(r'kcal\s*/\s*', 'kcal/', value)


def _qa_density_value(label: str, value: str) -> str:
    """Carry a density label's units into its answer, without guessing units."""
    value = _compact(value)
    if _QA_LABELS.get(label) != 'caloric_density' or not value:
        return value
    unit = _DENSITY_LABEL_UNITS.get(label)
    if _numeric(value) is not None:
        return value + (' ' + unit if unit else ' (density unit unavailable)')
    explicit = _density_value(value)
    if explicit is not None and unit and not explicit.endswith(' ' + unit):
        # Preserve this conflict in the retained source. A syntactically invalid
        # internal value prevents selection from silently favoring either unit.
        return value + ' (source density unit ' + unit + ')'
    return value


def _qa_pair(raw: str) -> tuple[str, str, str] | None:
    line = raw.replace('\u00a0', ' ').replace('：', ':').strip()
    inline = re.match(r'^Question\s*:\s*(.*?)\s*Answer\s*:\s*(.*)$', line, re.I)
    if inline:
        label, value = inline.groups()
        value, *comment = re.split(r'\s+Comment\s*:\s*', value, maxsplit=1, flags=re.I)
        label = _qa_label(label)
        key = _QA_LABELS.get(label)
        return (key, _qa_density_value(label, value), _compact(comment[0]) if comment else '') if key else None
    if '\t' in line:
        cells = line.split('\t')
        label = _qa_label(cells[0])
        key = _QA_LABELS.get(label)
        if key:
            return key, _qa_density_value(label, cells[1]) if len(cells) > 1 else '', _compact(' '.join(cells[2:]))
    if ':' in line:
        label, value = line.split(':', 1)
        label = _qa_label(label)
        key = _QA_LABELS.get(label)
        if key:
            return key, _qa_density_value(label, value), ''
    match = _QA_START.match(line)
    if match:
        label = _qa_label(match[1])
        return _QA_LABELS[label], _qa_density_value(label, match[2]), ''
    return None


def _numeric(value: str, unit_pattern: str = '') -> str | None:
    pattern = rf'(?P<number>{_NUTRITION_NUMBER})'
    if unit_pattern:
        pattern += rf'(?:\s*(?:{unit_pattern}))?'
    match = re.fullmatch(pattern, _compact(value), re.I)
    if not match:
        return None
    numeric = match['number'].replace(',', '')
    if len(numeric) > MAX_NUMERIC_LENGTH:
        return None
    number = Decimal(numeric)
    return format(number, 'f').rstrip('0').rstrip('.') if '.' in format(number, 'f') else format(number, 'f')


def _density_value(value: str, *, default_unit: str = '') -> str | None:
    """Normalize only an explicit density or the known ounce-based order slot."""
    match = _DENSITY_VALUE.fullmatch(_compact(value))
    if match:
        number = _numeric(match['number'])
        if number is None:
            return None
        source_unit = match['unit'].casefold()
        unit = 'kcal/mL' if source_unit.startswith('ml') or source_unit.startswith('millilit') else 'kcal/L' if source_unit.startswith('l') else 'kcal/oz'
        return number + ' ' + unit
    number = _numeric(value)
    return number + ' ' + default_unit if number is not None and default_unit else None


def _normalize_nutrition_value(field: str, value: str) -> str | None:
    value = _compact(value)
    if value.casefold().rstrip('.') in ('', '--', '-', 'n/a', 'na', 'unk', 'unknown', 'not documented', 'not available'):
        return None if field == 'hours' and value.casefold().rstrip('.') in ('unk', 'unknown') else ''
    if field == 'rate':
        number = _numeric(value, r'mL(?:\s*(?:/\s*(?:h|hr|hrs|hours?)|per\s+hour))?')
        return None if number is None else number + ' mL/hr'
    if field == 'hours':
        number = _numeric(value, r'(?:h|hr|hrs|hours?)(?:\s*(?:/\s*day|per\s+day))?')
        return number if number is not None and 0 < Decimal(number) <= 24 else None
    if field == 'daily_volume':
        return _numeric(value, r'mL(?:\s*(?:/\s*day|per\s+day))?')
    if field == 'caloric_density':
        return _density_value(value, default_unit='kcal/oz')
    if field == 'feeding_type':
        if re.fullmatch(r'continuous(?:\s+feeds?)?', value, re.I):
            return 'Continuous Feeds'
        if re.fullmatch(r'bolus(?:\s+feeds?)?', value, re.I):
            return 'Bolus Feeds'
    return value


def _field_key(field: str, value: str) -> str:
    if field == 'route':
        method = feeding_method(value)
        if method != 'UNK':
            return method
    return value.casefold()


def _add_field(record: dict, field: str, value: str) -> None:
    if _compact(value):
        record['fields'].setdefault(field, []).append(_compact(value))


def _new_record(kind: str, header: str, number: int) -> dict:
    return {'kind': kind, 'header': _clean_order_header(header), 'fields': {},
            'source': [_compact(header)], 'comments': [], 'number': number}


def _seed_enteral_fields(record: dict) -> None:
    _, body = _status_and_body(record['header'])
    parts = [part.strip() for part in body.split(';')]
    # Only the documented Epic order layout is positional. An incomplete or
    # different order retains its source and available QA fields for review.
    if len(parts) >= 4 and re.search(r'\b(?:Infant|Pediatric|Adult)\s+Tube\s+Feeding\b', parts[0], re.I):
        for field, value in zip(('formula', 'feeding_type', 'route', 'hours', 'rate'), parts[1:6]):
            _add_field(record, field, value)
        tail = parts[6:]
        if tail and (not tail[0] or _numeric(tail[0], r'mL(?:\s*/\s*day)?') is not None):
            _add_field(record, 'daily_volume', tail.pop(0))
        if tail:
            flag = tail.pop(0)
            if re.fullmatch(r'(?:No\s+)?Additives\??', flag, re.I):
                _add_field(record, 'additives_flag', flag)
                remainder = '; '.join(tail).strip()
                if remainder:
                    if re.fullmatch(r'No\s+Additives\??', flag, re.I):
                        _add_field(record, 'caloric_density', remainder)
                    else:
                        _add_field(record, 'additives', remainder)
            elif flag:
                # The total volume field cannot shift into additives merely
                # because its value was unreadable.
                _add_field(record, 'daily_volume', flag)
                if tail:
                    _add_field(record, 'additives', '; '.join(tail))


def _record_source(record: dict) -> str:
    return ' | '.join(dict.fromkeys(_compact(value) for value in record['source'] if _compact(value)))


def _nutrition_conflict(out: DietResult, field: str, number: int) -> None:
    out.diagnostics.append(diagnostic('x', 'nutrition_conflict', line=number,
                                      field=field if field in {'method', 'formula', 'rate', 'hours', 'daily_volume', 'caloric_density', 'additives', 'route', 'feeding_type'} else '',
                                      action='field_unknown'))


def _select_field(record: dict, field: str, out: DietResult) -> str:
    values = []
    invalid = False
    for raw in record['fields'].get(field, []):
        value = _normalize_nutrition_value(field, raw)
        if value is None:
            invalid = True
        elif value:
            values.append(value)
    unique = {}
    for value in values:
        unique.setdefault(_field_key(field, value), value)
    if invalid or len(unique) > 1:
        _nutrition_conflict(out, field, record['number'])
        return ''
    return next(iter(unique.values()), '')


def _oral_rows(record: dict, out: DietResult) -> list[dict]:
    source = _record_source(record)
    base = summarize_order(record['header']) or ''
    variants = [base] if base else []
    status, body = _status_and_body(record['header'])
    annotation = record['header'][:len(record['header']) - len(body)]
    prefix = re.match(r'^(?:(Adult|Pediatric|Peds|Infant)\s+)?diet\b', body, re.I)
    for raw in record['fields'].get('oral_type', []):
        text = ((prefix[1] + ' ') if prefix and prefix[1] else '') + 'diet ' + raw
        summary = summarize_order(annotation + text)
        if summary:
            variants.append(summary)
    exceptions = record['fields'].get('npo_except', [])
    comments = record['fields'].get('npo_comment', [])
    if exceptions or comments:
        for exception in exceptions or ['Other (specify)']:
            for comment in comments or ['']:
                summary = summarize_order(annotation + 'NPO diet NPO except: ' + exception +
                                          ('; Explanatory comment: ' + comment if comment else ''))
                if summary:
                    variants.append(summary)
    unique = {v.casefold(): v for v in variants}
    # A bare NPO heading or explicitly unspecified exception is completed by
    # its own scoped Question/Answer table. A concrete disagreement is kept.
    header_exception = re.search(r'\bNPO\s+except\s*:', body, re.I)
    if len(unique) > 1 and (exceptions or comments):
        for key in list(unique):
            plain = _status_and_body(unique[key])[1].casefold()
            incomplete_header = plain == 'npo (exception unspecified)' or plain == 'npo' and not header_exception
            if incomplete_header and base == unique[key]:
                unique.pop(key)
    if len(unique) > 1:
        _nutrition_conflict(out, '', record['number'])
    return [{'id': uuid.uuid4().hex, 'source': source, 'text': text, 'include': True}
            for text in unique.values()]


def _enteral_row(record: dict, out: DietResult) -> dict:
    _seed_enteral_fields(record)
    # An explicitly named fortifier density is another source value. Resolve
    # disagreement with a caloric-density answer instead of choosing one.
    for additive in record['fields'].get('additives', []):
        for value in re.findall(rf'({_NUTRITION_NUMBER})\s*kcal\s*/\s*oz\b', additive, re.I):
            _add_field(record, 'caloric_density', value)
    row = {key: '' for key in ENTERAL_KEYS - {'id', 'include'}}
    row.update(id=uuid.uuid4().hex, source=_record_source(record), include=True,
               status=_status_and_body(record['header'])[0])
    for key in ('route', 'formula', 'feeding_type', 'rate', 'hours', 'daily_volume', 'caloric_density', 'additives'):
        row[key] = _select_field(record, key, out)
    flags = {_compact(v).casefold() for v in record['fields'].get('additives_flag', [])}
    if len(flags) > 1:
        _nutrition_conflict(out, 'additives', record['number'])
    if any(re.fullmatch(r'no\s+additives\??', value) for value in flags) and row['additives']:
        row['additives'] = ''
        _nutrition_conflict(out, 'additives', record['number'])
    row['method'] = feeding_method(row['route'])
    row['comments'] = ' '.join(dict.fromkeys(record['comments']))
    continuous = re.fullmatch(r'continuous(?:\s+(?:feeds?|feeding))?', row['feeding_type'], re.I) is not None
    if not row['formula'] or row['method'] == 'UNK' or not row['rate'] or (not row['hours'] and not continuous):
        out.diagnostics.append(diagnostic('x', 'nutrition_incomplete', line=record['number'], action='field_unknown'))
    return row


def _parenteral_row(record: dict, out: DietResult) -> dict:
    status, body = _status_and_body(record['header'])
    rates = list(_NUTRITION_RATE.finditer(body))
    for match in rates:
        _add_field(record, 'rate', match.group())
    name = re.sub(r'\s+at\s+.*$', '', body, flags=re.I).strip()
    return {'id': uuid.uuid4().hex, 'source': _record_source(record), 'name': name,
            'rate': _select_field(record, 'rate', out), 'status': status, 'include': True}


def _detailed_format(block: str) -> bool:
    if re.search(r'^\s*Dietary\s+Orders\b|^\s*Question(?:\s*:|\s+Answer\b)', block, re.I | re.M):
        return True
    for line in block.splitlines():
        clean = _clean_order_header(line)
        if _TUBE_ORDER.match(_status_and_body(clean)[1]) and len(clean.split(';')) >= 7:
            return True
    return False


def parse_diet(block: str, *, detailed: bool = False) -> DietResult:
    """Parse detailed orders when supplied, while accepting legacy snapshots."""
    if not isinstance(block, str) or len(block) > 60000:
        return _parse_legacy_diet(block)
    if not detailed and not _detailed_format(block):
        return _parse_legacy_diet(block)
    out = DietResult(data={'rows': [], 'enteral': [], 'parenteral': []})
    records, current = [], None
    comments_open = False
    normalized = block.replace('\r\n', '\n').replace('\r', '\n').replace('\u00a0', ' ')
    for number, raw in enumerate(normalized.splitlines(), 1):
        line = _compact(re.sub(r'^\s*[•\-]\s*', '', raw))
        if not line:
            continue
        if len(line) > MAX_SOURCE:
            out.error = 'Diet line ' + str(number) + ' is too long.'
            return out
        if re.fullmatch(r'(?:Diet(?:ary)?(?: Orders)?(?: \(From admission, onward\))?|Start(?: Ordered)?|Question Answer(?: Comment)?)\s*:?', line, re.I):
            if re.match(r'^Diet(?:ary)?\s+Orders\b', line, re.I):
                current, comments_open = None, False
            elif re.match(r'^Question\b', line, re.I):
                comments_open = False
            continue
        if _ORDER_TIMESTAMP.fullmatch(line):
            current, comments_open = None, False
            continue
        if EMPTY.fullmatch(line):
            current, comments_open = None, False
            continue
        if re.match(r'^Question\s*:', line, re.I):
            comments_open = False
        if comments_open and current is not None:
            current['source'].append(line)
            current['comments'].append(re.sub(r'^Comments?\s*:\s*', '', line, flags=re.I))
            continue
        qa = _qa_pair(raw)
        if qa:
            field, value, comment = qa
            comments_open = False
            if current is None:
                if field == 'diet' and re.search(r'\btube\s*feeding\b', value, re.I):
                    current = _new_record('enteral', 'Infant tube feeding ' + value, number)
                elif field == 'oral_type':
                    current = _new_record('oral', 'Diet: ' + value, number)
                elif field in ('npo_except', 'npo_comment'):
                    current = _new_record('oral', 'NPO', number)
                else:
                    out.diagnostics.append(diagnostic('x', 'diet_unrecognized', line=number, action='row_omitted'))
                    continue
                records.append(current)
            current['source'].append(line)
            _add_field(current, field, value)
            if comment:
                current['comments'].append(field.replace('_', ' ') + ': ' + comment)
            continue
        comment = re.match(r'^Comments?\s*:\s*(.*)$', line, re.I)
        if comment:
            if current is not None:
                current['source'].append(line)
                if comment[1]:
                    current['comments'].append(comment[1])
                comments_open = True
            continue
        kind = _order_kind(line)
        if kind:
            current = _new_record(kind, line, number)
            records.append(current)
            comments_open = False
            continue
        if comments_open and current is not None:
            current['source'].append(line)
            current['comments'].append(line)
            continue
        out.diagnostics.append(diagnostic('x', 'diet_unrecognized', line=number, action='row_omitted'))

    # The detailed list and compact summary often repeat exactly the same
    # order header. Combine their scoped fields before resolving conflicts.
    combined = {}
    for record in records:
        if record['kind'] == 'ignored':
            continue
        key = (record['kind'], record['header'].casefold())
        if key not in combined:
            combined[key] = record
            continue
        previous = combined[key]
        previous['source'].extend(record['source'])
        previous['comments'].extend(record['comments'])
        for field, values in record['fields'].items():
            previous['fields'].setdefault(field, []).extend(values)
    try:
        for record in combined.values():
            if record['kind'] == 'oral':
                out.data['rows'].extend(_oral_rows(record, out))
            elif record['kind'] == 'enteral':
                out.data['enteral'].append(_enteral_row(record, out))
            elif record['kind'] == 'parenteral':
                out.data['parenteral'].append(_parenteral_row(record, out))
        for group in ('rows', 'enteral', 'parenteral'):
            unique = {}
            for row in out.data[group]:
                fields = ['text'] if group == 'rows' else sorted(set(row) - {'id', 'source', 'comments', 'include'})
                key = tuple((field, row[field].casefold()) for field in fields)
                if key in unique:
                    old = unique[key]
                    if len(row['source']) > len(old['source']):
                        old['source'] = row['source']
                    if group == 'enteral' and row['comments'] and row['comments'] != old['comments']:
                        old['comments'] = ' '.join(v for v in (old['comments'], row['comments']) if v)
                else:
                    unique[key] = row
            out.data[group] = list(unique.values())
        if len(out.data['rows']) > 1:
            out.diagnostics.append(diagnostic('x', 'diet_multiple', action='field_unknown'))
            out.issues.append('Multiple oral diet orders are listed. Verify which apply. Tube feeding and parenteral nutrition remain separate.')
        if any(item['code'] == 'nutrition_conflict' for item in out.diagnostics):
            out.issues.append('Nutrition order fields disagree or could not be read. The affected values were left blank and the source was retained for review.')
        if any(item['code'] == 'nutrition_incomplete' for item in out.diagnostics):
            out.issues.append('A tube feeding order lacks a documented formula, route, rate or required schedule. Review the incomplete fields.')
        if any(item['code'] == 'diet_unrecognized' for item in out.diagnostics):
            out.issues.append('Unrecognized dietary-order content was omitted. Review the retained orders against the source.')
        out.diagnostics = out.diagnostics[:100]
        validate_diet(out.data)
    except (ValueError, InvalidOperation) as exc:
        out.error = str(exc)
    return out


def diet_failed(sheet: dict) -> bool:
    return any(d['action'] == 'diet_hidden' for section in ('x', 'ab')
               for d in sheet.get('import_warnings', {}).get(section, []))


def diet_for_output(sheet: dict) -> dict | None:
    return None if diet_failed(sheet) else sheet.get('diet')


def diet_text(data: dict | None, rich: bool = False, esc=escape) -> str:
    if data is None:
        return ''
    rows = [r for r in data['rows'] if r['include']]
    if not rows:
        return ''
    label = '<b>Diet:</b> ' if rich else 'Diet: '
    encode = esc if rich else lambda value: value
    return label + ' | '.join(encode(r['text']) for r in rows)
