"""Patient-free diagnostics and durable section-level import review flags.

Only allowlisted codes, field names and numeric source positions are retained.
No source text, clinical values, room identifiers or stack traces belong here.
"""
from __future__ import annotations

SECTIONS = {
    'a': 'Diagnoses', 'b': 'Medications', 'cd': 'Respiratory support',
    'e': 'Vitals', 'f': 'Cultures', 'g': 'Labs', 'i': 'Weight / measurements',
    'k': 'Arousal target', 'l': 'WAT', 'm': 'ICP / CPP', 'n': 'Admission',
    'o': 'Viral panel', 'p': 'Blood gas', 'q': 'CBC', 'r': 'Orders',
    's': 'Intake / output', 't': 'Feeds', 'u': 'Devices', 'v': 'Neuro devices', 'w': 'Pacemaker', 'x': 'Diet', 'y': 'CAPD', 'document': 'Paste',
}
CODES = {
    'diet_multiple': 'Multiple distinct diet orders are listed. All are retained; verify which apply.',
    'diet_unrecognized': 'A diet line was not recognized and was omitted. Review the dietary summary.',

    'pacemaker_incomplete': 'A pacemaker mode or matching rate was not supplied. Missing values are shown as UNK.',
    'section_parse_failed': 'This section was not updated. Previous values are retained for review.',
    'section_boundary': 'Section boundaries were not reliable. This section was not updated.',
    'parser_exception': 'An unexpected parser problem occurred. This section was not updated.',
    'orders_count': 'The recurring-order occurrence count could not be read reliably. The R section was skipped.',
    'orders_timing': 'Conflicting recurring-order schedules were supplied. The R section was skipped.',
    'orders_structure': 'The R section did not match the supported order structure. It was skipped.',
    'orders_skipped': 'Orders were not imported. The previous automatic order list is hidden from the handoff until reviewed.',
    'cbc_multiple_values': 'More than one result occupies this CBC cell. The ambiguous cell is excluded, not guessed.',
    'cbc_invalid_cell': 'A CBC cell could not be read. That cell was omitted.',
    'cbc_row_columns': 'A CBC row did not match the dated columns. That row was omitted.',
    'cbc_conflict': 'Conflicting CBC results were excluded from the affected cell.',
    'cbc_percentage': 'A percentage-labelled row was omitted from absolute counts.',
    'feeds_conflict': 'A feeding field contains conflicting or unusable values. It is shown as UNK.',
    'feeds_rate_invalid': 'The backup feed rate could not be established in mL/hr. The rate is shown as UNK.',
    'feeds_unassigned': 'A feeding field was not associated with exactly one tube and was not assigned.',
    'feeds_unrecognized': 'An unrecognized feeding line was omitted. Review the feeding summary.',
    'device_unrecognized': 'A device line could not be read and was omitted. Review the device summary.',
    'device_unclassified': 'A device was retained under Other devices because its type was not recognized.',
    'device_conflict': 'Conflicting or unreadable device details were not guessed. Review the entry.',
    'device_missing_status': 'An EVD was identified without a drain status. Its status is shown as UNK.',
    'document_rejected': 'The paste could not be assigned safely to one handoff. Nothing was changed.',
}
FIELDS = {'', 'WBC', 'HGB', 'HGB_ISTAT', 'HCT', 'HCT_ISTAT', 'MCV', 'PLT', 'ANC', 'ALC', 'method', 'formula', 'rate', 'device_date', 'device_size', 'device_secured', 'device_status'}
ACTIONS = {'not_updated', 'orders_hidden', 'cell_omitted', 'row_omitted', 'nothing_changed', 'field_unknown', 'feeds_hidden', 'devices_hidden', 'neuro_devices_hidden', 'pacemaker_hidden', 'diet_hidden'}


def diagnostic(section: str, code: str, *, line: int = 0, column: int = 0,
               field: str = '', action: str = 'not_updated') -> dict:
    value = dict(section=section, code=code, line=line, column=column, field=field, action=action)
    validate_diagnostic(value)
    return value


def validate_diagnostic(value: dict) -> None:
    if not isinstance(value, dict) or set(value) != {'section', 'code', 'line', 'column', 'field', 'action'}:
        raise ValueError('The import diagnostic has an invalid structure.')
    if (value['section'] not in SECTIONS or value['code'] not in CODES
            or value['field'] not in FIELDS or value['action'] not in ACTIONS):
        raise ValueError('The import diagnostic contains an unsupported code.')
    for key in ('line', 'column'):
        if type(value[key]) is not int or not 0 <= value[key] <= 150000:
            raise ValueError('The import diagnostic source position is invalid.')


def validate_import_warnings(value: dict) -> None:
    if not isinstance(value, dict) or len(value) > len(SECTIONS):
        raise ValueError('Import review flags are invalid.')
    for section, items in value.items():
        if section not in SECTIONS or not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise ValueError('An import review flag is invalid.')
        for item in items:
            validate_diagnostic(item)
            if item['section'] != section:
                raise ValueError('An import review flag does not match its section.')


def diagnostic_text(item: dict) -> str:
    validate_diagnostic(item)
    position = (' | line ' + str(item['line']) if item['line'] else '')
    position += (' | column ' + str(item['column']) if item['column'] else '')
    field = (' | ' + item['field']) if item['field'] else ''
    return SECTIONS[item['section']] + field + position + ': ' + CODES[item['code']] + (' Previous automatic orders are hidden from print.' if item['action'] == 'orders_hidden' and item['code'] != 'orders_skipped' else '') + (' Previous automatic feeds are hidden from print.' if item['action'] == 'feeds_hidden' else '') + (' Previous automatic device details are hidden from print.' if item['action'] in ('devices_hidden', 'neuro_devices_hidden') else '') + (' Previous automatic pacemaker settings are hidden from print.' if item['action'] == 'pacemaker_hidden' else '') + (' Previous automatic diet details are hidden from print.' if item['action'] == 'diet_hidden' else '')


def review_summary(sheet: dict) -> str:
    parts = []
    for section, items in sheet.get('import_warnings', {}).items():
        if section == 'x':
            note = 'not updated; prior diet hidden' if any(i['action'] == 'diet_hidden' for i in items) else 'review diet orders'
        elif section == 'r':
            note = 'orders skipped; prior list hidden'
        elif section == 't' and any(item['action'] == 'feeds_hidden' for item in items):
            note = 'not updated; prior feeds hidden'
        elif section == 'w' and any(item['action'] == 'pacemaker_hidden' for item in items):
            note = 'not updated; prior pacemaker settings hidden'
        elif section == 'w':
            note = 'mode or matching rate missing; verify settings'
        elif section in ('u', 'v') and any(item['action'] in ('devices_hidden', 'neuro_devices_hidden') for item in items):
            note = 'not updated; prior devices hidden'
        elif any(item['action'] == 'not_updated' for item in items):
            note = 'not updated; verify retained values'
        elif section in ('u', 'v'):
            note = 'incomplete; some devices omitted' if any(i['action'] == 'row_omitted' for i in items) else 'review device details'
        else:
            note = 'incomplete; some results omitted'
        parts.append(SECTIONS[section] + ': ' + note)
    return 'IMPORT REVIEW: ' + ' | '.join(parts) if parts else ''


def orders_for_output(sheet: dict):
    return None if 'r' in sheet.get('import_warnings', {}) else sheet.get('recurring_orders')
