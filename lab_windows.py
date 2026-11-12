"""Display-only laboratory time windows. Raw rows and flags are never changed.

24-hour windows use the current Eastern clock, not the newest laboratory date.
A previous-day date without a time may overlap the cutoff and is included.
Its recorded date is retained without inventing a collection time.
METHB and O2SATV use a stricter window: date-only results qualify only when
the beginning of their source date is within the past 24 hours.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
from inspect import signature

_WINDOW_TIME = ContextVar("lab_window_time", default=None)

from labs import canonical, date_parts, ordered_components, lactate_endpoints, is_lactate

EASTERN = ZoneInfo('America/New_York')
CARDIAC_RECENT = {'METHB', 'O2SATV'}
RECENT = {'THEOPH', 'CK', 'VANCOTROUGH'} | CARDIAC_RECENT
ADMISSION = {'CRP', 'PROCAL'}


def clock(as_of: datetime | None = None) -> datetime:
    value = as_of if as_of is not None else (_WINDOW_TIME.get() or datetime.now(timezone.utc))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('The laboratory window clock must include a timezone.')
    return value.astimezone(EASTERN)


def analyte(component: str) -> str:
    key = canonical(component)
    if is_lactate(key):
        return 'LACTATE'
    return {'CPK': 'CK', 'CREATINE KINASE': 'CK', 'CREATINE KINASE TOTAL': 'CK',
            'NT-PROBNP': 'NTPROBNP', 'NT PRO BNP': 'NTPROBNP',
            'NT PROBNP': 'NTPROBNP'}.get(key, key)


def measured(value: str) -> bool:
    """A single numeric measurement, optional units/flags, not a status message."""
    return bool(re.fullmatch(
        r'[<>≤≥]?\s*[+-]?(?:\d[\d,]*(?:\.\d*)?|\.\d+)'
        r'(?:\s*(?:[A-Za-zµμ%]+(?:\s*/\s*[A-Za-zµμ0-9^]+)?))?'
        r'(?:\s*(?:\*|\((?:H|L|HH|LL|A|C|CRIT|HIGH|LOW)\)))*',
        str(value).strip(), re.I))


def eligible_time(row: dict, as_of: datetime, hours: int | None = None,
                  admission: str = '') -> bool:
    try:
        value, timed = date_parts(row['date'])
    except (ValueError, KeyError, TypeError):
        return False
    if timed:
        instant = value.replace(tzinfo=EASTERN)
        if instant > as_of:
            return False
        if hours is not None and instant.astimezone(timezone.utc) < as_of.astimezone(timezone.utc) - timedelta(hours=hours):
            return False
    else:
        if value.date() > as_of.date():
            return False
        if hours is not None:
            cutoff = (as_of.astimezone(timezone.utc) - timedelta(hours=hours)).astimezone(EASTERN)
            # The last possible instant of this date must overlap the window.
            end = datetime.combine(value.date() + timedelta(days=1), datetime.min.time(), EASTERN)
            if end <= cutoff:
                return False
    if admission:
        try:
            start, has_time = date_parts(admission)
        except ValueError:
            return False
        if timed and has_time:
            if value < start:
                return False
        elif value.date() < start.date():
            return False
    return True


def uncertain_24h(row: dict, as_of: datetime) -> bool:
    value, timed = date_parts(row['date'])
    if timed:
        return False
    cutoff = (as_of.astimezone(timezone.utc) - timedelta(hours=24)).astimezone(EASTERN)
    return value.date() <= cutoff.date()


def cardiac_recent_time(row: dict, as_of: datetime) -> bool:
    """Only include results whose possible age fits the 24-hour window.

    Date-only rows use their earliest possible collection instant for the
    cutoff check, without storing or displaying an invented time. A repeated
    Eastern fall-back time must qualify in both folds. Nonexistent spring
    clock times and future results are excluded.
    """
    now = clock(as_of)
    try:
        local, timed = date_parts(row['date'])
    except (ValueError, KeyError, TypeError, AttributeError):
        return False
    now_utc = now.astimezone(timezone.utc)
    cutoff = now_utc - timedelta(hours=24)
    if not timed:
        start = local.replace(tzinfo=EASTERN).astimezone(timezone.utc)
        return local.date() <= now.date() and cutoff <= start <= now_utc
    possible = set()
    for fold in (0, 1):
        instant = local.replace(tzinfo=EASTERN, fold=fold).astimezone(timezone.utc)
        if instant.astimezone(EASTERN).replace(tzinfo=None) == local:
            possible.add(instant)
    return bool(possible) and all(cutoff <= instant <= now_utc for instant in possible)


def rows_for(sheet: dict, component: str, as_of: datetime | None = None) -> list[dict]:
    now = clock(as_of)
    rows = []
    # Failed import: do not make newly derived current displays from stale G.
    if 'g' in sheet.get('import_warnings', {}):
        return rows
    admission = sheet.get('admission_date', '') if 'n' not in sheet.get('import_warnings', {}) else ''
    if component in ADMISSION and not admission:
        return []
    for row in sheet['labs']['rows']:
        if (not row['include'] or analyte(row['component']) != component
                or not measured(row['value'])):
            continue
        if component in CARDIAC_RECENT | {'HEPLMW'} and re.search(r'\b(?:pending|cancelled|canceled|hemolyzed|haemolysed|rejected|invalid)\b', row['value'], re.I):
            continue
        hours = 24 if component in RECENT | {'LACTATE'} else None
        eligible = (cardiac_recent_time(row, now) if component in CARDIAC_RECENT else
                    eligible_time(row, now, hours, admission if component in ADMISSION else ''))
        if eligible:
            rows.append(row)
    return rows


def ordered(rows: list[dict]) -> list[dict]:
    # Reuse source ordering rules across aliases, without modifying source labels.
    data = {'rows': [dict(r, component='RESULT') for r in rows], 'notes': []}
    ids = {r['id']: r for r in rows}
    return [ids[r['id']] for r in ordered_components(data).get('RESULT', [])]


def stamp(row: dict, now: datetime, recent: bool = False) -> str:
    return '[' + row['date'] + ']'


def lactate_summary(sheet: dict, as_of: datetime | None = None) -> str:
    now = clock(as_of)
    values = ordered(rows_for(sheet, 'LACTATE', now))
    if not values:
        return ''
    latest, earliest = values[0], values[-1]
    # Presentation only: retain the existing 24-hour selection and source order.
    # Keep each supplied value/flag/unit intact. Never convert unlike assays.
    day, _ = date_parts(latest['date'])
    date_label = f"{day.month}/{day.day}/{day.year}"
    trend = latest['value'] if len(values) == 1 else earliest['value'] + ' -> ' + latest['value']
    return 'Lactate: ' + trend + ' [' + date_label + ']'


def theophylline_summary(sheet: dict, as_of: datetime | None = None) -> str:
    now = clock(as_of)
    values = ordered(rows_for(sheet, 'THEOPH', now))
    return ('Theophylline level: ' + values[0]['value'] + ' ' + stamp(values[0], now, True)) if values else ''


def cardiac_labs_summary(sheet: dict, as_of: datetime | None = None) -> str:
    now = clock(as_of)
    parts = [lactate_summary(sheet, now)]
    values = ordered(rows_for(sheet, 'NTPROBNP', now))
    if values:
        parts.append('NT-proBNP: ' + values[0]['value'] + ' ' + stamp(values[0], now))
    for component, label in (('METHB', 'Methemoglobin'), ('O2SATV', 'SvO2')):
        values = ordered(rows_for(sheet, component, now))
        if values:
            parts.append(label + ': ' + values[0]['value'] + ' ' + stamp(values[0], now, True))
    return '\n'.join(p for p in parts if p)


def id_summary(sheet: dict, as_of: datetime | None = None) -> str:
    from labs import id_labs_text
    now = clock(as_of)
    if 'g' in sheet.get('import_warnings', {}):
        return ''
    data = deepcopy(sheet['labs'])
    ids = {r['id'] for key in ADMISSION for r in rows_for(sheet, key, now)}
    data['rows'] = [r for r in data['rows'] if analyte(r['component']) not in ADMISSION or r['id'] in ids]
    result = id_labs_text(data)
    if (not sheet.get('admission_date') or 'n' in sheet.get('import_warnings', {})) and any(
            r['include'] and analyte(r['component']) in ADMISSION for r in sheet['labs']['rows']):
        result += ('\n' if result else '') + 'CRP / procalcitonin: admission date needed.'
    levels = id_drug_levels(sheet, now)
    if levels:
        result += ('\n-----\n' if result else '') + levels
    return result


def id_drug_levels(sheet: dict, as_of: datetime | None = None) -> str:
    now = clock(as_of)
    values = ordered(rows_for(sheet, 'VANCOTROUGH', now))
    if not values:
        return ''
    return 'Drug Levels\nVancomycin trough: ' + values[0]['value'] + ' ' + stamp(values[0], now)


def anti_xa_today(sheet: dict, as_of: datetime | None = None) -> dict | None:
    """Latest included numeric HEPLMW on today's Eastern calendar date.

    This is intentionally not a rolling 24-hour window. Supplied collection
    times are used when available, otherwise keep Epic's source ordering.
    Generic ANTI-XA and other heparin assays are not substituted for HEPLMW.
    """
    now = clock(as_of)
    values = ordered([row for row in rows_for(sheet, 'HEPLMW', now)
                      if date_parts(row['date'])[0].date() == now.date()])
    return values[0] if values else None


def anti_xa_today_summary(sheet: dict, as_of: datetime | None = None) -> str:
    now = clock(as_of)
    row = anti_xa_today(sheet, now)
    return ('Anti-Xa (HEPLMW): ' + row['value'] + ' ' + stamp(row, now)) if row else ''


def laboratory_data(sheet: dict, as_of: datetime | None = None) -> dict:
    """Filter system-specific G rows without changing stored laboratory data."""
    now = clock(as_of)
    data = deepcopy(sheet['labs'])
    ck = {r['id'] for r in rows_for(sheet, 'CK', now)}
    # When promoted to HEME, do not also show an older HEPLMW below. Once its
    # date is no longer today, the existing coagulation card selects it below.
    anti_xa_in_heme = anti_xa_today(sheet, now) is not None
    anti_xa_ids = {r['id'] for r in rows_for(sheet, 'HEPLMW', now)}
    out = []
    for row in data['rows']:
        key = analyte(row['component'])
        if key in {'NTPROBNP', 'VANCOTROUGH'} | CARDIAC_RECENT:
            continue  # shown only in the appropriate system column
        if key == 'HEPLMW' and (anti_xa_in_heme or row['id'] not in anti_xa_ids):
            continue
        if key == 'CK':
            if row['id'] not in ck:
                continue
            row['component'] = 'CK'
            row['panel'] = 'CK (last 24h)'
        out.append(row)
    data['rows'] = out
    return data


def window_help(sheet: dict, as_of: datetime | None = None) -> str:
    now = clock(as_of)
    return ('Display windows as of ' + now.strftime('%m/%d/%Y %H:%M %Z') +
            '. Lactate, theophylline, CK and vancomycin trough: rolling 24 hours. '
            'Methemoglobin (METHB) and SvO2 (O2SATV): latest within 24 hours. '
            'A date-only result for these two tests qualifies only when the start of its '
            'Eastern date is within 24 hours. Include collection times for prior-day results. '
            'CRP/procalcitonin: admission onward. NT-proBNP: latest from all supplied dates. '
            'HEPLMW: today in HEME, older results in the lower coagulation area. '
            'Original rows remain available below.')


@contextmanager
def display_clock(as_of: datetime | None = None):
    value = clock(as_of)
    token = _WINDOW_TIME.set(value)
    try:
        yield value
    finally:
        _WINDOW_TIME.reset(token)


def stable_window_clock(function):
    """Use one evaluation time for a PDF batch and all its auto-fit attempts."""
    spec = signature(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        explicit = spec.bind_partial(*args, **kwargs).arguments.get('printed_at')
        with display_clock(explicit):
            return function(*args, **kwargs)
    return wrapped
