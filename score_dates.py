"""Source dates for recorded scores, with clinician attribution discarded.

Source times are used for ordering only. The compact public date is never the
paste time, print time, report time, or an inferred measurement date.
"""
from __future__ import annotations

from datetime import datetime
import re

from labs import date_parts as _legacy_date_parts

DATE = r"\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})(?!\d)"
TIME = r"(?:\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?|\d{4}(?!\d))"
_STAMP = r"(?P<date>" + DATE + r")(?:[ \t]+(?P<time>" + TIME + r"))?"
_PAREN = re.compile(r"\(" + _STAMP + r"(?:[ \t]*:[ \t]*[^\r\n]*)?\)[ \t]*$")
_BRACKET = re.compile(r"\[" + _STAMP + r"(?:[ \t]*:[ \t]*[^\r\n]*)?\][ \t]*$")
_PLAIN = re.compile(r"(?:\bat\b|\bon\b)[ \t]+" + _STAMP + r"[ \t]*$", re.I)
_ERROR = "A score recording date or time could not be read. Check the source entry."
_ORDER_ERROR = "The latest recorded score could not be established from the supplied dates and times."

# Score imports and saved rows use a small, known date grammar. Trying every
# strptime format for each validation repeatedly evicts its format cache and
# also slows unrelated laboratory dates in the same render.
_DATE_PARTS = re.compile(
    r"(?P<month>[0-9]{1,2})/(?P<day>[0-9]{1,2})/(?P<year>[0-9]{4}|[0-9]{2})"
    r"(?:[ \t]+(?:(?P<hour>[0-9]{1,2}):(?P<minute>[0-9]{2})"
    r"(?::(?P<second>[0-9]{2}))?(?:[ \t]*(?P<period>AM|PM))?"
    r"|(?P<compact>[0-9]{4})))?", re.I)


def date_parts(value: str) -> tuple[datetime, bool]:
    """Parse ordinary score dates directly, retaining legacy format support.

This performs calendar validation without keeping a global cache of clinical
data. Unusual formats accepted by older archives use the unchanged parser.
"""
    text = value.strip()
    match = _DATE_PARTS.fullmatch(text)
    if match is None or (match['period'] and match['second'] is not None):
        return _legacy_date_parts(value)
    year = int(match['year'])
    if len(match['year']) == 2:
        year += 2000 if year <= 68 else 1900
    timed = match['hour'] is not None or match['compact'] is not None
    if match['compact'] is not None:
        hour, minute = int(match['compact'][:2]), int(match['compact'][2:])
    else:
        hour, minute = int(match['hour'] or 0), int(match['minute'] or 0)
    if match['period']:
        if not 1 <= hour <= 12:
            raise ValueError(_ERROR)
        hour = hour % 12 + (12 if match['period'].upper() == 'PM' else 0)
    try:
        when = datetime(year, int(match['month']), int(match['day']),
                        hour, minute, int(match['second'] or 0))
    except ValueError:
        raise ValueError(_ERROR) from None
    return when, timed


def _normalized_stamp(value: str) -> str:
    try:
        when, timed = date_parts(re.sub(r"\s+", " ", value.strip()))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(_ERROR) from None
    return when.strftime("%m/%d/%Y %H:%M:%S" if timed and when.second else
                         "%m/%d/%Y %H:%M" if timed else "%m/%d/%Y")


def split_score_stamp(text: str) -> tuple[str, str]:
    """Split a trailing source timestamp and discard any EPIC staff attribution.

The remainder must still be validated as a recognized score by the caller.
Unrecognized prose is never turned into a score or copied into an error.
"""
    if not isinstance(text, str) or len(text) > 4000 or "\n" in text or "\r" in text:
        raise ValueError(_ERROR)
    value = text.replace("\u00a0", " ").strip()
    match = _PAREN.search(value) or _BRACKET.search(value) or _PLAIN.search(value)
    if match is None:
        return value, ""
    stamp = match["date"] + (" " + match["time"] if match["time"] else "")
    return value[:match.start()].rstrip(), _normalized_stamp(stamp)


def sanitize_score_line(text: str) -> str:
    """Remove staff names before any score parser can retain a source value."""
    body, stamp = split_score_stamp(text)
    # Empty tab-separated cells carry position in legacy SBS tables.
    return body + " (" + stamp + ")" if stamp else text


def date_label(stamp: str) -> str:
    """Return only MM/DD/YY from a valid source timestamp, or blank if absent."""
    if not stamp:
        return ""
    try:
        when, _ = date_parts(stamp)
    except (ValueError, TypeError, AttributeError):
        raise ValueError(_ERROR) from None
    return when.strftime("%m/%d/%y")


def score_with_date(value: str, stamp: str) -> str:
    date = date_label(stamp)
    return value + (" (" + date + ")" if date else "")


def latest_score(candidates: list[dict], *, value_key: str = "value",
                 stamp_key: str = "recorded_at") -> dict | None:
    """Choose the most recent source entry without ranking numerical scores.

Missing times cannot break a same-day conflict. A conflicting undated result
cannot be assumed older than dated data. Equivalent duplicate rows are safe.
"""
    active = [row for row in candidates if row.get("include", True)]
    if not active:
        return None
    dated: list[tuple[datetime, bool, dict]] = []
    undated = []
    for row in active:
        stamp = row.get(stamp_key, "")
        if not stamp:
            undated.append(row)
            continue
        try:
            when, timed = date_parts(stamp)
        except (ValueError, TypeError, AttributeError):
            raise ValueError(_ERROR) from None
        dated.append((when, timed, row))
    if not dated:
        if len({row[value_key] for row in undated}) > 1:
            raise ValueError(_ORDER_ERROR)
        return dict(undated[0])
    newest_day = max(when.date() for when, _, _ in dated)
    today = [(when, timed, row) for when, timed, row in dated if when.date() == newest_day]
    date_only = [row for _, timed, row in today if not timed]
    timed_rows = [(when, row) for when, timed, row in today if timed]
    if timed_rows:
        newest = max(when for when, _ in timed_rows)
        choices = [row for when, row in timed_rows if when == newest]
    else:
        choices = date_only
    # An untimed row on the latest day could be later than every timed entry.
    values = {row[value_key] for row in choices + date_only + undated}
    if len(values) != 1:
        raise ValueError(_ORDER_ERROR)
    return dict(choices[0])
