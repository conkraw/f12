"""Current-shift output only. Never change the separate 24-hour I/O snapshot.

Read the H block's explicit current-shift Out breakdown and Weight. The H
summary's generation timestamp is the cutoff, never Last data filed, a prior
saved timestamp, wall-clock time, admission time, or the time of printing.
Only normalized numeric output fields and the source cutoff are stored.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
import re
from zoneinfo import ZoneInfo

LABELS = {"urine": "UOP", "drains": "Drains", "chest_tube": "Chest Tube", "other": "Other"}
ALIASES = {"urine": "urine", "urine output": "urine", "uop": "urine",
           "drain": "drains", "drains": "drains",
           "chest tube": "chest_tube", "chest tubes": "chest_tube", "other": "other"}
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
_VOLUME = re.compile(rf"(?P<value>{_NUMBER})\s*(?:mL|cc)?"
                     rf"(?:\s*\(\s*(?:{_NUMBER})\s*mL/kg(?:/(?:hr|h))?\s*\))?", re.I)
_WEIGHT = re.compile(rf"(?P<value>{_NUMBER})\s*(?P<unit>kg|g)", re.I)
_HEADER = re.compile(r"^\s*(?:I\s*/?\s*O\s+Current\s+Shift|I\s*/\s*O\s+this\s+shift)\s*:?\s*$", re.I | re.M)
_SUMMARY = re.compile(r"^\s*Intake\s*/\s*Output\s+Summary(?:\s*\([^\n]*\))?\s+at\s+([^\n]+)\s*$", re.I | re.M)
_TIME = re.compile(r"(?P<date>\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))\s+"
                   r"(?P<clock>\d{1,2}:\d{2}(?::\d{2})?|\d{3,4})\s*(?P<ampm>AM|PM)?", re.I)
_MISSING = {"", "--", "-", "none", "n/a", "unknown", "unk", "no data recorded", "not documented"}


@dataclass
class CurrentShiftResult:
    data: dict | None = None
    issues: list[str] = field(default_factory=list)
    error: str = ""


def _number(value: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or len(value) > 24 or not re.fullmatch(_NUMBER, value):
        raise ValueError("A current-shift number could not be read safely.")
    try:
        parsed = Decimal(value.replace(",", ""))
    except InvalidOperation:
        raise ValueError("A current-shift number could not be read safely.") from None
    if not parsed.is_finite() or parsed < 0 or (positive and parsed == 0) or parsed > Decimal("1000000000"):
        raise ValueError("A current-shift number is outside the supported range.")
    return parsed


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _source_time(value: str) -> datetime:
    match = _TIME.fullmatch(value.strip())
    if not match:
        raise ValueError("Current Shift needs the source summary date and time. No hourly rates were calculated.")
    date, clock, ampm = match.group("date", "clock", "ampm")
    date_format = "%m/%d/%Y" if len(date.rsplit("/", 1)[1]) == 4 else "%m/%d/%y"
    parts = clock.split(":") if ":" in clock else [clock[:-2], clock[-2:]]
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if ampm:
        if not 1 <= hour <= 12:
            raise ValueError("The current-shift source time is invalid.")
        hour = hour % 12 + (12 if ampm.upper() == "PM" else 0)
    try:
        return datetime.strptime(date, date_format).replace(hour=hour, minute=minute, second=second)
    except ValueError:
        raise ValueError("The current-shift source date or time is invalid.") from None


def validate_current_shift(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != {"as_of", "weight_kg", "outputs"}:
        raise ValueError("The current-shift snapshot has an invalid structure.")
    stamp = data["as_of"]
    if not isinstance(stamp, str) or (stamp and not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", stamp)):
        raise ValueError("The current-shift source timestamp is invalid.")
    if stamp:
        try:
            datetime.fromisoformat(stamp)
        except ValueError:
            raise ValueError("The current-shift source timestamp is invalid.") from None
    weight = data["weight_kg"]
    if not isinstance(weight, str):
        raise ValueError("The current-shift weight is invalid.")
    if weight:
        _number(weight, positive=True)
    outputs = data["outputs"]
    if not isinstance(outputs, dict) or not outputs or set(outputs) - set(LABELS):
        raise ValueError("The current-shift output categories are invalid.")
    for value in outputs.values():
        _number(value)


def _eastern(naive: datetime) -> datetime:
    """Reject missing/repeated local times instead of guessing a DST fold."""
    zone = ZoneInfo("America/New_York")
    candidates = {}
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == naive:
            candidates[utc] = aware
    if len(candidates) != 1:
        raise ValueError("The source time is ambiguous or nonexistent during a daylight-saving change. Current-shift rates are withheld.")
    return next(iter(candidates.values()))


def shift_window(stamp: str) -> tuple[datetime, datetime, Decimal]:
    """Return local boundaries and actual elapsed hours for 7am/3pm/11pm."""
    if not stamp:
        raise ValueError("The source summary timestamp is missing. Current-shift rates are withheld.")
    end = datetime.fromisoformat(stamp)
    if end.hour < 7:
        start = (end - timedelta(days=1)).replace(hour=23, minute=0, second=0)
    else:
        start = end.replace(hour=7 if end.hour < 15 else 15 if end.hour < 23 else 23,
                            minute=0, second=0)
    start_utc = _eastern(start).astimezone(timezone.utc)
    end_utc = _eastern(end).astimezone(timezone.utc)
    seconds = int((end_utc - start_utc).total_seconds())
    if seconds <= 0:
        raise ValueError("The source time is exactly the start of a shift. Current-shift rates are withheld until elapsed time is available.")
    return start, end, Decimal(seconds) / Decimal(3600)


def current_shift_issues(data: dict | None) -> list[str]:
    validate_current_shift(data)
    if data is None:
        return []
    issues = []
    if not data["weight_kg"]:
        issues.append("The current-shift Weight is missing or invalid. No other weight is substituted and no hourly rates are calculated.")
    try:
        shift_window(data["as_of"])
    except ValueError as exc:
        issues.append(str(exc))
    return issues


def parse_current_shift(block: str) -> CurrentShiftResult:
    result = CurrentShiftResult()
    if not isinstance(block, str) or len(block) > 20000:
        result.error = "The current-shift H block is invalid or too long."
        return result
    text = block.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    headers = list(_HEADER.finditer(text))
    if not headers:
        return result  # A newly supplied H without this snapshot clears old shift data.
    # The normal pair is IO Current Shift immediately followed by I/O this shift.
    if (len(headers) > 2 or (len(headers) == 2 and
            (text[headers[0].end():headers[1].start()].strip() or
             not re.search(r"Current\s+Shift", headers[0].group(), re.I) or
             not re.search(r"this\s+shift", headers[1].group(), re.I)))):
        result.error = "More than one current-shift snapshot was found. Paste one current-shift snapshot per patient."
        return result
    prefix, body = text[:headers[0].start()], text[headers[-1].end():]
    data = {"as_of": "", "weight_kg": "", "outputs": {}}
    try:
        summaries = list(_SUMMARY.finditer(prefix))
        if len(summaries) > 1:
            raise ValueError("More than one source I/O timestamp was found for Current Shift.")
        if summaries:
            data["as_of"] = _source_time(summaries[0].group(1)).isoformat(timespec="seconds")
        weights = re.findall(r"^\s*Weight\s*:\s*([^\n]*)", body, re.I | re.M)
        if len(weights) > 1:
            raise ValueError("More than one current-shift weight was found.")
        if weights:
            match = _WEIGHT.fullmatch(weights[0].strip())
            if match:
                try:
                    kg = _number(match.group("value"), positive=True)
                    if match.group("unit").lower() == "g":
                        kg /= Decimal(1000)
                    data["weight_kg"] = _plain(kg)
                except ValueError:
                    pass  # Explicit invalid weight withholds rates, not guessed.
        out_lines = list(re.finditer(r"^\s*Out\s*:", body, re.I | re.M))
        if len(out_lines) > 1:
            raise ValueError("More than one current-shift Out line was found.")
        if not out_lines:
            result.issues.append("No current-shift Out breakdown was supplied. No output is inferred from intake or total output.")
            return result
        tail = body[out_lines[0].end():]
        tail = re.split(r"^\s*(?:In|Weight)\s*:", tail, maxsplit=1, flags=re.I | re.M)[0].strip()
        breakdown = re.search(r"\[([^\[\]]*)\]", tail, re.S)
        if not breakdown:
            if "[" in tail or "]" in tail:
                raise ValueError("The current-shift output breakdown is incomplete.")
            result.issues.append("No current-shift output categories were supplied. Total output is not treated as urine.")
            return result
        if tail.count("[") != 1 or tail.count("]") != 1 or tail[breakdown.end():].strip():
            raise ValueError("The current-shift output breakdown could not be read safely.")
        seen = set()
        for entry in breakdown.group(1).split(";"):
            if not entry.strip():
                continue
            label, separator, value = entry.strip().partition(":")
            key = ALIASES.get(re.sub(r"\s+", " ", label).strip().casefold())
            if key is None:
                continue  # Do not reclassify other categories into Other.
            if key in seen:
                raise ValueError("A current-shift output category occurs more than once. Values were not added or guessed.")
            seen.add(key)
            if not separator:
                raise ValueError("A current-shift output category has no readable volume.")
            if value.strip().casefold() in _MISSING:
                result.issues.append("A current-shift output volume is missing and was omitted, not treated as zero.")
                continue
            match = _VOLUME.fullmatch(value.strip())
            if match is None:
                raise ValueError("A current-shift output volume could not be read in mL. No hourly rates were calculated.")
            data["outputs"][key] = _plain(_number(match.group("value")))
        if not data["outputs"]:
            return result
        validate_current_shift(data)
        result.data = data
        result.issues.extend(current_shift_issues(data))
    except ValueError as exc:
        result.data = None
        result.error = str(exc)
    return result


def _clock(value: datetime) -> str:
    clock = str(value.hour % 12 or 12)
    if value.minute or value.second:
        clock += f":{value.minute:02d}"
    if value.second:
        clock += f":{value.second:02d}"
    return clock + ("am" if value.hour < 12 else "pm")


def current_shift_heading(data: dict | None) -> str:
    validate_current_shift(data)
    if data is None or not data["as_of"]:
        return "Current Shift"
    try:
        start, end, _ = shift_window(data["as_of"])
    except ValueError:
        return "Current Shift"
    return f"Current Shift ({_clock(start)} - {_clock(end)})"


def current_shift_rows(data: dict | None) -> str:
    if data is None or current_shift_issues(data):
        return ""
    _, _, hours = shift_window(data["as_of"])
    weight = _number(data["weight_kg"], positive=True)
    rows = []
    for key, label in LABELS.items():
        if key not in data["outputs"]:
            continue
        rate = _number(data["outputs"][key]) / weight / hours
        displayed = "<0.01" if Decimal(0) < rate < Decimal("0.01") else format(rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")
        rows.append(f"{label}: {displayed} mL/kg/hr")
    return "\n".join(rows)


def current_shift_text(sheet: dict, rich: bool = False, esc=escape) -> str:
    if "h" in sheet.get("import_warnings", {}):
        # Recovered omissions can still show valid independent categories.
        if any(item["action"] == "current_shift_hidden" for item in sheet["import_warnings"]["h"]):
            return ""
    data = sheet.get("current_shift")
    rows = current_shift_rows(data)
    if not rows:
        return ""
    heading = current_shift_heading(data)
    if rich:
        rendered = "\n".join("<b>" + esc(line.split(":", 1)[0] + ":") + "</b>" + esc(line.split(":", 1)[1]) for line in rows.splitlines())
        return "<b>" + esc(heading) + "</b>\n" + rendered
    return heading + "\n" + rows
