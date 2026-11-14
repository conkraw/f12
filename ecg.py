"""Extract a dated Bazett QTc without retaining an ECG's narrative or identity.

ECG measurements have no age or admission-date cutoff. Only an explicitly
named Bazett result in milliseconds is used. Display warnings follow the
clinician-configured >450 msec workflow threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re


_NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
_UNIT = r"(?:ms|msec|milliseconds?)"
_FIELD = re.compile(
    r"^QTc\s+Calculation\s*\(\s*Bazett\s*\)"
    rf"\s*(?:\(\s*(?P<unit>{_UNIT})\s*\))?\s*(?::|\t+)\s*(?P<value>.*)$", re.I)
_BAZETT_LABEL = re.compile(r"^QTc\s+Calculation\s*\(\s*Bazett\s*\)", re.I)
_HEADER = re.compile(r"^(?:ECG|EKG|Electrocardiogram)\b", re.I)
_DATE_FIELD = re.compile(
    r"^(?:(?:(?:ECG|EKG|Study|Collection|Acquisition|Performed)\s+)?"
    r"Date(?:\s*/\s*Time)?|Performed|Acquired)\s*:", re.I)
_DATE = re.compile(
    r"(?<!\d)(?:\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})|\d{4}-\d{2}-\d{2})(?!\d)"
    r"(?:[ T]+(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?|\d{4})(?!\d))?", re.I)
_VALUE = re.compile(rf"(?P<value>{_NUMBER})\s*(?P<unit>{_UNIT})?", re.I)
_MISSING = {"", "--", "-", "n/a", "na", "none", "unknown", "not available",
            "not documented", "no data recorded", "no results", "no results found"}


@dataclass
class ECGResult:
    data: dict | None = None
    error: str = ""
    issues: list[str] = field(default_factory=list)


def _number(value: str) -> Decimal:
    if not isinstance(value, str) or len(value) > 20 or not re.fullmatch(_NUMBER, value):
        raise ValueError("The Bazett QTc must be one positive numeric value in milliseconds.")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("The Bazett QTc must be one positive numeric value in milliseconds.") from None
    if not number.is_finite() or number <= 0:
        raise ValueError("The Bazett QTc must be one positive numeric value in milliseconds.")
    return number


def _date_value(value: str) -> tuple[datetime, bool]:
    compact = re.sub(r"\s+", " ", value.strip()).upper()
    date_part, *time_parts = re.split(r"[ T]+", compact, maxsplit=1)
    date_formats = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d")
    day = None
    for fmt in date_formats:
        try:
            day = datetime.strptime(date_part, fmt)
            break
        except ValueError:
            pass
    if day is None:
        raise ValueError("An ECG result date could not be read. Check its month, day, and year.")
    if not time_parts:
        return day, False
    time_text = re.sub(r"\s+", "", time_parts[0])
    for fmt in ("%H:%M:%S", "%H:%M", "%H%M", "%I:%M:%S%p", "%I:%M%p"):
        try:
            time = datetime.strptime(time_text, fmt)
            return day.replace(hour=time.hour, minute=time.minute, second=time.second), True
        except ValueError:
            pass
    raise ValueError("An ECG result time could not be read. Check the recorded time.")


def _date_in(text: str) -> tuple[datetime, bool] | None:
    matches = [_date_value(m.group()) for m in _DATE.finditer(text)]
    if not matches:
        return None
    if len(set(matches)) > 1:
        raise ValueError("One ECG header contains conflicting dates. Keep each result with its own ECG date.")
    return matches[0]


def _merge_date(old: tuple[datetime, bool] | None,
                new: tuple[datetime, bool] | None) -> tuple[datetime, bool] | None:
    if old is None:
        return new
    if new is None:
        return old
    if old[0].date() != new[0].date() or old[1] and new[1] and old[0] != new[0]:
        raise ValueError("One ECG report contains conflicting dates. Keep each result with its own ECG date.")
    return new if new[1] else old


def validate_ecg(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != {"value", "date"}:
        raise ValueError("The ECG snapshot has an invalid structure.")
    _number(data["value"])
    date = data["date"]
    if not isinstance(date, str) or date and not re.fullmatch(r"\d{2}/\d{2}/\d{4}", date):
        raise ValueError("The ECG date must be MM/DD/YYYY or blank when unavailable.")
    if date:
        _date_value(date)


def parse_ecg(block: str) -> ECGResult:
    """Use the newest dated Bazett result, independent of the current date.

    ECG headings reset date context. Confirmation narrative and unrelated
    dates do not assign a measurement date. An undated result stays undated.
    Distinct values tied at the newest documented date/time are ambiguous.
    """
    out = ECGResult()
    if not isinstance(block, str):
        out.error = "The ECG section must contain pasted text."
        return out
    reports = []
    report = {"date": None, "values": []}
    try:
        for raw in block.replace("\r\n", "\n").replace("\r", "\n").splitlines():
            line = raw.replace("\u00a0", " ").replace("：", ":").strip()
            if not line:
                continue
            match = _FIELD.fullmatch(line)
            if match:
                value_text = match["value"].strip()
                if value_text.rstrip(".").casefold() in _MISSING:
                    continue
                inline_date = _date_in(value_text)
                if inline_date is not None:
                    # A date immediately attached to the named result is explicit.
                    value_text = _DATE.sub("", value_text).strip().rstrip("[]() ")
                    value_text = value_text.rstrip("[ (")
                value = _VALUE.fullmatch(value_text)
                if value is None or not (value["unit"] or match["unit"]):
                    raise ValueError("A Bazett QTc result could not be read as one numeric value in milliseconds.")
                _number(value["value"])
                report["values"].append((value["value"], inline_date))
                continue
            if _BAZETT_LABEL.match(line):
                raise ValueError("A Bazett QTc field needs a colon followed by its result in milliseconds.")
            if _DATE_FIELD.match(line):
                value = line.split(":", 1)[1].strip()
                if value.rstrip(".").casefold() in _MISSING:
                    continue
                date = _date_in(value)
                if date is None:
                    raise ValueError("An ECG date field could not be read. Use its recorded month, day, and year.")
                report["date"] = _merge_date(report["date"], date)
                continue
            if _HEADER.match(line):
                if report["values"]:
                    reports.append(report)
                report = {"date": _date_in(line), "values": []}
                continue
            if not report["values"] and _DATE.fullmatch(line):
                report["date"] = _merge_date(report["date"], _date_in(line))
        reports.append(report)
        candidates = []
        for item in reports:
            for value, inline_date in item["values"]:
                date = _merge_date(item["date"], inline_date)
                candidates.append((value, date))
        if not candidates:
            return out
        dated = [item for item in candidates if item[1] is not None]
        if dated:
            latest_day = max(item[1][0].date() for item in dated)
            same_day = [item for item in dated if item[1][0].date() == latest_day]
            if any(not item[1][1] for item in same_day):
                newest = same_day
            else:
                latest_time = max(item[1][0] for item in same_day)
                newest = [item for item in same_day if item[1][0] == latest_time]
            undated = [item for item in candidates if item[1] is None]
            if undated:
                newest_numbers = {_number(item[0]) for item in newest}
                if any(_number(item[0]) not in newest_numbers for item in undated):
                    raise ValueError("Dated and undated Bazett QTc results disagree. Keep one verified result with its date.")
                out.issues.append("An undated duplicate Bazett QTc result was omitted because a dated result was available.")
        else:
            newest = candidates
        if len({_number(item[0]) for item in newest}) > 1:
            raise ValueError("The newest ECG has conflicting Bazett QTc values. Keep one verified result with its date.")
        value, date = newest[-1]
        out.data = {"value": value, "date": date[0].strftime("%m/%d/%Y") if date else ""}
        validate_ecg(out.data)
    except ValueError as exc:
        out.data = None
        out.error = str(exc)
    return out


def long_qtc(data: dict | None) -> bool:
    validate_ecg(data)
    return data is not None and _number(data["value"]) > Decimal("450")


def format_ecg(data: dict | None) -> str:
    validate_ecg(data)
    if data is None:
        return ""
    text = "QTc: " + data["value"] + " msec"
    if data["date"]:
        text += " [" + data["date"] + "]"
    return text + (" (!)" if long_qtc(data) else "")


def ecg_text(sheet: dict) -> str:
    """Keep a previous snapshot out of output after an invalid ECG import."""
    if "z" in sheet.get("import_warnings", {}):
        return ""
    return format_ecg(sheet.get("ecg"))
