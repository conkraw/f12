"""User-requested FEN/GI display groups, not inferred medication indications.

The specified drug-name list supplies the automatic defaults. Per-formulation,
route and frequency choices can override them. Original medication fields and
saved system rules are not destroyed by presentation grouping.
"""
from __future__ import annotations
from copy import deepcopy
from html import escape
import re
from medications import is_bupivacaine, match_name, normalized, visible, format_medication
from output_text import medication_output
from clinical_style import clinical_markup
from fluid_balance import balance_text, balance_heading
from feeds import feeds_text
from diet import diet_text
from medication_groups import group_for as special_group, GROUP_SECTIONS

MODES = ("auto", "prophylaxis", "bowel", "diuretic", "antiemetic", "endocrine", "prokinetic", "tpn", "hypoglycemia", "probiotic", "other")
MODE_LABELS = {"auto": "Automatic", "prophylaxis": "GI prophylaxis", "bowel": "Bowel Regimen", "diuretic": "Diuretics", "antiemetic": "Antiemetics", "endocrine": "Endocrine Medications", "prokinetic": "Prokinetic Agents", "tpn": "TPN", "hypoglycemia": "Hypoglycemia:", "probiotic": "Probiotic", "other": "No GI grouping"}
GROUP_NAMES = {"prophylaxis": "GI prophylaxis", "bowel": "Bowel Regimen", "diuretic": "Diuretics", "antiemetic": "Antiemetics", "endocrine": "Endocrine Medications", "prokinetic": "Prokinetic Agents", "tpn": "TPN", "hypoglycemia": "Hypoglycemia:", "probiotic": "Probiotic"}


def automatic_group(row: dict) -> str:
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
    if (re.match(r"^pediatric\s+2[- ]in[- ]1\s+pn\b", name)
            or re.match(r"^smoflipid\b", name)
            or (name.startswith("fat emulsion ") and "smoflipid" in name)):
        # Name/route grouping only. Do not infer the current bag or calculate a rate.
        if normalized(row.get("route", "")) in {"", "iv", "intravenous"}:
            return "tpn"
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
    mode = row.get("gi_mode", "auto")
    return automatic_group(row) if mode == "auto" else mode if mode in GROUP_NAMES else ""


def effective_section(row: dict) -> str:
    if is_bupivacaine(row.get("name", "")):
        return "Neurologic"
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
        if not rule["name"] or rule["mode"] not in ("prophylaxis", "bowel", "diuretic", "antiemetic", "endocrine", "prokinetic", "tpn", "hypoglycemia", "probiotic", "other"):
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


def fen_gi_body(notes: str, rows: list[dict], intake_output: dict | None, rich: bool = False, esc=escape, feeds: dict | None = None, feeds_failed: bool = False, diet: dict | None = None, diet_failed: bool = False, dosing_weight: str = "", sheet: dict | None = None) -> str:
    """Totals, then feeds.  Each visible order appears exactly once, without changing doses."""
    encode = esc if rich else lambda s: s
    meds = [r for r in rows if visible(r) and effective_section(r) == "FEN / GI"]
    sections = []
    totals = balance_text(intake_output, dosing_weight)
    if totals:
        heading = balance_heading(intake_output) + ":"
        sections.append(("<b>" + esc(heading) + "</b>\n" + clinical_markup(totals, esc)) if rich else heading + "\n" + totals)
    diet_summary = diet_text(diet, rich, esc)
    if diet_failed:
        diet_summary = ("<b>Diet:</b>" if rich else "Diet:") + " Not updated. Review needed."
    if diet_summary:
        sections.append(diet_summary)
    feeding = feeds_text(feeds, rich, esc)
    if feeds_failed:
        feeding = ("<b>Feeds:</b>" if rich else "Feeds:") + "\nNot updated. Review needed."
    if feeding:
        sections.append(feeding)
    from categories import medication_blocks
    from infusions import render_body_blocks
    body = render_body_blocks(medication_blocks("FEN / GI", notes, rows, sheet), rich, esc)
    if body:
        sections.append(body)
    return "\n-----\n".join(sections)
