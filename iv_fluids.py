"""Display explicitly named continuous IV fluids and a recorded-rate comparison.

The hourly 4-2-1 value is a display reference using documented dosing weight.
It is not an order, a target, or a sum of the patient's fluid intake. Original
formulations, rates, timestamps, and saved overrides are never changed here.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
from html import escape
import re

from infusion_rates import ADMIN_STATUS_LABELS, is_rate, valid_admin_time
from medications import match_name, normalized
from output_text import medication_name_output, medication_output


_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
_NUMBER = "(?:" + _NUMBER + ")"
_SALT = r"(?:sodium\s+chloride|nacl)\s+(?:0?\.9|0?\.45|0?\.225|0?\.2)(?:0*)\s*%"
_DEXTROSE = r"dextrose\s+(?:2\.5|5|10)(?:\.0+)?\s*%"
_RINGER = r"(?:lactated\s+ringer(?:'?s)?|ringer(?:'?s)?\s+lactate|lr)"
_PLASMALYTE = r"plasma[ -]?lyte(?:\s+(?:a|148))?"
_SHORT = r"(?:d(?:2\.5|5|10)(?:\s*w)?|d(?:5|10)[ /]*(?:ns|lr|(?:0?\.45|0?\.9)\s*%?\s*ns|1/2\s*ns)|(?:0?\.9|0?\.45)\s*%?\s*ns|ns|normal\s+saline)"
_BASE = "(?:" + "|".join((
    _DEXTROSE + r"(?:\s+(?:and|in|with)\s+(?:" + _SALT + "|" + _RINGER + "))?",
    _SALT, _RINGER, _PLASMALYTE, _SHORT,
)) + ")"
_FORMULATION = re.compile(
    r"^(?:sodium\s+acetate\s+" + _NUMBER + r"\s*meq\s+in\s+)?"
    + _BASE
    + r"(?:\s+in\s+water)?(?:\s+" + _NUMBER + r"\s*(?:ml|l))?"
    + r"(?:\s+(?:infusion|injection|solution|intravenous|iv))*$", re.I)
_KCL_FORMULATION = re.compile(
    r"^(?:potassium\s+chloride|kcl)\s+(?P<amount>" + _NUMBER + r")\s*meq\s+in\s+"
    + _BASE + r"\s+(?P<volume>" + _NUMBER + r")\s*ml"
    + r"(?:\s+(?:infusion|injection|solution|intravenous|iv))*$", re.I)
_VOLUME_RATE = re.compile(r"^\s*(?P<value>" + _NUMBER + r")\s*ml\s*/\s*(?:h|hr|hrs|hour|hours)\s*$", re.I)
_QUALIFIER = re.compile(r"\(\s*(?:dosing\s+weight|order-specific)\s*\)", re.I)
_NONRUNNING = {"stopped", "paused", "held", "not_given", "not_administered", "discontinued"}


def is_iv_fluid(row: dict) -> bool:
    """Require a complete recognized fluid formulation and explicit IV delivery.

    Full matching prevents a drug merely diluted in saline or dextrose from
    becoming a generic fluid. Concentrated salts, D50, PN/lipids, boluses,
    flushes, nebulizers, and enteral products do not match this allowlist.
    """
    if normalized(row.get("route", "")) not in {"iv", "intravenous"}:
        return False
    frequency = normalized(row.get("frequency", ""))
    if row.get("infusion_mode") == "other" or re.search(r"\bprn\b|\bas[ -]+needed\b", frequency):
        return False
    if not (re.search(r"\bcontinuous\b|\btitrat(?:e|able)\b", frequency)
            or row.get("infusion_mode") == "infusion"):
        return False
    name = match_name(row.get("name", ""))
    if _FORMULATION.fullmatch(name):
        return True
    additive = _KCL_FORMULATION.fullmatch(name)
    if not additive:
        return False
    amount = Decimal(additive.group("amount").replace(",", ""))
    volume = Decimal(additive.group("volume").replace(",", ""))
    # Accept only the explicitly named standard dilute bags. Small-volume
    # electrolyte replacement products and unspecified concentrations retain
    # their existing medication placement, even with a continuous frequency.
    return volume in {Decimal(500), Decimal(1000)} and amount * 1000 / volume in {Decimal(20), Decimal(40)}


def _dosing_kg(value: str) -> Decimal | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(kg|g|lbs?|oz)\s*", value, re.I)
    if not match:
        return None
    weight = Decimal(match.group(1))
    if weight <= 0:
        return None
    factor = {"kg": Decimal(1), "g": Decimal("0.001"),
              "lb": Decimal("0.45359237"), "lbs": Decimal("0.45359237"),
              "oz": Decimal("0.028349523125")}[match.group(2).casefold()]
    return weight * factor


def maintenance_annotation(rate_ml_hr, dosing_weight: str) -> str:
    """Compare one explicit hourly rate with uncapped 4-2-1 using only DCW."""
    weight = _dosing_kg(dosing_weight)
    try:
        rate = Decimal(str(rate_ml_hr))
    except (InvalidOperation, ValueError, TypeError):
        return ""
    if weight is None or not rate.is_finite() or rate <= 2:
        return ""
    baseline = (4 * min(weight, Decimal(10))
                + 2 * min(max(weight - 10, Decimal(0)), Decimal(10))
                + max(weight - 20, Decimal(0)))
    ratio = rate / baseline
    quarter_count = (ratio * 4).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    quarter = quarter_count / 4
    if quarter > 0 and abs(ratio - quarter) <= Decimal("0.02"):
        fraction = Fraction(int(quarter_count), 4)
        if fraction == 1:
            label = "maintenance"
        elif fraction.denominator == 1:
            label = str(fraction.numerator) + "x maintenance"
        elif fraction.numerator > fraction.denominator:
            whole, numerator = divmod(fraction.numerator, fraction.denominator)
            label = f"{whole} {numerator}/{fraction.denominator} maintenance"
        else:
            label = f"{fraction.numerator}/{fraction.denominator} maintenance"
        return ("" if ratio == quarter else "~") + label
    percent = ratio * 100
    rounded = percent.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if rounded == 0:
        return "<1% maintenance"
    return ("" if percent == rounded else "~") + str(rounded) + "% maintenance"


def _hourly_rate(value: str) -> Decimal | None:
    match = _VOLUME_RATE.fullmatch(_QUALIFIER.sub("", value))
    return Decimal(match.group("value").replace(",", "")) if match else None


def _stamp(value: str) -> str:
    # No date guessing and no propagation of unexpected author text.
    return value.strip() if isinstance(value, str) and valid_admin_time(value.strip()) else ""


def _unclear_last_rate(row: dict) -> bool:
    return any("last rate field" in normalized(warning) for warning in row.get("warnings", []))


def iv_fluid_entry(row: dict, sheet: dict | None = None, rich: bool = False, esc=escape,
                   *, dosing_weight: str | None = None) -> str:
    """Render a fluid without mutating its rate, dose, or source provenance."""
    encode = esc if rich else lambda text: text
    bold = lambda text: "<b>" + encode(text) + "</b>" if rich else text
    custom = medication_output(row.get("custom_text", "").strip())
    if custom:
        return bold(custom)
    name = medication_name_output(medication_output(row.get("_display_name") or row.get("name", "")))
    lines = [bold(name)]
    context = sheet if sheet is not None else row.get("_iv_fluid_context", {})
    weight = dosing_weight if dosing_weight is not None else context.get("dosing_weight", "")
    if "i" in context.get("import_warnings", {}):
        weight = ""
    eligible = is_iv_fluid(row)
    status = row.get("last_admin_status", "unavailable")
    admin_rate = row.get("last_admin_rate", "").strip()
    admin_stamp = _stamp(row.get("last_admin_time", ""))
    recorded = row.get("last_rate", "").strip()
    recorded_stamp = _stamp(row.get("rate_time", ""))
    dose = row.get("dose", "").strip()
    unclear_recorded = _unclear_last_rate(row)
    if row.get("rate_time", "") and not recorded_stamp:
        unclear_recorded = True
    held_name = re.search(r"\[(held\s+by\s+provider|discontinued)\]", row.get("name", ""), re.I)

    def rate_line(label: str, value: str, stamp: str = "", compare: bool = False) -> str:
        text = label + ": " + medication_output(value)
        if stamp:
            text += " [" + stamp + "]"
        hourly = _hourly_rate(value) if compare and eligible else None
        annotation = maintenance_annotation(hourly, weight) if hourly is not None else ""
        if annotation:
            text += " (" + annotation + ")"
        return encode(text)

    if status in _NONRUNNING:
        lines.append(rate_line("Last Admin", ADMIN_STATUS_LABELS[status], admin_stamp))
    elif held_name:
        # The source order status remains visible even if its Last Admin still
        # contains an older numeric event. Do not present that as a running rate.
        lines.append(encode("Order status: " + held_name.group(1).capitalize()))
    elif status == "rate" and is_rate(admin_rate):
        lines.append(rate_line("Last Admin rate", admin_rate, admin_stamp, True))
        if recorded and normalized(recorded) != normalized(admin_rate):
            lines.append(rate_line("Last Rate", recorded, recorded_stamp))
        elif recorded_stamp and recorded_stamp != admin_stamp:
            lines.append(encode("Last Rate also recorded [" + recorded_stamp + "]"))
    else:
        unclear_admin = status == "unreadable" or (status == "rate" and not is_rate(admin_rate))
        if unclear_admin:
            lines.append(rate_line("Last Admin", "Unclear entry", admin_stamp))
        if recorded:
            lines.append(rate_line("Last Rate", recorded, recorded_stamp,
                                   not unclear_admin and not unclear_recorded))
            if unclear_recorded:
                lines.append(encode("Last Rate needs review."))
        elif unclear_recorded:
            lines.append(encode("Last Rate: UNK. Review needed."))
        elif dose:
            # An ordered hourly rate is explicitly labeled as ordered. A range,
            # bag volume, or weight-based dose never supplies an hourly value.
            label = "Ordered rate" if _hourly_rate(dose) is not None else "Dose"
            lines.append(rate_line(label, dose, compare=not unclear_admin))
        else:
            lines.append(encode("Rate: UNK"))
        if status == "no_rate" and admin_stamp and (not recorded or admin_stamp != recorded_stamp):
            lines.append(rate_line("Last Admin", "Event without a rate", admin_stamp))
    details = ", ".join(medication_output(row.get(key, "").strip())
                        for key in ("route", "frequency") if row.get(key, "").strip())
    if details:
        lines.append(encode(details))
    return "\n".join(lines)
