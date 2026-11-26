"""Read-only note candidates from recorded virology, nutrition and lab findings.

Use existing handoff selection and abnormality rules. No laboratory values,
reference ranges, nutritional requirements or clinical diagnoses are calculated
or written back. The caller controls which review candidates enter the Plan.
"""
from __future__ import annotations

from datetime import datetime
import re

from cbc import cbc_cards, cbc_component
from diet import diet_for_output
from ecg import format_ecg, long_qtc
from feeds import RATE as FEED_RATE, feeds_for_output
from lab_windows import clock, eligible_time, measured
from labs import canonical, date_parts
from note_medications import build_note_medications
from pn_orders import dietary_rows_for_display, parenteral_kind
from problem_review import HIGH, LOW, _is_high_sodium, _is_low, _latest_rows, empty_review, numeric
from viral import TEXT_ALIASES, _latest_groups, component_key, display_name, result_status


_LOW_RULES = {
    "HGB": ("anemia", "Hemoglobin"),
    "PLT": ("thrombocytopenia", "Platelets"),
    "NA": ("hyponatremia", "Sodium"),
    "K": ("hypokalemia", "Potassium"),
    "MG": ("hypomagnesemia", "Magnesium"),
    "PHOS": ("hypophosphatemia", "Phosphorus"),
    "CALCIUM": ("hypocalcemia", "Calcium"),
    "GLUCOSE": ("hypoglycemia", "Glucose"),
    "ANC": ("neutropenia", "Absolute neutrophil count"),
    "ALC": ("lymphopenia", "Absolute lymphocyte count"),
}
_CBC_KEYS = {"HGB", "PLT", "ANC", "ALC"}
_INVALID_RESULT = re.compile(
    r"\b(?:pending|cancelled|canceled|hemolyzed|hemolysed|haemolysed|haemolyzed|"
    r"rejected|invalid|clotted|contaminated|not done|not available|not reported)\b", re.I
)
_FLAGS = re.compile(r"\((?:H|L|HH|LL|A|C|CRIT|HIGH|LOW)\)|\*", re.I)
_MISSING = {"", "unk", "unknown", "none", "n/a", "na", "not documented", "not available", "--", "-"}


def _valid_result(row: dict | None) -> bool:
    if not row or not isinstance(row.get("value"), str):
        return False
    value = row["value"]
    if _INVALID_RESULT.search(value) or (HIGH.search(value) and LOW.search(value)):
        return False
    parsed = numeric(value)
    if not parsed or parsed[1] < 0:
        return False
    unflagged = _FLAGS.sub("", value).strip()
    # CBC display helpers may place units after flags. Remove only source
    # flag typography for measurement validation, retaining the original row.
    if measured(unflagged):
        return True
    return bool(re.fullmatch(
        r"[<>≤≥]?\s*\+?(?:\d[\d,]*(?:\.\d*)?|\.\d+)\s*(?:[x×]\s*)?10\^?[369]\s*/\s*[uµμmL]+",
        unflagged, re.I,
    ))


def _latest_guard(rows: list[dict], selected: dict, now: datetime, admission: str, warn) -> bool:
    """Do not revive hidden results or choose between unordered conflicting rows."""
    current = [row for row in rows if eligible_time(row, now, admission=admission)]
    if not current:
        return False
    day = max(date_parts(row["date"])[0].date() for row in current)
    newest = [row for row in current if date_parts(row["date"])[0].date() == day]
    if all(date_parts(row["date"])[1] for row in newest):
        stamp = max(date_parts(row["date"])[0] for row in newest)
        newest = [row for row in newest if date_parts(row["date"])[0] == stamp]
    values = {(str(row.get("value", "")).strip(), str(row.get("unit", "")).strip()) for row in newest}
    if len(values) > 1:
        warn("Some latest laboratory results have conflicting values without a clear collection order. Those findings were omitted from note suggestions.")
        return False
    return any(row.get("include", True) and row.get("id") == selected.get("id") for row in newest)


