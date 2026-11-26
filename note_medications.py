"""Plain medication lists for the on-demand progress-note review utility.

Use the handoff's effective main section, without therapeutic subheadings or
new calculations. A recorded infusion rate is never calculated from a bag,
concentration, weight, or an ordered dose range. This module is read-only.
"""
from __future__ import annotations

from datetime import datetime
import re

from categories import placement
from infusion_rates import is_rate, requested_titration
from infusions import is_infusion
from lab_windows import clock
from labs import date_parts
from medication_groups import is_prn
from medications import clean, suggested_key, visible
from output_text import medication_output
from pn_orders import medication_rows_for_display, parenteral_kind


MAIN_SECTIONS = (
    "Neurologic", "Respiratory", "Cardiovascular", "FEN / GI", "Hematology",
    "Infectious Disease", "Labs", "Skin / Wounds", "Other Medications",
)
GROUPS = ("Drips", "Scheduled", "PRN")
_NONRUNNING = {
    "stopped": "Stopped", "paused": "Paused", "held": "Held",
    "not_given": "Not given", "not_administered": "Not administered",
    "discontinued": "Discontinued",
}
_PREFIX = re.compile(
    r"^(?:\[(?P<bracket>[^\]]+)\]|"
    r"(?P<status>discontinued|removed|cancelled|canceled|stopped|paused|held(?:\s+by\s+provider)?)\s*:\s*|"
    r"(?P<connector>followed\s+by|and|or|alternative\s+order)\b\s*:?)\s*",
    re.I,
)
_FORM = re.compile(
    r"\s+(?:tablets?|capsules?|oral\s+(?:solution|suspension)|solution|suspension|liquid|"
    r"injection|infusion|syringe|nebulizer|ophthalmic|cream|ointment|gel|patch|powder)\s*$",
    re.I,
)
_QUALIFIER = re.compile(r"\(\s*(?:dosing\s+weight|order-specific)\s*\)", re.I)


def _contexts(name: str) -> tuple[str, list[str]]:
    """Keep meaningful order qualifiers separate from the short drug name."""
    remaining = clean(name)
    qualifiers = []
    while remaining:
        match = _PREFIX.match(remaining)
        if match is None:
            break
        bracket = match.group("bracket")
        connector = match.group("connector")
        status = match.group("status")
        if bracket or status:
            qualifiers.append("[" + (bracket or status) + "]")
        elif connector and connector.casefold() != "and":
            qualifiers.append(clean(connector).capitalize() + ":")
        remaining = remaining[match.end():].strip()
    return remaining or clean(name), qualifiers


def _short_name(row: dict) -> tuple[str, list[str]]:
    source, qualifiers = _contexts(row.get("name", ""))
    # Salts, compound formulations, concentrations, and PN names must remain
    # identifiable. Never shorten them to a generic ingredient alone.
    preserve = (
        not clean(row.get("dose", ""))
        or "%" in source
        or bool(parenteral_kind(source, row.get("route", "")))
        or bool(re.search(r"[A-Za-z]-?\d", source))
        or bool(re.search(r"\b(?:flush|lock|and|with)\b|\+|\b\d+(?:\.\d+)?\s*mEq\s+in\b", source, re.I))
        or bool(re.match(r"^(?:d\d|normal saline|lactated ringer|plasma[ -]?lyte)\b", source, re.I))
    )
    if preserve:
        name = source
        # Remove only a genuinely repeated terminal dose. Product strengths
        # and percentages elsewhere in the name remain unchanged.
        dose = clean(row.get("dose", ""))
        if dose and name.casefold().endswith(" " + dose.casefold()):
            name = name[:-(len(dose) + 1)].rstrip()
    else:
        name = suggested_key(source)
        while _FORM.search(name):
            name = _FORM.sub("", name).strip()
        name = re.sub(r"\s+(?:PF|NCS|neo/ped)$", "", name, flags=re.I).strip()
    name = name or source
    return name[:1].upper() + name[1:], qualifiers


def _frequency(value: str) -> str:
    text = clean(value)
    text = re.sub(r"\bq\s*(\d+)\s*h\b", lambda match: "Q" + match[1] + "H", text, flags=re.I)
    text = re.sub(r"\bevery\s+(\d+)\s+hours?\b", lambda match: "Q" + match[1] + "H", text, flags=re.I)
    text = re.sub(r"\b(?:prn|as[ -]+needed)\b", "PRN", text, flags=re.I)
    text = re.sub(r"\b(?:bid|tid|qid|qhs|qam|qpm)\b", lambda match: match[0].upper(), text, flags=re.I)
    text = re.sub(r"\s*\bSCH\b", "", text, flags=re.I).strip()
    return text


def _route(row: dict) -> str:
    value = clean(row.get("route", ""))
    # The usual oral, tube, and IV routes can stay out of the compact list.
    # Retain routes whose omission changes the meaning of a medication line.
    if value.casefold() in {
        "", "oral", "po", "intravenous", "iv", "per g tube", "per ng tube",
        "per j tube", "per gj tube", "per og tube", "g tube", "ng tube",
        "j tube", "gj tube", "og tube", "enteral", "feeding tube",
    }:
        return ""
    return " (" + value + ")"


