"""Data model. All durable room and handoff data lives inside the encrypted vault."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
import uuid

LEGACY_SYSTEMS = (
    "Diagnoses", "Demographics / Weight", "Neurologic", "Respiratory",
    "Cardiovascular", "FEN / GI", "Hematology", "Infectious Disease",
    "Labs", "Skin / Wounds", "Tasks", "Other",
)
SYSTEMS = LEGACY_SYSTEMS + ("Other Medications", "Lab Results / Trends", "Goals / Follow-up", "Airway", "Last Intubation", "Access", "Drains / Tubes")
from medications import validate_medication, validate_rules, format_medication, validate_visibility, visible
from ventilation import validate_ventilation, format_ventilation
from noninvasive import validate_noninvasive, format_noninvasive
from labs import empty_labs, validate_labs, labs_text, lactate_text, id_labs_text, theophylline_text
from vitals import validate_vitals, text_by_system
from observations import empty_neuro, validate_neuro, neuro_rows, validate_nutrition, format_nutrition

from cultures import empty_cultures, validate_cultures, cultures_text
from demographics import validate_dosing_weight, validate_admission_date, demographic_weight_text
from viral import empty_viral_panel, validate_viral_panel, viral_text
from infusions import validate_infusion_rules, neuro_body, cardiovascular_body, hematology_body, respiratory_body
from medication_groups import validate_group_rules
from blood_gases import validate_gases
from cbc import validate_cbc
from output_text import medication_output
from recurring_orders import validate_orders, orders_text
from feeds import validate_feeds, feeds_for_output
from devices import validate_devices, evd_text
from pacemaker import validate_pacemaker, pacemaker_text
from diet import validate_diet, diet_for_output, diet_failed
from fluid_balance import validate_balance
from fen_gi import validate_gi_rules, effective_section, fen_gi_body

from import_review import validate_import_warnings, orders_for_output

SCHEMA_VERSION = 34
from problem_review import validate_review, empty_review
from difficult_airway import validate_airway
from lab_windows import cardiac_labs_summary, theophylline_summary, id_summary, laboratory_data
from mrsa import mrsa_screen_text
from anthropometrics import empty_anthropometrics, validate_anthropometrics, measurements_text


def section_label(section: str) -> str:
    """Display rename only. Keep the Labs archive key and mappings compatible."""
    return "Labs/Imaging" if section == "Labs" else section

# Interpretation of the user's ranges: even P4102..P4116, then the listed 4200 rooms.
PRESET_NUMBERS = [str(n) for n in range(4102, 4117, 2)] + ["4201", "4203", "4209"] + [str(n) for n in range(4211, 4224, 2)]
DEFAULT_ROOMS = ["P" + n for n in PRESET_NUMBERS]
MAX_FIELD = 20_000


class ValidationError(ValueError):
    """Only use static, patient-free messages for this exception."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_room(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 -]{0,15}", value):
        raise ValidationError("Use a room label of 1 to 16 letters, digits, spaces or hyphens. Do not enter a patient name.")
    # Treat an optional P as an alias for the preset numerical room, not a new bed.
    digits = value[1:] if value.startswith("P") else value
    if digits in PRESET_NUMBERS:
        return "P" + digits
    return value


def new_sheet(room: str) -> dict:
    return {"id": uuid.uuid4().hex, "room": normalize_room(room), "created_at": utc_now(),
            "updated_at": None, "fields": {s: "" for s in SYSTEMS}, "medications": [], "ventilation": None, "noninvasive": [], "vitals": [], "labs": empty_labs(), "neuro_vitals": empty_neuro(), "nutrition": None, "cultures": empty_cultures(), "dosing_weight": "", "admission_date": "", "viral_panel": empty_viral_panel(), "blood_gas": None, "cbc": None, "recurring_orders": None, "intake_output": None, "feeds": None, "devices": None, "neuro_devices": None, "pacemaker": None, "diet": None, "import_warnings": {}}


