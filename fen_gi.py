"""User-requested FEN/GI display groups, not inferred medication indications.

The specified drug-name list supplies the automatic defaults. Per-formulation,
route and frequency choices can override them. Original medication fields and
saved system rules are not destroyed by presentation grouping.
"""
from __future__ import annotations
from copy import deepcopy
from html import escape
import re
from medications import ignored, is_bupivacaine, match_name, normalized, visible, format_medication
from output_text import medication_output
from clinical_style import clinical_markup
from fluid_balance import balance_text, balance_heading
from current_shift import current_shift_text
from diet import diet_text
from nutrition_display import has_detailed_nutrition, nutrition_sections, parenteral_kind
from medication_groups import group_for as special_group, GROUP_SECTIONS, fixed_handoff_group
from airway_clearance import is_sodium_chloride_3_percent_nebulizer
from iv_fluids import is_iv_fluid
from feeds import feeding_method

FIXED_GI_GROUPS = ("hypocalcemia", "hyponatremia", "zinc_deficiency")
MODES = ("auto", "prophylaxis", "bowel", "diuretic", "antiemetic", "endocrine", "prokinetic", "tpn", "hypoglycemia", "probiotic", "iv_fluids") + FIXED_GI_GROUPS + ("other",)
MODE_LABELS = {"auto": "Automatic", "prophylaxis": "GI prophylaxis", "bowel": "Bowel Regimen", "diuretic": "Diuretics", "antiemetic": "Antiemetics", "endocrine": "Endocrine Medications", "prokinetic": "Prokinetic Agents", "tpn": "TPN", "hypoglycemia": "Hypoglycemia:", "probiotic": "Probiotic", "iv_fluids": "Intravenous Fluids", "hypocalcemia": "Hypocalcemia", "hyponatremia": "Hyponatremia", "zinc_deficiency": "Zinc Deficiency", "other": "No GI grouping"}
GROUP_NAMES = {"prophylaxis": "GI prophylaxis", "bowel": "Bowel Regimen", "diuretic": "Diuretics", "antiemetic": "Antiemetics", "endocrine": "Endocrine Medications", "prokinetic": "Prokinetic Agents", "tpn": "TPN", "hypoglycemia": "Hypoglycemia:", "probiotic": "Probiotic", "iv_fluids": "Intravenous Fluids", "hypocalcemia": "Hypocalcemia", "hyponatremia": "Hyponatremia", "zinc_deficiency": "Zinc Deficiency"}

_FIXED_SUPPLEMENT = re.compile(r"^(calcium\s+carbonate|sodium\s+chloride|nacl|zinc\s+acetate)(?=$|[\s(])")
_NONENTERAL_ROUTE = re.compile(r"\biv\b|intraven|intraosse|intraarter|intracath|intramus|subcut|topical|dermal|cutaneous|extern|ophthalm|otic|eye|ear|nasal|nostril|nebul|inhal|respir|tracheal|irrig|rectal", re.I)
_NONENTERAL_FORM = re.compile(r"\b(?:injection|injectable|infusion|iv|ivpb|intravenous|intramuscular|subcutaneous|flush|lock|nebulizer|nebuliser|nebulization|nebulisation|nebulized|nebulised|inhalation|inhaled|nasal|spray|ophthalmic|otic|topical|cream|ointment|gel|irrigation|enema|suppository)\b")
_ENTERAL_FORM = re.compile(r"\b(?:enteral|oral|tablet|tablets|capsule|capsules|chewable)\b")


def fixed_gi_group(row: dict) -> str:
    """The requested supplement headings, without changing indications or doses.

    Salts need an enteral route or explicit enteral product form. Zinc acetate
    is named directly by the requested rule, including when its route is absent.
    A conflicting recorded route or nonenteral form never qualifies.
    """
    name = match_name(row.get("name", ""))
    matched = _FIXED_SUPPLEMENT.match(name)
    if (not matched or _NONENTERAL_FORM.search(name)
            or re.search(r"\b(?:with|plus|and)\b|\bin\s+(?:sodium\s+chloride|nacl|dextrose)\b", name)
            or re.search(r"(?:carbonate|chloride|acetate)\s*[-+/]\s*[a-z]", name)):
        return ""
    route = normalized(row.get("route", ""))
    if _NONENTERAL_ROUTE.search(route):
        return ""
    enteral = (route in {"oral", "po", "enteral", "by mouth", "per os", "gastric", "intragastric",
                         "feeding tube", "per feeding tube", "via feeding tube"}
               or feeding_method(route) != "UNK")
    if route and not enteral:
        return ""
    ingredient = re.sub(r"\s+", " ", matched[1])
    if ingredient == "zinc acetate":
        return "zinc_deficiency"
    if not enteral and not _ENTERAL_FORM.search(name):
        return ""
    return "hypocalcemia" if ingredient == "calcium carbonate" else "hyponatremia"