def _status(row: dict, qualifiers: list[str], now: datetime) -> tuple[str, str]:
    text = " ".join(qualifiers + [row.get("custom_text", "")])
    if re.search(r"\[(?:discontinued|removed|cancelled|canceled)\]", text, re.I):
        return "discontinued", "Discontinued"
    if re.search(r"\[held(?:\s+by\s+provider)?\]", text, re.I):
        return "held", "Held"
    for status in ("stopped", "paused", "not_given", "not_administered"):
        if re.search(r"\[" + status.replace("_", r"\s+") + r"\]", text, re.I):
            return status, _NONRUNNING[status]
    admin_status = row.get("last_admin_status", "unavailable")
    if admin_status in _NONRUNNING:
        return admin_status, _NONRUNNING[admin_status]
    start = re.search(r"\[START ON ([^\]]+)\]", text, re.I)
    if start:
        try:
            when, timed = date_parts(start[1])
            if when.date() > now.date() or (timed and when > now.replace(tzinfo=None)):
                return "future", "Scheduled to start " + start[1]
        except ValueError:
            return "start_unverified", "Start date requires review"
    if re.search(r"\bfollowed\s+by\s*:", text, re.I):
        return "sequence", "Sequence order requires review"
    return "active", ""


def _rate(row: dict) -> tuple[str, str]:
    """Return a directly recorded rate and its source, without conversions."""
    admin = clean(row.get("last_admin_rate", ""))
    if row.get("last_admin_status") == "rate" and is_rate(admin):
        return clean(_QUALIFIER.sub("", admin)), "last_admin"
    pump = clean(row.get("last_rate", ""))
    if is_rate(pump):
        return clean(_QUALIFIER.sub("", pump)), "last_rate"
    dose = clean(row.get("dose", ""))
    if not requested_titration(row) and is_rate(dose):
        return clean(_QUALIFIER.sub("", dose)), "fixed_order"
    return "", "unavailable"


def build_note_medications(sheet: dict, as_of: datetime | None = None) -> dict:
    """Return JSON-friendly sections, entries, and review warnings.

    ``sections[main_section]`` has Drips, Scheduled, and PRN string lists.
    Entries carry id, name, source_name, section, group, text, status, active,
    route, frequency, dose, and rate_source. Use source_name for matching and
    active to keep nonrunning or future orders out of diagnosis suggestions.
    Input rows and the handoff are never mutated. Only represented sections
    are returned, in the usual handoff order.
    """
    now = clock(as_of)
    sections = {}
    entries = []
    warnings = []
    rows = medication_rows_for_display(sheet.get("medications", []), sheet=sheet)
    if sheet.get("import_warnings", {}).get("b"):
        warnings.append("Medication import has unresolved review items. Review the current handoff medication list.")
    for row in rows:
        if not visible(row):
            continue
        section = placement(row)["section"]
        if section == "Ignore":
            continue
        name, qualifiers = _short_name(row)
        prn = is_prn(row)
        drip = not prn and is_infusion(row)
        group = "PRN" if prn else "Drips" if drip else "Scheduled"
        status, status_label = _status(row, qualifiers, now)
        rate_source = ""
        custom = clean(row.get("custom_text", ""))
        if status != "active":
            # Never pair a held/stopped marker with a stale current rate.
            text = name + _route(row) + " [" + status_label + "]"
            warnings.append(name + ": " + status_label + ".")
        elif custom:
            text = medication_output(custom)
        elif drip:
            rate, rate_source = _rate(row)
            if rate:
                text = name + " at " + rate + _route(row)
            else:
                text = name + _route(row) + " [rate not supplied]"
                warnings.append(name + ": no single recorded infusion rate is available. No rate was calculated.")
        else:
            dose = medication_output(clean(row.get("dose", "")))
            text = " ".join(part for part in (name, dose, _frequency(row.get("frequency", ""))) if part)
            text += _route(row)
            if not dose and row.get("route", "").casefold() not in {"topical", "ophthalmic", "both eyes", "left eye", "right eye"}:
                text += " [dose not supplied]"
                warnings.append(name + ": verify the dose before using this medication line.")
        if status == "active":
            context = [item for item in qualifiers if not re.match(r"\[START ON ", item, re.I)]
            if context:
                text = " ".join(context + [text])
        sections.setdefault(section, {key: [] for key in GROUPS})[group].append(text)
        entries.append({
            "id": row.get("id", ""), "name": name,
            "source_name": row.get("name", ""), "section": section,
            "group": group, "text": text, "status": status,
            "active": status == "active", "route": row.get("route", ""),
            "frequency": row.get("frequency", ""), "dose": row.get("dose", ""),
            "rate_source": rate_source,
        })
    section_order = list(MAIN_SECTIONS) + [section for section in sections if section not in MAIN_SECTIONS]
    return {
        "sections": {section: sections[section] for section in section_order if section in sections},
        "entries": entries,
        "warnings": list(dict.fromkeys(warnings)),
    }
