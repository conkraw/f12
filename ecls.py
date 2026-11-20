"""Read one AD-section ECLS snapshot and derive indexed flow from explicit inputs.

Only the named pump settings are retained. Flow goal, separately charted cardiac
index, ventilator oxygen, narrative and patient identifiers are never retained.
The caller passes the AD block, not the complete SmartPhrase. Derived values use
the saved dosing weight and the chart-reported BSA, without weight/BSA fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re

from anthropometrics import clean_field
from demographics import validate_dosing_weight, WEIGHT


FIELDS = ("mode", "oxygenator_day", "blood_flow_l_min", "rpm", "sweep_l_min", "fio2_percent")
_NUMBER = r"(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
_MISSING = {"", "-", "--", "---", "none", "n/a", "na", "unknown", "unk",
            "not documented", "not recorded", "no data recorded", "no results found"}
_NAMES = {"mode": "mode", "oxygenator_day": "oxygenator day",
          "blood_flow_l_min": "pump flow", "rpm": "set speed",
          "sweep_l_min": "sweep gas flow rate", "fio2_percent": "blender FiO2"}
_LABELS = {"ecmo mode": "mode", "ecls mode": "mode",
           "oxygenator day": "oxygenator_day", "oxy day": "oxygenator_day",
           "pump flow": "blood_flow_l_min", "set speed": "rpm",
           "sweep gas flow rate": "sweep_l_min", "blender fio2": "fio2_percent"}
_UNIT_PATTERNS = {
    "blood_flow_l_min": r"(?:l\s*/\s*min(?:ute)?|lpm)",
    "sweep_l_min": r"(?:l\s*/\s*min(?:ute)?|lpm)",
    "rpm": r"(?:rev\s*/\s*min(?:ute)?|rpm)",
    "fio2_percent": r"(?:%|percent)",
}
_HEADER = re.compile(r"^(?:system readings|ecls settings|ecmo settings)\s*:?$", re.I)
_DELIMITER = re.compile(r"^(?:ad){3,}$", re.I)


@dataclass
class ECLSResult:
    data: dict | None = None
    error: str = ""
    issues: list[str] = field(default_factory=list)
    recognized: bool = False
    clear_only: bool = False


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ").replace("₂", "2")).strip()


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _number(value: str) -> Decimal:
    if not isinstance(value, str) or len(value) > 24 or not re.fullmatch(_NUMBER, value):
        raise ValueError("An ECLS number could not be read safely.")
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation:
        raise ValueError("An ECLS number could not be read safely.") from None
    if not number.is_finite() or not 0 <= number <= Decimal("1000000000"):
        raise ValueError("An ECLS number is outside the supported range.")
    return number


def _identify(label: str) -> tuple[str, str] | None:
    label = _clean(label).rstrip(":").strip()
    match = re.fullmatch(r"(.+?)(?:\s*\(([^()]*)\))?", label)
    if not match:
        return None
    key = _LABELS.get(match.group(1).strip().casefold())
    return (key, (match.group(2) or "").strip()) if key else None


def _field_line(line: str) -> tuple[str, str, str] | None:
    cells = re.split(r"\t+|:\s*| {2,}", line, maxsplit=1)
    identified = _identify(cells[0])
    if identified is None:
        return None
    key, unit = identified
    return key, unit, _clean(cells[1]) if len(cells) == 2 else ""


def _mode(value: str) -> str:
    compact = re.sub(r"[\s\-–]+", "", value).casefold()
    modes = {"va": "VA", "venoarterial": "VA", "vv": "VV", "venovenous": "VV"}
    if compact not in modes:
        raise ValueError("ECLS mode is not a supported VA or VV label. It is shown as UNK.")
    return modes[compact]


def _value(key: str, raw: str, label_unit: str) -> str:
    if raw.casefold().rstrip(".") in _MISSING:
        return ""
    if key == "mode":
        return _mode(raw)
    if key == "oxygenator_day":
        match = re.fullmatch(r"(\d+)(?:\s*days?)?", raw, re.I)
        if not match:
            raise ValueError("ECLS oxygenator day could not be read as a nonnegative whole number. It is shown as UNK.")
        return _plain(_number(match.group(1)))
    unit_pattern = _UNIT_PATTERNS[key]
    if label_unit and not re.fullmatch(unit_pattern, label_unit, re.I):
        raise ValueError("An ECLS setting has unsupported units. The affected setting is shown as UNK.")
    match = re.fullmatch(rf"({_NUMBER})\s*({unit_pattern})?", raw, re.I)
    if not match or not (label_unit or match.group(2)):
        raise ValueError("An ECLS setting could not be read as one number with its documented units. The affected setting is shown as UNK.")
    number = _number(match.group(1))
    if key == "rpm" and number != number.to_integral_value():
        raise ValueError("ECLS set speed could not be read as a whole number of revolutions per minute. It is shown as UNK.")
    if key == "fio2_percent" and number > 100:
        raise ValueError("ECLS blender FiO2 is outside 0 to 100 percent. It is shown as UNK.")
    return _plain(number)


def validate_ecls(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        raise ValueError("The ECLS snapshot has an invalid structure.")
    if data["mode"] not in ("", "VA", "VV"):
        raise ValueError("The ECLS mode must be VA, VV, or blank when unavailable.")
    for key in FIELDS[1:]:
        value = data[key]
        if not isinstance(value, str):
            raise ValueError("An ECLS setting has an invalid value.")
        if not value:
            continue
        number = _number(value)
        if _plain(number) != value:
            raise ValueError("An ECLS setting is not normalized.")
        if key in ("oxygenator_day", "rpm") and number != number.to_integral_value():
            raise ValueError("ECLS oxygenator day and RPM must be whole numbers.")
        if key == "fio2_percent" and number > 100:
            raise ValueError("ECLS blender FiO2 must be between 0 and 100 percent.")
    if not any(data.values()):
        raise ValueError("An empty ECLS snapshot must be stored as absent.")


def parse_ecls(text: str) -> ECLSResult:
    """Parse one AD snapshot, never choosing between undated distinct reports.

    Missing or unreadable individual settings are blank and produce static
    review notes. Conflicting duplicate fields or multiple populated System
    Readings reports reject the snapshot, so old and new settings never merge.
    """
    out = ECLSResult()
    if not isinstance(text, str) or len(text) > 20000:
        out.error = "The ECLS section is invalid or too large."
        return out
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("：", ":")
    reports: list[list[str]] = [[]]
    for raw in normalized.splitlines():
        line = raw.replace("\u00a0", " ").strip()
        if not line or _DELIMITER.fullmatch(line) or line.casefold().rstrip(".") in _MISSING:
            continue
        if _HEADER.fullmatch(line):
            if reports[-1]:
                reports.append([])
            continue
        reports[-1].append(line)
    reports = [report for report in reports if report]
    if not reports:
        out.clear_only = True
        return out
    recognized_reports = [report for report in reports if any(_field_line(line) for line in report)]
    out.recognized = bool(recognized_reports)
    if len(reports) > 1:
        out.error = "More than one ECLS settings snapshot was found. Paste one verified AD snapshot per patient."
        return out
    if not recognized_reports:
        out.error = "No supported ECLS settings were found. Check the AD section."
        return out
    data = {key: "" for key in FIELDS}
    seen: dict[str, str] = {}
    invalid: set[str] = set()
    try:
        for line in recognized_reports[0]:
            entry = _field_line(line)
            if entry is None:
                continue
            key, unit, raw_value = entry
            try:
                value = _value(key, raw_value, unit)
            except ValueError:
                if key in seen:
                    raise ValueError("Conflicting ECLS settings were supplied. Check the AD section against the chart.") from None
                invalid.add(key)
                note = "ECLS " + _NAMES[key] + " could not be read safely. The affected setting is shown as UNK."
                if note not in out.issues:
                    out.issues.append(note)
                continue
            if not value:
                continue
            if key in invalid or key in seen and seen[key] != value:
                raise ValueError("Conflicting ECLS settings were supplied. Check the AD section against the chart.")
            seen[key] = value
            data[key] = value
        if not any(data.values()):
            out.clear_only = not invalid
            return out
        validate_ecls(data)
        out.data = data
        if any(not data[key] for key in FIELDS):
            out.issues.append("Some ECLS settings were not supplied or could not be read. Missing settings are shown as UNK.")
    except ValueError as exc:
        out.error = str(exc)
        out.data = None
    return out


def _blocked(sheet: dict) -> bool:
    flags = sheet.get("import_warnings", {}).get("ad", [])
    return any(item.get("action") in ("ecls_hidden", "not_imported", "not_updated")
               or item.get("code") == "section_boundary" for item in flags)


def _dosing_kg(sheet: dict) -> Decimal | None:
    if sheet.get("import_warnings", {}).get("i"):
        return None
    value = sheet.get("dosing_weight", "")
    try:
        validate_dosing_weight(value)
        if not value:
            return None
        match = WEIGHT.fullmatch(value.strip())
        kg = _number(match.group("value"))
        unit = match.group("unit").lower()
        if unit == "g":
            kg /= 1000
        elif unit in ("lb", "lbs"):
            kg *= Decimal("0.45359237")
        elif unit == "oz":
            kg *= Decimal("0.028349523125")
        return kg if kg > 0 else None
    except (ValueError, AttributeError):
        return None


def _chart_bsa(sheet: dict) -> Decimal | None:
    if sheet.get("import_warnings", {}).get("i"):
        return None
    measurements = sheet.get("anthropometrics")
    if not isinstance(measurements, dict):
        return None
    value = measurements.get("bsa", "")
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = clean_field("bsa", value)
        if not normalized:
            return None
        number = _number(normalized.split(" ", 1)[0])
        return number if number > 0 else None
    except ValueError:
        return None


def ecls_issues(sheet: dict) -> list[str]:
    """Return static explanations for unavailable derived flow values."""
    data = sheet.get("ecls")
    validate_ecls(data)
    if data is None or _blocked(sheet) or not data["blood_flow_l_min"]:
        return []
    issues = []
    if _dosing_kg(sheet) is None:
        issues.append("ECLS flow in mL/kg/min is unavailable because a valid dosing weight was not imported.")
    if _chart_bsa(sheet) is None:
        issues.append("ECLS CI is unavailable because a valid chart-reported BSA was not imported.")
    return issues


def ecls_lines(sheet: dict) -> list[str]:
    """Return the compact four-line ECLS block, or no block when absent/hidden."""
    if _blocked(sheet):
        return []
    data = sheet.get("ecls")
    validate_ecls(data)
    if data is None:
        return []
    mode, day = data["mode"] or "UNK", data["oxygenator_day"] or "UNK"
    blood_flow = data["blood_flow_l_min"]
    flow_text = (blood_flow + " L/min") if blood_flow else "UNK"
    if blood_flow:
        flow = _number(blood_flow)
        weight, bsa = _dosing_kg(sheet), _chart_bsa(sheet)
        with localcontext() as context:
            context.prec = 80
            indexed = format((flow * 1000 / weight).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), ".1f") if weight else "UNK"
            ci = _plain((flow / bsa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if bsa else "UNK"
        flow_text += ", " + indexed + " mL/kg/min [CI: " + ci + (" L/min/m²" if bsa else "") + "]"
    return ["ECLS settings:",
            "Mode: " + mode + " [Oxy Day: " + day + "]",
            "Blood flow: " + flow_text,
            "RPM: " + (data["rpm"] or "UNK") + " | Sweep: " + (data["sweep_l_min"] + " L/min" if data["sweep_l_min"] else "UNK")
            + " | FiO₂: " + (data["fio2_percent"] + "%" if data["fio2_percent"] else "UNK")]


def ecls_text(sheet: dict) -> str:
    return "\n".join(ecls_lines(sheet))