def new_vault() -> dict:
    return {"schema": SCHEMA_VERSION, "reset_generation": "", "settings": {"diagnoses_destination": "Diagnoses", "rooms": list(DEFAULT_ROOMS), "medication_mappings": [], "medication_visibility": [], "medication_infusions": [], "medication_gi_groups": [], "medication_groups": []}, "rooms": {}}


def validate_sheet(sheet: dict) -> None:
    if not isinstance(sheet, dict) or set(sheet) - {"anthropometrics", "problem_review", "difficult_airway", "empty_group_layout", "sbs_observations", "sbs_vent_mode"} != {"id", "room", "created_at", "updated_at", "fields", "medications", "ventilation", "noninvasive", "vitals", "labs", "neuro_vitals", "nutrition", "cultures", "dosing_weight", "admission_date", "viral_panel", "blood_gas", "cbc", "recurring_orders", "intake_output", "feeds", "devices", "neuro_devices", "pacemaker", "diet", "import_warnings"}:
        raise ValidationError("The handoff structure is invalid.")
    if not isinstance(sheet["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", sheet["id"]):
        raise ValidationError("The handoff identifier is invalid.")
    if normalize_room(sheet["room"]) != sheet["room"]:
        raise ValidationError("The room label is not normalized.")
    if not isinstance(sheet["created_at"], str) or not isinstance(sheet["updated_at"], (str, type(None))):
        raise ValidationError("The handoff timestamps are invalid.")
    if not isinstance(sheet["fields"], dict) or set(sheet["fields"]) != set(SYSTEMS):
        raise ValidationError("The handoff section structure is invalid.")
    for value in sheet["fields"].values():
        if not isinstance(value, str) or len(value) > MAX_FIELD:
            raise ValidationError("A handoff section is too long or invalid.")

    if not isinstance(sheet["medications"], list) or len(sheet["medications"]) > 300:
        raise ValidationError("The medication list is invalid or too large.")
    try:
        validate_ventilation(sheet["ventilation"])
        validate_noninvasive(sheet["noninvasive"])
        validate_vitals(sheet["vitals"])
        validate_labs(sheet["labs"])
        validate_neuro(sheet["neuro_vitals"])
        from sbs import validate_sbs, validate_sbs_vent_mode
        validate_sbs(sheet.get("sbs_observations"))
        if "sbs_vent_mode" in sheet:
            validate_sbs_vent_mode(sheet["sbs_vent_mode"])
        from empty_groups import validate_empty_group_layout
        validate_empty_group_layout(sheet.get("empty_group_layout", []))
        validate_nutrition(sheet["nutrition"])
        validate_cultures(sheet["cultures"])
        validate_dosing_weight(sheet["dosing_weight"])
        validate_admission_date(sheet["admission_date"])
        validate_viral_panel(sheet["viral_panel"])
        validate_gases(sheet["blood_gas"])
        validate_cbc(sheet["cbc"])
        validate_orders(sheet["recurring_orders"])
        validate_balance(sheet["intake_output"])
        validate_feeds(sheet["feeds"])
        validate_devices(sheet["devices"], "u")
        validate_devices(sheet["neuro_devices"], "v")
        validate_pacemaker(sheet["pacemaker"])
        validate_diet(sheet["diet"])
        validate_anthropometrics(sheet.get("anthropometrics", empty_anthropometrics()))
        validate_import_warnings(sheet["import_warnings"])
        validate_review(sheet.get("problem_review", empty_review()))
        validate_airway(sheet.get("difficult_airway"))
    except ValueError as exc:
        raise ValidationError(str(exc)) from None
    ids = set()
    for row in sheet["medications"]:
        try:
            validate_medication(row)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        if row["id"] in ids:
            raise ValidationError("Medication row identifiers must be unique.")
        ids.add(row["id"])


def validate_vault(vault: dict) -> None:
    if not isinstance(vault, dict) or set(vault) != {"schema", "reset_generation", "settings", "rooms"} or vault["schema"] != SCHEMA_VERSION:
        raise ValidationError("The encrypted archive has an unsupported structure. It was not overwritten.")
    if not isinstance(vault["reset_generation"], str) or not re.fullmatch(r"(?:[0-9a-f]{32})?", vault["reset_generation"]):
        raise ValidationError("The archive reset generation is invalid.")
    settings = vault["settings"]
    if not isinstance(settings, dict) or set(settings) - {"medication_categories", "medication_category_rules"} != {"diagnoses_destination", "rooms", "medication_mappings", "medication_visibility", "medication_infusions", "medication_gi_groups", "medication_groups"}:
        raise ValidationError("The saved Admin settings are invalid.")
    try:
        from categories import validate_settings
        validate_settings(settings)
        validate_rules(settings["medication_mappings"])
        validate_visibility(settings["medication_visibility"])
        validate_infusion_rules(settings["medication_infusions"])
        validate_gi_rules(settings["medication_gi_groups"])
        validate_group_rules(settings["medication_groups"])
    except ValueError as exc:
        raise ValidationError(str(exc)) from None
    if settings["diagnoses_destination"] not in SYSTEMS:
        raise ValidationError("The saved diagnosis destination is invalid.")
    if not isinstance(settings["rooms"], list) or not 1 <= len(settings["rooms"]) <= 100:
        raise ValidationError("The room list must contain between 1 and 100 rooms.")
    for room in settings["rooms"]:
        if normalize_room(room) != room:
            raise ValidationError("A saved room label is invalid.")
    if len(set(settings["rooms"])) != len(settings["rooms"]):
        raise ValidationError("The room list contains duplicates.")
    if not isinstance(vault["rooms"], dict) or len(vault["rooms"]) > 100:
        raise ValidationError("The archive has too many room handoffs.")
    for room, sheet in vault["rooms"].items():
        validate_sheet(sheet)
        if sheet["room"] != room:
            raise ValidationError("The saved handoff does not match its room.")


def save_sheet_in(vault: dict, sheet: dict) -> dict:
    validate_sheet(sheet)
    candidate = deepcopy(vault)
    saved = deepcopy(sheet)
    saved["updated_at"] = utc_now()
    candidate["rooms"][sheet["room"]] = saved
    validate_vault(candidate)
    return candidate


def apply_diagnoses(sheet: dict, diagnosis_text: str, destination: str, append: bool = False) -> dict:
    if destination not in SYSTEMS or not isinstance(diagnosis_text, str) or not diagnosis_text.strip():
        raise ValidationError("Choose a destination and enter diagnosis text before applying it.")
    result = deepcopy(sheet)
    existing = result["fields"][destination].rstrip()
    result["fields"][destination] = (existing + "\n" if append and existing else "") + diagnosis_text.strip()
    validate_sheet(result)
    return result


def upgrade_vault(vault: dict) -> dict:
    """Migrate schemas 1-25 without replacing keys, notes or saved mappings."""
    if not isinstance(vault, dict):
        raise ValidationError("The encrypted archive has an invalid structure.")
    version = vault.get("schema")
    if version == SCHEMA_VERSION:
        validate_vault(vault)
        return vault
    if version != SCHEMA_VERSION and isinstance(vault.get("settings"), dict) and "medication_categories" in vault["settings"]:
        from categories import add_missing_builtin_categories
        vault = deepcopy(vault)
        vault["settings"] = add_missing_builtin_categories(vault["settings"])
    if version == 33:
        candidate = deepcopy(vault)
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 32:
        candidate = deepcopy(vault)
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 31:
        candidate = deepcopy(vault)
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 30:
        candidate = deepcopy(vault)
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 29:
        candidate = deepcopy(vault)
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 28:
        candidate = deepcopy(vault)
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 27:
        candidate = deepcopy(vault)
        # Existing categories, subcategories and assignments keep their IDs.
        from categories import add_missing_builtin_categories
        candidate["settings"] = add_missing_builtin_categories(candidate["settings"])
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 26:
        candidate = deepcopy(vault)
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 25:
        candidate = deepcopy(vault)
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 24:
        candidate = deepcopy(vault)
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 23:
        candidate = deepcopy(vault)
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 22:
        candidate = deepcopy(vault)
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 21:
        if set(vault) != {"schema", "reset_generation", "settings", "rooms"} or not isinstance(vault["rooms"], dict):
            raise ValidationError("The previous archive structure is invalid. Nothing was discarded.")
        candidate = deepcopy(vault)
        expected = set(new_sheet("P4102")) - {"diet"}
        for sheet in candidate["rooms"].values():
            if not isinstance(sheet, dict) or set(sheet) != expected:
                raise ValidationError("A previous handoff structure is invalid. Nothing was discarded.")
            sheet["diet"] = None
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 20:
        if set(vault) != {"schema", "reset_generation", "settings", "rooms"} or not isinstance(vault["rooms"], dict):
            raise ValidationError("The previous archive structure is invalid. Nothing was discarded.")
        candidate = deepcopy(vault)
        expected = set(new_sheet("P4102")) - {"diet", "pacemaker"}
        for sheet in candidate["rooms"].values():
            if not isinstance(sheet, dict) or set(sheet) != expected:
                raise ValidationError("A previous handoff structure is invalid. Nothing was discarded.")
            sheet["pacemaker"] = None
            sheet["diet"] = None
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 19:
        if set(vault) != {"schema", "reset_generation", "settings", "rooms"} or not isinstance(vault["rooms"], dict):
            raise ValidationError("The previous archive structure is invalid. Nothing was discarded.")
        candidate = deepcopy(vault)
        expected = set(new_sheet("P4102")) - {"diet", "devices", "neuro_devices", "pacemaker"}
        for sheet in candidate["rooms"].values():
            if not isinstance(sheet, dict) or set(sheet) != expected:
                raise ValidationError("A previous handoff structure is invalid. Nothing was discarded.")
            sheet["devices"] = None
            sheet["neuro_devices"] = None
            sheet["pacemaker"] = None
            sheet["diet"] = None
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if version == 18:
        if set(vault) != {"schema", "reset_generation", "settings", "rooms"} or not isinstance(vault["rooms"], dict):
            raise ValidationError("The previous archive structure is invalid. Nothing was discarded.")
        candidate = deepcopy(vault)
        expected = set(new_sheet("P4102")) - {"diet", "feeds", "devices", "neuro_devices", "pacemaker"}
        for sheet in candidate["rooms"].values():
            if not isinstance(sheet, dict) or set(sheet) != expected:
                raise ValidationError("A previous handoff structure is invalid. Nothing was discarded.")
            sheet["feeds"] = None
            sheet["devices"] = None
            sheet["neuro_devices"] = None
            sheet["pacemaker"] = None
            sheet["diet"] = None
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    if set(vault) != {"schema", "settings", "rooms"}:
        raise ValidationError("The previous archive structure is invalid. Nothing was discarded.")
    if version not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17):
        raise ValidationError("The encrypted archive has an unsupported structure. It was not overwritten.")
    candidate = deepcopy(vault)
    candidate["reset_generation"] = ""
    if version == 17:
        if not isinstance(candidate["rooms"], dict):
            raise ValidationError("The previous archive structure is invalid. Nothing was discarded.")
        expected = set(new_sheet("P4102")) - {"diet", "feeds", "devices", "neuro_devices", "pacemaker"}
        for sheet in candidate["rooms"].values():
            if not isinstance(sheet, dict) or set(sheet) != expected:
                raise ValidationError("A previous handoff structure is invalid. Nothing was discarded.")
            sheet["feeds"] = None
            sheet["devices"] = None
            sheet["neuro_devices"] = None
            sheet["pacemaker"] = None
            sheet["diet"] = None
        candidate["schema"] = SCHEMA_VERSION
        validate_vault(candidate)
        return candidate
    settings = candidate["settings"]
    expected_settings = {"diagnoses_destination", "rooms"} | ({"medication_mappings"} if version >= 2 else set())
    if version >= 6:
        expected_settings.add("medication_visibility")
    if version >= 11:
        expected_settings.add("medication_infusions")
    if version >= 15:
        expected_settings.add("medication_gi_groups")
    if not isinstance(settings, dict) or set(settings) != expected_settings or not isinstance(candidate["rooms"], dict):
        raise ValidationError("The previous archive structure is invalid. Nothing was discarded.")
    if version == 1:
        settings["medication_mappings"] = []
    if version < 6:
        settings["medication_visibility"] = []
    if version < 11:
        settings["medication_infusions"] = []
    if version < 15:
        settings["medication_gi_groups"] = []
    settings["medication_groups"] = []
    settings["rooms"] = list(dict.fromkeys(normalize_room(r) for r in settings["rooms"]))
    converted_rooms = {}
    for original_room, sheet in candidate["rooms"].items():
        expected = {"id", "room", "created_at", "updated_at", "fields"}
        if version >= 2:
            expected.add("medications")
        if version >= 3:
            expected.add("ventilation")
        if version >= 4:
            expected.add("noninvasive")
        if version >= 6:
            expected.update({"vitals", "labs"})
        if version >= 7:
            expected.update({"neuro_vitals", "nutrition"})
        if version >= 8:
            expected.add("cultures")
        if version >= 9:
            expected.update({"dosing_weight", "admission_date"})
        if version >= 10:
            expected.add("viral_panel")
        if version >= 12:
            expected.add("blood_gas")
        if version >= 13:
            expected.add("cbc")
        if version >= 14:
            expected.add("recurring_orders")
        if version >= 15:
            expected.add("intake_output")
        if version >= 16:
            expected.add("import_warnings")
        if not isinstance(sheet, dict) or set(sheet) != expected:
            raise ValidationError("A previous handoff structure is invalid. Nothing was discarded.")
        expected_fields = set(LEGACY_SYSTEMS if version == 1 else SYSTEMS)
        if not isinstance(sheet["fields"], dict) or set(sheet["fields"]) != expected_fields:
            raise ValidationError("A previous handoff has unexpected fields. Nothing was discarded.")
        if version == 1:
            for section in SYSTEMS:
                sheet["fields"].setdefault(section, "")
            sheet["medications"] = []
        if version < 3:
            sheet["ventilation"] = None
        if version < 4:
            sheet["noninvasive"] = []
        elif version == 4:
            if not isinstance(sheet["noninvasive"], list):
                raise ValidationError("The previous respiratory support list is invalid.")
            for device in sheet["noninvasive"]:
                if (not isinstance(device, dict)
                        or set(device) != {"device", "values", "flow_inferred"}
                        or device["device"] not in ("BiPAP", "CPAP", "HFNC")):
                    raise ValidationError("A previous respiratory entry is invalid. Nothing was discarded.")
                device["pressure_inferred"] = False
        if version < 6:
            sheet["vitals"] = []
            sheet["labs"] = empty_labs()
            for row in sheet["medications"]:
                if "hidden" in row:
                    raise ValidationError("The previous medication structure is invalid.")
                row["hidden"] = False
        if version < 7:
            sheet["neuro_vitals"] = empty_neuro()
            sheet["nutrition"] = None
        if version < 8:
            sheet["cultures"] = empty_cultures()
        if version < 9:
            sheet["dosing_weight"] = ""
            sheet["admission_date"] = ""
        if version < 10:
            sheet["viral_panel"] = empty_viral_panel()
        if version < 12:
            sheet["blood_gas"] = None
        if version < 13:
            sheet["cbc"] = None
        if version < 14:
            sheet["recurring_orders"] = None
        if version < 15:
            sheet["intake_output"] = None
        if version < 16:
            sheet["import_warnings"] = {}
        sheet["feeds"] = None
        sheet["devices"] = None
        sheet["neuro_devices"] = None
        sheet["pacemaker"] = None
        sheet["diet"] = None
        room = normalize_room(original_room)
        if normalize_room(sheet["room"]) != room:
            raise ValidationError("A previous handoff does not match its room. Nothing was discarded.")
        if room in converted_rooms:
            raise ValidationError("Two saved room aliases refer to the same preset room. Resolve the duplicate before upgrading. Nothing was overwritten.")
        sheet["room"] = room
        converted_rooms[room] = sheet
    candidate["rooms"] = converted_rooms
    candidate["schema"] = SCHEMA_VERSION
    validate_vault(candidate)
    return candidate