def automatic_group(row: dict) -> str:
    requested = fixed_gi_group(row)
    if requested:
        return requested
    name = match_name(row.get("name", ""))
    # Match the generic genus at the start of the product name.
    # No probiotic indication or dose is inferred.
    if re.match(r"^lactobacillus(?=$|[\s(,./])", name):
        return "probiotic"
    # Only a documented 50% dextrose infusion. Do not catch D5/D10, a 50 mL
    # bag, another drug diluted in dextrose, or a one-time D50 rescue bolus.
    if (re.match(r"^dextrose\s+50(?:\.0+)?\s*%(?=$|[^a-z0-9])", name)
            and normalized(row.get("route", "")) in {"iv", "intravenous"}
            and row.get("infusion_mode") != "other"
            and not re.search(r"\bprn\b|\bas[ -]+needed\b", normalized(row.get("frequency", "")))
            and (row.get("infusion_mode") == "infusion" or
                 re.search(r"\bcontinuous\b|\btitrat(?:e|able)\b", normalized(row.get("frequency", ""))))):
        return "hypoglycemia"
    if parenteral_kind(name) in {"pn", "lipid"}:
        # Intravenous nutrition products share the TPN display group. The
        # latest-order selector chooses the displayed bags independently.
        if normalized(row.get("route", "")) in {"", "iv", "intravenous"}:
            return "tpn"
    if is_iv_fluid(row) and row.get("section", "Other Medications") in {"Other Medications", "FEN / GI"}:
        # An existing explicit system placement remains authoritative. New
        # unmapped fluids receive the requested FEN/GI display category.
        return "iv_fluids"
    if re.match(r"^(?:levothyroxine|synthroid|levoxyl|insulin|lantus|metformin)(?=$|[\s(,])", name):
        return "endocrine"
    if re.match(r"^(?:erythromycin|prucalopride)(?=$|[\s(,])", name):
        # User-requested organizational default. No indication or dose is inferred.
        # Explicit category assignments can place antimicrobial use elsewhere.
        # Eye/skin products do not belong in the GI prokinetic group.
        route = normalized(row.get("route", ""))
        if not re.search(r"ophthalm|\beyes?\b|otic|topical|apply externally", route) and not re.search(r"\b(?:ophthalmic|ointment|cream|gel|otic)\b", name):
            return "prokinetic"
    if re.match(r"^(?:ondansetron|zofran)\b", name):
        return "antiemetic"
    if re.match(r"^(?:bumetanide|chlorothiazide|furosemide)\b", name):
        return "diuretic"
    if re.match(r"^(?:famotidine|omeprazole|pantoprazole)\b", name):
        return "prophylaxis"
    if re.match(r"^(?:docusate|lactulose|polyethylene\s+glycol|sennosides)\b", name):
        return "bowel"
    if re.match(r"^glycerin\b", name) and (re.search(r"\b(?:supp|suppository|suppositories|rectal)\b", name) or normalized(row.get("route", "")) == "rectal"):
        return "bowel"
    return ""


def group_for(row: dict) -> str:
    requested = fixed_gi_group(row)
    if requested:
        return requested
    mode = row.get("gi_mode", "auto")
    return automatic_group(row) if mode == "auto" else mode if mode in GROUP_NAMES else ""


def effective_section(row: dict) -> str:
    if ignored(row):
        return "Ignore"
    if is_bupivacaine(row.get("name", "")):
        return "Neurologic"
    if is_sodium_chloride_3_percent_nebulizer(row):
        return "Respiratory"
    requested_group = fixed_handoff_group(row)
    if requested_group:
        return GROUP_SECTIONS[requested_group]
    if fixed_gi_group(row):
        return "FEN / GI"
    if row.get("category_path") is not None:
        return row["category_path"]["section"]
    special = special_group(row)
    if special:
        return GROUP_SECTIONS[special]
    return "FEN / GI" if group_for(row) else row["section"]


