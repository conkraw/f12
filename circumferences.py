"""Read explicit circumference measurements and their own charted dates.

Only normalized values and measurement dates are retained. Staff names and
other charting annotations are never stored. This module does not infer a
measurement date from an admission, weight, or handoff timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import re

from anthropometrics import age_bounds


LABELS = {"head": "Head circumference", "abdominal": "Abdominal girth"}
_LABEL = r"(?:head\s+circumference|head\s+circ\.?|HC|abdominal\s+circumference|abdominal\s+girth|abd\.?\s+(?:circumference|girth))"
_HEADING = re.compile(rf"^\s*(?P<label>{_LABEL})\s*:\s*(?P<value>.*)$", re.I)
_ANY_HEADING = re.compile(rf"(?<!\w){_LABEL}\s*:\s*", re.I)
_DATE = re.compile(r"(?<![\d/\-])(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))(?![\d/\-])")
_DATE_LIKE = re.compile(r"(?<!\d)\d{1,4}[/-]\d{1,2}(?:[/-]\d{1,4})?(?!\d)")
_CLOCK = re.compile(r"^\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?\s*(?P<ampm>AM|PM)?\b|^\s+(?P<compact>\d{4})(?!\d)", re.I)
_NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
_MEASUREMENT = re.compile(rf"^(?P<number>{_NUMBER})\s*(?P<unit>centimeters?|centimetres?|cm|millimeters?|millimetres?|mm|inches|inch|in|[\"\u2033])(?=$|\s|[()\[\],.])", re.I)
_QUANTITY = re.compile(_MEASUREMENT.pattern[1:], re.I)
_OTHER_HEADING = re.compile(r"^(?:[A-Za-z][A-Za-z /()\-]*\s*:|(?:Body\s+mass\s+index|Body\s+surface\s+area)\s+is\b|(?:Wt\s+Readings|Dosing\s+Weight)\b)", re.I)
_MISSING = {"", "-", "--", "---", "none", "na", "n/a", "unknown", "no data", "no data recorded", "not recorded", "not documented", "not measured"}


def empty_circumferences() -> dict:
    return {"head": None, "abdominal": None}


def _canonical(number: Decimal) -> str:
    value = format(number, "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def validate_circumferences(data: dict) -> None:
    if not isinstance(data, dict) or set(data) != set(LABELS):
        raise ValueError("The circumference measurements have an invalid structure.")
    for key, item in data.items():
        if item is None:
            continue
        if not isinstance(item, dict) or set(item) != {"value_cm", "date"}:
            raise ValueError("A circumference measurement has an invalid structure.")
        raw, recorded = item["value_cm"], item["date"]
        if not isinstance(raw, str) or len(raw) > 20 or not re.fullmatch(_NUMBER, raw):
            raise ValueError("A circumference measurement must be a positive number in centimeters.")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise ValueError("A circumference measurement must be a positive number in centimeters.") from None
        if not value.is_finite() or not 0 < value <= (100 if key == "head" else 300) or _canonical(value) != raw:
            raise ValueError("A circumference measurement is outside the supported range or is not normalized.")
        if not isinstance(recorded, str) or (recorded and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", recorded)):
            raise ValueError("A circumference measurement date is invalid.")
        if recorded:
            try:
                date.fromisoformat(recorded)
            except ValueError:
                raise ValueError("A circumference measurement date is invalid.") from None


@dataclass
class CircumferenceResult:
    data: dict = field(default_factory=empty_circumferences)
    remainder: str = ""
    issues: list[str] = field(default_factory=list)


@dataclass
class _Reading:
    item: dict | None
    recorded: date | None
    clock: time | None
    invalid: bool = False


def _key(label: str) -> str:
    return "head" if label.lower().startswith(("head", "hc")) else "abdominal"


def _factor(unit: str) -> Decimal:
    unit = unit.casefold()
    if unit.startswith(("mm", "milli")):
        return Decimal("0.1")
    if unit.startswith("in") or unit in ('"', "\u2033"):
        return Decimal("2.54")
    return Decimal(1)


def _source_date(text: str) -> tuple[date | None, time | None, bool]:
    matches = list(_DATE.finditer(text))
    if not matches:
        return None, None, bool(_DATE_LIKE.search(text))
    if len(matches) != 1:
        return None, None, True
    raw = matches[0].group()
    try:
        form = "%Y-%m-%d" if "-" in raw else "%m/%d/%Y" if len(raw.rsplit("/", 1)[-1]) == 4 else "%m/%d/%y"
        recorded = datetime.strptime(raw, form).date()
    except ValueError:
        return None, None, True
    clock = None
    match = _CLOCK.match(text[matches[0].end():])
    if match:
        try:
            if match["compact"]:
                clock = time(int(match["compact"][:2]), int(match["compact"][2:]))
            else:
                hour = int(match["hour"])
                if match["ampm"]:
                    if not 1 <= hour <= 12:
                        raise ValueError
                    hour = hour % 12 + (12 if match["ampm"].upper() == "PM" else 0)
                clock = time(hour, int(match["minute"]), int(match["second"] or 0))
        except ValueError:
            return recorded, None, True
    return recorded, clock, False


def _date_metadata_line(text: str) -> bool:
    """A date/time annotation cannot contain a separate weight or other value."""
    rest = text.lstrip("([ ")
    match = _DATE.match(rest)
    if not match:
        return False
    rest = rest[match.end():]
    clock = _CLOCK.match(rest)
    if clock:
        rest = rest[clock.end():]
    rest = rest.strip()
    return not rest or rest in (")", "]") or rest.startswith(":")


def _reading(key: str, text: str) -> _Reading | None:
    text = " ".join(text.replace("\u00a0", " ").split()).strip()
    if text.casefold().rstrip(".") in _MISSING:
        return None
    recorded, clock, invalid_date = _source_date(text)
    leading_date = _DATE.match(text)
    if leading_date:
        text = text[leading_date.end():].lstrip()
        leading_clock = _CLOCK.match(" " + text)
        if leading_clock:
            text = (" " + text)[leading_clock.end():].lstrip()
    match = _MEASUREMENT.match(text)
    if match is None or invalid_date:
        return _Reading(None, recorded, clock, True)
    try:
        value = Decimal(match["number"])
        value *= _factor(match["unit"])
        item = {"value_cm": _canonical(value), "date": recorded.isoformat() if recorded else ""}
        check = empty_circumferences()
        check[key] = item
        validate_circumferences(check)
    except (InvalidOperation, ValueError):
        return _Reading(None, recorded, clock, True)
    # The primary number must not conceal a range or a second metric value.
    # An Epic imperial equivalent in parentheses remains an annotation.
    tail = text[match.end():].strip()
    if tail and not tail.startswith(("(", "[")) and not _DATE.match(tail) and not re.match(r"^(?:on|at)\s+" + _DATE.pattern, tail, re.I):
        return _Reading(None, recorded, clock, True)
    if re.search(r"\b(?:entered\s+in\s+error|invalid|incorrect|unreliable|erroneous|estimated|approximate|not\s+measured|do\s+not\s+use)\b", tail, re.I):
        return _Reading(None, recorded, clock, True)
    for alternate in _QUANTITY.finditer(tail):
        # Epic may supply one equivalent in inches, with rounding in both units.
        alternate_value = Decimal(alternate["number"]) * _factor(alternate["unit"])
        primary_rounding = Decimal(1).scaleb(Decimal(match["number"]).as_tuple().exponent) * _factor(match["unit"]) / 2
        alternate_rounding = Decimal(1).scaleb(Decimal(alternate["number"]).as_tuple().exponent) * _factor(alternate["unit"]) / 2
        if _factor(alternate["unit"]) == _factor(match["unit"]) or abs(value - alternate_value) > primary_rounding + alternate_rounding:
            return _Reading(None, recorded, clock, True)
    return _Reading(item, recorded, clock)


def _select(key: str, rows: list[_Reading], result: CircumferenceResult) -> None:
    if not rows:
        return
    label = LABELS[key]
    if any(row.invalid for row in rows):
        result.issues.append(label + " contains an unreadable measurement or date. Verify the source entry.")
    # An undated, conflicting entry cannot safely be placed before a dated one.
    undated = [row for row in rows if row.recorded is None]
    valid_values = {row.item["value_cm"] for row in rows if row.item}
    if undated and (any(row.invalid for row in undated) or len(valid_values) > 1):
        result.issues.append(label + " was omitted because the latest measurement could not be established from the supplied dates.")
        return
    dated = [row for row in rows if row.recorded is not None]
    if not dated:
        result.data[key] = rows[-1].item
        return
    latest_day = max(row.recorded for row in dated)
    latest = [row for row in dated if row.recorded == latest_day]
    if len(latest) > 1 and all(row.clock is not None for row in latest):
        latest_time = max(row.clock for row in latest)
        latest = [row for row in latest if row.clock == latest_time]
    if any(row.invalid for row in latest):
        return
    if len({row.item["value_cm"] for row in latest}) > 1:
        result.issues.append(label + " was omitted because measurements at the latest date or time conflict.")
        return
    result.data[key] = latest[0].item


def parse_circumferences(block: str) -> CircumferenceResult:
    """Remove labeled circumference rows and return the latest usable readings.

    Blank headings clear their measurement. Value-only and date-only following
    lines are accepted only while attached to a recognized circumference label.
    Multiple readings need comparable dates when their values differ.
    """
    result = CircumferenceResult()
    rows = {key: [] for key in LABELS}
    remaining = []
    pending_key = None
    pending_value = ""

    def flush() -> None:
        nonlocal pending_key, pending_value
        if pending_key:
            item = _reading(pending_key, pending_value)
            if item is not None:
                rows[pending_key].append(item)
        pending_key, pending_value = None, ""

    source_lines = []
    for raw in block.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        # Also accept two labeled measurements on one copied chart line.
        matches = list(_ANY_HEADING.finditer(raw)) if _HEADING.match(raw) else []
        if len(matches) > 1:
            source_lines.extend(raw[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(raw)]
                                for index, match in enumerate(matches))
        else:
            source_lines.append(raw)
    for raw in source_lines:
        line = raw.replace("\u00a0", " ").strip()
        heading = _HEADING.match(line)
        if heading:
            flush()
            pending_key, pending_value = _key(heading["label"]), heading["value"]
            repeated = _HEADING.match(pending_value)
            while repeated and _key(repeated["label"]) == pending_key:
                pending_value = repeated["value"]
                repeated = _HEADING.match(pending_value)
            continue
        if pending_key and line:
            # A separate charted date belongs only to the preceding value.
            if pending_value and re.match(r"^[([]?\s*" + _DATE.pattern, line):
                if not _QUANTITY.search(line) and _date_metadata_line(line):
                    pending_value += " " + line
                    continue
                if _QUANTITY.search(line):
                    current_key = pending_key
                    flush()
                    pending_key, pending_value = current_key, line
                    continue
            if pending_value and _MEASUREMENT.match(line):
                current_key = pending_key
                flush()
                pending_key, pending_value = current_key, line
                continue
            if not pending_value:
                unrelated_dated_row = _DATE.match(line) and not _QUANTITY.search(line)
                if not unrelated_dated_row and (_MEASUREMENT.match(line) or _DATE.match(line)
                        or line.casefold().rstrip(".") in _MISSING
                        or re.match(r"^[+-]?(?:\d|\.)", line)
                        or not _OTHER_HEADING.match(line)):
                    pending_value = line
                    continue
            flush()
        remaining.append(raw)
    flush()
    for key in LABELS:
        _select(key, rows[key], result)
    result.remainder = "\n".join(remaining)
    validate_circumferences(result.data)
    return result


def circumferences_text(data: dict, age_text: str) -> str:
    validate_circumferences(data)
    bounds = age_bounds(age_text)
    under_two = bounds is not None and bounds[0] < 24 and bounds[1] <= 24
    lines = []
    for key in LABELS:
        if key == "head" and not under_two:
            continue
        item = data[key]
        if item:
            recorded = " [" + date.fromisoformat(item["date"]).strftime("%m/%d/%y") + "]" if item["date"] else ""
            lines.append(LABELS[key] + ": " + item["value_cm"] + " cm" + recorded)
    return "\n".join(lines)
