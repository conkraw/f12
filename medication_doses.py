"""Derived per-dose display for selected medications, without changing orders.

The structured Dose column supplies the amount. Product strengths, Last Admin,
pump rates and administration counts are never treated as a per-dose amount.
An already documented mg/kg or mcg/kg dose remains authoritative in the ordinary
formatter, so this helper adds nothing to it. Derived annotations are transient.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re


_NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
_ABSOLUTE_DOSE = re.compile(
    rf"\s*({_NUMBER})\s*(mg|mcg|[uµμ]g)(?:\s*(?:/\s*dose|per\s+dose))?\s*",
    re.I,
)
_WEIGHT = re.compile(r"\s*(\d+(?:\.\d+)?)\s*(kg|g)\s*", re.I)
_DIURETIC = re.compile(r"^(?:chlorothiazide|furosemide|diuril|lasix)(?=$|[\s(,])")
_CONTINUOUS = re.compile(r"\bcontinuous\b|\btitrat\w*", re.I)


def _positive_decimal(text: str) -> Decimal | None:
    # Bounded fixed-point source values only, not exponents, NaN or infinity.
    if len(text) > 32 or re.fullmatch(_NUMBER, text) is None:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() and value > 0 else None


def _weight(value: object, label: str) -> tuple[Decimal | None, str]:
    if not isinstance(value, str):
        return None, ""
    match = _WEIGHT.fullmatch(value)
    if match is None:
        return None, ""
    number = _positive_decimal(match[1])
    if number is None:
        return None, ""
    with localcontext() as context:
        context.prec = 80
        kg = number / (1000 if match[2].lower() == "g" else 1)
    return kg, label + " " + match[1] + " " + match[2].lower()


def medication_weight(sheet: dict | None) -> tuple[Decimal | None, str]:
    """Use documented DCW, otherwise included measured weight, in kg or g.

    A failed I-block import blocks both sources. A present but invalid DCW does
    not silently fall back to another weight. No weight is recovered from I/O,
    product names, calculated doses, free-text notes or older room content.
    """
    if not isinstance(sheet, dict) or "i" in sheet.get("import_warnings", {}):
        return None, ""
    dosing_weight = sheet.get("dosing_weight", "")
    if not isinstance(dosing_weight, str):
        return None, ""
    if dosing_weight.strip():
        return _weight(dosing_weight, "DCW")
    nutrition = sheet.get("nutrition")
    if not isinstance(nutrition, dict) or nutrition.get("include") is not True:
        return None, ""
    return _weight(nutrition.get("weight"), "weight")


def _eligible(row: dict, placement: dict | None) -> bool:
    # Lazy imports keep the helper usable from the central medication formatter.
    from medications import match_name, visible
    from medication_groups import is_prn

    if not visible(row) or row.get("custom_text", "").strip():
        return False
    if row.get("infusion_mode") == "infusion" or _CONTINUOUS.search(row.get("frequency", "")):
        return False
    if _DIURETIC.match(match_name(row.get("name", ""))):
        return True
    if not is_prn(row):
        return False
    if placement is None:
        from categories import placement as resolve_placement
        placement = resolve_placement(row)
    return "group:sedative_prn" in (placement.get("id"), placement.get("parent_id"))


def _display_number(value: Decimal) -> str:
    """Three significant figures, fixed point, including very small doses."""
    with localcontext() as context:
        context.prec = 80
        rounded = value.quantize(Decimal(1).scaleb(value.adjusted() - 2), rounding=ROUND_HALF_UP)
    text = format(rounded, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def dose_per_kg_annotation(row: dict, sheet: dict | None, placement: dict | None = None) -> str:
    """Return a calculated per-dose annotation or an empty string.

    Example output: ``1.4 mg/kg/dose (DCW 10 kg)``. Callers append this to a
    rendered copy only. All absolute source amounts and explicit weight-based
    source doses remain unchanged. This describes an ordered dose, not the
    amount administered over a day or shift.

    Only one unambiguous mg/mcg amount in the Dose column is eligible. Ranges,
    concentrations, infusion rates, daily totals and unknown annotations are
    deliberately left as documented, with no derived number added.
    """
    if not _eligible(row, placement):
        return ""
    dose = row.get("dose", "")
    if not isinstance(dose, str):
        return ""
    match = _ABSOLUTE_DOSE.fullmatch(dose)
    if match is None:
        return ""
    amount = _positive_decimal(match[1])
    weight, basis = medication_weight(sheet)
    if amount is None or weight is None:
        return ""
    with localcontext() as context:
        context.prec = 80
        ratio = amount / weight
    unit = "mg" if match[2].lower() == "mg" else "mcg"
    return _display_number(ratio) + " " + unit + "/kg/dose (" + basis + ")"
