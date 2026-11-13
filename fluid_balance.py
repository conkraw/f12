"""S-block fluid totals copied verbatim, with no net calculation or H fallback."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import re

FIELDS = ("intake", "output", "net")
META_FIELDS = ("period", "as_of", "last_filed")
KEYS = set(FIELDS + META_FIELDS) | {"include"}
LABELS = {"intake": "Intake", "output": "Output", "net": "Net"}
MISSING = {"", "--", "-", "—", "–", "n/a", "not documented", "not available"}
NUMBER = r"[+\-−]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
VOLUME = re.compile(rf"{NUMBER}(?:\s*(?:ml|l|cc))?", re.I)
SUMMARY = re.compile(r"^Intake\s*/\s*Output\s+Summary(?:\s*\(([^)]*)\))?(?:\s+at\s+(.+))?\s*$", re.I)
TOTAL = re.compile(r"^(Intake|Output|Net)(?:\s*:\s*|\s+)(.*?)\s*$", re.I)
DATE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}:?\d{2}(?:\s*[APap][Mm])?)?")


@dataclass
class FluidBalanceResult:
    data: dict | None = None
    issues: list[str] = field(default_factory=list)
    error: str = ""


def empty_balance() -> dict:
    return {**{name: "" for name in FIELDS + META_FIELDS}, "include": True}


def validate_balance(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != KEYS or not isinstance(data["include"], bool):
        raise ValueError("The intake/output snapshot has an invalid structure.")
    for name in FIELDS + META_FIELDS:
        value = data[name]
        if not isinstance(value, str) or len(value) > 120 or any(c in value for c in "\n\r\t"):
            raise ValueError("An intake/output field is invalid or too long.")
        if name in FIELDS and value.strip().casefold() not in MISSING and not VOLUME.fullmatch(value.strip()):
            raise ValueError("Use a recorded numeric fluid total with its supplied volume unit, or -- when missing.")
    for name in ("as_of", "last_filed"):
        if data[name] and not DATE.fullmatch(data[name]):
            raise ValueError("The intake/output source date or time is invalid.")


def parse_balance(block: str) -> FluidBalanceResult:
    result = FluidBalanceResult()
    if not isinstance(block, str) or len(block) > 20000:
        result.error = "The S intake/output block is invalid or too long. Nothing was imported."
        return result
    data = empty_balance()
    found = set()
    summary_seen = False
    unrecognized = False
    for raw in block.replace("\r", "\n").replace("\u00a0", " ").splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.rstrip(":.").casefold()
        if low in {"intake/output", "intake / output", "intake/output totals", "intake / output totals", "fluid balance", "none", "no results found", "no data", "not documented", "no intake or output data"}:
            continue
        summary = SUMMARY.fullmatch(line)
        if summary:
            period, as_of = (v.strip() if v else "" for v in summary.groups())
            if summary_seen and (data["period"], data["as_of"]) != (period, as_of):
                result.error = "The S block contains different intake/output summaries. Paste one snapshot. Nothing was imported."
                return result
            data.update(period=period, as_of=as_of)
            summary_seen = True
            continue
        filed = re.fullmatch(r"Last data filed at\s+(.+)", line, re.I)
        if filed:
            value = filed.group(1).strip()
            if data["last_filed"] and data["last_filed"] != value:
                result.error = "The S block contains conflicting last-filed times. Nothing was imported."
                return result
            data["last_filed"] = value
            continue
        if re.fullmatch(r"Gross\s+per\s+\d+(?:\.\d+)?\s+hours?", line, re.I):
            continue
        total = TOTAL.fullmatch(line)
        if total:
            name, value = total.group(1).lower(), total.group(2).strip()
            if name in found and data[name] != value:
                result.error = "The S block contains conflicting fluid totals. Nothing was imported."
                return result
            data[name] = value
            found.add(name)
        elif re.fullmatch(r"(?:Intake|Output|Net)\s*:?", line, re.I):
            name = line.rstrip(":").strip().lower()
            if name in found and data[name]:
                result.error = "The S block contains conflicting fluid totals. Nothing was imported."
                return result
            found.add(name)
        else:
            unrecognized = True
    if unrecognized:
        result.error = "An S-block line could not be read as an intake/output total. Check the source. Nothing was imported."
        return result
    if not found:
        return result  # A valid empty S clears the previous snapshot.
    try:
        validate_balance(data)
    except ValueError as exc:
        result.error = str(exc)
        return result
    result.data = data
    if any(data[name].strip().casefold() in MISSING for name in FIELDS):
        result.issues.append("A fluid total is missing in S. It remains --, not zero. Net is never calculated by the app.")
    return result


def balance_text(data: dict | None, dosing_weight: str = "") -> str:
    validate_balance(data)
    if data is None or not data["include"]:
        return ""
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    weight = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(kg|g)", dosing_weight.strip(), re.I)
    kg = Decimal(weight.group(1)) / (1000 if weight.group(2).lower() == "g" else 1) if weight else None
    if kg is not None and kg <= 0:
        kg = None
    rows = []
    for name in FIELDS:
        value = "--" if data[name].strip().casefold() in MISSING else data[name].strip()
        result = LABELS[name] + ": " + value
        volume = re.fullmatch(rf"({NUMBER})\s*(ml|l|cc)", value, re.I)
        if name in ("intake", "output") and kg and volume:
            ml = Decimal(volume.group(1).replace(",", "").replace("−", "-")) * (1000 if volume.group(2).lower() == "l" else 1)
            per_kg = (ml / kg).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            number = format(per_kg, "f").rstrip("0").rstrip(".") if "." in str(per_kg) else str(per_kg)
            result = ("In" if name == "intake" else "Out") + ": " + value + " (" + number + " mL/kg)"
        rows.append(result)
    if kg:
        rows.append("Using dosing weight: " + dosing_weight)
    return "\n".join(rows)


def balance_heading(data: dict | None) -> str:
    """Label a documented 24-hour snapshot by its source hour, not reprint time.

    Minute precision remains in as_of. Only the displayed hour is abbreviated.
    Missing/invalid timestamps and non-24-hour periods keep the generic title.
    Last-filed time is not the reporting cutoff and is never a fallback.
    """
    validate_balance(data)
    title = "Intake/Output"
    if data is None or not re.fullmatch(r"(?:last|past)?\s*24\s*(?:hours?|hrs?|h)", data["period"].strip(), re.I):
        return title
    match = re.fullmatch(
        r"(?P<date>\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))\s+"
        r"(?P<hour>\d{1,2}):?(?P<minute>\d{2})(?:\s*(?P<meridiem>am|pm))?",
        data["as_of"].strip(), re.I,
    )
    if match is None:
        return title
    try:
        date = match.group("date")
        datetime.strptime(date, "%m/%d/%Y" if len(date.rsplit("/", 1)[1]) == 4 else "%m/%d/%y")
    except ValueError:
        return title
    hour, minute = int(match.group("hour")), int(match.group("minute"))
    meridiem = (match.group("meridiem") or "").lower()
    if not 0 <= minute < 60:
        return title
    if meridiem:
        if not 1 <= hour <= 12:
            return title
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    elif not 0 <= hour < 24:
        return title
    window = str(hour % 12 or 12) + ("a" if hour < 12 else "p")
    return title + " (" + window + "-" + window + ")"