def _lab_rows(sheet: dict, now: datetime, warn) -> dict:
    warnings = sheet.get("import_warnings") or {}
    labs = sheet.get("labs") or {"rows": [], "notes": []}
    source = dict(sheet, labs=labs)
    if "g" in warnings:
        warn("The laboratory import needs review. Retained general lab values were not used for new note findings.")
    if "q" in warnings:
        warn("The CBC import needs review. Retained CBC values were not used for new note findings.")
    try:
        latest = _latest_rows(source, now)
        admission = sheet.get("admission_date", "")
        eligible_labs = [row for row in labs.get("rows", [])
                         if row.get("include") and eligible_time(row, now, admission=admission)] if "g" not in warnings else []
        if "q" not in warnings:
            cards = cbc_cards({"rows": eligible_labs, "notes": []}, sheet.get("cbc"))
            for key in ("ANC", "ALC"):
                row = cards[0]["rows"].get(key) if cards else None
                if row and row.get("date") and eligible_time(row, now, admission=admission):
                    latest[key] = row
        for key in tuple(latest):
            row = latest[key]
            if key in _CBC_KEYS:
                if "q" in warnings:
                    latest.pop(key, None)
                    continue
                snapshot = sheet.get("cbc")
                raw = snapshot.get("rows", []) if snapshot is not None else (labs.get("rows", []) if "g" not in warnings else [])
                if key == "HGB":
                    standard = [item for item in raw if cbc_component(item.get("component", "")) == "HGB"]
                    candidates = standard or [item for item in raw if cbc_component(item.get("component", "")) == "HGB_ISTAT"]
                else:
                    candidates = [item for item in raw if cbc_component(item.get("component", "")) == key]
                if key in ("ANC", "ALC"):
                    candidates = [item for item in candidates
                                  if str(item.get("unit", "")).casefold() not in ("%", "percent", "percentage")
                                  and "%" not in item.get("value", "")]
            else:
                candidates = [item for item in labs.get("rows", []) if canonical(item.get("component", "")) == key]
            if not _latest_guard(candidates, row, now, admission, warn):
                latest.pop(key, None)
        return latest
    except (KeyError, TypeError, ValueError):
        warn("Some laboratory data could not be verified. Review the source before adding laboratory-based note phrases.")
        return {}


def _lab_reason(row: dict, label: str, rule: str) -> str:
    unit = str(row.get("unit", "")).strip()
    value = row["value"]
    unit_suffix = " " + unit if unit and unit.casefold() not in value.casefold() else ""
    return f"Latest recorded {label}: {value}{unit_suffix} [{row['date']}], {rule}. Review the source range and clinical context."


def _add_labs(sheet: dict, now: datetime, add, warn) -> None:
    latest = _lab_rows(sheet, now, warn)
    config = sheet.get("problem_review") or empty_review()
    limits = config.get("low_limits") or {}
    for key, (candidate, label) in _LOW_RULES.items():
        row = latest.get(key)
        if not _valid_result(row) or HIGH.search(row["value"]):
            continue
        try:
            low, why = _is_low(row, limits.get(key), key)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            warn("A configured low-result limit could not be applied. Verify the saved limit and its units.")
            continue
        if low:
            add(candidate, _lab_reason(row, label, why))
    sodium = latest.get("NA")
    if _valid_result(sodium) and not LOW.search(sodium["value"]):
        if HIGH.search(sodium["value"]):
            add("hypernatremia", _lab_reason(sodium, "Sodium", "source marked high"))
        elif _is_high_sodium(sodium):
            add("hypernatremia", _lab_reason(sodium, "Sodium", "meets the handoff's existing sodium greater than 145 review rule"))
    for key, candidate, label in (
        ("K", "hyperkalemia", "Potassium"),
        ("AST", "transaminitis", "AST"),
        ("ALT", "transaminitis", "ALT"),
    ):
        row = latest.get(key)
        if _valid_result(row) and HIGH.search(row["value"]):
            add(candidate, _lab_reason(row, label, "source marked high"))
    for key in ("INR", "PT", "PTT"):
        row = latest.get(key)
        if _valid_result(row) and HIGH.search(row["value"]):
            add("coagulopathy", _lab_reason(row, key, "source marked high") + " Confirm anticoagulant therapy and the cause before using the coagulopathy plan.")
    fibrinogen = latest.get("FIB")
    if _valid_result(fibrinogen) and LOW.search(fibrinogen["value"]):
        add("coagulopathy", _lab_reason(fibrinogen, "Fibrinogen", "source marked low") + " Confirm the coagulation disorder before using this plan.")
    co2 = latest.get("CO2")
    if _valid_result(co2) and LOW.search(co2["value"]):
        warn("Low serum CO2 alone does not identify the cause of an acid-base disorder. The supplied acidosis phrases require a documented cause and were not selected from this result alone.")
    # The catalog only contains stress hyperglycemia, acute renal failure and
    # acute liver failure. Isolated glucose/creatinine/bilirubin flags do not
    # establish those specific causes or acuity, so no such rule is invented.
    if "z" not in (sheet.get("import_warnings") or {}):
        try:
            if long_qtc(sheet.get("ecg")):
                add("prolonged_qt", format_ecg(sheet["ecg"]) + ". Meets the handoff's existing Bazett QTc greater than 450 msec review rule.")
        except (KeyError, TypeError, ValueError):
            warn("The ECG measurement needs review before adding a prolonged-QT phrase.")


