"""Select explicitly documented continuous-infusion rates, never calculate doses.

Only a rate with an explicit time denominator is extracted from Last Admin.
Raw administration text and provider names are not retained. Source Dose and
Last Rate remain separate and unchanged. All outputs share this selection.
"""
from __future__ import annotations
from datetime import datetime
import re

ADMIN_FIELDS = ("last_admin_rate", "last_admin_time", "last_admin_status")
ADMIN_STATUSES = ("unavailable", "rate", "stopped", "paused", "held", "not_given", "not_administered", "discontinued", "no_rate", "unreadable")
ADMIN_STATUS_LABELS = {"unavailable": "Not supplied", "rate": "Recorded rate",
                       "stopped": "Stopped", "paused": "Paused", "held": "Held",
                       "not_given": "Not given", "not_administered": "Not administered", "discontinued": "Discontinued",
                       "no_rate": "Event without a rate", "unreadable": "Unclear entry"}

_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
_NUM = "(?:" + _NUM + ")"
_AMOUNT_UNIT = r"(?:mL|[uµμ]g|mcg|ng|mg|g|(?:milli)?units?|mU|mEq|mmol)"
_TIME_UNIT = r"(?:minutes?|mins?|hours?|hrs?|min|hr|h|days?|24h)"
RATE_PATTERN = _NUM + r"\s*" + _AMOUNT_UNIT + r"(?:\s*/\s*kg)?\s*/\s*" + _TIME_UNIT
_RATE = re.compile(r"^" + RATE_PATTERN + r"$", re.I)
_RANGE = re.compile(r"^" + _NUM + r"\s*[-–—]\s*" + RATE_PATTERN + r"$", re.I)
_QUALIFIER = re.compile(r"\(\s*(?:dosing\s+weight|order-specific)\s*\)", re.I)
_STAMP = re.compile(r"\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})\s+(?:\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?|\d{4})(?:\s+(?:EST|EDT))?", re.I)
_ADMIN_SPLIT = re.compile(r"\s+at\s+", re.I)
_EVENT = re.compile(r"^(?:rate/dose\s+(?:change|changed|verify)|rate\s+(?:change|changed|verify)|new\s+bag|restart(?:ed)?|given)\s*:?\s*", re.I)
_STATUS = re.compile(r"^(stopped|paused|held|not\s+given|not\s+administered|discontinued)\b", re.I)
# These explicit requested medications need an actual Last Admin rate even when
# their Dose is a single number or an old archive has not stored Last Admin yet.
_REQUESTED = re.compile(r"^(?:(?:sodium\s+)?nitroprusside|nipride(?:\s+rtu)?|nitropress|nicardipine|cardene(?:\s+iv)?|norepinephrine|noradrenaline|levophed)\b", re.I)
_PREFIX = re.compile(r"^(?:\[(?:held by provider|discontinued|start\s+on[^\]]*)\]\s*|(?:and|followed\s+by)\s*:\s*)", re.I)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _unqualified(value: str) -> str:
    return _clean(_QUALIFIER.sub("", value))


def is_rate(value: str) -> bool:
    return bool(_RATE.fullmatch(_unqualified(value)))


def valid_admin_time(value: str) -> bool:
    if not value:
        return True
    if not _STAMP.fullmatch(value):
        return False
    text = re.sub(r"\s+(?:EST|EDT)$", "", value, flags=re.I).strip()
    for date_fmt in ("%m/%d/%y", "%m/%d/%Y"):
        for time_fmt in ("%H%M", "%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p", "%I:%M%p", "%I:%M:%S%p"):
            try:
                datetime.strptime(text, date_fmt + " " + time_fmt)
                return True
            except ValueError:
                pass
    return False


def continuous_order(row: dict) -> bool:
    frequency = _clean(row.get("frequency", "")).casefold()
    route = _clean(row.get("route", "")).casefold().replace("-", " ")
    return (bool(re.search(r"\bcontinuous\b|\btitrat(?:e|able)\b", frequency))
            and not bool(re.search(r"\bprn\b|as needed", frequency))
            and route in {"intravenous", "iv", "intra arterial", "intraarterial", "ia",
                          "subcutaneous", "subcut", "sq", "epidural", "intrathecal",
                          "nebulization", "nebulisation", "inhalation", "inhaled"})


def requested_titration(row: dict) -> bool:
    if not continuous_order(row):
        return False
    name = _clean(row.get("name", ""))
    while _PREFIX.match(name):
        name = _PREFIX.sub("", name, count=1).strip()
    return (bool(_REQUESTED.match(name)) or bool(_RANGE.fullmatch(_unqualified(row.get("dose", ""))))
            or bool(re.search(r"\btitrat(?:e|able)\b", row.get("frequency", ""), re.I)))


