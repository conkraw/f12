"""Presentation-only infusion grouping. No clinical dose inference or conversion.

Explicit continuous parenteral orders are recognized automatically. Respiratory
continuous nebulized/inhaled orders also use the emphasized display. A saved
user choice is keyed to the complete formulation, route and frequency, so a
PRN order for the same drug is not accidentally changed. No doses are supplied
by a rule. Source amounts, qualifiers, held/start labels and recorded rates stay.
"""
from __future__ import annotations
from copy import deepcopy
from html import escape
import re
from medications import normalized, match_name, visible, format_medication
from output_text import medication_output, medication_name_output
from infusion_rates import administration_display, show_recorded_pump_rate
from fen_gi import effective_section, group_for as gi_group
from medication_groups import (group_for as special_group, GROUP_NAMES, CV_GROUPS,
                               RESP_GROUPS, NEURO_OTHER_GROUPS, NEURO_PRIORITY_GROUPS)

MODES = ("auto", "infusion", "other")
MODE_LABELS = {"auto": "Automatic", "infusion": "Infusion", "other": "Other medication"}
INFUSION_HEADINGS = {
    "Neurologic": "Infusions", "Cardiovascular": "CV Infusions",
    "Respiratory": "Respiratory Infusions", "Hematology": "Heme Infusions",
}
INFUSION_SECTIONS = tuple(INFUSION_HEADINGS)
DISPLAY_LABELS = {"Neurologic": "Neuro", "Cardiovascular": "CV",
                  "Respiratory": "Respiratory", "Hematology": "Heme", "FEN / GI": "Endocrine"}


def supports_infusion_display(row: dict) -> bool:
    """Keep existing special groups, allowing DVT infusions to be emphasized.

    This does not change the stored system mapping or any clinical source field.
    PRN/fever and GI groups retain their existing priority over infusion display.
    """
    section = effective_section(row)
    if row.get("category_path") is not None:
        return section in INFUSION_HEADINGS or section == "FEN / GI"
    group = special_group(row)
    if section == "FEN / GI":
        return gi_group(row) in {"endocrine", "tpn"}
    return section in INFUSION_HEADINGS and (not group or group in {"dvt", "antiplatelet"}
                                            or group in CV_GROUPS + RESP_GROUPS + ("paralytic_infusion", "epidural"))


def infusion_key(row: dict) -> tuple[str, str, str]:
    return (match_name(row["name"]), normalized(row["route"]), normalized(row["frequency"]))


def is_infusion(row: dict) -> bool:
    mode = row.get("infusion_mode", "auto")
    if mode != "auto":
        return mode == "infusion"
    frequency = normalized(row.get("frequency", ""))
    route = normalized(row.get("route", "")).replace("-", " ")
    # A PRN syringe may say 'infusion' in its product name. That is not sufficient.
    if re.search(r"\bprn\b|as needed", frequency):
        return False
    parenteral = route in {
        "intravenous", "iv", "intra arterial", "intraarterial", "ia",
        "subcutaneous", "subcut", "sq", "epidural", "intrathecal",
    }
    respiratory_delivery = effective_section(row) == "Respiratory" and route in {
        "nebulization", "nebulisation", "nebulized", "nebulised",
        "inhalation", "inhaled", "nebulized inhalation", "nebulised inhalation",
    }
    return bool(re.search(r"\bcontinuous\b|\btitrat(?:e|able)\b", frequency) and (parenteral or respiratory_delivery))


def validate_infusion_rules(rules: list[dict]) -> None:
    if not isinstance(rules, list) or len(rules) > 1500:
        raise ValueError("The infusion display rules are invalid or too large.")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"name", "route", "frequency", "mode"}:
            raise ValueError("An infusion display rule has an invalid structure.")
        for key in ("name", "route", "frequency"):
            value = rule[key]
            if not isinstance(value, str) or len(value) > 4000 or any(c in value for c in "\n\r\t"):
                raise ValueError("An infusion display rule contains invalid text.")
        if not rule['name'] or rule['mode'] not in ("infusion", "other"):
            raise ValueError("An infusion display rule has an invalid choice.")
        key = (rule['name'], rule['route'], rule['frequency'])
        if key in seen:
            raise ValueError("Duplicate infusion display rules were found.")
        seen.add(key)


def set_infusion_rule(rules: list[dict], row: dict, mode: str) -> list[dict]:
    if mode not in MODES:
        raise ValueError("Choose Automatic, Infusion or Other medication.")
    key = infusion_key(row)
    result = [deepcopy(r) for r in rules if (r['name'], r['route'], r['frequency']) != key]
    if mode != 'auto':
        result.append(dict(zip(('name', 'route', 'frequency'), key), mode=mode))
    result.sort(key=lambda r: (r['name'], r['route'], r['frequency']))
    validate_infusion_rules(result)
    return result