def _viral_name_target(name: str) -> tuple[str, str, bool]:
    normalized = re.sub(r"\s+", " ", name).strip().casefold()
    if re.fullmatch(r"(?:human )?rhinovirus\s*[/\-]\s*enterovirus", normalized):
        return "rhinovirus", "rhinovirus/enterovirus", True
    if normalized in ("rhinovirus", "human rhinovirus"):
        return "rhinovirus", "rhinovirus", False
    if normalized in ("rsv", "respiratory syncytial virus"):
        return "rsv", "rsv", False
    if normalized == "adenovirus":
        return "adenovirus", "adenovirus", False
    influenza = re.fullmatch(r"influenza(?: virus)?(?: ([ab]))?", normalized)
    if influenza:
        return "influenza", "influenza " + (influenza[1] or "unspecified"), False
    parainfluenza = re.fullmatch(r"(?:human )?parainfluenza(?: virus)?(?: ([1-4]))?", normalized)
    if parainfluenza:
        return "parainfluenza", "parainfluenza " + (parainfluenza[1] or "unspecified"), False
    if re.fullmatch(r"(?:sars[ -]?cov[ -]?2|covid[ -]?19)(?: (?:rna|pcr|virus))?", normalized):
        return "covid19", "sars-cov-2", False
    return "", normalized, False


def _viral_target(row: dict) -> tuple[str, str, bool]:
    component = str(row.get("component", "")).strip()
    known = display_name(component)
    source_target = _viral_name_target(known)
    # A known source name, as well as a source-code alias, retains its identity
    # if its editable display label changes. Otherwise a new negative RSV row
    # could be moved into another series and revive an old positive RSV row.
    if source_target[0] or known.casefold() != component.casefold() or component_key(component) in TEXT_ALIASES:
        return source_target
    named_target = _viral_name_target(str(row.get("name") or component))
    return named_target if named_target[0] else ("", component.casefold(), False)


def _add_viruses(sheet: dict, now: datetime, add, warn) -> None:
    if "o" in (sheet.get("import_warnings") or {}):
        warn("The respiratory viral panel import needs review. Retained results were not used for new note phrases.")
        return
    rows = (sheet.get("viral_panel") or {}).get("rows", [])
    admission = sheet.get("admission_date", "")
    groups = {}
    for row in rows:
        if not eligible_time(row, now, admission=admission):
            continue
        candidate, identity, combined = _viral_target(row)
        # Consolidate equivalent text/code aliases without merging distinct
        # influenza or parainfluenza subtypes into a single result series.
        groups.setdefault(identity, []).append((row, candidate, combined))
    for values in groups.values():
        identity_rows = [dict(row, component="SAME_TARGET") for row, _, _ in values]
        try:
            recent = _latest_groups({"rows": identity_rows})[0]
        except (KeyError, TypeError, ValueError):
            warn("Conflicting latest viral results need review. No phrase was added for the affected target.")
            continue
        latest_ids = {row["id"] for row in recent}
        for row, candidate, combined in values:
            if row.get("id") not in latest_ids or not row.get("include") or result_status(row.get("result", "")) != "positive":
                continue
            label = display_name(row["component"])
            if label == row["component"]:
                label = row.get("name") or label
            if not candidate:
                warn("A positive viral target has no verified matching phrase in the supplied catalog: " + label + ".")
                continue
            reason = f"Latest recorded viral result: {label} {row['result']} [{row['date']}]."
            if combined:
                reason += " The combined rhinovirus/enterovirus assay does not distinguish the two targets. Confirm the rhinovirus phrase before use."
            else:
                reason += " Confirm that this result represents the condition addressed in today's note."
            add(candidate, reason)