def apply_medications(sheet: dict, rows: list[dict]) -> dict:
    """Replace the previous medication import, never append duplicate orders.

    System notes remain separate, so reimporting/remapping cannot erase them.
    Each source order remains separate even when names/doses repeat.
    """
    candidate = deepcopy(sheet)
    candidate["medications"] = deepcopy(rows)
    validate_sheet(candidate)
    return candidate


def fields_with_medications(sheet: dict, include_lab_text: bool = True) -> dict[str, str]:
    validate_sheet(sheet)
    result = dict(sheet["fields"])
    for row in sheet["medications"]:
        if not visible(row):
            continue
        section = effective_section(row)
        content = medication_output(format_medication(row))
        result[section] = (result[section].rstrip() + "\n" if result[section].strip() else "") + content
    result["FEN / GI"] = fen_gi_body(sheet["fields"]["FEN / GI"], sheet["medications"], sheet["intake_output"], feeds=feeds_for_output(sheet), feeds_failed=any(i["action"] == "feeds_hidden" for i in sheet["import_warnings"].get("t", [])), diet=diet_for_output(sheet), diet_failed=diet_failed(sheet), dosing_weight=sheet["dosing_weight"] if "i" not in sheet["import_warnings"] else "", sheet=sheet)
    scheduled = orders_text(orders_for_output(sheet))
    if "r" in sheet["import_warnings"]:
        scheduled = "Orders not imported. Review needed."
    if scheduled:
        result["Labs"] = scheduled + ("\n-----\n" + result["Labs"] if result["Labs"].strip() else "")
    result["Neurologic"] = neuro_body(sheet["fields"]["Neurologic"], sheet["medications"], sheet=sheet)
    result["Cardiovascular"] = cardiovascular_body(sheet["fields"]["Cardiovascular"], sheet["medications"], sheet=sheet)
    result["Hematology"] = hematology_body(sheet["fields"]["Hematology"], sheet["medications"], sheet=sheet)
    result["Respiratory"] = respiratory_body(sheet["fields"]["Respiratory"], sheet["medications"], sheet=sheet)
    from categories import theophylline_anchor, medication_blocks
    from infusions import render_body_blocks
    for section in ("Infectious Disease", "Skin / Wounds", "Other Medications"):
        result[section] = render_body_blocks(medication_blocks(section, sheet["fields"][section], sheet["medications"], sheet))
    theophylline = "" if theophylline_anchor(sheet) else theophylline_summary(sheet)
    if theophylline:
        result["Respiratory"] = theophylline + ("\n-----\n" + result["Respiratory"] if result["Respiratory"].strip() else "")
    vent = respiratory_text(sheet)
    if vent:
        result["Respiratory"] = vent + "\n-----" + ("\n" + result["Respiratory"] if result["Respiratory"].strip() else "")
    lactate = cardiac_labs_summary(sheet)
    if lactate:
        result["Cardiovascular"] = lactate + ("\n-----\n" + result["Cardiovascular"] if result["Cardiovascular"].strip() else "")
    id_notes = result["Infectious Disease"]
    auto_vitals = automatic_vitals(sheet)
    for section, text in auto_vitals.items():
        result[section] = text + ("\n-----\n" + result[section] if result[section].strip() else "")
    culture_block = "" if "f" in sheet["import_warnings"] else cultures_text(sheet["cultures"], empty_none=True)
    id_labs = id_summary(sheet)
    if culture_block or id_labs:
        id_vitals = auto_vitals.get("Infectious Disease", "")
        parts = [part for part in (id_vitals, id_labs, culture_block, id_notes) if part.strip()]
        result["Infectious Disease"] = ("" if id_vitals else "------\n") + "\n------\n".join(parts)
    if sheet["admission_date"]:
        text = "Admission: " + sheet["admission_date"]
        result["Demographics / Weight"] = text + ("\n" + result["Demographics / Weight"] if result["Demographics / Weight"].strip() else "")
    screen = mrsa_screen_text(sheet)
    if screen:
        demographic_notes = result["Demographics / Weight"].rstrip()
        result["Demographics / Weight"] = (demographic_notes + "\n" if demographic_notes else "") + screen
    nutrition = demographic_weight_text(sheet["nutrition"], sheet["dosing_weight"])
    if nutrition:
        diagnosis = result["Diagnoses"].rstrip()
        result["Diagnoses"] = (diagnosis + "\n----\n" if diagnosis else "") + nutrition
    measurements = measurements_text(sheet.get("anthropometrics", empty_anthropometrics()))
    if measurements:
        result["Diagnoses"] += "\n" + measurements
    positive = viral_text(sheet["viral_panel"])
    if positive:
        result["Diagnoses"] = result["Diagnoses"].rstrip() + ("\n" if result["Diagnoses"].strip() else "") + "----\n" + positive
    if include_lab_text:
        laboratory = labs_text(laboratory_data(sheet), include_id_panels=False, blood_gas=sheet["blood_gas"], cbc=sheet["cbc"])
        if laboratory:
            result["Lab Results / Trends"] = laboratory + ("\n" + result["Lab Results / Trends"] if result["Lab Results / Trends"].strip() else "")
    return result


