"""T-block feeding display. Never treat an intake volume as an hourly rate.

Feed rates and formulas are matched by the complete active device label. Removed
lines, source tube size/site details, and backup volumes do not print. There is
no lookup in medications, orders or old snapshots, and no volume/time division.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html import escape
import re
import uuid

from import_review import diagnostic

METHODS = ("UNK", "NJ", "NG", "OG", "ND", "GT", "GJ", "PEG", "PEG-J", "J", "PEJ", "PO", "Post-pyloric")
RATE_SOURCES = ("primary", "backup", "manual", "unknown")
ROW_KEYS = {"id", "device", "method", "formula", "rate", "rate_source", "backup_intake", "include"}
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
HOURLY_UNIT = r"m[lL]\s*(?:/\s*(?:h|hr|hrs|hour|hours)\b|per\s+hour\b)"
RATE = re.compile(rf"(?<![\w.\-])(?P<number>{NUMBER})\s*(?P<unit>{HOURLY_UNIT})", re.I)
BARE_VOLUME = re.compile(rf"(?P<number>{NUMBER})\s*(?:m[lL])?", re.I)
REMOVED = re.compile(r"\[\s*removed\s*\]", re.I)
MISSING = {"", "--", "-", "n/a", "na", "unk", "unknown", "none", "not documented", "not available"}
# A field embedded after the device name, not a match on arbitrary prose.
DEVICE_FIELD = re.compile(
    r"^(?P<device>.+?)\s*-\s*(?P<label>Continuous\s+Tube\s+Feeding\s+Ordered\s+Rate\s*"
    r"(?:mL\s*/\s*hr)?\s*(?:\(not\s+calculated\))?|Tube\s+Feeding|"
    r"(?:Back\s*Up\s+)?Feed(?:ing)?\s+Rate(?:\s*\(mL\s*/\s*hr\))?|Intake\s*\(mL\))\s*:\s*(?P<value>.*)$", re.I)
BACKUP_PREFIX = re.compile(r"^Back\s*Up\s+Feed\s+(?P<kind>Rate|Intake)(?P<unit>\s*\(mL\s*/\s*hr\))?\s*:\s*(?P<value>.*)$", re.I)
SIMPLE_FIELD = re.compile(r"^(Feeding Method|Formula|Tube Feeding|Feed(?:ing)? Rate(?:\s*\(mL\s*/\s*hr\))?|Rate(?:\s*\(mL\s*/\s*hr\))?)\s*:\s*(.*)$", re.I)


@dataclass
class FeedsResult:
    data: dict | None = None
    issues: list[str] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    error: str = ""


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _empty(value: str) -> bool:
    return _text(value).casefold().rstrip('.') in MISSING


def feeding_method(device: str) -> str:
    """Abbreviate explicit tube terminology only. No medication-route inference."""
    text = _text(device).casefold()
    tests = (
        ("PEG-J", r"\bpeg\s*[-/]\s*j\b|\bpeg\s+with\s+jejunal\s+extension\b"),
        ("GJ", r"\bgastrojejunostomy\b|\bgastrojejunal\b|\bgj\b|\bg[-/]j\b"),
        ("PEG", r"\bpercutaneous\s+endoscopic\s+gastrostomy\b|\bpeg\b"),
        ("PEJ", r"\bpercutaneous\s+endoscopic\s+jejunostomy\b|\bpej\b"),
        ("NJ", r"\bnasojejunal\b|\bnj(?:t)?\b"),
        ("NG", r"\bnasogastric\b|\bng(?:t)?\b"),
        ("OG", r"\borogastric\b|\bog(?:t)?\b"),
        ("ND", r"\bnasoduodenal\b|\bnd(?:t)?\b"),
        ("J", r"\bjejunostomy\b|\bjejunal\b|\bj(?:-tube|\s+tube)?\b"),
        ("GT", r"\bgastrostomy\b(?!\s*/\s*enterostomy)|\bgastric\s+button\b|\bg[- ]?tube\b|\bgt\b"),
        ("PO", r"^(?:po|oral|by mouth)$"),
        ("Post-pyloric", r"\bnasoenteric\s*\(post[- ]pyloric\)"),
    )
    for method, pattern in tests:
        if re.search(pattern, text):
            return method
    return "UNK"


def _number_key(value: str) -> Decimal:
    return Decimal(value.replace(',', ''))


def _rate_value(value: str, label: str) -> tuple[str, bool]:
    """Return (hourly rate, invalid). Label units can qualify a numeric mL cell."""
    value = _text(value)
    if _empty(value):
        return "", False
    # Multiple/ranged values and arithmetic are not converted into one rate.
    m = RATE.fullmatch(value)
    if m:
        return m['number'] + " mL/hr", False
    m = BARE_VOLUME.fullmatch(value)
    if m and re.search(HOURLY_UNIT, label, re.I):
        return m['number'] + " mL/hr", False
    return "", True


def _formula(value: str) -> tuple[str, str, bool]:
    value = _text(value)
    value = re.sub(r"^Other\s*\(\s*Comment\s*\)\s*", "", value, flags=re.I).strip()
    # Only trim one enclosing parenthetical wrapper, not embedded qualifiers.
    if value.startswith('(') and value.endswith(')'):
        depth = 0
        encloses = True
        for n, char in enumerate(value):
            depth += (char == '(') - (char == ')')
            if depth == 0 and n < len(value) - 1:
                encloses = False
                break
        if encloses:
            value = value[1:-1].strip()
    inline_rate = ""
    invalid_rate = False
    if '@' in value:
        name, raw_rate = value.rsplit('@', 1)
        inline_rate, invalid_rate = _rate_value(raw_rate, "")
        value = name.strip()
    if _empty(value) or value.casefold() in ('other', 'other - note in comment', 'other - note in comments', '(comment)'):
        value = ""
    return value, inline_rate, invalid_rate


def validate_feeds(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != {"rows"} or not isinstance(data['rows'], list) or len(data['rows']) > 50:
        raise ValueError("The feeding snapshot has an invalid structure.")
    ids = set()
    for row in data['rows']:
        if not isinstance(row, dict) or set(row) != ROW_KEYS:
            raise ValueError("A feeding entry has an invalid structure.")
        if not isinstance(row['id'], str) or not re.fullmatch(r'[0-9a-f]{32}', row['id']) or row['id'] in ids:
            raise ValueError("A feeding entry identifier is invalid or repeated.")
        ids.add(row['id'])
        if not isinstance(row['include'], bool) or row['method'] not in METHODS or row['rate_source'] not in RATE_SOURCES:
            raise ValueError("A feeding entry has an invalid display choice.")
        for name, limit in (("device", 600), ("formula", 600), ("rate", 80), ("backup_intake", 120)):
            if not isinstance(row[name], str) or len(row[name]) > limit or any(c in row[name] for c in '\n\r\t'):
                raise ValueError("A feeding field is invalid or too long.")
        if row['rate'] and not RATE.fullmatch(row['rate']):
            raise ValueError("Use a documented feed rate in mL/hr, or leave it blank for UNK.")
        if bool(row['rate']) != (row['rate_source'] != 'unknown'):
            raise ValueError("The feed rate does not match its recorded source.")


def parse_feeds(block: str) -> FeedsResult:
    out = FeedsResult()
    if not isinstance(block, str) or len(block) > 30000:
        out.error = "The T feeding section is invalid or too long."
        return out
    groups: dict[str, dict] = {}
    generic = {'method': [], 'formula': [], 'primary': [], 'backup': [], 'intake': [], 'bad_primary': False, 'bad_backup': False}
    unrecognized = []
    saw_line = False

    def group(device: str) -> dict:
        key = _text(device).casefold()
        if key not in groups:
            groups[key] = {'device': _text(device), 'method': [], 'formula': [], 'primary': [], 'backup': [], 'intake': [], 'bad_primary': False, 'bad_backup': False}
        return groups[key]

    def consume(g: dict, label: str, value: str, backup: str, line: int) -> None:
        low = _text(label).casefold()
        if low in ('tube feeding', 'formula'):
            formula, rate, invalid = _formula(value)
            if formula:
                g['formula'].append(formula)
            if rate:
                g['primary'].append(rate)
            g['bad_primary'] |= invalid
        elif low == 'feeding method':
            if not _empty(value):
                g['method'].append(feeding_method(value))
        elif 'intake' in low or backup == 'intake':
            if not _empty(value):
                g['intake'].append(_text(value))
        else:
            category = 'backup' if backup == 'rate' or 'back' in low else 'primary'
            rate, invalid = _rate_value(value, label)
            if rate:
                g[category].append(rate)
            g['bad_' + category] |= invalid

    for n, raw in enumerate(block.replace('\r\n', '\n').replace('\r', '\n').splitlines(), 1):
        line = raw.strip().replace('\u00a0', ' ')
        if not line or line.rstrip(':.').casefold() in ('feeds', 'feeding', 'enteral feeds', 'none', 'no data', 'not documented', 'no results found'):
            continue
        if REMOVED.search(line):
            continue
        backup = ''
        bm = BACKUP_PREFIX.match(line)
        # An unpopulated template label is an empty section, not a malformed
        # feeding order. Do not treat intake volume as a rate or invent a feed.
        if bm and not bm['value'].strip():
            continue
        saw_line = True
        if bm:
            backup, line = bm['kind'].lower(), bm['value'].strip()
        dm = DEVICE_FIELD.match(line)
        if dm:
            consume(group(dm['device']), dm['label'], dm['value'], backup, n)
            continue
        simple = SIMPLE_FIELD.match(line)
        if simple:
            consume(generic, simple[1], simple[2], backup, n)
            continue
        if backup:
            consume(generic, 'Intake (mL)' if backup == 'intake' else 'Back Up Feed Rate' + (bm['unit'] or ''), line, backup, n)
            continue
        unrecognized.append(n)
    # Generic fields can attach only when exactly one device is present.
    has_generic = any(generic[k] for k in generic)
    if has_generic:
        if len(groups) <= 1:
            g = next(iter(groups.values())) if groups else group('')
            for name in ('method', 'formula', 'primary', 'backup', 'intake'):
                g[name].extend(generic[name])
            g['bad_primary'] |= generic['bad_primary']
            g['bad_backup'] |= generic['bad_backup']
        else:
            out.issues.append("A feeding field was not tied to a specific tube. It was not assigned across multiple devices.")
            out.diagnostics.append(diagnostic('t', 'feeds_unassigned', action='field_unknown'))
    if not groups:
        if saw_line:
            out.error = "No supported active feeding field was found in T. The feeding section was not updated."
        return out
    if len(groups) > 50:
        out.error = "Too many active feeding devices were found in T."
        return out
    rows = []
    unknown_count = 0
    for index, g in enumerate(groups.values(), 1):
        row = {'id': uuid.uuid4().hex, 'device': g['device'], 'method': feeding_method(g['device']),
               'formula': '', 'rate': '', 'rate_source': 'unknown', 'backup_intake': '', 'include': True}
        methods = list(dict.fromkeys(g['method']))
        if methods:
            if len(methods) == 1 and (row['method'] == 'UNK' or row['method'] == methods[0]):
                row['method'] = methods[0]
            else:
                row['method'] = 'UNK'
                out.diagnostics.append(diagnostic('t', 'feeds_conflict', field='method', action='field_unknown'))
        formulas = list(dict.fromkeys(g['formula']))
        if len(formulas) == 1:
            row['formula'] = formulas[0]
        elif len(formulas) > 1:
            # Do not combine conflicting formula names into a fictitious mixture.
            out.diagnostics.append(diagnostic('t', 'feeds_conflict', field='formula', action='field_unknown'))
        row['backup_intake'] = ' | '.join(dict.fromkeys(g['intake']))[:120]

        def unique_rates(values: list[str]) -> list[str]:
            unique = {}
            for value in values:
                unique.setdefault(_number_key(RATE.fullmatch(value)['number']), value)
            return list(unique.values())

        primary = unique_rates(g['primary'])
        backup = unique_rates(g['backup'])
        if len(primary) == 1 and not g['bad_primary']:
            row['rate'], row['rate_source'] = primary[0], 'primary'
        elif primary or g['bad_primary']:
            out.diagnostics.append(diagnostic('t', 'feeds_conflict', field='rate', action='field_unknown'))
        elif len(backup) == 1 and not g['bad_backup']:
            row['rate'], row['rate_source'] = backup[0], 'backup'
        elif backup or g['bad_backup']:
            out.diagnostics.append(diagnostic('t', 'feeds_rate_invalid', field='rate', action='field_unknown'))
        if row['rate_source'] == 'backup':
            out.issues.append("A feeding entry uses its documented backup rate.")
        if not row['rate']:
            unknown_count += 1
        rows.append(row)
    if unrecognized:
        out.issues.append("Unrecognized feeding lines were not interpreted. Check the feeding summary.")
        out.diagnostics.extend(diagnostic('t', 'feeds_unrecognized', line=n, action='row_omitted') for n in unrecognized[:20])
    if unknown_count:
        out.issues.append("A feed rate could not be determined and is shown as UNK. Intake in mL is not converted to mL/hr.")
    if any(r['method'] == 'UNK' or not r['formula'] for r in rows):
        out.issues.append("An unknown feeding method or formula is shown as UNK. You can edit it under FEN / GI.")
    if out.diagnostics:
        out.issues.append("Ambiguous feeding fields are marked UNK rather than guessed. Review them in FEN / GI.")
    out.diagnostics = out.diagnostics[:100]
    out.issues = list(dict.fromkeys(out.issues))
    out.data = {'rows': rows}
    try:
        validate_feeds(out.data)
    except (ValueError, InvalidOperation):
        out.data = None
        out.error = "The feeding snapshot could not be read safely."
    return out


def feeds_text(data: dict | None, rich: bool = False, esc=escape) -> str:
    validate_feeds(data)
    if data is None:
        return ''
    rows = [r for r in data['rows'] if r['include']]
    if not rows:
        return ''
    encode = esc if rich else lambda v: v
    parts = ['<b>Feeds:</b>' if rich else 'Feeds:']
    for row in rows:
        parts.extend(('Feeding Method: ' + encode(row['method']),
                      encode(row['formula'] or 'UNK') + ' @ ' + encode(row['rate'] or 'UNK')))
    return '\n'.join(parts)


def feeds_for_output(sheet: dict) -> dict | None:
    """A failed whole-T import cannot make retained feeding information look fresh."""
    flags = sheet.get('import_warnings', {}).get('t', [])
    if any(item['action'] in ('feeds_hidden', 'not_updated') for item in flags):
        return None
    return sheet.get('feeds')
