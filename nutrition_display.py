"""Display explicit dietary orders beside recorded feeds and medication PN.

Dietary rates and schedules describe ordered nutrition. Only a documented
continuous rate and daily infusion duration are multiplied. A dosing weight
is required for mL/kg/day. Stored source rows are never changed by rendering.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
import re

from feeds import RATE, validate_feeds
from medications import match_name


_NUMBER = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+")
_POST_PYLORIC = {"NJ", "ND", "Post-pyloric"}
_STATUS_LABELS = {"held": "[Held] ", "future": "[Future order] "}


def has_detailed_nutrition(diet: dict | None) -> bool:
    return isinstance(diet, dict) and "enteral" in diet and "parenteral" in diet


def _number(value: str) -> Decimal | None:
    if not isinstance(value, str) or not _NUMBER.fullmatch(value.strip()):
        return None
    try:
        result = Decimal(value.replace(",", "").strip())
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def _display_number(value: Decimal, places: int | None = None) -> str:
    if places is not None:
        value = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def dosing_weight_for_feeds(dosing_weight: str = "", sheet: dict | None = None) -> tuple[Decimal | None, str]:
    """Use only an explicit positive DCW in kg/g, never a measured fallback."""
    if sheet is not None:
        if "i" in sheet.get("import_warnings", {}):
            return None, ""
        dosing_weight = sheet.get("dosing_weight", dosing_weight)
    if not isinstance(dosing_weight, str):
        return None, ""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(kg|g)\s*", dosing_weight, re.I)
    if match is None:
        return None, ""
    amount = Decimal(match[1])
    kg = amount / (1000 if match[2].casefold() == "g" else 1)
    if kg <= 0:
        return None, ""
    return kg, match[1] + " " + match[2].lower()


def parenteral_kind(name: str) -> str:
    """Identify explicitly named PN and lipid products, not their indication."""
    name = match_name(name)
    if re.match(r"^(?:fat\s+emulsion|smoflipid|intralipid)\b", name):
        return "lipid"
    if re.search(r"\b(?:TPN|PPN|PN|parenteral\s+nutrition)\b", name, re.I):
        return "pn"
    return ""


def _formula_key(value: str) -> str:
    # Decimal strengths and ratios are formulation data, not punctuation noise.
    text = re.sub(r"(?<=\d)\s*([.:/%+\-])\s*(?=\d)", r"\1", value.casefold())
    return re.sub(r"[^\w.:/%+\-]+", " ", text).strip()


def _pn_key(name: str) -> str:
    """Normalize typography and generic wrappers without merging products."""
    text = match_name(name).replace("–", "-").replace("—", "-")
    text = re.sub(r"\btotal\s+parenteral\s+nutrition\b", "tpn", text)
    text = re.sub(r"\bperipheral\s+parenteral\s+nutrition\b", "ppn", text)
    text = re.sub(r"\bparenteral\s+nutrition\b|\btpn\b", "pn", text)
    text = re.sub(r"\b(\d+)\s*[- ]?in\s*[- ]?(\d+)\b", r"\1-in-\2", text)
    if re.search(r"\b(?:smoflipid|intralipid)\b", text):
        text = re.sub(r"^fat\s+emulsion\s*", "", text)
    text = re.sub(r"\s+(?:infusion|injection)\s*$", "", text)
    return _formula_key(text)


def _generic_pn(key: str) -> bool:
    return re.fullmatch(r"(?:(?:pediatric|peds|adult|infant|neonatal)\s+)?pn(?:\s+(?:continuous|cyclic))?", key) is not None


def _pn_compatible(left: str, right: str) -> bool:
    """A generic label may match only when its supplied qualifiers agree."""
    if bool(re.search(r"\bppn\b", left)) != bool(re.search(r"\bppn\b", right)):
        return False
    for pattern in (r"\b(?:continuous|cyclic)\b", r"\b(?:pediatric|peds|adult|infant|neonatal)\b"):
        a, b = re.search(pattern, left), re.search(pattern, right)
        if a and b:
            av, bv = a.group(), b.group()
            av = "pediatric" if av == "peds" else av
            bv = "pediatric" if bv == "peds" else bv
            if av != bv:
                return False
    return True


def _pn_duplicate_indexes(orders: list[dict], medications) -> set[int]:
    """Suppress only matching products or a uniquely resolvable generic PN.

    Hidden medication entries still participate so a dietary copy cannot undo
    a user's visibility choice. Distinct formulations and lipid brands remain.
    """
    medication_keys = {(_pn_key(row.get("name", "")), parenteral_kind(row.get("name", "")))
                       for row in medications if parenteral_kind(row.get("name", ""))}
    order_keys = {(_pn_key(row["name"]), parenteral_kind(row["name"])) for row in orders}
    duplicated = set()
    for index, row in enumerate(orders):
        key, kind = _pn_key(row["name"]), parenteral_kind(row["name"])
        if (key, kind) in medication_keys:
            duplicated.add(index)
            continue
        if kind != "pn":
            continue
        candidates = {other for other, other_kind in medication_keys
                      if other_kind == "pn" and (_generic_pn(key) or _generic_pn(other))
                      and _pn_compatible(key, other)}
        if len(candidates) != 1:
            continue
        candidate = next(iter(candidates))
        reverse = {other for other, other_kind in order_keys if other_kind == "pn"
                   and (other == candidate or _generic_pn(candidate) or _generic_pn(other))
                   and _pn_compatible(candidate, other)}
        if len(reverse) == 1:
            duplicated.add(index)
    return duplicated


def _compatible_route(ordered: str, recorded: str) -> bool:
    if ordered == recorded and ordered != "UNK":
        return True
    return ordered == "Post-pyloric" and recorded in _POST_PYLORIC


def _feed_matches(ordered: dict, recorded: dict) -> bool:
    if not _compatible_route(ordered.get("method", "UNK"), recorded.get("method", "UNK")):
        return False
    left, right = _formula_key(ordered.get("formula", "")), _formula_key(recorded.get("formula", ""))
    # Missing formula may be corroborated only through an otherwise unique
    # compatible tube. Different supplied formulas are not declared equivalent.
    return not left or not right or left == right


def _recorded_matches(ordered: list[dict], recorded: list[dict]) -> dict[int, int]:
    candidates = {index: [j for j, row in enumerate(recorded) if _feed_matches(order, row)]
                  for index, order in enumerate(ordered)}
    counts = {}
    for matches in candidates.values():
        for index in matches:
            counts[index] = counts.get(index, 0) + 1
    return {index: matches[0] for index, matches in candidates.items()
            if len(matches) == 1 and counts[matches[0]] == 1}


def _rate_number(rate: str) -> Decimal | None:
    match = RATE.fullmatch(rate.strip()) if isinstance(rate, str) else None
    return _number(match["number"]) if match else None


def _continuous(row: dict) -> bool:
    return re.fullmatch(r"continuous(?:\s+(?:feeds?|feeding))?", row.get("feeding_type", "").strip(), re.I) is not None


def _feeding_lines(row: dict, recorded: dict | None, kg: Decimal | None) -> tuple[list[str], bool]:
    method = row.get("method", "UNK")
    status = row.get("status", "active")
    prefix = _STATUS_LABELS.get(status, "")
    label = "Oral feed" if method == "PO" else "Tube feeds"
    label += " (ordered, " + method + "): "
    formula = row.get("formula", "") or "UNK formula"
    density = row.get("caloric_density", "").strip()
    if density and density.casefold() not in formula.casefold():
        formula += " (" + density + ")"
    rate = row.get("rate", "").strip()
    hours = _number(row.get("hours", ""))
    rate_number = _rate_number(rate)
    daily = _number(row.get("daily_volume", ""))
    line = prefix + label + formula + " @ " + (rate or "UNK rate")
    if hours is not None and 0 < hours <= 24:
        line += " x " + _display_number(hours) + " hr/day"
    elif row.get("hours", "").strip():
        line += " | Infusion time: " + row["hours"] + " hr/day"
    lines = []
    calculated = False
    can_calculate = (status == "active" and _continuous(row) and rate_number is not None
                     and hours is not None and 0 < hours <= 24)
    if can_calculate:
        total = rate_number * hours
        line += " = " + _display_number(total) + " mL/day"
        if daily is not None and daily != total:
            lines.append("Listed total: " + _display_number(daily) + " mL/day. Review rate/hours.")
        elif kg is not None:
            line += " (" + _display_number(total / kg, 1) + " mL/kg/day)"
            calculated = True
    elif daily is not None:
        lines.append("Listed total: " + _display_number(daily) + " mL/day")
    feeding_type = row.get("feeding_type", "").strip()
    if feeding_type and not _continuous(row):
        lines.insert(0, "Schedule: " + feeding_type)
    if recorded is not None and recorded.get("include", False):
        if not row.get("formula", "").strip() and recorded.get("formula", "").strip():
            lines.append("Recorded formula: " + recorded["formula"])
        other_rate = recorded.get("rate", "")
        other_number = _rate_number(other_rate)
        if other_number is not None and other_number != rate_number:
            # An older/other recorded rate is never used with the new order's
            # duration to manufacture a hybrid calculated volume.
            lines.append("Recorded rate: " + other_rate)
    additive = row.get("additives", "").strip()
    if additive and not re.fullmatch(r"(?:no\s+)?additives|other\s*[-:]?\s*note\s+in\s+comments?", additive, re.I):
        lines.append("Additives: " + additive)
    comments = row.get("comments", "").strip()
    if comments:
        lines.append("Instructions: " + comments)
    return [line] + lines, calculated


def nutrition_sections(diet: dict | None, feeds: dict | None = None, medications=(), *,
                       dosing_weight: str = "", sheet: dict | None = None,
                       rich: bool = False, esc=escape) -> list[str]:
    """Return oral, ordered/recorded tube feeding, and diet-only PN sections.

    Medication PN remains in the normal medication renderer. Any corresponding
    medication PN, including a deliberately hidden entry, suppresses the diet
    duplicate. Lipids are distinct from PN solutions.
    """
    if not has_detailed_nutrition(diet):
        return []
    from diet import validate_diet
    validate_diet(diet)
    validate_feeds(feeds)
    encode = esc if rich else lambda value: value
    def label(text: str) -> str:
        return "<b>" + encode(text) + "</b>" if rich else text
    parts = []
    oral = [row["text"] for row in diet["rows"] if row["include"]]
    if oral:
        parts.append(label("Oral:") + " " + " | ".join(encode(value) for value in oral))
    ordered = diet["enteral"]
    recorded = feeds["rows"] if feeds else []
    if "recorded_feed_ids" in diet:
        # The importer records which feed rows belong to this dietary update.
        # A new empty/NPO order must not resurrect an older T snapshot.
        current_ids = set(diet["recorded_feed_ids"])
        recorded = [row for row in recorded if row["id"] in current_ids]
    matches = _recorded_matches(ordered, recorded)
    consumed = set(matches.values())
    kg, basis = dosing_weight_for_feeds(dosing_weight, sheet)
    lines, calculated = [], False
    for index, row in enumerate(ordered):
        if not row["include"]:
            continue
        linked = recorded[matches[index]] if index in matches else None
        result, uses_weight = _feeding_lines(row, linked, kg)
        lines.extend(encode(value) for value in result)
        calculated |= uses_weight
    if calculated:
        lines.append(encode("Using dosing weight: " + basis))
    if lines:
        parts.append("\n".join(lines))
    for index, row in enumerate(recorded):
        if index in consumed or not row["include"]:
            continue
        if ordered and _rate_number(row["rate"]) is None:
            # A device may retain a formula label while used for venting or
            # medication. A current detailed feed order is stronger evidence
            # than an unmatched label with no documented feeding rate.
            continue
        method = row["method"]
        heading = "Oral feed (recorded):" if method == "PO" else "Tube feeds (recorded, " + method + "):"
        parts.append(label(heading) + " " + encode(row["formula"] or "UNK formula") + " @ " + encode(row["rate"] or "UNK rate"))
    duplicated_pn = _pn_duplicate_indexes(diet["parenteral"], medications)
    for index, row in enumerate(diet["parenteral"]):
        if not row["include"]:
            continue
        kind = parenteral_kind(row["name"])
        if index in duplicated_pn:
            continue
        text = _STATUS_LABELS.get(row.get("status", "active"), "") + row["name"]
        if row.get("rate", ""):
            text += " @ " + row["rate"]
        parts.append(label("TPN (diet order):" if kind != "lipid" else "Lipids (diet order):") + " " + encode(text))
    return parts


def nutrition_text(diet: dict | None, feeds: dict | None = None, medications=(), **kwargs) -> str:
    return "\n-----\n".join(nutrition_sections(diet, feeds, medications, **kwargs))