def apply_ventilation(sheet: dict, data: dict | None) -> dict:
    result = deepcopy(sheet)
    result["ventilation"] = deepcopy(data)
    validate_sheet(result)
    return result


def respiratory_text(sheet: dict) -> str:
    """Automatic support only, before the separator, notes and medications."""
    invasive = format_ventilation(sheet["ventilation"])
    noninvasive = format_noninvasive(sheet["noninvasive"])
    has_vent = bool(invasive) or any(
        d.get("include", True) and d.get("device") in {"BiPAP", "CPAP", "AVAPS NIV", "NAVA NIV"}
        for d in sheet["noninvasive"]
    )
    parts = (["Vent Settings"] if has_vent else []) + [invasive, noninvasive]
    return "\n".join(part for part in parts if part)


def apply_respiratory(sheet: dict, invasive: dict | None, devices: list[dict]) -> dict:
    """Replace the support snapshot only. Never merge it with old device settings."""
    result = deepcopy(sheet)
    result["ventilation"] = deepcopy(invasive)
    result["noninvasive"] = deepcopy(devices)
    result["sbs_vent_mode"] = invasive["mode"] if invasive else ""
    validate_sheet(result)
    return result


def automatic_vitals(sheet: dict) -> dict[str, str]:
    """Keep imported neurologic observations before notes and medications."""
    neuro = sheet["neuro_vitals"]
    if "y" in sheet.get("import_warnings", {}):
        # Do not print a retained old score as though a failed Y import refreshed it.
        neuro = dict(neuro, y=[])
    if "m" in sheet.get("import_warnings", {}):
        # A failed M paste cannot refresh the retained last pressures.
        neuro = dict(neuro, m=[])
    from sbs import sbs_display_rows
    neuro = dict(neuro, k=sbs_display_rows(sheet))
    # A target in the old E section is not an observed, timestamped SBS.
    unrelated_vitals = [r for r in sheet["vitals"]
        if not re.search(r"\bSBS\b|target arousal", r["label"], re.I)]
    result = text_by_system(neuro_rows(neuro) + unrelated_vitals)
    evd = evd_text(sheet)
    if evd:
        old = result.get("Neurologic", "")
        result["Neurologic"] = (old + "\n" if old else "") + evd
    pacing = pacemaker_text(sheet)
    if pacing:
        old = result.get("Cardiovascular", "")
        result["Cardiovascular"] = (old + "\n" if old else "") + pacing
    return result