def gi_key(row: dict) -> tuple[str, str, str]:
    return match_name(row["name"]), normalized(row["route"]), normalized(row["frequency"])


def validate_gi_rules(rules: list[dict]) -> None:
    if not isinstance(rules, list) or len(rules) > 1500:
        raise ValueError("The FEN/GI display rules are invalid or too large.")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"name", "route", "frequency", "mode"}:
            raise ValueError("A FEN/GI display rule has an invalid structure.")
        for key in ("name", "route", "frequency"):
            if not isinstance(rule[key], str) or len(rule[key]) > 4000 or any(c in rule[key] for c in "\n\r\t"):
                raise ValueError("A FEN/GI display rule contains invalid text.")
        if not rule["name"] or rule["mode"] not in (*GROUP_NAMES, "other"):
            raise ValueError("A FEN/GI display rule has an invalid choice.")
        key = (rule["name"], rule["route"], rule["frequency"])
        if key in seen:
            raise ValueError("Duplicate FEN/GI display rules were found.")
        seen.add(key)


def set_gi_rule(rules: list[dict], row: dict, mode: str) -> list[dict]:
    if mode not in MODES:
        raise ValueError("Choose a valid FEN/GI display setting.")
    key = gi_key(row)
    result = [deepcopy(r) for r in rules if (r["name"], r["route"], r["frequency"]) != key]
    if mode != "auto":
        result.append(dict(zip(("name", "route", "frequency"), key), mode=mode))
    result.sort(key=lambda r: (r["name"], r["route"], r["frequency"]))
    validate_gi_rules(result)
    return result


def gi_mode_for(row: dict, rules: list[dict]) -> str:
    key = gi_key(row)
    return next((r["mode"] for r in rules if (r["name"], r["route"], r["frequency"]) == key), "auto")


def apply_gi_rules(rows: list[dict], rules: list[dict]) -> list[dict]:
    validate_gi_rules(rules)
    result = deepcopy(rows)
    for row in result:
        mode = gi_mode_for(row, rules)
        if mode != "auto" or "gi_mode" in row:
            row["gi_mode"] = mode
    return result


def fen_gi_body(notes: str, rows: list[dict], intake_output: dict | None, rich: bool = False, esc=escape, feeds: dict | None = None, feeds_failed: bool = False, diet: dict | None = None, diet_failed: bool = False, dosing_weight: str = "", sheet: dict | None = None, include_current_shift: bool = True) -> str:
    """Totals, then feeds.  Each visible order appears exactly once, without changing doses."""
    encode = esc if rich else lambda s: s
    meds = [r for r in rows if visible(r) and effective_section(r) == "FEN / GI"]
    sections = []
    totals = balance_text(intake_output, dosing_weight)
    if totals:
        heading = balance_heading(intake_output) + ":"
        sections.append(("<b>" + esc(heading) + "</b>\n" + clinical_markup(totals, esc)) if rich else heading + "\n" + totals)
    shift = current_shift_text(sheet or {}, rich, esc) if include_current_shift else ""
    if shift:
        sections.append(shift)
    if has_detailed_nutrition(diet) and not diet_failed:
        sections.extend(nutrition_sections(diet, None if feeds_failed else feeds, rows,
                        dosing_weight=dosing_weight, sheet=sheet, rich=rich, esc=esc))
        if feeds_failed:
            sections.append(("<b>Recorded feeds:</b>" if rich else "Recorded feeds:") + " Not updated. Review needed.")
    else:
        diet_summary = diet_text(diet, rich, esc)
        if diet_failed:
            diet_summary = ("<b>Diet:</b>" if rich else "Diet:") + " Not updated. Review needed."
        if diet_summary:
            sections.append(diet_summary)
        feeding = "\n-----\n".join(nutrition_sections(
            {"rows": [], "enteral": [], "parenteral": []}, feeds, rows,
            dosing_weight=dosing_weight, sheet=sheet, rich=rich, esc=esc))
        if feeds_failed:
            feeding = ("<b>Tube feed:</b>" if rich else "Tube feed:") + "\nNot updated. Review needed."
        if feeding:
            sections.append(feeding)
    from categories import medication_blocks
    from infusions import render_body_blocks
    body = render_body_blocks(medication_blocks("FEN / GI", notes, rows, sheet,
                              diet=None if diet_failed else diet,
                              dosing_weight=dosing_weight or None), rich, esc)
    if body:
        sections.append(body)
    return "\n-----\n".join(sections)