def infusion_mode_for(row: dict, rules: list[dict]) -> str:
    key = infusion_key(row)
    for rule in rules:
        if (rule['name'], rule['route'], rule['frequency']) == key:
            return rule['mode']
    return 'auto'


def apply_infusion_rules(rows: list[dict], rules: list[dict]) -> list[dict]:
    validate_infusion_rules(rules)
    result = deepcopy(rows)
    for row in result:
        mode = infusion_mode_for(row, rules)
        if mode != 'auto' or 'infusion_mode' in row:
            row['infusion_mode'] = mode
    return result


def infusion_entry(row: dict, rich: bool = False, esc=escape, handoff_only: bool = False) -> str:
    """Emphasize documented Last Admin rate when available, without altering Dose."""
    if handoff_only:
        row = deepcopy(row)
        for field in ("name", "dose", "route", "frequency", "last_rate", "custom_text", "last_admin_rate"):
            row[field] = medication_output(row.get(field, ""))
        if "_display_name" in row:
            row["_display_name"] = medication_output(row["_display_name"])
    encode = esc if rich else lambda v: v
    bold = lambda v: '<b>' + encode(v) + '</b>' if rich else v
    custom = row.get('custom_text', '').strip()
    if custom:
        # A user override remains authoritative. Do not add a contradictory dose.
        return bold(custom)
    name = medication_name_output(row.get('_display_name') or row['name'])
    lines = [bold(name)]
    dose = row['dose'].strip()
    rate = row['last_rate'].strip()
    admin = administration_display(row)
    if admin:
        label, value, stamp = admin
        text = label + ': ' + value
        primary = '<b><u>' + encode(text) + '</u></b>' if rich else text
        if stamp:
            primary += ' [' + encode(stamp) + ']'
        lines.append(primary)
    elif dose:
        lines.append('<b><u>' + encode('Dose: ' + dose) + '</u></b>' if rich else 'Dose: ' + dose)
    if rate and show_recorded_pump_rate(row):
        text = 'Recorded rate: ' + rate
        # Explicit infusion choice also enables rate display with a blank frequency.
        if not dose and not admin:
            lines.append('<b><u>' + encode(text) + '</u></b>' if rich else text)
        elif normalized(admin[1] if admin else dose) != normalized(rate):
            lines.append(encode(text))
    details = ' | '.join(v.strip() for v in (row['route'], row['frequency']) if v.strip())
    if details:
        lines.append(encode(details))
    return '\n'.join(lines)


def system_body_blocks(section: str, notes: str, rows: list[dict], sheet: dict | None = None) -> list[tuple[str, object]]:
    from categories import medication_blocks
    return medication_blocks(section, notes, rows, sheet)


def render_body_blocks(blocks: list[tuple[str, object]], rich: bool = False, esc=escape) -> str:
    encode = esc if rich else lambda v: v
    lines = []
    for kind, item in blocks:
        if kind == "infusion":
            lines.append(infusion_entry(item, rich, esc, handoff_only=True))
        elif kind == "heading":
            lines.append("<b>" + encode(item) + "</b>" if rich else item)
        elif kind == "empty_group":
            lines.append("<b>" + encode(item + ":") + "</b> None" if rich else item + ": None")
        elif kind == "subheading":
            lines.append("<b><i>" + encode(item) + "</i></b>" if rich else item)
        elif kind == "lab" and rich:
            from clinical_style import clinical_markup
            lines.append(clinical_markup(item, esc))
        elif kind == "medication":
            lines.append(encode(medication_output(format_medication(item))))
        else:
            lines.append(encode(item))
    return "\n".join(lines)


def neuro_body(notes: str, rows: list[dict], rich: bool = False, esc=escape, sheet: dict | None = None) -> str:
    """Infusions, PRNs, paralytics, alphabetical categories, notes and other meds."""
    return render_body_blocks(system_body_blocks("Neurologic", notes, rows, sheet), rich, esc)


def cardiovascular_body(notes: str, rows: list[dict], rich: bool = False, esc=escape, sheet: dict | None = None) -> str:
    return render_body_blocks(system_body_blocks("Cardiovascular", notes, rows, sheet), rich, esc)


def hematology_body(notes: str, rows: list[dict], rich: bool = False, esc=escape, sheet: dict | None = None) -> str:
    return render_body_blocks(system_body_blocks("Hematology", notes, rows, sheet), rich, esc)


def respiratory_body(notes: str, rows: list[dict], rich: bool = False, esc=escape, sheet: dict | None = None) -> str:
    return render_body_blocks(system_body_blocks("Respiratory", notes, rows, sheet), rich, esc)