def parse_last_admin(value: str) -> dict[str, str]:
    """Sanitize one administration event. No range, quantity or pump conversion.

    Multiple events in a single cell are deliberately not combined. The exact
    latest event must be supplied by Epic rather than selecting a convenient
    numeric value from an ambiguous string.
    """
    result = dict(last_admin_rate="", last_admin_time="", last_admin_status="unavailable")
    text = _clean(value)
    if not text or text in {"--", "-"}:
        return result
    pieces = _ADMIN_SPLIT.split(text)
    if len(pieces) > 2:
        result["last_admin_status"] = "unreadable"
        return result
    event = pieces[0].strip()
    if len(pieces) == 2:
        stamp = pieces[1].strip()
        if not valid_admin_time(stamp):
            result["last_admin_status"] = "unreadable"
            return result
        result["last_admin_time"] = stamp
    status = _STATUS.fullmatch(event)
    if status:
        word = status.group(1).casefold()
        result["last_admin_status"] = {"stopped": "stopped", "paused": "paused", "held": "held",
                                         "not given": "not_given", "not administered": "not_administered", "discontinued": "discontinued"}[word]
        return result
    numeric = _unqualified(_EVENT.sub("", event, count=1))
    if _RATE.fullmatch(numeric):
        result["last_admin_status"] = "rate"
        result["last_admin_rate"] = numeric
    elif _EVENT.match(event):
        result["last_admin_status"] = "no_rate"
    elif re.fullmatch(_NUM + r"\s*" + _AMOUNT_UNIT + r"(?:\s*/\s*kg)?", numeric, re.I):
        # A PN volume/lipid amount is not an hourly rate.
        result["last_admin_status"] = "no_rate"
    else:
        result["last_admin_status"] = "unreadable"
    return result


def validate_admin_fields(row: dict) -> None:
    present = [field in row for field in ADMIN_FIELDS]
    if any(present) and not all(present):
        raise ValueError("Last Admin rate, time and status must be kept together.")
    if not any(present):
        return
    for field in ADMIN_FIELDS:
        value = row[field]
        if not isinstance(value, str) or len(value) > 200 or any(c in value for c in "\n\r\t"):
            raise ValueError("A Last Admin field contains invalid text.")
    status = row["last_admin_status"]
    rate, stamp = row["last_admin_rate"], row["last_admin_time"]
    if status not in ADMIN_STATUSES or not valid_admin_time(stamp):
        raise ValueError("The Last Admin status or timestamp is invalid.")
    if status == "rate":
        if not is_rate(rate):
            raise ValueError("Last Admin needs one numeric rate with its time units, not a range or total dose.")
    elif rate:
        raise ValueError("A numeric Last Admin rate requires Recorded rate status.")


def administration_display(row: dict) -> tuple[str, str, str] | None:
    """Return primary label/value/time, or None for the existing ordered-dose view."""
    if not continuous_order(row):
        return None
    status = row.get("last_admin_status", "unavailable")
    if status == "rate" and is_rate(row.get("last_admin_rate", "")):
        return ("Last Admin rate", row["last_admin_rate"].strip(), row.get("last_admin_time", ""))
    if status in ("stopped", "paused", "held", "not_given", "not_administered", "discontinued"):
        return ("Last Admin", ADMIN_STATUS_LABELS[status], row.get("last_admin_time", ""))
    if requested_titration(row):
        return ("Last Admin rate", "UNK", row.get("last_admin_time", ""))
    return None


def admin_display_text(row: dict) -> str:
    view = administration_display(row)
    if not view:
        return ""
    label, value, stamp = view
    return label + ": " + value + (" [" + stamp + "]" if stamp else "")


def show_recorded_pump_rate(row: dict) -> bool:
    # An explicit stopped/paused/held event must not be paired with a stale pump
    # rate as though both were simultaneous current settings. Keep it in editor.
    return not (continuous_order(row) and row.get("last_admin_status") in ("stopped", "paused", "held", "not_given", "not_administered", "discontinued"))


def merge_admin_edits(row: dict, values: dict) -> None:
    """Synchronize the optional editor fields without changing untouched old rows."""
    before = {field: row.get(field, "unavailable" if field == "last_admin_status" else "") for field in ADMIN_FIELDS}
    after = dict(before)
    after.update({field: value.strip() for field, value in values.items() if field in ADMIN_FIELDS})
    if after == before:
        return
    if after["last_admin_rate"] != before["last_admin_rate"]:
        after["last_admin_status"] = "rate" if after["last_admin_rate"] else "unavailable"
        if after["last_admin_time"] == before["last_admin_time"]:
            after["last_admin_time"] = ""
    elif after["last_admin_status"] != before["last_admin_status"] and after["last_admin_status"] != "rate":
        after["last_admin_rate"] = ""
    row.update(after)
