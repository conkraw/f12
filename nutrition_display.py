"""Display explicit dietary orders beside recorded feeds and medication PN.

Dietary rates and schedules describe ordered nutrition. A missing continuous
schedule defaults to 24 hours unless the supplied duration was invalid or
conflicting. Daily kcal needs an explicit calorie density. A dosing weight is
required for kcal/kg/day and mL/kg/day. Unknown formula and rate fields are
omitted. Stored source rows are never changed by rendering.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
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
    if len(value.replace(",", "").strip()) > 20:
        return None
    try:
        result = Decimal(value.replace(",", "").strip())
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def _display_number(value: Decimal, places: int | None = None) -> str:
    if places is not None:
        with localcontext() as context:
            context.prec = 80
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
    amount = _number(match[1])
    if amount is None:
        return None, ""
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


def _known_formula(value: str) -> str:
    value = value.strip()
    return "" if value.casefold() in {"unk", "unknown"} else value


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
    return (ordered == "Post-pyloric" and recorded in _POST_PYLORIC
            or recorded == "Post-pyloric" and ordered in _POST_PYLORIC)


def recorded_feed_matches(ordered: list[dict], recorded: list[dict]) -> dict[int, int]:
    """Pair unique exact formulas first, then unique compatible tube routes.

    A detailed order is authoritative for its paired tube even if the recorded
    formula differs. Pairing does not equate those formulas or copy any value.
    Multiple possible tubes remain separate rather than guessed.
    """
    matched = {}
    consumed = set()
    for exact_formula in (True, False):
        candidates = {}
        for index, order in enumerate(ordered):
            if index in matched:
                continue
            choices = []
            for j, row in enumerate(recorded):
                if j in consumed or not _compatible_route(order.get("method", "UNK"), row.get("method", "UNK")):
                    continue
                if exact_formula:
                    left = _formula_key(_known_formula(order.get("formula", "")))
                    right = _formula_key(_known_formula(row.get("formula", "")))
                    if not left or not right or left != right:
                        continue
                choices.append(j)
            candidates[index] = choices
        counts = {}
        for choices in candidates.values():
            for index in choices:
                counts[index] = counts.get(index, 0) + 1
        for index, choices in candidates.items():
            if len(choices) == 1 and counts[choices[0]] == 1:
                matched[index] = choices[0]
                consumed.add(choices[0])
    return matched


def _rate_number(rate: str) -> Decimal | None:
    match = RATE.fullmatch(rate.strip()) if isinstance(rate, str) else None
    return _number(match["number"]) if match else None


def _continuous(row: dict) -> bool:
    return re.fullmatch(r"continuous(?:\s+(?:feeds?|feeding))?", row.get("feeding_type", "").strip(), re.I) is not None


def _conflicted_fields(sheet: dict | None) -> set[str]:
    if sheet is None:
        return set()
    return {item.get("field", "") for section in ("x", "ab")
            for item in sheet.get("import_warnings", {}).get(section, [])
            if item.get("code") == "nutrition_conflict"}


def _source_hours_conflict(row: dict) -> bool:
    """Retain duration safety after a warning has been acknowledged.

    Stored sources join an order header and its scoped fields with `` | ``.
    Reparse the header and duration answers alone so intervening comments do
    not hide a retained answer. A valid manual duration bypasses this check.
    """
    source = row.get("source", "")
    if not source:
        return False
    from diet import parse_diet
    parts = source.split(" | ")
    duration_answers = [part for part in parts[1:]
                        if re.match(r"^(?:Question\s*:\s*)?Infusion\s+time\s*\(hours\)", part, re.I)]
    parsed = parse_diet("\n".join([parts[0], *duration_answers]), detailed=True)
    return any(item.get("code") == "nutrition_conflict" and item.get("field") == "hours"
               for item in parsed.diagnostics)


_DENSITY = re.compile(r"(?<![\w.+\-/:])(?P<number>(?:\d+(?:\.\d+)?|\.\d+))\s*kcal\s*(?:/|per\s+)\s*(?P<unit>mL|L|oz|ounces?)\b", re.I)


def _density_per_ml(value: str) -> Decimal | None:
    match = _DENSITY.fullmatch(value.strip())
    if match is None:
        return None
    amount = _number(match["number"])
    if amount is None or amount <= 0:
        return None
    unit = match["unit"].casefold()
    return amount / (Decimal("30") if unit in ("oz", "ounce", "ounces") else Decimal("1000") if unit == "l" else Decimal("1"))


def _recorded_density(formula: str) -> str:
    # Only an unambiguous ending density can describe the whole recorded
    # formula. A brand number or recipe component does not establish it.
    if re.search(r"[+]|\b(?:water|dilut\w*|mix(?:ed|ture)?|plus|blend(?:ed|ing)?|with)\b", formula, re.I):
        return ""
    if len(re.findall(r"\bkcal\s*(?:/|per\s+)\s*(?:mL|L|oz|ounces?)\b", formula, re.I)) != 1:
        return ""
    matches = list(_DENSITY.finditer(formula))
    if len(matches) != 1:
        return ""
    if re.fullmatch(r"\s*\)?\s*", formula[matches[0].end():]) is None:
        return ""
    before = formula[:matches[0].start()].rstrip()
    if re.search(r"(?:[-+–—−/:<>≤≥~≈]|\b(?:to|and))$", before, re.I):
        return ""
    return matches[0].group()


def _compact_feed_line(row: dict, kg: Decimal | None, conflicts: set[str]) -> str:
    method = row.get("method", "UNK")
    status = row.get("status", "active")
    prefix = _STATUS_LABELS.get(status, "")
    formula = _known_formula(row.get("formula", ""))
    rate = row.get("rate", "").strip()
    if RATE.fullmatch(rate) is None:
        rate = ""
    if not formula and not rate:
        return ""
    density = row.get("caloric_density", "").strip()
    if formula and density and density.casefold() not in formula.casefold():
        formula += " (" + density + ")"
    hours_text = row.get("hours", "").strip()
    hours = _number(hours_text)
    continuous = _continuous(row)
    invalid_hours = bool(hours_text) and (hours is None or not 0 < hours <= 24)
    blocked_default = not hours_text and ("hours" in conflicts or _source_hours_conflict(row))
    if not hours_text and continuous and not blocked_default:
        hours = Decimal("24")
    rate_number = _rate_number(rate)
    daily = _number(row.get("daily_volume", ""))
    details = formula + " @ " + rate if formula and rate else formula or rate
    if not formula and density:
        details += " (" + density + ")"
    line = prefix + (method + ": " if method and method != "UNK" else "") + details
    if hours is not None and 0 < hours < 24:
        line += " (" + _display_number(hours) + " hr/day)"
    elif not continuous and row.get("feeding_type", "").strip():
        line += " (" + row["feeding_type"].strip() + ")"
    schedule_issue = invalid_hours or blocked_default or (not rate and "rate" in conflicts)
    schedule_issue |= not row.get("daily_volume", "").strip() and "daily_volume" in conflicts
    with localcontext() as context:
        # Numeric inputs are capped at 20 characters. This precision also
        # covers their products and a very small, explicitly supplied DCW.
        context.prec = 80
        total = None
        if (status == "active" and continuous and rate_number is not None
                and hours is not None and 0 < hours <= 24):
            total = rate_number * hours
            schedule_issue |= daily is not None and daily != total
        if total is not None and not schedule_issue:
            density_number = _density_per_ml(density)
            if density_number is not None:
                calories = total * density_number
                line += " | " + _display_number(calories, 1) + " kcal/day"
                if kg is not None:
                    line += " (" + _display_number(calories / kg, 1) + " kcal/kg/day)"
            if kg is not None:
                line += " | " + _display_number(total / kg, 1) + " mL/kg/day"
    if schedule_issue and status == "active":
        line += " | Review rate/hours"
    return line


def _recorded_feed_line(row: dict, kg: Decimal | None, conflicts: set[str]) -> str:
    return _compact_feed_line(dict(row, feeding_type="Continuous Feeds", hours="",
                                  daily_volume="", caloric_density=_recorded_density(row["formula"]),
                                  status="active"), kg, conflicts)


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
    ordered = diet["enteral"]
    recorded = feeds["rows"] if feeds else []
    if "recorded_feed_ids" in diet:
        # The importer records which feed rows belong to this dietary update.
        # A new empty/NPO order must not resurrect an older T snapshot.
        current_ids = set(diet["recorded_feed_ids"])
        recorded = [row for row in recorded if row["id"] in current_ids]
    recorded = [row for row in recorded if row["include"]]
    matches = recorded_feed_matches(ordered, recorded)
    consumed = set(matches.values())
    kg, _basis = dosing_weight_for_feeds(dosing_weight, sheet)
    conflicts = _conflicted_fields(sheet)
    lines, oral_feeds = [], []
    for row in ordered:
        if not row["include"]:
            continue
        line = _compact_feed_line(row, kg, conflicts)
        if line:
            target = oral_feeds if row["method"] == "PO" else lines
            target.append(line)
    for index, row in enumerate(recorded):
        if index in consumed or not row["include"]:
            continue
        if ordered and _rate_number(row["rate"]) is None:
            # A formula-only device may be used for venting or medication.
            continue
        line = _recorded_feed_line(row, kg, conflicts)
        if line:
            target = oral_feeds if row["method"] == "PO" else lines
            target.append(line)
    if oral or oral_feeds:
        content = ([" | ".join(oral)] if oral else []) + oral_feeds
        parts.append(label("Diet:") + " " + "\n".join(encode(value) for value in content))
    if lines:
        parts.append(label("Tube feed:") + "\n" + "\n".join(encode(value) for value in lines))
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
