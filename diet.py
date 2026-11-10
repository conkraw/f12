"""Compact X-section dietary orders. No inferred feeding permissions.

Nutrition medications and label-only orders are intentionally not duplicated.
T remains the source of tube-feed formula, route, and rate. Every displayed
summary has its source retained for editing. Dates are not used to silently
choose between incompatible listed orders.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from html import escape
import re
import uuid
from import_review import diagnostic

MAX_ROWS = 100
MAX_SOURCE = 6000
EMPTY = re.compile(r'^(?:none|no (?:active )?(?:diet(?:ary)? )?orders?(?: found)?|no data(?: recorded)?|not documented)\.?$', re.I)
IGNORE = re.compile(
    r'\b(?:parenteral nutrition|TPN|PPN|PN)\b|'
    r'\b(?:print(?:ing)? labels?|labels? only|breast\s*milk labels?|breastmilk labels?)\b|'
    r'^\s*(?:fat emulsion|SMOFlipid|Intralipid|nutrition consult|dietitian consult|calorie count)\b', re.I)
REMOVED = re.compile(r'^\s*(?:\[(?:REMOVED|DISCONTINUED|CANCELLED|CANCELED)\]|(?:Discontinued|Canceled|Cancelled)\s*:)', re.I)
STARTS = re.compile(r'\s+starting\s+(?:at|on)\s+.+$', re.I)


@dataclass
class DietResult:
    data: dict = field(default_factory=lambda: {"rows": []})
    issues: list[str] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    error: str = ''


def validate_diet(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != {'rows'} or not isinstance(data['rows'], list) or len(data['rows']) > MAX_ROWS:
        raise ValueError('The dietary snapshot has an invalid structure or is too large.')
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


def parse_diet(block: str) -> DietResult:
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


def diet_failed(sheet: dict) -> bool:
    return any(d['action'] == 'diet_hidden' for d in sheet.get('import_warnings', {}).get('x', []))


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