def _nutrition_active(row: dict, now: datetime) -> bool:
    if not row.get("include", True) or row.get("status", "active") != "active":
        return False
    value = " ".join(str(row.get(key, "")) for key in ("text", "name", "source", "device"))
    if re.search(r"\[(?:held(?: by provider)?|stopped|paused|discontinued|removed|cancelled|canceled)\]|^\s*(?:discontinued|cancelled|canceled)\s*:", value, re.I):
        return False
    for match in re.finditer(r"\[START ON ([^\]]+)\]", value, re.I):
        try:
            when, timed = date_parts(match[1])
        except ValueError:
            return False
        if when.date() > now.date() or (timed and when > now.replace(tzinfo=None)):
            return False
    return True


def _add_nutrition(sheet: dict, now: datetime, add, warn, medications=None) -> None:
    try:
        diet = diet_for_output(sheet)
        feeds = feeds_for_output(sheet)
        for row in (diet or {}).get("rows", []):
            if not _nutrition_active(row, now):
                continue
            value = re.sub(r"^\[START ON [^\]]+\]\s*", "", row.get("text", ""), flags=re.I)
            if re.match(r"^(?:Diet\s*:\s*)?NPO\b", value, re.I):
                add("malnutrition_risk", "Current dietary order: " + value + ". Review nutritional risk and the duration of restricted intake.")
            elif re.match(r"^(?:(?:Peds|Pediatric|Infant|Adult) )?Tube Feeding\b", value, re.I):
                add("malnutrition_risk", "A current tube-feeding order is listed. Review nutritional risk and adequacy of intake.")
        for row in (diet or {}).get("enteral", []):
            if _nutrition_active(row, now):
                add("malnutrition_risk", "An active structured feeding order is listed. Review nutritional risk and adequacy of intake.")
        recorded = (feeds or {}).get("rows", [])
        if isinstance(diet, dict) and "recorded_feed_ids" in diet:
            current_ids = set(diet["recorded_feed_ids"])
            recorded = [row for row in recorded if row.get("id") in current_ids]
        for row in recorded:
            formula, rate = str(row.get("formula", "")).strip(), str(row.get("rate", "")).strip()
            known_formula = formula.casefold().rstrip(".") not in _MISSING
            rate_match = FEED_RATE.fullmatch(rate)
            positive_rate = bool(rate_match and re.search(r"[1-9]", rate_match["number"]))
            if _nutrition_active(row, now) and (known_formula or positive_rate):
                detail = formula if known_formula else "rate " + rate
                if known_formula and rate_match:
                    detail += " at " + rate
                add("malnutrition_risk", "Recorded feeding: " + detail + ". Review nutritional risk and adequacy of intake.")
        if "b" not in (sheet.get("import_warnings") or {}):
            medication_data = medications if medications is not None else build_note_medications(sheet, as_of=now)
            for row in medication_data["entries"]:
                if row.get("active") and parenteral_kind(row.get("source_name", ""), row.get("route", "")):
                    add("malnutrition_risk", "Current parenteral nutrition or intravenous lipid order: " + row["name"] + ". Review nutritional risk and adequacy of intake.")
        for row in dietary_rows_for_display(diet, sheet.get("medications", []), sheet):
            if _nutrition_active(row, now) and parenteral_kind(row.get("name", "")):
                add("malnutrition_risk", "Current dietary parenteral nutrition order: " + row["name"] + ". Review nutritional risk and adequacy of intake.")
    except (KeyError, TypeError, ValueError):
        warn("Some nutrition orders need review before using them to suggest a malnutrition-risk phrase.")


def clinical_note_candidates(sheet: dict, *, settings=None, as_of=None, medications=None) -> dict:
    """Return catalog IDs and reasons without changing the handoff.

    ``medications`` may be the existing ``build_note_medications`` payload, so
    a caller that already formatted orders need not repeat that work for PN.
    """
    if not isinstance(sheet, dict):
        raise ValueError("Choose a handoff before reviewing clinical note findings.")
    now = clock(as_of)
    candidates = {}
    warnings = []

    def add(candidate: str, reason: str) -> None:
        reasons = candidates.setdefault(candidate, [])
        if reason not in reasons:
            reasons.append(reason)

    def warn(message: str) -> None:
        if message not in warnings:
            warnings.append(message)

    _add_viruses(sheet, now, add, warn)
    _add_nutrition(sheet, now, add, warn, medications)
    _add_labs(sheet, now, add, warn)
    return {
        "candidates": [{"id": candidate, "reason": " ".join(reasons)} for candidate, reasons in candidates.items()],
        "warnings": warnings,
    }
