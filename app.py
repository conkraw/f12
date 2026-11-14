"""PICU SmartPhrase v6.69: AVAPS settings with separate target and observed volumes."""
from __future__ import annotations
from copy import deepcopy
from workspace_ui import (WORKSPACE_TABS, COMPACT_STYLES, compact_help, alert_rows,
                          alert_lines_html, remember_notice, remember_import, workspace_attention)
from empty_groups import refresh_empty_group_layout
from categories import apply_category_rules, set_category_rule, theophylline_anchor, matching_target
from category_ui import placement_picker, category_admin, local_target
from html import escape
from pathlib import Path
import time
import json
from threading import Event
from datetime import datetime, timezone

import streamlit as st
from cryptography.fernet import Fernet
from exports import handoff_html, handoff_text, handoff_pdf, handoffs_pdf, handoffs_html, print_layout_info, print_fit_report, download_payload
from github_store import GitHubConfig, GitHubVault, StorageError
from error_store import ErrorJournal, new_error_event
from import_review import review_summary, diagnostic_text, SECTIONS as REVIEW_SECTIONS
from models import (MAX_FIELD, SYSTEMS, ValidationError, new_sheet, new_vault,
                    normalize_room, save_sheet_in, validate_vault, validate_sheet,
                    upgrade_vault, fields_with_medications, respiratory_text, automatic_vitals, SCHEMA_VERSION, DEFAULT_ROOMS, section_label)
from infusion_rates import ADMIN_FIELDS, ADMIN_STATUSES, ADMIN_STATUS_LABELS, continuous_order, merge_admin_edits
from medications import (DESTINATIONS, format_medication, suggested_key, upsert_rule,
                         remap, rule_for_inline_mapping, validate_medication, visible, hidden_for, set_visibility_rule, ignored, explicit_ignore_mapping)
from ventilation import LABELS, format_ventilation, validate_ventilation
from noninvasive import DEVICE_FIELDS, format_noninvasive, validate_noninvasive
from importing import import_sections, SUPPORTED_SECTIONS
from batching import available_handoffs
from handoff_reset import cleared_vault, census_was_reset
from daily_start import daily_reset_plan, start_daily_list, START_MARKER
from census_guard import guard_download
from save_status import (room_save_status, saved_time_text, latest_saved_time,
                         most_recent_save_caption, save_status_table)
from parser import MAX_PASTE, SECTION_NAMES
from security import valid_password_hash, verify_password
from admin_access import admin_valid, unlock_admin, lock_admin, config_error as admin_config_error
from user_guide import (default_guide, publication, validate_guide, instructions_html, handoff_instructions,
                        MAX_TEMPLATE, MAX_INSTRUCTIONS, MAX_NOTES)
from guide_store import GuideStore
from difficult_airway import (empty_airway, validate_airway, collect_airway, airway_summary,
                              FIELDS as AIRWAY_FIELDS, TEXT_LIMITS as AIRWAY_LIMITS,
                              MASK_OPTIONS, PASSAGE_OPTIONS)
from labs import validate_labs
from lab_windows import (cardiac_labs_summary, theophylline_summary, id_summary, laboratory_data, window_help)
from problem_review import (suggestions, empty_review, validate_review, set_decision, limitation_notes,
                            LOW_RULES, LABELS as PROBLEM_LAB_LABELS, STATUSES as PROBLEM_STATUSES)
from cbc import validate_cbc, cbc_summary, cbc_selection_issues
from recurring_orders import validate_orders, selected_orders, orders_text, order_line, recurring_frequency
from blood_gases import FIELDS as GAS_FIELDS, validate_gases, latest_sample, gas_summary, legacy_gases
from vitals import validate_vitals, text_by_system
from lab_layout import laboratory_html
from observations import NEURO_SECTIONS, validate_neuro, validate_nutrition, format_nutrition
from demographics import validate_dosing_weight, validate_admission_date, demographic_weight_text
from mrsa import mrsa_screen_text
from clinical_style import clinical_markup
from anthropometrics import empty_anthropometrics, clean_field, validate_anthropometrics, measurements_text, FIELDS as ANTHRO_FIELDS
from bmi_reference import bmi_percentile_summary, download_reference, install_reference, REFERENCE_PATH
from cultures import validate_cultures, cultures_text, compact_groups, category_for
from viral import validate_viral_panel, viral_text
from microbiology_display import culture_markup, viral_markup
from pacemaker import (validate_pacemaker, format_pacemaker, pacemaker_text,
                       EDIT_FIELDS as PACER_FIELDS, STATUSES as PACER_STATUSES, normalize_mode, normalize_rate)
from devices import validate_devices, EDIT_FIELDS as DEVICE_EDIT_FIELDS, device_line, devices_markup, evd_text
from diet import validate_diet, diet_text, diet_for_output, diet_failed
from feeds import METHODS as FEED_METHODS, validate_feeds, feeds_text, feeds_for_output
from fluid_balance import balance_heading, FIELDS as IO_FIELDS, META_FIELDS as IO_META_FIELDS, validate_balance, balance_text, empty_balance
from fen_gi import (MODES as GI_MODES, MODE_LABELS as GI_MODE_LABELS, GROUP_NAMES,
                    automatic_group, group_for, effective_section, fen_gi_body,
                    apply_gi_rules, set_gi_rule, gi_key, gi_mode_for)
from infusions import (MODES, MODE_LABELS, is_infusion, infusion_entry, neuro_body, cardiovascular_body, hematology_body,
                       set_infusion_rule, apply_infusion_rules, infusion_key, infusion_mode_for, respiratory_body, INFUSION_SECTIONS, DISPLAY_LABELS, supports_infusion_display)

from medication_groups import (MODES as GROUP_MODES, MODE_LABELS as GROUP_MODE_LABELS,
    GROUP_SECTIONS, group_for as special_group, automatic_group as automatic_special_group,
    apply_group_rules, set_group_rule, group_key, group_mode_for)

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="PICU Handoff", layout="wide", initial_sidebar_state="expanded")


def note(text: str, kind: str = "info") -> None:
    st.session_state["notice"] = (kind, text)


def clear_session() -> None:
    old = st.session_state.get("download_revocation")
    if old is not None:
        old.set()
    st.session_state.clear()


def require_session() -> bool:
    now = time.monotonic()
    ss = st.session_state
    if (not ss.get("authenticated")
            or now - ss.get("last_activity", 0) > ss.get("idle_seconds", 900)
            or now - ss.get("login_at", 0) > 8 * 3600):
        clear_session()
        return False
    ss["last_activity"] = now
    return True


def authenticate(encoded: str) -> None:
    now = time.monotonic()
    if now < st.session_state.get("retry_after", 0):
        st.session_state.pop("login_password", None)
        return
    password = st.session_state.pop("login_password", "")
    if verify_password(password, encoded):
        clear_session()
        st.session_state.update(authenticated=True, last_activity=now, login_at=now)
    else:
        attempts = min(st.session_state.get("attempts", 0) + 1, 10)
        st.session_state.update(attempts=attempts, retry_after=now + min(30, 2 ** attempts),
                                login_error="Password not accepted. Wait briefly before trying again.")


def edit_key(sheet: dict, section: str) -> str:
    return "field_" + sheet["id"] + "_" + str(SYSTEMS.index(section))


def discard_editor_widget_values() -> None:
    for key in list(st.session_state):
        if key.startswith(("field_", "med_draft_", "med_pending_", "vent_", "niv_", "lab_", "vital_", "neuro_", "sbs_", "weight_", "culture_", "demo_", "viral_", "gas_", "cbc_", "rorder_", "io_", "feed_", "device_", "pacer_", "diet_", "anthro_", "problem_", "dairway_")):
            st.session_state.pop(key, None)


def set_editor(room: str, sheet: dict) -> None:
    validate_sheet(sheet)
    st.session_state.pop("airway_update_pending", None)
    discard_editor_widget_values()
    st.session_state.setdefault("drafts", {})[room] = deepcopy(sheet)
    st.session_state["drafts"][room]["medications"] = apply_category_rules(sheet["medications"], st.session_state.get("vault", {}).get("settings", {}))
    refresh_empty_group_layout(st.session_state["drafts"][room], st.session_state.get("vault", {}).get("settings", {}))
    st.session_state["paste"] = ""
    st.session_state.pop("import_result", None)
    st.session_state.get("workspace_imports", {}).pop(sheet["id"], None)
    st.session_state["handoff_tab"] = "Preview / print"
    st.session_state["handoff_active_tab"] = "Preview / print"


def editor_snapshot(room: str) -> dict:
    """Capture current widget values before a room callback clears widgets.

    Streamlit can deliver a blurred text edit and a room change in one event.
    Read only widget keys belonging to the outgoing sheet. Validate the whole
    candidate before any save or switch. No pasted source text enters storage.
    """
    ss = st.session_state
    sheet = deepcopy(ss["drafts"][room])
    if any("dairway_" + sheet["id"] + "_" + field in ss for field in AIRWAY_FIELDS):
        sheet["difficult_airway"] = collect_airway(sheet, ss)
    for section in SYSTEMS:
        key = edit_key(sheet, section)
        if key in ss:
            sheet["fields"][section] = ss[key]
    for row in sheet["medications"]:
        old_signature = infusion_key(row)
        old_mode = row.get("infusion_mode", "auto")
        old_gi_mode = row.get("gi_mode", "auto")
        old_group_mode = row.get("group_mode", "auto")
        old_effective = effective_section(row)
        prefix = "med_draft_" + row["id"] + "_"
        for field in ("name", "dose", "route", "frequency", "last_rate", "rate_time", "section", "custom_text", "include", "infusion_mode", "gi_mode", "group_mode"):
            if prefix + field in ss:
                if field in ("group_mode", "gi_mode", "infusion_mode") and field not in row and ss[prefix + field] == "auto":
                    continue  # Merely opening an editor must not change a legacy record.
                if field == "section" and ss[prefix + field] == old_effective:
                    continue  # The automatic FEN/GI label is not a changed saved mapping.
                row[field] = ss[prefix + field]
        merge_admin_edits(row, {field: ss[prefix + field] for field in ADMIN_FIELDS if prefix + field in ss})
        if row.get("gi_mode", "auto") != old_gi_mode and row.get("gi_mode", "auto") not in ("auto", "other"):
            row["group_mode"] = "auto"
        if infusion_key(row) != old_signature and row.get("infusion_mode", "auto") == old_mode:
            row["infusion_mode"] = infusion_mode_for(row, ss["vault"]["settings"]["medication_infusions"])
        if infusion_key(row) != old_signature and row.get("gi_mode", "auto") == old_gi_mode:
            row["gi_mode"] = gi_mode_for(row, ss["vault"]["settings"]["medication_gi_groups"])
        if infusion_key(row) != old_signature and row.get("group_mode", "auto") == old_group_mode:
            row["group_mode"] = group_mode_for(row, ss["vault"]["settings"]["medication_groups"])
        if prefix + "section" in ss and ss[prefix + "section"] != old_effective:
            if row["section"] != "FEN / GI":
                row["gi_mode"] = "other"
            group = special_group(row)
            if group and row["section"] != GROUP_SECTIONS[group]:
                row["group_mode"] = "other"
    sheet["medications"] = apply_category_rules(sheet["medications"], ss["vault"]["settings"])
    refresh_empty_group_layout(sheet, ss["vault"]["settings"])
    if sheet["intake_output"] is not None:
        for field in IO_FIELDS + IO_META_FIELDS + ("include",):
            key = "io_" + sheet["id"] + "_" + field
            if key in ss:
                sheet["intake_output"][field] = ss[key].strip() if isinstance(ss[key], str) else ss[key]
    if sheet["feeds"] is not None:
        for row in sheet["feeds"]["rows"]:
            for field in ("method", "formula", "rate", "include"):
                key = "feed_" + row["id"] + "_" + field
                if key in ss:
                    value = ss[key]
                    if field == "rate":
                        value = "" if str(value).strip().casefold() in ("", "unk", "unknown", "--") else str(value).strip()
                        if value != row["rate"]:
                            row["rate_source"] = "manual" if value else "unknown"
                    row[field] = value.strip() if isinstance(value, str) else value
    for row in (sheet["diet"] or {}).get("rows", []):
        for field in ("text", "include"):
            key = "diet_" + row["id"] + "_" + field
            if key in ss:
                value = ss[key]
                row[field] = value.strip() if isinstance(value, str) else value
    for source in ("devices", "neuro_devices"):
        for row in (sheet[source] or {}).get("rows", []):
            for field in DEVICE_EDIT_FIELDS:
                key = "device_" + row["id"] + "_" + field
                if key in ss:
                    value = ss[key]
                    row[field] = value.strip() if isinstance(value, str) else value
    for group, prefix, fields in (
        (sheet["labs"]["rows"], "lab_", ("value", "date", "include")),
        (sheet["viral_panel"]["rows"], "viral_", ("name", "result", "date", "include")),
        (sheet["cultures"]["rows"], "culture_", ("date", "specimen", "organisms", "include")),
    ):
        for row in group:
            for field in fields:
                key = prefix + row["id"] + "_" + field
                if key in ss:
                    value = ss[key]
                    if field == "organisms":
                        value = [line.strip() for line in value.splitlines() if line.strip()]
                    row[field] = value
    if sheet["recurring_orders"] is not None:
        for row in sheet["recurring_orders"]["rows"]:
            for field in ("name", "timing", "occurrences", "include"):
                key = "rorder_" + row["id"] + "_" + field
                if key in ss:
                    row[field] = order_widget_value(field, ss[key])
    if sheet["cbc"] is not None:
        for row in sheet["cbc"]["rows"]:
            dkey = "cbc_date_" + sheet["id"] + "_" + str(row["column"])
            if dkey in ss:
                row["date"] = ss[dkey].strip()
            for field in ("value", "unit", "include"):
                key = "cbc_" + row["id"] + "_" + field
                if key in ss:
                    row[field] = ss[key].strip() if isinstance(ss[key], str) else ss[key]
    if sheet["blood_gas"] is not None:
        for sample in sheet["blood_gas"]["samples"]:
            prefix = "gas_" + sample["id"] + "_"
            for field in ("date", "include"):
                if prefix + field in ss:
                    sample[field] = ss[prefix + field]
            for index, label in enumerate(GAS_FIELDS):
                if label in sample["values"]:
                    for field in ("value", "unit"):
                        key = prefix + str(index) + "_" + field
                        if key in ss:
                            sample["values"][label][field] = ss[key].strip()
    for index, row in enumerate(sheet["vitals"]):
        key = "vital_" + sheet["id"] + "_" + str(index)
        for field, widget in (("value", key), ("include", key + "_include")):
            if widget in ss:
                row[field] = ss[widget]
    for source, rows in sheet["neuro_vitals"].items():
        for index, row in enumerate(rows):
            key = "neuro_" + sheet["id"] + "_" + source + "_" + str(index)
            for field, widget in (("value", key), ("include", key + "_include")):
                if widget in ss:
                    row[field] = ss[widget]
    for index, row in enumerate((sheet.get("sbs_observations") or {}).get("readings", [])):
        for field in ("value", "recorded_at", "include"):
            key = "sbs_" + sheet["id"] + "_" + str(index) + "_" + field
            if key in ss:
                row[field] = ss[key].strip() if isinstance(ss[key], str) else ss[key]
    window = (sheet.get("sbs_observations") or {}).get("source_window")
    if window is not None:
        for field in ("value", "include"):
            key = "sbs_window_" + sheet["id"] + "_" + field
            if key in ss:
                value = ss[key]
                if field == "value":
                    from sbs import score
                    value = str(value).strip()
                    value = "" if not value or value.casefold() == "none" else score(value)
                window[field] = value
    historical = (sheet.get("sbs_observations") or {}).get("last_available")
    if historical is not None:
        for field in ("value", "recorded_at", "include"):
            key = "sbs_history_" + sheet["id"] + "_" + field
            if key in ss:
                value = ss[key]
                if field == "value":
                    from sbs import score
                    value = score(str(value))
                elif field == "recorded_at":
                    value = str(value).strip()
                historical[field] = value
    if sheet["pacemaker"] is not None:
        for field in PACER_FIELDS:
            key = "pacer_" + sheet["id"] + "_" + field
            if key in ss:
                value = ss[key]
                if field == "mode":
                    value = normalize_mode(value)
                elif field in ("atrial_rate", "ventricular_rate", "rate"):
                    value = normalize_rate(value)
                sheet["pacemaker"][field] = value
    if sheet["nutrition"] is not None:
        for field in ("weight", "z_score", "include"):
            key = "weight_" + sheet["id"] + "_" + field
            if key in ss:
                value = ss[key]
                sheet["nutrition"][field] = value.strip() if isinstance(value, str) else value
    for field in ANTHRO_FIELDS:
        key = "anthro_" + sheet["id"] + "_" + field
        if key in ss:
            value = clean_field(field, ss[key])
            if value or "anthropometrics" in sheet:
                sheet.setdefault("anthropometrics", empty_anthropometrics())[field] = value
    for field in ("admission_date", "dosing_weight"):
        key = "demo_" + sheet["id"] + "_" + field
        if key in ss:
            sheet[field] = ss[key].strip()
    if sheet["ventilation"] is not None:
        for index, label in enumerate(LABELS):
            key = "vent_" + sheet["id"] + "_" + str(index)
            if key not in ss:
                continue
            value = ss[key].strip()
            if index == 0:
                sheet["ventilation"]["mode"] = value
                sheet["sbs_vent_mode"] = value
            elif value:
                sheet["ventilation"]["values"][label] = value
            else:
                sheet["ventilation"]["values"].pop(label, None)
    for device in sheet["noninvasive"]:
        for index, label in enumerate(DEVICE_FIELDS[device["device"]]):
            key = "niv_" + sheet["id"] + "_" + device["device"] + "_" + str(index)
            if key in ss:
                value = ss[key].strip()
                if value:
                    device["values"][label] = value
                else:
                    device["values"].pop(label, None)
    review_key = 'problem_' + sheet['id'] + '_enabled'
    if review_key in ss and bool(ss[review_key]) != sheet.get("problem_review", empty_review())["enabled"]:
        sheet.setdefault('problem_review', empty_review())['enabled'] = bool(ss[review_key])
    for item in suggestions(sheet):
        prefix = 'problem_' + sheet['id'] + '_' + item['key'] + '_' + item['fingerprint'][:12]
        status_key, text_key = prefix + '_status', prefix + '_text'
        if status_key in ss and text_key in ss and (ss[status_key] != item['status'] or ss[text_key] != item['label']):
            sheet = set_decision(sheet, item['key'], item['fingerprint'], ss[status_key], ss[text_key])
    validate_sheet(sheet)
    return sheet


def autosave_before_room_change(store: GitHubVault | None, *, for_print: bool = False) -> bool:
    ss = st.session_state
    room = ss.get("current_room")
    ss.pop("airway_update_pending", None)  # Obsolete pre-6.62 prompt state.
    if not room or room not in ss.get("drafts", {}):
        return True
    try:
        draft = editor_snapshot(room)
    except (ValueError, TypeError, KeyError) as exc:
        note("The current room was not saved or changed. Correct the highlighted editor value before " + ("opening Print all. " if for_print else "switching rooms. ") + str(exc), "error")
        return False
    # Keep the original draft and all widgets until the write is confirmed.
    # A retry captures the same values, including pending mapping changes.
    prior = ss["drafts"][room]
    if draft == ss["vault"]["rooms"].get(room):
        return True
    if ss.get("base_sheets", {}).get(room) != ss["vault"]["rooms"].get(room):
        note("Autosave was blocked because the saved room changed. You are still in the current room and your edits are kept. Reload the archive and compare before saving.", "error")
        return False
    try:
        candidate = deepcopy(ss["vault"])
        rules = candidate["settings"]["medication_mappings"]
        changed_rules = False
        infusion_rules = candidate["settings"]["medication_infusions"]
        gi_rules = candidate["settings"]["medication_gi_groups"]
        group_rules = candidate["settings"]["medication_groups"]
        old_rows = {row["id"]: row for row in prior["medications"]}
        for row in draft["medications"]:
            old = old_rows.get(row["id"])
            if old is not None and old["section"] != row["section"]:
                name, match = rule_for_inline_mapping(row["name"], rules)
                rules = upsert_rule(rules, name, row["section"], match)
                changed_rules = True
            if old is not None and old.get("infusion_mode", "auto") != row.get("infusion_mode", "auto"):
                infusion_rules = set_infusion_rule(infusion_rules, row, row.get("infusion_mode", "auto"))
                changed_rules = True
            if old is not None and old.get("gi_mode", "auto") != row.get("gi_mode", "auto"):
                gi_rules = set_gi_rule(gi_rules, row, row.get("gi_mode", "auto"))
                changed_rules = True
            if old is not None and old.get("group_mode", "auto") != row.get("group_mode", "auto"):
                group_rules = set_group_rule(group_rules, row, row.get("group_mode", "auto"))
                changed_rules = True
        if changed_rules:
            candidate["settings"]["medication_groups"] = group_rules
            candidate["settings"]["medication_gi_groups"] = gi_rules
            candidate["settings"]["medication_mappings"] = rules
            candidate["settings"]["medication_infusions"] = infusion_rules
            draft["medications"] = apply_group_rules(apply_gi_rules(apply_infusion_rules(remap(draft["medications"], rules, candidate["settings"]["medication_visibility"]), infusion_rules), gi_rules), group_rules)
        candidate = save_sheet_in(candidate, draft)
        commit(candidate, store)
    except (StorageError, ValidationError, ValueError) as exc:
        note("Autosave failed. You are still in the current room and your edits are kept. " + str(exc), "error")
        return False
    except Exception:
        # A custom storage implementation must not cause a silent room switch.
        note("Autosave was not confirmed. You are still in the current room and your edits are kept. Check the connection and retry.", "error")
        return False
    saved = deepcopy(candidate["rooms"][room])
    ss["drafts"][room] = saved
    ss.setdefault("base_sheets", {})[room] = deepcopy(saved)
    if changed_rules:
        reapply_open_mappings()
    message = (("Handoff automatically saved before Print all." if for_print else "Previous room automatically saved to shared storage.") if store else
               "Handoff saved in this session only. Shared storage is not enabled.")
    note(message + " Last saved: " + saved_time_text(saved["updated_at"]),
         "success" if store else "info")
    return True


def open_room(store: GitHubVault | None = None) -> None:
    if not require_session():
        return
    ss = st.session_state
    choice = ss.get("room_choice", "")
    if choice == "Choose a room":
        return
    value = ss.get("other_room", "") if choice == "Other room" else choice
    try:
        room = normalize_room(value)
    except ValidationError as exc:
        note(str(exc), "error")
        return
    old_room = ss.get("current_room")
    if room == old_room:
        ss["room_choice"] = room
        return
    if not autosave_before_room_change(store):
        ss["room_choice"] = old_room or "Choose a room"
        return
    ss["current_room"] = room
    ss["room_choice"] = room
    drafts = ss.setdefault("drafts", {})
    if room not in drafts:
        saved = ss["vault"]["rooms"].get(room)
        ss.setdefault("base_sheets", {})[room] = deepcopy(saved)
        set_editor(room, saved if saved else new_sheet(room))
    else:
        discard_editor_widget_values()
        ss["paste"] = ""
        ss.pop("import_result", None)
        ss["handoff_tab"] = "Preview / print"
        ss["handoff_active_tab"] = "Preview / print"


def room_changed(store: GitHubVault | None = None) -> None:
    if not require_session():
        return
    ss = st.session_state
    if ss.get("room_choice") in ("Choose a room", "Other room"):
        # Selecting Other hides the current editor too, so save before that.
        if not autosave_before_room_change(store):
            ss["room_choice"] = ss.get("current_room", "Choose a room")
        return
    open_room(store)


def update_field(room: str, section: str, key: str) -> None:
    if require_session() and room == st.session_state.get("current_room") and key in st.session_state:
        st.session_state["drafts"][room]["fields"][section] = st.session_state[key]


def load_neuro_sample() -> None:
    if require_session():
        st.session_state["paste"] = (ROOT / "examples" / "synthetic_neuro_weight.txt").read_text(encoding="utf-8")
        st.session_state.pop("import_result", None)


def load_compact_sample() -> None:
    if require_session():
        st.session_state["paste"] = (ROOT / "examples" / "synthetic_compact_pn.txt").read_text(encoding="utf-8")
        st.session_state.pop("import_result", None)


def load_observed_sample() -> None:
    if require_session():
        st.session_state["paste"] = (ROOT / "examples" / "synthetic_observed_vt.txt").read_text(encoding="utf-8")
        st.session_state.pop("import_result", None)


def neuro_row_change(room: str, source: str, index: int, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    candidate = deepcopy(ss["drafts"][room]["neuro_vitals"])
    if source not in candidate or not 0 <= index < len(candidate[source]) or field not in ("value", "include"):
        return
    old = candidate[source][index][field]
    candidate[source][index][field] = ss[key]
    try:
        validate_neuro(candidate)
        ss["drafts"][room]["neuro_vitals"] = candidate
        if source == "y":
            ss["drafts"][room]["import_warnings"].pop("y", None)
    except ValueError as exc:
        ss[key] = old
        note(str(exc), "error")


def nutrition_change(room: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    current = ss["drafts"][room]["nutrition"]
    if current is None or field not in ("weight", "z_score", "include"):
        return
    candidate = deepcopy(current)
    candidate[field] = ss[key].strip() if isinstance(ss[key], str) else ss[key]
    try:
        validate_nutrition(candidate)
        ss["drafts"][room]["nutrition"] = candidate
    except ValueError as exc:
        ss[key] = current[field]
        note(str(exc), "error")


def anthropometric_change(room: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room") or field not in ANTHRO_FIELDS:
        return
    ss = st.session_state
    previous = deepcopy(ss["drafts"][room].get("anthropometrics", empty_anthropometrics()))
    try:
        value = clean_field(field, ss[key])
        data = dict(previous)
        data[field] = value
        validate_anthropometrics(data)
        ss["drafts"][room]["anthropometrics"] = data
        ss[key] = value
    except ValueError as exc:
        ss[key] = previous[field]
        note(str(exc), "error")


def demographic_change(room: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    validators = {"dosing_weight": validate_dosing_weight, "admission_date": validate_admission_date}
    if field not in validators:
        return
    ss = st.session_state
    old = ss["drafts"][room][field]
    value = ss[key].strip()
    try:
        validators[field](value)
        ss["drafts"][room][field] = value
    except ValueError as exc:
        ss[key] = old
        note(str(exc), "error")


def load_demographics_sample() -> None:
    if require_session():
        st.session_state["paste"] = (ROOT / "examples" / "synthetic_demographics_labs.txt").read_text(encoding="utf-8")
        st.session_state.pop("import_result", None)



def load_viral_sample() -> None:
    if require_session():
        st.session_state["paste"] = (ROOT / "examples" / "synthetic_viral_positive.txt").read_text(encoding="utf-8")
        st.session_state.pop("import_result", None)


def viral_row_change(room: str, row_id: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    if field not in ("name", "result", "date", "include"):
        return
    ss = st.session_state
    candidate = deepcopy(ss["drafts"][room]["viral_panel"])
    row = next((r for r in candidate["rows"] if r["id"] == row_id), None)
    if row is None:
        return
    old = row[field]
    value = ss[key]
    row[field] = value.strip() if isinstance(value, str) else value
    try:
        validate_viral_panel(candidate)
        ss["drafts"][room]["viral_panel"] = candidate
    except ValueError as exc:
        ss[key] = old
        note(str(exc), "error")


def viral_editor(sheet: dict) -> None:
    st.subheader("Rapid Viral Panel")
    data = sheet["viral_panel"]
    summary = viral_text(data)
    if summary:
        st.markdown('<div style="white-space:pre-wrap">' + viral_markup(data) + '</div>', unsafe_allow_html=True)
    else:
        st.caption("No positive viral results selected for the handoff.")
    st.caption("Only explicit Detected / Positive results print below a separator in the patient column. Source dates stay here, not on the compact summary. A newer negative or unresolved result does not reuse an older positive.")
    if not data["rows"]:
        st.caption("Paste a paired O block headed Respiratory Viral Panel to add results.")
        return
    with st.expander("Edit viral results and display names (" + str(len(data["rows"])) + ")"):
        st.caption("The code-to-name aliases are editable labels. HUMRHINENRNA is displayed as Rhinovirus/enterovirus, without splitting the combined target. Unfamiliar codes remain unchanged.")
        for row in data["rows"]:
            st.text(row["component"] + " | " + row["result"] + " | " + row["date"])
            for field, label in (("name", "Display name"), ("result", "Source result"), ("date", "Source date / optional time"), ("include", "Include if positive")):
                key = "viral_" + row["id"] + "_" + field
                if key not in st.session_state:
                    st.session_state[key] = row[field]
                kwargs = dict(key=key, on_change=viral_row_change, args=(sheet["room"], row["id"], field, key))
                if field == "include":
                    st.checkbox(label, **kwargs)
                else:
                    st.text_input(label, max_chars={"name": 200, "result": 500, "date": 80}[field], **kwargs)

def sbs_row_change(room: str, index: int, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    candidate = deepcopy(ss["drafts"][room].get("sbs_observations"))
    if not candidate or field not in ("value", "recorded_at", "include") or not 0 <= index < len(candidate["readings"]):
        return
    previous = candidate["readings"][index][field]
    candidate["readings"][index][field] = ss[key].strip() if isinstance(ss[key], str) else ss[key]
    from sbs import validate_sbs
    try:
        validate_sbs(candidate)
        ss["drafts"][room]["sbs_observations"] = candidate
        ss["drafts"][room]["import_warnings"].pop("k", None)
    except ValueError as exc:
        ss[key] = previous
        note(str(exc), "error")


def sbs_add_reading(room: str, score_key: str, time_key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    from sbs import score, validate_sbs
    from labs import date_parts
    ss = st.session_state
    try:
        value = score(str(ss.get(score_key, "")))
        recorded_at = str(ss.get(time_key, "")).strip()
        _, has_time = date_parts(recorded_at)
        if not has_time:
            raise ValueError("Enter the recording date AND time from Epic, not the time of this upload.")
        candidate = deepcopy(ss["drafts"][room].get("sbs_observations") or {"readings": [], "notes": []})
        candidate["readings"].append({"value": value, "recorded_at": recorded_at, "include": True})
        # An explicitly entered measured observation supersedes a prefiltered
        # snapshot. Its actual source time, not a report time, controls expiry.
        candidate.pop("source_window", None)
        validate_sbs(candidate)
        ss["drafts"][room]["sbs_observations"] = candidate
        ss["drafts"][room]["import_warnings"].pop("k", None)
        ss[score_key] = ""
        ss[time_key] = ""
    except ValueError as exc:
        note(str(exc), "error")


def sbs_window_change(room: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    candidate = deepcopy(ss["drafts"][room].get("sbs_observations"))
    if not candidate or "source_window" not in candidate or field not in ("value", "include"):
        return
    from sbs import score, validate_sbs
    previous = candidate["source_window"][field]
    try:
        value = ss[key]
        if field == "value":
            value = str(value).strip()
            value = "" if not value or value.casefold() == "none" else score(value)
        candidate["source_window"][field] = value
        validate_sbs(candidate)
        ss["drafts"][room]["sbs_observations"] = candidate
        ss["drafts"][room]["import_warnings"].pop("k", None)
    except ValueError as exc:
        ss[key] = previous
        note(str(exc), "error")


def sbs_history_change(room: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    candidate = deepcopy(ss["drafts"][room].get("sbs_observations"))
    if not candidate or "last_available" not in candidate or field not in ("value", "recorded_at", "include"):
        return
    from sbs import score, validate_sbs
    previous = candidate["last_available"][field]
    try:
        value = ss[key]
        if field == "value":
            value = score(str(value))
        elif field == "recorded_at":
            value = str(value).strip()
        candidate["last_available"][field] = value
        validate_sbs(candidate)
        ss["drafts"][room]["sbs_observations"] = candidate
    except ValueError as exc:
        ss[key] = previous
        note(str(exc), "error")


def sbs_editor(sheet: dict) -> None:
    from sbs import latest_sbs, sbs_display_rows, recognized_vent_mode
    data = sheet.get("sbs_observations")
    latest = latest_sbs(data) if "k" not in sheet["import_warnings"] else None
    window = (data or {}).get("source_window")
    rendered = sbs_display_rows(sheet)
    st.caption((rendered[0]["label"] + ": " + rendered[0]["value"]) if rendered else "No eligible SBS is displayed, or its import needs review.")
    if window is not None:
        st.caption("24-hour snapshot time: " + window["reported_as_of"] + ". This is not an individual observation's recording time.")
    elif latest:
        st.caption("Recorded at: " + latest["recorded_at"])
    with st.expander("Observed SBS / recording time"):
        st.caption("Recent SBS takes priority. When no recent value is available, Last SBS Ever can display only with a recognized documented ventilator mode. It is labelled last available. Explicit targets keep a target label.")
        mode = recognized_vent_mode(sheet)
        st.caption("Fallback mode: " + mode if mode else "No qualifying ventilator mode for historical SBS fallback.")
        if window is not None:
            for field, label in (("value", "SBS Last 24 Hours value (blank allows mode-gated fallback)"), ("include", "Include the imported 24-hour SBS field")):
                key = "sbs_window_" + sheet["id"] + "_" + field
                if key not in st.session_state:
                    st.session_state[key] = window[field]
                opts = dict(key=key, on_change=sbs_window_change, args=(sheet["room"], field, key))
                if field == "include":
                    st.checkbox(label, **opts)
                elif not data.get("readings"):
                    st.text_input(label, max_chars=10, **opts)
            if window["kind"] == "target":
                st.caption("Epic labelled this value as a target. It prints as SBS target, not as an observed score.")
        historical = (data or {}).get("last_available")
        if historical is not None:
            st.caption("Last SBS Ever is a target." if historical["kind"] == "target" else "Last SBS Ever is a recorded score.")
            for field, label in (("value", "Last SBS Ever value"), ("recorded_at", "Historical recording date / time (if supplied)"), ("include", "Allow this last-available value when ventilator mode qualifies")):
                key = "sbs_history_" + sheet["id"] + "_" + field
                if key not in st.session_state:
                    st.session_state[key] = historical[field]
                opts = dict(key=key, on_change=sbs_history_change, args=(sheet["room"], field, key))
                if field == "include":
                    st.checkbox(label, **opts)
                else:
                    st.text_input(label, max_chars=80, **opts)
        for message in (data or {}).get("notes", []):
            st.caption(message)
        for index, row in enumerate((data or {}).get("readings", [])):
            for field, label in (("value", "Recorded SBS"), ("recorded_at", "Recorded date / time"), ("include", "Include this observed SBS")):
                key = "sbs_" + sheet["id"] + "_" + str(index) + "_" + field
                if key not in st.session_state:
                    st.session_state[key] = row[field]
                opts = dict(key=key, on_change=sbs_row_change, args=(sheet["room"], index, field, key))
                if field == "include":
                    st.checkbox(label, **opts)
                else:
                    st.text_input(label, max_chars=80, **opts)
        score_key, time_key = "sbs_add_score_" + sheet["id"], "sbs_add_time_" + sheet["id"]
        st.text_input("Add observed SBS", key=score_key, max_chars=10)
        st.text_input("Source date and time (MM/DD/YYYY HH:MM)", key=time_key, max_chars=80)
        st.button("Add SBS reading", key="sbs_add_" + sheet["id"], on_click=sbs_add_reading,
                  args=(sheet["room"], score_key, time_key))


def neuro_weight_editor(sheet: dict) -> None:
    st.subheader("Neurologic observations")
    st.caption("K: recent SBS first, last available only with a recognized ventilator mode. Y: CAPD, L: WAT-1, M: ICP/CPP. Targets remain editable but do not print as observed scores. CAPD always prints between SBS and WAT-1. None means no available score, not a zero score. ICP/CPP show the documented range and Last reading in brackets. Range and Last fields can be edited separately.")
    sbs_editor(sheet)
    present = False
    for source, title in NEURO_SECTIONS.items():
        if source == "y" and not sheet["neuro_vitals"].get("y"):
            st.caption("CAPD: None. Paste a Y section to add the recorded score.")
        for index, row in enumerate(sheet["neuro_vitals"].get(source, [])):
            present = True
            key = "neuro_" + sheet["id"] + "_" + source + "_" + str(index)
            if key not in st.session_state:
                st.session_state[key] = row["value"]
            st.text_input(row["label"], key=key, max_chars=1500, on_change=neuro_row_change,
                          args=(sheet["room"], source, index, "value", key))
            ikey = key + "_include"
            if ikey not in st.session_state:
                st.session_state[ikey] = row["include"]
            st.checkbox("Include " + row["label"], key=ikey, on_change=neuro_row_change,
                        args=(sheet["room"], source, index, "include", ikey))
    if not present:
        st.caption("Paste K, Y, L and/or M to add recorded neurologic observations.")
    st.subheader("Demographics / Weight")
    st.caption("Admission is shown in the patient column. Below Diagnoses: weight, Z-score when supplied, then dosing weight. A blank dosing-weight field prints Dosing weight: none. Clearing admission omits that date.")
    field = "admission_date"
    key = "demo_" + sheet["id"] + "_" + field
    if key not in st.session_state:
        st.session_state[key] = sheet[field]
    st.text_input("Date of admission", key=key, max_chars=32,
                  on_change=demographic_change, args=(sheet["room"], field, key))
    attributes = sheet.get("anthropometrics", empty_anthropometrics())
    with st.expander("Age, sex, BMI, height and BSA", expanded=True):
        st.caption("Age and sex print directly below the room. The combined Epic line Age: 6 y.o. Sex: female is accepted in A, I, or N. For BMI percentile, supply age AT THE BMI MEASUREMENT in months or years and months, plus growth-chart sex. Only explicit Age: and Sex: labels are read, not clinical diagnoses or weight-chart footnotes. BMI and BMI percentile are hidden from handoff output below age 2, or until age is documented. Imported values stay editable.")
        for field, label in (("age", "Age (for example 5 years 2 months)"), ("sex", "Sex for BMI growth chart (Male / Female, or blank)"), ("bmi", "Recorded BMI (kg/m²)"), ("height", "Recorded Height (for example 100 cm)"), ("bsa", "Recorded BSA (for example 0.65 m²)")):
            key = "anthro_" + sheet["id"] + "_" + field
            if key not in st.session_state:
                st.session_state[key] = attributes[field]
            st.text_input(label, key=key, max_chars=100, on_change=anthropometric_change,
                          args=(sheet["room"], field, key))
        summary, reason = bmi_percentile_summary(attributes)
        if summary:
            st.text("BMI percentile: " + summary)
            st.caption(reason)
    data = sheet["nutrition"]
    if data is None:
        st.caption("Paste the I block to add a measured weight. Dosing weight is kept separately.")
    else:
        for field, label in (("weight", "Recorded measured weight, with unit"), ("z_score", "Recorded Z-score"), ("include", "Include measured weight and Z-score")):
            key = "weight_" + sheet["id"] + "_" + field
            if key not in st.session_state:
                st.session_state[key] = data[field]
            kwargs = dict(key=key, on_change=nutrition_change, args=(sheet["room"], field, key))
            if field == "include":
                st.checkbox(label, **kwargs)
            else:
                st.text_input(label, max_chars=80 if field == "weight" else 40, **kwargs)
    field = "dosing_weight"
    key = "demo_" + sheet["id"] + "_" + field
    if key not in st.session_state:
        st.session_state[key] = sheet[field]
    st.text_input("Dosing weight, with unit (blank prints none)", key=key, max_chars=80,
                  on_change=demographic_change, args=(sheet["room"], field, key))


def load_taper_sample() -> None:
    if require_session():
        st.session_state["paste"] = (ROOT / "examples" / "synthetic_medication_taper.txt").read_text(encoding="utf-8")
        st.session_state.pop("import_result", None)


def load_labs_sample() -> None:
    if require_session():
        st.session_state["paste"] = (ROOT / "examples" / "synthetic_labs_vitals.txt").read_text(encoding="utf-8")
        st.session_state.pop("import_result", None)


def change_visibility_rule(name: str, hidden: bool, match: str, store: GitHubVault | None) -> None:
    if not require_session():
        return
    ss = st.session_state
    candidate = deepcopy(ss["vault"])
    try:
        candidate["settings"]["medication_visibility"] = set_visibility_rule(candidate["settings"]["medication_visibility"], name, hidden, match)
        commit(candidate, store)
        reapply_open_mappings()
        note(("Medication hidden from exports and kept for restoration." if hidden else "Medication restored to exports.") + (" Rule saved to shared storage." if store else " Session-only mode."), "success")
    except (ValueError, StorageError) as exc:
        note(str(exc) + " The visibility rule was not changed.", "error")


def hide_medication(room: str, row_id: str, hidden: bool, store: GitHubVault | None) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    row = next((r for r in st.session_state["drafts"][room]["medications"] if r["id"] == row_id), None)
    if row:
        settings = st.session_state["vault"]["settings"]
        if not hidden and (matching_target(row, settings) == "system:Ignore"
                           or explicit_ignore_mapping(row["name"], settings["medication_mappings"])):
            candidate = deepcopy(st.session_state["vault"])
            try:
                candidate["settings"] = set_category_rule(candidate["settings"], row["name"], "system:Other Medications", "exact", row["route"], row["frequency"])
                candidate["settings"]["medication_visibility"] = set_visibility_rule(candidate["settings"]["medication_visibility"], row["name"], False, "exact")
                commit(candidate, store)
                reapply_open_mappings()
                note("Medication restored to handoff. Choose its category if needed." + (" Rule saved to shared storage." if store else " Session-only mode."), "success")
            except (ValueError, StorageError) as exc:
                note(str(exc) + " The medication was not restored.", "error")
            return
        change_visibility_rule(row["name"], hidden, "exact", store)


def visibility_admin(store: GitHubVault | None) -> None:
    st.subheader("Hidden medication rules")
    rules = st.session_state["vault"]["settings"]["medication_visibility"]
    st.caption("Hide/restore choices are remembered independently of system mappings. Full retained entries remain in their handoffs. No open handoff is needed to restore a rule here.")
    hidden = [r for r in rules if r["hidden"]]
    if not hidden:
        st.caption("No hidden medication rules.")
    for i, rule in enumerate(hidden):
        st.text(rule["name"] + " [" + rule["match"] + "]")
        st.button("Restore this medication", key="restore_rule_" + str(i), on_click=admin_visibility_rule,
                  args=(rule["name"], False, rule["match"], store))
    with st.expander("Previously restored rules"):
        for i, rule in enumerate(rules):
            if not rule["hidden"]:
                st.text(rule["name"] + " [" + rule["match"] + "]")
                st.button("Hide again", key="rehide_rule_" + str(i), on_click=admin_visibility_rule,
                          args=(rule["name"], True, rule["match"], store))



def load_cultures_sample() -> None:
    if require_session():
        st.session_state["paste"] = (ROOT / "examples" / "synthetic_cultures_ads.txt").read_text(encoding="utf-8")
        st.session_state.pop("import_result", None)


def culture_row_change(room: str, row_id: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    snapshot = ss["drafts"][room]["cultures"]
    candidate = deepcopy(snapshot)
    row = next((r for r in candidate["rows"] if r["id"] == row_id), None)
    if row is None or field not in ("date", "specimen", "organisms", "include"):
        return
    previous = row[field]
    row[field] = ([x.strip() for x in ss[key].splitlines() if x.strip()]
                  if field == "organisms" else ss[key])
    try:
        validate_cultures(candidate)
        ss["drafts"][room]["cultures"] = candidate
    except ValueError as exc:
        ss[key] = "\n".join(previous) if field == "organisms" else previous
        note(str(exc), "error")


def cultures_editor(sheet: dict) -> None:
    st.subheader("Cultures to Infectious Disease")
    st.caption("Prints the two newest collection-date/specimen groups per category: blood, respiratory, urine, and other sites. Same date and site rows are combined for display only, with all their distinct organisms and statuses. No sensitivity columns are stored or printed.")
    st.caption("Collection IDs are not supplied. A displayed group is not proof of one culture. Same-date ties keep source order. Unspecified aspirates stay under their own site rather than being assumed respiratory.")
    data = sheet["cultures"]
    text = cultures_text(data)
    if text:
        st.markdown('<div style="white-space:pre-wrap">' + culture_markup(data) + '</div>', unsafe_allow_html=True)
    else:
        st.caption("No culture results selected. Paste an F block to import them.")
    for message in data["notes"]:
        st.caption(message)
    selected = {key for group in compact_groups(data) for key in group["row_ids"]}
    with st.expander("Edit retained culture rows (" + str(len(data["rows"])) + ")"):
        for number, row in enumerate(data["rows"], 1):
            status = "shown in compact output" if row["id"] in selected else "older / excluded from compact output"
            st.text(str(number) + ". " + row["date"] + " | " + row["specimen"] + " | " + status)
            st.caption("Category: " + category_for(row["specimen"]))
            for field, label in (("date", "Collection date / optional time"), ("specimen", "Sample location"),
                                 ("organisms", "Organisms / results, one per line"), ("include", "Include in newest-result selection")):
                key = "culture_" + row["id"] + "_" + field
                if key not in st.session_state:
                    st.session_state[key] = "\n".join(row[field]) if field == "organisms" else row[field]
                kwargs = dict(key=key, on_change=culture_row_change, args=(sheet["room"], row["id"], field, key))
                if field == "include":
                    st.checkbox(label, **kwargs)
                elif field == "organisms":
                    st.text_area(label, height=90, max_chars=20000, **kwargs)
                else:
                    st.text_input(label, max_chars=80 if field == "date" else 500, **kwargs)


def lab_row_change(room: str, row_id: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    snapshot = ss["drafts"][room]["labs"]
    candidate = deepcopy(snapshot)
    row = next((r for r in candidate["rows"] if r["id"] == row_id), None)
    if row is None:
        return
    previous = row[field]
    row[field] = ss[key]
    try:
        validate_labs(candidate)
        ss["drafts"][room]["labs"] = candidate
    except ValueError as exc:
        ss[key] = previous
        note(str(exc), "error")


def vital_row_change(room: str, index: int, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    candidate = deepcopy(ss["drafts"][room]["vitals"])
    previous = candidate[index][field]
    candidate[index][field] = ss[key]
    try:
        validate_vitals(candidate)
        ss["drafts"][room]["vitals"] = candidate
    except ValueError as exc:
        ss[key] = previous
        note(str(exc), "error")


def cbc_edit(room: str, row_id: str, field: str, key: str, column: int = -1) -> None:
    if not require_session():
        return
    ss = st.session_state
    if room != ss.get("current_room"):
        return
    data = ss["drafts"][room]["cbc"]
    if data is None:
        return
    candidate = deepcopy(data)
    targets = [row for row in candidate["rows"] if row["column"] == column] if field == "date" else [row for row in candidate["rows"] if row["id"] == row_id]
    if not targets:
        return
    previous = targets[0][field]
    value = ss[key].strip() if isinstance(ss[key], str) else ss[key]
    for row in targets:
        row[field] = value
    try:
        validate_cbc(candidate)
        ss["drafts"][room]["cbc"] = candidate
    except ValueError as exc:
        ss[key] = previous
        note(str(exc), "error")


def cbc_editor(sheet: dict) -> None:
    st.subheader("CBC / absolute counts")
    data = sheet["cbc"]
    st.caption("Q keeps each CBC column together. Standard hemoglobin is preferred over ISTAT across the supplied snapshot. ANC and ALC are the latest absolute counts across automatic/manual rows, with their own dates. No percentages are converted.")
    if data is None:
        st.caption("No Q snapshot yet. Earlier G-block CBC rows remain available until a Q block replaces their display.")
        return
    if not data["rows"]:
        st.caption("The included Q section contains no CBC results. Older G-block CBC results are not substituted.")
        return
    for issue in data.get("notes", []):
        if issue.startswith("CBC"):
            st.caption(issue)
    for issue in cbc_selection_issues(data):
        st.caption(issue)
    with st.expander("Edit retained CBC results (" + str(len(data["rows"])) + ")"):
        columns = list(dict.fromkeys(row["column"] for row in data["rows"]))
        for column in columns:
            rows = [row for row in data["rows"] if row["column"] == column]
            st.text("CBC source column " + str(column + 1))
            key = "cbc_date_" + sheet["id"] + "_" + str(column)
            if key not in st.session_state:
                st.session_state[key] = rows[0]["date"]
            st.text_input("Collection date / time (whole column)", key=key, max_chars=80,
                          on_change=cbc_edit, args=(sheet["room"], "", "date", key, column))
            for row in rows:
                st.text(row["component"] + " | " + row["value"] + " " + row["unit"])
                if "|" in row["value"]:
                    st.warning("Multiple source results in this cell. It is excluded from the CBC tree. Replace it with a verified single result before including it.")
                for field, label in (("value", "Recorded CBC result"), ("unit", "Source unit"), ("include", "Include result in CBC selection")):
                    key = "cbc_" + row["id"] + "_" + field
                    if key not in st.session_state:
                        st.session_state[key] = row[field]
                    kwargs = dict(key=key, on_change=cbc_edit, args=(sheet["room"], row["id"], field, key))
                    if field == "include":
                        st.checkbox(label, **kwargs)
                    else:
                        st.text_input(label, max_chars=100 if field == "value" else 50, **kwargs)


def gas_edit(room: str, sample_id: str, label: str, field: str, key: str) -> None:
    if not require_session():
        return
    ss = st.session_state
    if room != ss.get("current_room"):
        return
    data = ss["drafts"][room]["blood_gas"]
    if data is None:
        return
    candidate = deepcopy(data)
    sample = next((row for row in candidate["samples"] if row["id"] == sample_id), None)
    if sample is None:
        return
    target = sample["values"][label] if label else sample
    old = target[field]
    target[field] = ss[key].strip() if isinstance(ss[key], str) else ss[key]
    try:
        validate_gases(candidate)
        ss["drafts"][room]["blood_gas"] = candidate
    except ValueError as exc:
        ss[key] = old
        note(str(exc), "error")


def gas_editor(sheet: dict) -> None:
    st.subheader("Latest blood gas")
    data = sheet["blood_gas"]
    selection_data = legacy_gases(laboratory_data(sheet)) if data is None else data
    sample, issues = latest_sample(selection_data)
    if sample:
        st.text(gas_summary(selection_data))
    else:
        st.caption("No gas results selected. Paste the paired P block to add the latest gas.")
    if data is None and sample:
        st.caption("This is a legacy G-block result. A date-only listing cannot establish a common draw or exact time. Paste P for timed column-based selection.")
    for issue in issues:
        st.caption(issue)
    if data is None:
        return
    st.caption("The newest included specimen/column prints once. Empty and hidden cells are not backfilled. Older columns stay available here but do not print.")
    with st.expander("Review retained gas columns (" + str(len(data["samples"])) + ")"):
        for sample in data["samples"]:
            prefix = "gas_" + sample["id"] + "_"
            st.text(sample["specimen"] + " | " + sample["date"])
            for field, label in (("date", "Gas collection date / time"), ("include", "Include this gas in latest selection")):
                key = prefix + field
                if key not in st.session_state:
                    st.session_state[key] = sample[field]
                kwargs = dict(key=key, on_change=gas_edit, args=(sheet["room"], sample["id"], "", field, key))
                if field == "include":
                    st.checkbox(label, **kwargs)
                else:
                    st.text_input(label, max_chars=80, **kwargs)
            for index, label in enumerate(GAS_FIELDS):
                if label not in sample["values"]:
                    continue
                for field in ("value", "unit"):
                    key = prefix + str(index) + "_" + field
                    if key not in st.session_state:
                        st.session_state[key] = sample["values"][label][field]
                    st.text_input(label + (" result" if field == "value" else " source unit"), key=key,
                                  max_chars=100 if field == "value" else 50,
                                  on_change=gas_edit, args=(sheet["room"], sample["id"], label, field, key))


def labs_vitals_editor(sheet: dict) -> None:
    import streamlit.components.v1 as components
    neuro_weight_editor(sheet)
    viral_editor(sheet)
    st.subheader("Laboratory results")
    st.caption("Q supplies the two latest CBC columns. BMP and older G-only CBCs retain per-component selection. Other tests show the latest result per component. Only one latest gas is printed, labeled VEN, ART or CAP. The P table keeps specimen and column values together. Dates and source flags are preserved. No collection times or same-draw groupings are invented.")
    components.html('<style>.labcards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}.labcard{width:100%;border:1px solid #aaa}.labnote{font:13px sans-serif;margin:8px 0}.lab-summary{font:14px/1.3 sans-serif;overflow-wrap:anywhere;margin:3px 0}.lab-full{grid-column:1/-1}</style>' + laboratory_html(laboratory_data(sheet), blood_gas=sheet["blood_gas"], cbc=sheet["cbc"]), height=490, scrolling=True)
    if theophylline_summary(sheet):
        st.text("Respiratory: " + theophylline_summary(sheet))
    if cardiac_labs_summary(sheet):
        st.text("Cardiovascular: " + cardiac_labs_summary(sheet))
        st.caption("Lactate shows the earliest and latest usable results in the rolling 24-hour display window. The printed result omits the source code. All original codes, dates, flags and units remain in the editor. NT-proBNP shows the latest from all supplied dates. The original dates remain visible.")
    st.caption("Cardiovascular shows the latest METHB as Methemoglobin and O2SATV as SvO2 within 24 hours. Include collection times to use results from yesterday. A date-only result is included only when the start of that Eastern date is within 24 hours.")
    if id_summary(sheet):
        st.text("Infectious Disease:\n" + id_summary(sheet))
    st.caption("Glucose is in the BMP tree. Mg and phosphorus are below it. Albumin stays in Hepatic. Coagulation, including Anti-Xa (HEPLMW), is immediately below Hepatic in the lab results. CRP and procalcitonin (PROCAL) remain in ID below temperature. The latest eligible THEOPH result prints directly below a visible aminophylline order, once. Without a visible aminophylline order it remains in Respiratory.")
    with st.expander("Edit retained laboratory rows (" + str(len(sheet["labs"]["rows"])) + ")"):
        for row in sheet["labs"]["rows"]:
            st.text(row["component"] + " | " + row["value"] + " | " + row["date"])
            for field, label in (("value", "Result"), ("date", "Source date / optional time"), ("include", "Include in lab selection")):
                key = "lab_" + row["id"] + "_" + field
                if key not in st.session_state:
                    st.session_state[key] = row[field]
                kwargs = dict(key=key, on_change=lab_row_change, args=(sheet["room"], row["id"], field, key))
                if field == "include":
                    st.checkbox(label, **kwargs)
                else:
                    st.text_input(label, max_chars=1000 if field == "value" else 80, **kwargs)
    cbc_editor(sheet)
    gas_editor(sheet)
    st.subheader("Vital signs")
    if not sheet["vitals"]:
        st.caption("Paste an E block to add vital signs.")
    for index, row in enumerate(sheet["vitals"]):
        st.text(row["label"] + " -> " + row["section"])
        key = "vital_" + sheet["id"] + "_" + str(index)
        if key not in st.session_state:
            st.session_state[key] = row["value"]
        st.text_input(row["label"], key=key, max_chars=1500, on_change=vital_row_change,
                      args=(sheet["room"], index, "value", key))
        ikey = key + "_include"
        if ikey not in st.session_state:
            st.session_state[ikey] = row["include"]
        st.checkbox("Include " + row["label"], key=ikey, on_change=vital_row_change,
                    args=(sheet["room"], index, "include", ikey))


def load_sample() -> None:
    if require_session():
        st.session_state["paste"] = (ROOT / "examples" / "synthetic_smartphrase.txt").read_text(encoding="utf-8")
        st.session_state.pop("import_result", None)



def load_niv_sample() -> None:
    if require_session():
        st.session_state["paste"] = (ROOT / "examples" / "synthetic_nc_smartphrase.txt").read_text(encoding="utf-8")
        st.session_state.pop("import_result", None)


def clear_paste() -> None:
    if require_session():
        st.session_state["paste"] = ""
        st.session_state.pop("import_result", None)


def _finish_handoff_import(room: str, result, store: GitHubVault | None) -> None:
    """Apply the normal section update and its import diagnostics."""
    ss = st.session_state
    ss.pop("airway_update_pending", None)
    ss.pop("last_error_reference", None)
    if result.sheet is not None:
        set_editor(room, result.sheet)
    ss["import_result"] = {"room": room, "errors": result.errors,
                           "notices": result.notices, "imported": result.imported}
    remember_import(ss, ss["drafts"][room], ss["import_result"])
    if result.diagnostics:
        record = new_error_event(result.diagnostics)
        ss.setdefault("pending_error_events", {})[record["id"]] = record
        ss["last_error_reference"] = record["id"]
        ss["error_log_saved"] = False
        send_pending_errors(store)


def create_handoff(store: GitHubVault | None = None) -> None:
    if not require_session():
        return
    ss = st.session_state
    room = ss.get("current_room")
    if not room:
        note("Select a room first.", "error")
        return
    # Capture just-blurred editor values before applying supplied sections.
    # Manual fields absent from the SmartPhrase keep their normal sheet values.
    try:
        before = editor_snapshot(room)
        result = import_sections(before, ss.get("paste", ""), ss["vault"]["settings"])
    except (ValueError, ValidationError) as exc:
        note("The handoff was not updated. " + str(exc), "error")
        return
    _finish_handoff_import(room, result, store)


def start_new_patient() -> None:
    if not require_session():
        return
    ss = st.session_state
    room = ss["current_room"]
    ss.setdefault("base_sheets", {})[room] = deepcopy(ss["vault"]["rooms"].get(room))
    set_editor(room, new_sheet(room))
    note("Blank handoff opened. Save to replace this room's saved sheet.")


def load_saved_into_editor() -> None:
    if not require_session():
        return
    ss = st.session_state
    room = ss["current_room"]
    saved = ss["vault"]["rooms"].get(room)
    ss.setdefault("base_sheets", {})[room] = deepcopy(saved)
    set_editor(room, saved if saved else new_sheet(room))
    note("Saved handoff loaded.")


def commit(candidate: dict, store: GitHubVault | None) -> None:
    validate_vault(candidate)
    if store is not None:
        new_sha = store.save(candidate, st.session_state.get("vault_sha"))
        st.session_state["vault_sha"] = new_sha
    st.session_state["vault"] = candidate


def save_rooms(store: GitHubVault | None, rooms: list[str]) -> bool:
    if not require_session():
        return False
    ss = st.session_state
    if not rooms:
        note("There are no open drafts to save.")
        return False
    ss.pop("airway_update_pending", None)  # Obsolete pre-6.62 prompt state.
    for room in rooms:
        if ss.get("base_sheets", {}).get(room) != ss["vault"]["rooms"].get(room):
            note("A saved room changed after its draft was opened. Reload that saved handoff and reapply your edits. No rooms were saved.", "error")
            return False
    try:
        candidate = deepcopy(ss["vault"])
        for room in rooms:
            sheet = editor_snapshot(room) if room == ss.get("current_room") else ss["drafts"][room]
            candidate = save_sheet_in(candidate, sheet)
        commit(candidate, store)
    except (StorageError, ValidationError, ValueError) as exc:
        note(str(exc), "error")
        return False
    except Exception:
        note("Save was not confirmed. Your edits are kept. Check the connection and retry.", "error")
        return False
    for room in rooms:
        saved = deepcopy(candidate["rooms"][room])
        ss["drafts"][room] = saved
        ss.setdefault("base_sheets", {})[room] = deepcopy(saved)
    message = ("Handoffs saved to shared storage." if store else
               "Saved in this session only. Shared storage is not enabled.")
    stamp = latest_saved_time({room: candidate["rooms"][room] for room in rooms})
    note(message + (" Last saved: " + stamp if stamp else ""), "success" if store else "info")

    return True


def save_room(store: GitHubVault | None) -> None:
    room = st.session_state.get("current_room")
    if room:
        save_rooms(store, [room])


def save_all_rooms(store: GitHubVault | None) -> None:
    save_rooms(store, list(st.session_state.get("drafts", {})))


def reapply_open_mappings() -> None:
    ss = st.session_state
    rules = ss["vault"]["settings"]["medication_mappings"]
    for sheet in ss.get("drafts", {}).values():
        sheet["medications"] = apply_group_rules(apply_gi_rules(apply_infusion_rules(remap(sheet["medications"], rules, ss["vault"]["settings"]["medication_visibility"]), ss["vault"]["settings"]["medication_infusions"]), ss["vault"]["settings"]["medication_gi_groups"]), ss["vault"]["settings"]["medication_groups"])
        sheet["medications"] = apply_category_rules(sheet["medications"], ss["vault"]["settings"])
        refresh_empty_group_layout(sheet, ss["vault"]["settings"])
    # These callbacks run before the widgets are instantiated on the next run.
    for key in list(ss):
        if (key.startswith("med_") and key.endswith(("_section", "_infusion_mode", "_gi_mode", "_group_mode", "_category_target"))) or key.startswith(("infusion_rule_mode_", "gi_rule_mode_", "group_rule_mode_")):
            ss.pop(key, None)


def medication_category_change(room: str, row_id: str, key: str, store: GitHubVault | None = None) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    row = next((r for r in ss["drafts"][room]["medications"] if r["id"] == row_id), None)
    if row is None:
        return
    old = local_target(row, ss["vault"]["settings"])
    try:
        candidate = deepcopy(ss["vault"])
        candidate["settings"] = set_category_rule(candidate["settings"], row["name"], ss[key], "exact", row["route"], row["frequency"])
        commit(candidate, store)
        reapply_open_mappings()
        note("Medication category remembered." + (" Saved to shared storage." if store else " Session-only test mode."), "success")
    except (ValueError, StorageError) as exc:
        ss[key] = old
        note(str(exc) + " The assignment was not saved.", "error")


def medication_row_change(room: str, row_id: str, field: str, widget_key: str, store: GitHubVault | None = None) -> None:
    if not require_session():
        return
    ss = st.session_state
    if room != ss.get("current_room"):
        return
    rows = ss["drafts"][room]["medications"]
    original = next((r for r in rows if r["id"] == row_id), None)
    if original is None:
        return
    old_value = original.get(field, "auto") if field in ("infusion_mode", "gi_mode", "group_mode") else original.get(field, "unavailable" if field == "last_admin_status" else "")
    edited = deepcopy(original)
    if field in ADMIN_FIELDS:
        merge_admin_edits(edited, {field: ss[widget_key]})
    else:
        edited[field] = ss[widget_key]
    if field == "section":
        old_value = effective_section(original)
    try:
        validate_medication(edited)
        if field == "group_mode":
            candidate = deepcopy(ss["vault"])
            candidate["settings"]["medication_groups"] = set_group_rule(candidate["settings"]["medication_groups"], edited, edited["group_mode"])
            commit(candidate, store)
            reapply_open_mappings()
            note("Medication display group remembered." + (" Saved to shared storage." if store else " Session-only test mode."), "success")
        elif field == "gi_mode":
            candidate = deepcopy(ss["vault"])
            if edited["gi_mode"] not in ("auto", "other"):
                candidate["settings"]["medication_groups"] = set_group_rule(candidate["settings"]["medication_groups"], edited, "auto")
            candidate["settings"]["medication_gi_groups"] = set_gi_rule(candidate["settings"]["medication_gi_groups"], edited, edited["gi_mode"])
            commit(candidate, store)
            reapply_open_mappings()
            note("FEN/GI display choice remembered." + (" Saved to shared storage." if store else " Session-only test mode."), "success")
        elif field == "infusion_mode":
            candidate = deepcopy(ss["vault"])
            candidate["settings"]["medication_infusions"] = set_infusion_rule(
                candidate["settings"]["medication_infusions"], edited, edited["infusion_mode"])
            commit(candidate, store)
            reapply_open_mappings()
            note("Infusion display choice remembered for this formulation, route and frequency." +
                 (" Saved to shared storage." if store else " Session-only test mode."), "success")
        elif field == "section":
            rules = ss["vault"]["settings"]["medication_mappings"]
            name, match = rule_for_inline_mapping(edited["name"], rules)
            new_rules = upsert_rule(rules, name, edited["section"], match)
            candidate = deepcopy(ss["vault"])
            candidate["settings"]["medication_mappings"] = new_rules
            if edited["section"] != "FEN / GI" and group_for(original):
                candidate["settings"]["medication_gi_groups"] = set_gi_rule(candidate["settings"]["medication_gi_groups"], edited, "other")
            group = special_group(original)
            if group and edited["section"] != GROUP_SECTIONS[group]:
                candidate["settings"]["medication_groups"] = set_group_rule(candidate["settings"]["medication_groups"], edited, "other")
            if candidate != ss["vault"]:
                commit(candidate, store)  # Persist the rule, not any draft clinical text.
            reapply_open_mappings()
            ss["admin_rule_index"] = -1
            for key in ("mapping_name", "mapping_destination", "mapping_match", "mapping_original"):
                ss.pop(key, None)
            note("Medication destination remembered in Admin." + (" Saved to shared storage." if store else " Session-only test mode."), "success")
        else:
            if field in ("name", "route", "frequency"):
                edited["infusion_mode"] = infusion_mode_for(edited, ss["vault"]["settings"]["medication_infusions"])
                edited["gi_mode"] = gi_mode_for(edited, ss["vault"]["settings"]["medication_gi_groups"])
                edited["group_mode"] = group_mode_for(edited, ss["vault"]["settings"]["medication_groups"])
                ss.pop("med_draft_" + row_id + "_group_mode", None)
                ss.pop("med_draft_" + row_id + "_gi_mode", None)
                ss.pop("med_draft_" + row_id + "_section", None)
                ss.pop("med_draft_" + row_id + "_infusion_mode", None)
            if field == "name":
                edited["hidden"] = hidden_for(edited["name"], ss["vault"]["settings"]["medication_visibility"])
            # Dose edits can change heparin grouping without changing its signature.
            if field == "dose":
                ss.pop("med_draft_" + row_id + "_section", None)
            resolved = apply_category_rules([edited], ss["vault"]["settings"])[0]
            original.clear()
            original.update(resolved)
            if field in ADMIN_FIELDS:
                for peer in ADMIN_FIELDS:
                    if peer != field:
                        ss.pop("med_draft_" + row_id + "_" + peer, None)
    except (ValueError, ValidationError, StorageError) as exc:
        # Do not claim a remembered mapping or move orders after a rejected save.
        ss[widget_key] = old_value
        note(str(exc) + " The change was not saved.", "error")


def ventilation_change(room: str, label: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room") or key not in st.session_state:
        return
    ss = st.session_state
    old = ss["drafts"][room]["ventilation"]
    if old is None:
        return
    updated = deepcopy(old)
    value = ss[key].strip()
    if label == "Vent Mode":
        updated["mode"] = value
    elif value:
        updated["values"][label] = value
    else:
        updated["values"].pop(label, None)
    try:
        validate_ventilation(updated)
    except ValueError as exc:
        ss[key] = old["mode"] if label == "Vent Mode" else old["values"].get(label, "")
        note(str(exc), "error")
        return
    ss["drafts"][room]["ventilation"] = updated
    if label == "Vent Mode":
        ss["drafts"][room]["sbs_vent_mode"] = updated["mode"]


def clear_ventilation() -> None:
    if require_session():
        ss = st.session_state
        ss["drafts"][ss["current_room"]]["ventilation"] = None
        ss["drafts"][ss["current_room"]]["sbs_vent_mode"] = ""
        for key in list(ss):
            if key.startswith("vent_"):
                ss.pop(key, None)


def upgrade_existing_session() -> None:
    ss = st.session_state
    vault = ss.get("vault")
    if not vault or vault.get("schema") == SCHEMA_VERSION:
        return
    old_schema, old_settings = vault["schema"], deepcopy(vault["settings"])
    converted = upgrade_vault(vault)
    changes = {}
    for key in ("drafts", "base_sheets"):
        changes[key] = {}
        for room, sheet in ss.get(key, {}).items():
            canonical = normalize_room(room)
            if canonical in changes[key]:
                raise ValidationError("Two open room aliases conflict. Save and resolve them before upgrading.")
            previous = {"schema": old_schema, "settings": old_settings, "rooms": {room: sheet}}
            if old_schema >= 18:
                previous["reset_generation"] = vault.get("reset_generation", "")
            changes[key][canonical] = None if sheet is None else upgrade_vault(previous)["rooms"][canonical]
    ss.update(vault=converted, **changes)
    for key in ("current_room", "room_choice"):
        if ss.get(key) and ss[key] not in ("Choose a room", "Other room"):
            ss[key] = normalize_room(ss[key])
    for key in ("admin_rooms", "print_rooms", "print_room_options", "removed_room"):
        ss.pop(key, None)
    for key in ("pending", "diagnosis_preview", "medication_pending"):
        ss.pop(key, None)
    discard_editor_widget_values()

def load_config() -> tuple[dict, GitHubVault | None]:
    try:
        config = st.secrets.to_dict()
    except Exception:
        st.error("Deployment secrets have not been configured. Follow START_HERE.html and create_secrets.py. There is no default password.")
        st.stop()
    app = config.get("app", {})
    if not valid_password_hash(app.get("password_hash", "")):
        st.error("Set a valid app.password_hash in deployment secrets. Use create_secrets.py to generate it.")
        st.stop()
    app["idle_minutes"] = max(5, min(120, int(app.get("idle_minutes", 15))))
    store = None
    if app.get("github_enabled", False):
        gh = config.get("github", {})
        key = app.get("encryption_key", "")
        try:
            Fernet(key.encode("ascii"))
            store = GitHubVault(GitHubConfig(token=gh.get("token", ""), repository=gh.get("repository", ""),
                                            branch=gh.get("branch", "main"), api_base=gh.get("api_base", "https://api.github.com"),
                                            api_version=gh.get("api_version", "2022-11-28")), key)
        except (ValueError, StorageError):
            st.error("The storage or encryption-key settings are incomplete. Check deployment secrets. No archive was opened.")
            st.stop()
    return app, store


@st.fragment(run_every=30)
def idle_guard(minutes: int) -> None:
    if st.session_state.get("authenticated"):
        now = time.monotonic()
        if now - st.session_state.get("last_activity", now) > minutes * 60 or now - st.session_state.get("login_at", now) > 8 * 3600:
            clear_session()
            st.rerun()
        elif st.session_state.get("admin_unlocked") and not admin_valid(st.session_state, admin_config()):
            st.rerun()



def _retained_reset_state(previous: dict, fresh: dict) -> dict:
    """Keep edits only when the saved handoff survives the shared reset.

    Original base snapshots stay intact so a concurrent edit still conflicts.
    Unsaved handoffs without a saved base cannot restore a cleared census.
    """
    ss = st.session_state
    drafts, bases = {}, {}
    for room, draft in ss.get("drafts", {}).items():
        before = previous["rooms"].get(room)
        after = fresh["rooms"].get(room)
        base = ss.get("base_sheets", {}).get(room)
        if (before is not None and after is not None and base is not None
                and before["id"] == after["id"] == base["id"] == draft["id"]):
            drafts[room] = deepcopy(draft)
            bases[room] = deepcopy(base)
    current = ss.get("current_room")
    if current in drafts:
        drafts[current] = editor_snapshot(current)
    else:
        current = None
    return {"drafts": drafts, "base_sheets": bases, "current_room": current,
            "paste": ss.get("paste", "") if current else ""}


def _apply_reset_state(retained: dict) -> None:
    """Discard obsolete widgets/downloads after a confirmed save or reload."""
    discard_all_handoff_state()
    ss = st.session_state
    ss.update(drafts=retained["drafts"], base_sheets=retained["base_sheets"])
    if retained["current_room"]:
        ss.update(current_room=retained["current_room"],
                  room_choice=retained["current_room"], paste=retained["paste"])


def reload_archive(store: GitHubVault | None) -> bool:
    if not require_session() or store is None:
        return False
    try:
        fresh, sha = store.load()
        validate_vault(fresh)
        was_reset = census_was_reset(st.session_state["vault"], fresh)
        if was_reset:
            # Revoke stale prepared files even if an invalid editor value
            # prevents this reload from replacing the current local state.
            download_revocation().set()
            retained = _retained_reset_state(st.session_state["vault"], fresh)
        st.session_state.update(vault=fresh, vault_sha=sha)
        st.session_state.pop("daily_start_preview", None)
        if was_reset:
            _apply_reset_state(retained)
            note("The patient list changed. The archive is reloaded and older open drafts were discarded for removed patients. Edits to retained handoffs were kept.", "warning")
        else:
            note("Saved archive reloaded. Open drafts were kept.")
        return True
    except (StorageError, ValidationError, ValueError, TypeError, KeyError) as exc:
        note(str(exc), "error")
        return False


def patient_list_now() -> datetime:
    return datetime.now(timezone.utc)


def continue_patient_list() -> None:
    """Enter the workspace without writing or deleting any handoff."""
    if not require_session():
        return
    ss = st.session_state
    ss["patient_list_ready"] = True
    ss.pop("daily_start_preview", None)
    ss.setdefault("page", "Handoff")


def prepare_daily_start(store: GitHubVault | None = None) -> None:
    """Read the current archive and freeze exactly what the user will review."""
    if not require_session():
        return
    ss = st.session_state
    if ss.get("patient_list_ready"):
        return
    ss.pop("daily_start_preview", None)
    if store is not None:
        try:
            if not reload_archive(store):
                return
        except Exception:
            note("The saved patient list could not be loaded. No handoffs were changed. Try loading it again.", "error")
            return
    try:
        plan = daily_reset_plan(ss["vault"], patient_list_now())
        ss["daily_start_preview"] = {"source": deepcopy(ss["vault"]),
                                     "sha": ss.get("vault_sha"), "plan": plan}
    except (ValueError, TypeError, KeyError):
        note("The patient list could not be reviewed. No handoffs were changed. Reload the saved archive.", "error")


def confirm_daily_start(store: GitHubVault | None = None) -> None:
    """Commit only the reviewed snapshot, with no automatic deletion retry."""
    if not require_session():
        return
    ss = st.session_state
    preview = ss.get("daily_start_preview")
    if ss.get("patient_list_ready") or not preview or preview.get("failed"):
        return
    try:
        if ss["vault"] != preview["source"] or ss.get("vault_sha") != preview["sha"]:
            raise ValueError("The saved list changed after this review.")
        now = patient_list_now()
        if daily_reset_plan(preview["source"], now)["date"] != preview["plan"]["date"]:
            raise ValueError("The date changed after this review.")
        if preview["plan"]["already_started"]:
            continue_patient_list()
            note("Today's patient list is already started. All saved handoffs were kept.")
            return
        candidate = start_daily_list(preview["source"], datetime.fromisoformat(preview["plan"]["as_of"]))
        # The selection stays frozen at review time. The shared start time
        # records confirmation, so later logins recognize the completed start.
        candidate["settings"][START_MARKER] = now.isoformat()
        validate_vault(candidate)
        retained = _retained_reset_state(ss["vault"], candidate)
        commit(candidate, store)
    except Exception:
        preview["failed"] = True
        note("Starting the new list was not confirmed. Your open handoffs were kept. Reload the saved list before trying again.", "error")
        return
    removed, kept = len(preview["plan"]["remove"]), len(preview["plan"]["keep"])
    _apply_reset_state(retained)
    continue_patient_list()
    note(("Today's patient list started. " if store else "Session-only patient list started. ") +
         str(removed) + " handoff(s) removed. " + str(kept) + " handoff(s) kept.",
         "success" if store else "info")


def _daily_room_table(rows: list[dict]) -> str:
    cells = "".join("<tr>" + "".join("<td style='padding:6px 10px;border-bottom:1px solid #ddd'>" +
        escape(row[key]) + "</td>" for key in ("room", "last_saved", "reason")) + "</tr>" for row in rows)
    return ("<div style='max-height:330px;overflow:auto'><table style='width:100%;text-align:left;border-collapse:collapse'>"
            "<thead><tr><th>Room</th><th>Last saved (Eastern)</th><th>Reason</th></tr></thead><tbody>" +
            cells + "</tbody></table></div>")


def patient_list_startup(store: GitHubVault | None) -> bool:
    """Two choices after every sign-in. Rendering never changes stored data."""
    ss = st.session_state
    if ss.get("patient_list_ready"):
        return True
    st.title("PICU Handoff")
    if "notice" in ss:
        kind, message = ss.pop("notice")
        getattr(st, kind)(message)
    preview = ss.get("daily_start_preview")
    if preview:
        plan = preview["plan"]
        st.subheader("Start a new patient list")
        if preview.get("failed"):
            st.warning("Reload the saved list to check its current status before trying again.")
            st.button("Reload saved list", key="daily_start_reload", on_click=prepare_daily_start, args=(store,))
        elif plan["already_started"]:
            st.info("Today's list was already started at " + saved_time_text(plan["started_at"]) + ". All saved handoffs will be kept.")
            st.button("Open today's patient list", key="daily_start_existing", on_click=continue_patient_list, type="primary")
        else:
            st.caption("Remove handoffs saved before today and today's saves from 5:00 AM through 8:30 AM Eastern. Other handoffs stay.")
            st.text("To remove: " + str(len(plan["remove"])) + ". To keep: " + str(len(plan["keep"])) + ".")
            if plan["remove"]:
                st.markdown(_daily_room_table(plan["remove"]), unsafe_allow_html=True)
                st.caption("Each selected handoff is removed in full, including its difficult-airway details.")
            if plan["keep"]:
                with st.expander("Handoffs that will stay", expanded=False):
                    st.markdown(_daily_room_table(plan["keep"]), unsafe_allow_html=True)
            st.caption("This starts the list once for today. Later sign-ins will keep the handoffs entered for that list.")
            label = ("Start new list and remove " + str(len(plan["remove"])) + " handoff(s)"
                     if plan["remove"] else "Start today's list")
            st.button(label, key="daily_start_confirm", on_click=confirm_daily_start, args=(store,), type="primary")
        st.button("Continue without deleting", key="daily_start_cancel", on_click=continue_patient_list)
    else:
        st.subheader("How would you like to start?")
        st.caption(str(len(ss["vault"]["rooms"])) + " saved handoff(s)")
        fresh, existing = st.columns(2)
        with fresh:
            st.subheader("Start a new patient list")
            st.caption("Review older handoffs and today's 5:00–8:30 AM saves for removal, then enter your patients.")
            st.button("Start new patient list", key="daily_start_review", on_click=prepare_daily_start, args=(store,), type="primary")
        with existing:
            st.subheader("Continue saved handoffs")
            st.caption("Print processed handoffs, update existing patients, or add patients. Nothing is deleted.")
            st.button("Continue saved handoffs", key="daily_start_continue", on_click=continue_patient_list)
    st.button("Log out", key="daily_start_logout", on_click=clear_session)
    return False


def main() -> None:
    app, store = load_config()
    now = time.monotonic()
    if st.session_state.get("authenticated") and (now - st.session_state.get("last_activity", now) > app["idle_minutes"] * 60 or now - st.session_state.get("login_at", now) > 8 * 3600):
        clear_session()
    if not st.session_state.get("authenticated"):
        st.title("PICU Handoff")
        with st.form("login"):
            st.text_input("App password", type="password", key="login_password", max_chars=1024)
            st.form_submit_button("Open app", on_click=authenticate, args=(app["password_hash"],))
        if st.session_state.get("login_error"):
            st.error(st.session_state["login_error"])
        return
    st.session_state["last_activity"] = now
    st.session_state["idle_seconds"] = app["idle_minutes"] * 60
    idle_guard(app["idle_minutes"])
    if "vault" not in st.session_state:
        try:
            vault, sha = store.load() if store else (new_vault(), None)
        except (StorageError, ValidationError) as exc:
            st.error(str(exc))
            st.button("Try loading again")
            st.button("Log out", on_click=clear_session)
            return
        st.session_state.update(vault=vault, vault_sha=sha, drafts={}, base_sheets={})
    upgrade_existing_session()
    if not patient_list_startup(store):
        return
    with st.sidebar:
        st.header("PICU Handoff")
        st.caption("Version 6.69 | AVAPS ventilator settings")
        # Retire the old instructions workspace without discarding room drafts.
        if st.session_state.get("page") == "Instructions / SmartPhrase":
            st.session_state["page"] = "Handoff"
        page = st.radio("Workspace", ["Handoff", "Print all", "Admin", "Import errors"], key="page", on_change=workspace_changed, args=(store,))
        st.caption("Shared storage connected" if store else "Session-only testing. No persistence.")
        st.button("Reload saved archive", on_click=reload_archive, args=(store,), disabled=store is None)
        st.button("Log out", on_click=clear_session)
        if st.session_state.get("pending_error_events"):
            st.caption("Unsaved technical reports: see Alerts or Import errors.")
        st.caption("Room changes and Print all save your handoff automatically. Use Save before logout.")
    st.session_state["active_workspace"] = page
    if "notice" in st.session_state:
        kind, text = st.session_state.pop("notice")
        if page == "Handoff":
            remember_notice(st.session_state, kind, text)
        else:
            getattr(st, kind)(text)
    if page == "Admin":
        admin_page(store)
    elif page == "Import errors":
        import_errors_page(store)
    elif page == "Print all":
        print_all_page(store)
    else:
        handoff_page(store)


def medication_editor(rows: list[dict], room: str, store: GitHubVault | None) -> None:
    for number, row in enumerate(rows, 1):
        prefix = "med_draft_" + row["id"] + "_"
        summary, destination = st.columns([3, 1])
        with summary:
            suffix = " [IGNORE]" if ignored(row) else " [HIDDEN]" if row["hidden"] else "" if row["include"] else " [EXCLUDED]"
            if supports_infusion_display(row) and is_infusion(row):
                st.markdown('<div style="white-space:pre-wrap;border-left:3px solid #555;padding-left:8px">' +
                            str(number) + '. <b>Infusion</b>' + suffix + '\n' +
                            infusion_entry(row, True) + '</div>', unsafe_allow_html=True)
            else:
                st.text(f"{number}. " + format_medication(row) + suffix)
        with destination:
            placement_picker(row, number, room, store, medication_category_change)
        if supports_infusion_display(row):
            key = prefix + "infusion_mode"
            if key not in st.session_state:
                st.session_state[key] = row.get("infusion_mode", "auto")
            st.selectbox("Infusion emphasis for order " + str(number), MODES, key=key,
                         format_func=lambda value: MODE_LABELS[value], on_change=medication_row_change,
                         args=(room, row["id"], "infusion_mode", key, store))
        needs_restore = row["hidden"] or ignored(row)
        st.button("Restore to handoff" if needs_restore else "Hide from handoff", key="hide_med_" + row["id"], on_click=hide_medication, args=(room, row["id"], not needs_restore, store))
        with st.expander("Edit details for order " + str(number), expanded=False):
            def widget(field: str, label: str, kind: str = "text"):
                key = prefix + field
                if key not in st.session_state:
                    st.session_state[key] = row.get(field, "unavailable" if field == "last_admin_status" else "")
                args = (room, row["id"], field, key, store)
                if kind == "check":
                    st.checkbox(label, key=key, on_change=medication_row_change, args=args)
                elif kind == "area":
                    st.text_area(label, key=key, height=90, max_chars=4000, on_change=medication_row_change, args=args)
                else:
                    st.text_input(label, key=key, max_chars=4000, on_change=medication_row_change, args=args)
            widget("include", "Include order", "check")
            widget("name", "Medication / formulation")
            left, right = st.columns(2)
            with left:
                widget("dose", "Dose")
                widget("frequency", "Frequency")
            with right:
                widget("route", "Route")
                widget("last_rate", "Last recorded rate")
            widget("rate_time", "Rate timestamp")
            if continuous_order(row) or any(key in row for key in ADMIN_FIELDS):
                st.caption("Last Admin supplies the displayed infusion dose-rate. Dose above remains the original order. Changes here apply only to this handoff, not Epic.")
                widget("last_admin_rate", "Last Admin rate")
                widget("last_admin_time", "Last Admin timestamp")
                key = prefix + "last_admin_status"
                if key not in st.session_state:
                    st.session_state[key] = row.get("last_admin_status", "unavailable")
                st.selectbox("Last Admin status", ADMIN_STATUSES, key=key,
                             format_func=lambda value: ADMIN_STATUS_LABELS[value],
                             on_change=medication_row_change,
                             args=(room, row["id"], "last_admin_status", key, store))
            widget("custom_text", "Custom handoff wording", "area")
            if row.get("custom_text", "").strip() and continuous_order(row):
                st.caption("Custom handoff wording overrides the automatic infusion summary, including its Last Admin rate. Recheck or clear custom wording after a rate change.")
            name, match = rule_for_inline_mapping(row["name"], st.session_state["vault"]["settings"]["medication_mappings"])
            st.caption("Changing the system remembers this rule: " + name + " [" + match + "].")
            for warning in row["warnings"]:
                st.caption(warning)


def invasive_editor(sheet: dict) -> None:
    data = sheet["ventilation"]
    if data is None:
        st.caption("No automatic invasive-ventilation block is currently included.")
        return
    st.text(format_ventilation(data))
    with st.expander("Edit ventilator values"):
        st.caption("The source mode stays editable. The handoff abbreviates it and prints mode-specific settings. Set and observed values are never substituted for one another. Pmin with a number uses your Home Vent display rule. Observed tidal volume prints as TV. Its original inspiratory/expiratory field stays available below.")
        for index, label in enumerate(LABELS):
            key = "vent_" + sheet["id"] + "_" + str(index)
            if key not in st.session_state:
                st.session_state[key] = data["mode"] if index == 0 else data["values"].get(label, "")
            st.text_input(label, key=key, max_chars=500, on_change=ventilation_change,
                          args=(sheet["room"], label, key))
        st.button("Clear ventilator block", on_click=clear_ventilation)



def noninvasive_change(room: str, device: str, label: str, widget_key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    devices = ss["drafts"][room]["noninvasive"]
    updated = deepcopy(devices)
    row = next((d for d in updated if d["device"] == device), None)
    if row is None:
        return
    old_value = row["values"].get(label, "")
    value = ss[widget_key].strip()
    if value:
        row["values"][label] = value
    else:
        row["values"].pop(label, None)
    try:
        validate_noninvasive(updated)
    except ValueError as exc:
        ss[widget_key] = old_value
        note(str(exc), "error")
        return
    ss["drafts"][room]["noninvasive"] = updated


def remove_support_device(room: str, device: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    sheet = ss["drafts"][room]
    sheet["noninvasive"] = [item for item in sheet["noninvasive"] if item["device"] != device]
    if device in ("CPAP", "BiPAP", "AVAPS NIV", "NAVA NIV") and not sheet["ventilation"]:
        sheet["sbs_vent_mode"] = ""
    for key in list(ss):
        if key.startswith("niv_" + sheet["id"] + "_" + device + "_"):
            ss.pop(key, None)


def ventilation_editor(sheet: dict) -> None:
    if sheet["ventilation"] is not None:
        invasive_editor(sheet)
    if not sheet["ventilation"] and not sheet["noninvasive"]:
        st.caption("No automatic respiratory-support entries are currently included.")
    for device in sheet["noninvasive"]:
        st.text(format_noninvasive([device]))
        if device["pressure_inferred"]:
            st.caption("Pressure-based BiPAP: Vent Mode was absent, but both IPAP and EPAP were documented. These may be carried-forward settings rather than current support. Remove the entry below if it no longer applies.")
        if device["flow_inferred"]:
            st.caption("Flow-based HFNC: the source delivery label is a CPAP/Bi-PAP mask. Your mask-plus-flow rule adds this entry, but it does not confirm concurrent HFNC. Remove it below when it does not apply.")
        with st.expander("Edit " + device["device"] + " settings"):
            for index, label in enumerate(DEVICE_FIELDS[device["device"]]):
                key = "niv_" + sheet["id"] + "_" + device["device"] + "_" + str(index)
                if key not in st.session_state:
                    st.session_state[key] = device["values"].get(label, "")
                st.text_input(label, key=key, max_chars=500, on_change=noninvasive_change,
                              args=(sheet["room"], device["device"], label, key))
            st.button("Remove " + device["device"], key="remove_niv_" + sheet["id"] + "_" + device["device"],
                      on_click=remove_support_device, args=(sheet["room"], device["device"]))

def display_room_save_status(room: str, store: GitHubVault | None = None, *, session_only: bool | None = None):
    """Read confirmed save metadata, independent of display or print timestamps."""
    ss = st.session_state
    kwargs = {"session_only": store is None if session_only is None else session_only}
    if room in ss.get("base_sheets", {}):
        kwargs["base_sheet"] = ss["base_sheets"][room]
    return room_save_status(room, ss["vault"]["rooms"].get(room),
                            ss.get("drafts", {}).get(room), **kwargs)


def render_room_save_table(rooms: list[str], store: GitHubVault | None) -> None:
    statuses = [display_room_save_status(room, store) for room in rooms]
    st.markdown(save_status_table(statuses, session_only=store is None), unsafe_allow_html=True)


def handoff_tab_changed() -> None:
    """Capture pending edits before an inactive tab's widgets are cleaned up."""
    if not require_session():
        return
    ss = st.session_state
    room = ss.get("current_room")
    previous = ss.get("handoff_active_tab", "Preview / print")
    if room and room in ss.get("drafts", {}):
        try:
            ss["drafts"][room] = editor_snapshot(room)
        except (ValueError, TypeError, KeyError):
            ss["handoff_tab"] = previous
            note("The tab was not changed. Correct the invalid editor value before continuing.", "error")
            return
    ss["handoff_active_tab"] = ss.get("handoff_tab", "Preview / print")


def handoff_tools(store: GitHubVault | None, choices: list[str]) -> None:
    """Secondary and destructive actions stay out of the copy/paste path."""
    ss = st.session_state
    room = ss.get("current_room")
    active = room in ss.get("drafts", {}) and ss.get("room_choice") == room
    with st.popover("Room actions"):
        st.button("Clear pasted text", on_click=clear_paste)
        if active:
            st.button("Load saved handoff", on_click=load_saved_into_editor)
            with st.expander("Start over / reload", expanded=False):
                st.caption("Replaces the open draft immediately. Save to replace the saved room.")
                st.button("Start blank for new patient", on_click=start_new_patient)
            if room not in DEFAULT_ROOMS:
                with st.expander("Custom room options", expanded=False):
                    st.button("Remove custom room", key="remove_current_room", on_click=remove_custom_room, args=(room, store))
        if ss.get("removed_room"):
            st.button("Undo last room removal", key="undo_room_handoff", on_click=undo_room_removal, args=(store,))
        with st.expander("Save status for all rooms", expanded=False):
            render_room_save_table(choices, store)
            st.caption("Eastern time. Reload saved archive to see another user's saves.")
        delete_handoffs_control(store)


def handoff_alerts(sheet: dict) -> None:
    """Read-only details plus the existing explicit import-review actions."""
    rows = alert_rows(sheet, st.session_state)
    st.markdown(alert_lines_html(rows), unsafe_allow_html=True)
    if sheet.get("import_warnings"):
        import_review_editor(sheet, compact=True)


def room_preview(sheet: dict, store: GitHubVault | None = None) -> None:
    """Build the inexpensive screen preview, not a PDF, when this tab is open."""
    import streamlit.components.v1 as components
    statuses = {sheet["room"]: display_room_save_status(
        sheet["room"], session_only=not st.session_state.get("workspace_shared_storage", False))}
    left, right = st.columns([3, 1])
    with right:
        with st.popover("Print options"):
            target = print_target_control("room_print_target")
            # Page fitting still runs on every actual PDF download. This
            # optional check avoids doing the same PDF work on each edit.
            if st.button("Check page count", key="check_room_page_fit"):
                render_print_fit([sheet], target)
    with left:
        try:
            st.download_button("Download this handoff (PDF)",
                               handoff_download([sheet], store, target_pages=target, save_statuses=statuses),
                               "handoff.pdf", "application/pdf", key="download_single_pdf", on_click="ignore")
        except (ValueError, ImportError):
            st.error("PDF export is unavailable. Refresh and retry.")
    components.html(handoff_html(sheet, save_statuses=statuses), height=650, scrolling=True)


def handoff_notes(sheet: dict) -> None:
    ss = st.session_state
    room = sheet["room"]
    observed_vitals = automatic_vitals(sheet)
    with st.expander("Respiratory support", expanded=False):
        ventilation_editor(sheet)
    devices_editor(sheet)
    st.caption("These are your separate notes. Re-pasting medications or ventilation does not erase them.")
    for section in SYSTEMS:
        key = edit_key(sheet, section)
        if key not in ss:
            ss[key] = sheet["fields"][section]
        with st.expander(section_label(section), expanded=section == "Diagnoses"):
            if section == "Cardiovascular":
                pacemaker_editor(sheet)
            if section == "FEN / GI":
                intake_output_editor(sheet)
                diet_editor(sheet)
                feeds_editor(sheet)
            if section == "Labs" and orders_text(sheet["recurring_orders"]):
                st.text(orders_text(sheet["recurring_orders"]) + "\n-----")
                st.caption("Edit the imported recurring orders in Labs/Imaging. Notes below stay separate.")
            if section in observed_vitals:
                if section == "Cardiovascular" and sheet.get("ecg"):
                    st.markdown('<div style="white-space:pre-wrap">' + clinical_markup(observed_vitals[section] + "\n-----") + '</div>', unsafe_allow_html=True)
                else:
                    st.text(observed_vitals[section] + "\n-----")
            if section == "Demographics / Weight" and sheet["admission_date"]:
                st.text("Admission: " + sheet["admission_date"])
            if section == "Demographics / Weight" and mrsa_screen_text(sheet):
                st.markdown('<div style="white-space:pre-wrap">' + clinical_markup(mrsa_screen_text(sheet)) + '</div>', unsafe_allow_html=True)
            if section == "Infectious Disease" and id_summary(sheet):
                st.text(id_summary(sheet) + "\n------")
            if section == "Cardiovascular" and cardiac_labs_summary(sheet):
                st.text(cardiac_labs_summary(sheet) + "\n-----")
            if section == "Respiratory" and respiratory_text(sheet):
                st.text(respiratory_text(sheet) + "\n-----")
                st.caption("Vital signs print first, then support settings. Edit support in Respiratory support above.")
            if section == "Respiratory" and theophylline_summary(sheet) and not theophylline_anchor(sheet):
                st.text(theophylline_summary(sheet) + "\n-----")
                st.caption("Latest included THEOPH result. Edit or exclude its original row in Labs / Vitals.")
            if section == "Diagnoses" and viral_text(sheet["viral_panel"]):
                st.markdown('<div style="white-space:pre-wrap">----\n' + viral_markup(sheet["viral_panel"]) + '</div>', unsafe_allow_html=True)
                st.caption("Positive O-block results print below the demographics / weight information. Edit under Labs / Vitals.")
            st.text_area("Notes: " + section_label(section), key=key, height=100, max_chars=MAX_FIELD,
                         on_change=update_field, args=(room, section, key))
            if section == "Infectious Disease" and "f" not in sheet["import_warnings"] and cultures_text(sheet["cultures"], empty_none=True):
                st.markdown('<div style="white-space:pre-wrap">------\n' + culture_markup(sheet["cultures"], empty_none=True) + '</div>', unsafe_allow_html=True)
                st.caption("Edit imported specimens and results in Cultures. Temperature stays first in the printed ID column.")
            if section == "FEN / GI":
                st.markdown('<div style="white-space:pre-wrap">' + fen_gi_body("", sheet["medications"], None, True, sheet=sheet) + "</div>", unsafe_allow_html=True)
                st.caption("Printed order: Intake/Output/Net, Diet, Feeds, TPN, GI prophylaxis, Bowel Regimen, Diuretics, Antiemetics, Endocrine Medications, then separate notes and remaining FEN/GI medications.")
            elif section in INFUSION_SECTIONS:
                render_body = {"Neurologic": neuro_body, "Cardiovascular": cardiovascular_body, "Hematology": hematology_body, "Respiratory": respiratory_body}[section]
                st.markdown('<div style="white-space:pre-wrap">' + render_body("", sheet["medications"], True, sheet=sheet) + '</div>', unsafe_allow_html=True)
            else:
                for row in sheet["medications"]:
                    if visible(row) and effective_section(row) == section:
                        st.text(format_medication(row))
            if section == "Diagnoses" and demographic_weight_text(sheet["nutrition"], sheet["dosing_weight"]):
                st.text("----\n" + demographic_weight_text(sheet["nutrition"], sheet["dosing_weight"]))
                st.caption("Edit measured weight, Z-score, dosing weight and admission date in Labs / Vitals.")


def handoff_page(store: GitHubVault | None) -> None:
    ss = st.session_state
    ss["workspace_shared_storage"] = store is not None
    st.markdown(COMPACT_STYLES, unsafe_allow_html=True)
    st.subheader("Handoff")
    # Refresh nonclinical instructions at most every five minutes rather than
    # doing a network read every 30 seconds while the user works.
    due = bool(store) and time.monotonic() - ss.get("handoff_guide_checked", 0) >= 300
    guide = load_user_guide(store, refresh=due)
    if due:
        ss["handoff_guide_checked"] = time.monotonic()
    st.caption(compact_help(guide))
    settings = ss["vault"]["settings"]
    choices = list(dict.fromkeys(settings["rooms"] + list(ss["vault"]["rooms"]) + list(ss.get("drafts", {}))))
    if "room_choice" not in ss:
        ss["room_choice"] = ss.get("current_room", "Choose a room")
    select, save, tools = st.columns([3, 1.3, 1.3], vertical_alignment="bottom")
    with select:
        st.selectbox("Room", ["Choose a room"] + choices + ["Other room"], key="room_choice",
                     on_change=room_changed, args=(store,), label_visibility="collapsed")
    room = ss.get("current_room")
    selected = ss.get("room_choice") not in ("Choose a room", "Other room")
    with save:
        st.button("Save handoff", on_click=save_room, args=(store,), disabled=not (room and selected))
    with tools:
        handoff_tools(store, choices)
    if ss.get("room_choice") == "Other room":
        st.text_input("Other room number", key="other_room", max_chars=16)
        st.button("Open room", on_click=open_room, args=(store,))
        attention = workspace_attention(None, ss)
        if attention:
            st.markdown(alert_lines_html([("error", attention)]), unsafe_allow_html=True)
        return
    if not selected or not room:
        st.caption("Select a room to begin.")
        attention = workspace_attention(None, ss)
        if attention:
            st.markdown(alert_lines_html([("error", attention)]), unsafe_allow_html=True)
        return
    sheet = ss["drafts"][room]
    status = display_room_save_status(room, store)
    anthropometrics = sheet.get("anthropometrics", {})
    status_text = ("Age: " + (anthropometrics.get("age") or "--") +
                   " | Sex: " + (anthropometrics.get("sex") or "--") +
                   " | " + status.caption + " | " + status.status)
    alerts = alert_rows(sheet, ss)
    attention_count = sum(kind in ("warning", "error") for kind, _ in alerts)
    if attention_count:
        status_text += " | Alerts: " + str(attention_count)
    st.caption(status_text)
    attention = workspace_attention(sheet, ss)
    if attention:
        st.markdown(alert_lines_html([("error", attention)]), unsafe_allow_html=True)
    # A two-line, fixed-height input remains visible above every tab. Long
    # SmartPhrases scroll within the field instead of expanding the page.
    with st.form("parse_smartphrase", border=False):
        text, submit = st.columns([5, 1.3], vertical_alignment="bottom")
        with text:
            st.text_area("SmartPhrase text", key="paste", height=68, max_chars=MAX_PASTE,
                         label_visibility="collapsed", placeholder="Paste Epic SmartPhrase here")
        with submit:
            st.form_submit_button("Create / update handoff", on_click=create_handoff, args=(store,), type="primary")
    if ss.get("handoff_tab") not in WORKSPACE_TABS:
        ss["handoff_tab"] = "Preview / print"
    tabs = st.tabs(list(WORKSPACE_TABS), key="handoff_tab", on_change=handoff_tab_changed)
    for label, panel in zip(WORKSPACE_TABS, tabs):
        if not panel.open:
            continue
        with panel:
            if label == "Preview / print":
                room_preview(sheet, store)
            elif label == "Medications":
                st.caption("Choose one destination per order. Mapping changes are remembered.")
                active = [row for row in sheet["medications"] if not row["hidden"] and not ignored(row)]
                hidden = [row for row in sheet["medications"] if row["hidden"] or ignored(row)]
                medication_editor(active, room, store)
                if hidden:
                    label = "Ignored / hidden medications" if any(ignored(row) for row in hidden) else "Hidden medications"
                    with st.expander(label + " (" + str(len(hidden)) + ")", expanded=False):
                        medication_editor(hidden, room, store)
                if not sheet["medications"]:
                    st.caption("No medications imported.")
            elif label == "Labs / Vitals":
                labs_vitals_editor(sheet)
            elif label == "Cultures":
                cultures_editor(sheet)
            elif label == "Labs/Imaging":
                recurring_orders_editor(sheet)
            elif label == "Problems":
                problem_review_editor(sheet)
            elif label == "Difficult airway":
                difficult_airway_editor(sheet)
            elif label == "Alerts":
                handoff_alerts(sheet)
            elif label == "Edit handoff":
                handoff_notes(sheet)


def download_deadline() -> float:
    ss = st.session_state
    return min(ss.get("last_activity", time.monotonic()) + ss.get("idle_seconds", 900),
               ss.get("login_at", time.monotonic()) + 8 * 3600)


def handoff_download(sheets: list[dict], store: GitHubVault | None, *,
                     target_pages: int = 1, save_statuses: dict | None = None):
    """Check the shared list at download time without accessing UI in its worker."""
    deadline, cancelled = download_deadline(), download_revocation()
    generate = download_payload(sheets, "pdf", deadline, target_pages=target_pages,
                                cancelled=cancelled, save_statuses=save_statuses)
    return guard_download(generate, store, st.session_state["vault"]["reset_generation"],
                          cancelled=cancelled, expires_at=deadline)


def print_target_control(key: str) -> int:
    # Keep a non-widget preference so lazy-tab cleanup does not reset a user's
    # selected page target. This remains private to the current app session.
    preference = "workspace_" + key
    ss = st.session_state
    if key not in ss and ss.get(preference) in (1, 2):
        ss[key] = ss[preference]
    choice = st.selectbox("PDF page target per patient", [1, 2], key=key,
                          format_func=lambda n: "Auto-fit to 1 page" if n == 1 else "Auto-fit to at most 2 pages")
    selected = choice if choice in (1, 2) else 1
    ss[preference] = selected
    return selected


def render_print_fit(sheets: list[dict], target: int) -> None:
    """Keep actual overflow alerts, without the routine layout diagnostics table."""
    for sheet in sheets:
        report = print_fit_report(sheet, target)
        if not report["target_met"]:
            st.warning("Room " + sheet["room"] + " needs " + str(report["page_count"]) +
                       " pages. All content is retained rather than cropped.")
        else:
            st.caption(sheet["room"] + ": " + str(report["page_count"]) +
                       (" page." if report["page_count"] == 1 else " pages."))


def print_all_page(store: GitHubVault | None) -> None:
    st.title("Print all handoffs")
    if not autosave_before_print_all(store):
        st.error("Print all paused because saving was not confirmed. Your edits are kept. Return to Handoff and resolve the save alert.")
        return
    st.caption("To reset the list, open Delete all handoff data on Handoff or in Admin.")
    ss = st.session_state
    ready = available_handoffs(ss["vault"], ss.get("drafts", {}))
    if not ready:
        st.info("Create a handoff first. Saved handoffs will also appear here after sign-in.")
        return
    st.caption("Open handoffs are saved before printing. Blank sheets are omitted.")
    st.button("Save all open handoffs", on_click=save_all_rooms, args=(store,))
    st.caption(most_recent_save_caption(ss["vault"]["rooms"], session_only=store is None))
    options = list(ready)
    # A fresh room list selects all rooms. Explicit selections survive normal reruns.
    if ss.get("print_room_options") != options or "print_rooms" not in ss:
        ss["print_room_options"] = options
        ss["print_rooms"] = options
    selected = st.multiselect("Rooms to print", options, key="print_rooms")
    selected_sheets = [ready[r] for r in options if r in selected]
    if not selected_sheets:
        st.info("Select at least one room.")
        return
    statuses = {sheet["room"]: display_room_save_status(sheet["room"], store) for sheet in selected_sheets}
    unsaved = sum(status.unsaved for status in statuses.values())
    st.caption(str(len(selected_sheets)) + " handoffs selected. Each room starts on a new page.")
    render_room_save_table([sheet["room"] for sheet in selected_sheets], store)
    st.caption("Save times are Eastern (EST/EDT) and come from the loaded archive. Reload saved archive to see saves from another session." if store else
               "Session-only testing: these save times are not durable shared saves.")
    if unsaved:
        st.error("Some selected handoffs are not saved. Resolve the save alert before printing.")
        return
    try:
        target = print_target_control("all_print_target")
        with st.expander("Page-fit details", expanded=False):
            if st.button("Check page count", key="check_all_page_fit"):
                render_print_fit(selected_sheets, target)
        st.download_button("Download all selected handoffs (PDF)", handoff_download(selected_sheets, store, target_pages=target, save_statuses=statuses), "all_handoffs.pdf", "application/pdf", type="primary", key="download_all_pdf", on_click="ignore")
    except (ValueError, ImportError):
        st.error("The combined PDF could not be created. Check the export requirements and retry.")
    st.caption("Compact PDF is preferred for printing. Each room starts on its own page. Exceptionally long handoffs continue rather than losing content. Downloads are not encrypted.")


def select_admin_rule() -> None:
    if not require_admin():
        return
    ss = st.session_state
    index = ss.get("admin_rule_index", -1)
    rules = ss["vault"]["settings"]["medication_mappings"]
    rule = rules[index] if isinstance(index, int) and 0 <= index < len(rules) else None
    ss["mapping_name"] = rule["name"] if rule else ""
    ss["mapping_destination"] = rule["destination"] if rule else "Other Medications"
    ss["mapping_match"] = rule["match"] if rule else "prefix"
    ss["mapping_original"] = (rule["name"], rule["match"]) if rule else None


def save_admin_rule(store: GitHubVault | None) -> None:
    if not require_admin():
        return
    ss = st.session_state
    candidate = deepcopy(ss["vault"])
    rules = candidate["settings"]["medication_mappings"]
    original = ss.get("mapping_original")
    if original:
        rules = [r for r in rules if (r["name"], r["match"]) != tuple(original)]
    try:
        candidate["settings"]["medication_mappings"] = upsert_rule(rules, ss.get("mapping_name", ""), ss.get("mapping_destination", "Other Medications"), ss.get("mapping_match", "prefix"))
        commit(candidate, store)
        reapply_open_mappings()
        ss["admin_rule_index"] = -1
        ss["mapping_original"] = None
        note("Medication mapping saved. Open drafts use the updated mappings.", "success")
    except (ValueError, ValidationError, StorageError) as exc:
        note(str(exc), "error")


def remove_admin_rule(store: GitHubVault | None) -> None:
    if not require_admin():
        return
    ss = st.session_state
    index = ss.get("admin_rule_index", -1)
    rules = ss["vault"]["settings"]["medication_mappings"]
    if not isinstance(index, int) or not 0 <= index < len(rules):
        return
    candidate = deepcopy(ss["vault"])
    candidate["settings"]["medication_mappings"].pop(index)
    try:
        commit(candidate, store)
        reapply_open_mappings()
        ss["admin_rule_index"] = -1
        select_admin_rule()
        note("Mapping removed. Open drafts have been remapped.")
    except (StorageError, ValidationError) as exc:
        note(str(exc), "error")


def save_admin_settings(store: GitHubVault | None) -> None:
    if not require_admin():
        return
    ss = st.session_state
    try:
        rooms = list(dict.fromkeys(normalize_room(line) for line in ss.get("admin_rooms", "").splitlines() if line.strip()))
        candidate = deepcopy(ss["vault"])
        candidate["settings"].update(diagnoses_destination=ss["admin_diagnosis_dest"], rooms=rooms)
        commit(candidate, store)
        ss["admin_rooms"] = "\n".join(rooms)
        note("Room and diagnosis settings saved.", "success")
    except (ValidationError, StorageError) as exc:
        note(str(exc), "error")


def download_revocation() -> Event:
    ss = st.session_state
    if "download_revocation" not in ss:
        ss["download_revocation"] = Event()
    return ss["download_revocation"]


def discard_all_handoff_state() -> None:
    """Only after a confirmed reset/load. Shared rules and guide remain intact."""
    ss = st.session_state
    guard = ss.get("download_revocation")
    if guard is not None:
        guard.set()
    ss["download_revocation"] = Event()
    discard_editor_widget_values()
    for key in ("current_room", "other_room", "import_result", "pending", "diagnosis_preview",
                "medication_pending", "removed_room", "print_rooms", "print_room_options",
                "custom_room_remove_choice", "room_print_target", "all_print_target",
                "workspace_notices", "workspace_imports", "handoff_tab", "handoff_active_tab",
                "workspace_room_print_target", "workspace_all_print_target", "airway_update_pending"):
        ss.pop(key, None)
    ss["drafts"] = {}
    ss["base_sheets"] = {}
    ss["paste"] = ""
    ss["room_choice"] = "Choose a room"
    ss["admin_rooms"] = "\n".join(ss["vault"]["settings"]["rooms"])


def clear_all_handoffs(store: GitHubVault | None) -> None:
    """Allow a signed-in user to reset. Discard drafts only after a confirmed write."""
    if not require_session():
        return
    ss = st.session_state
    try:
        candidate = cleared_vault(ss["vault"])
        commit(candidate, store)
    except (StorageError, ValidationError, ValueError) as exc:
        note("Clear all was not confirmed. Your open handoffs were kept. " + str(exc), "error")
        return
    except Exception:
        note("Clear all was not confirmed. Your open handoffs were kept. Reload the saved archive before retrying.", "error")
        return
    discard_all_handoff_state()
    note(("All saved handoffs and this session's drafts were cleared. Custom rooms were deleted. " if store else
          "Session-only reset: all handoffs in this session were cleared and custom rooms deleted. ") +
         "Preset rooms, medication rules, hidden rules, instructions and passwords were kept. Other team members should reload the saved archive. Earlier archive versions and downloaded files are not erased.",
         "success" if store else "info")


def delete_all_from_handoff(store: GitHubVault | None) -> None:
    """Use the app session, not the separate Admin grant, for a census reset."""
    # Remove a stale password widget value left by an older running version.
    st.session_state.pop("delete_all_password", None)
    clear_all_handoffs(store)


def delete_handoffs_control(store: GitHubVault | None) -> None:
    """Delete complete handoffs, available before selecting a room, without Admin."""
    with st.expander("Delete all handoff data", expanded=False):
        st.warning("Deletes every patient's saved handoff and this session's drafts, including difficult-airway details. Custom rooms are removed.")
        st.caption("Categories, medication mappings, SmartPhrase settings and passwords stay unchanged. Earlier archive versions and downloaded copies are not erased. Other team members must reload the saved archive.")
        st.caption("No Admin password is required. The button applies immediately.")
        with st.form("delete_all_handoffs_form"):
            st.form_submit_button("Delete all handoff data", on_click=delete_all_from_handoff, args=(store,))


def reset_handoffs_admin(store: GitHubVault | None) -> None:
    with st.expander("Delete all handoff data", expanded=False):
        st.warning("Deletes every patient's saved handoff, including difficult-airway details, and this session's drafts immediately.")
        st.caption("Custom rooms are removed. Settings, mappings, passwords and technical logs stay unchanged. This does not erase earlier archive versions or downloaded copies.")
        st.button("Delete all handoff data", key="clear_all_handoffs_button",
                  on_click=clear_all_handoffs, args=(store,))


def custom_room_names() -> list[str]:
    ss = st.session_state
    return [r for r in dict.fromkeys(ss["vault"]["settings"]["rooms"] +
            list(ss["vault"]["rooms"]) + list(ss.get("drafts", {}))) if r not in DEFAULT_ROOMS]


def remove_custom_room(room: str, store: GitHubVault | None) -> None:
    if not require_session():
        return
    ss = st.session_state
    try:
        room = normalize_room(room)
        if room in DEFAULT_ROOMS:
            raise ValidationError("This control removes custom rooms only. Preset rooms are kept.")
        if room not in custom_room_names():
            raise ValidationError("The custom room is no longer present.")
        if room in ss.get("drafts", {}) and ss.get("base_sheets", {}).get(room) != ss["vault"]["rooms"].get(room):
            raise ValidationError("A newer saved sheet exists for this room. Reload and compare before removing it.")
        draft = (editor_snapshot(room) if room == ss.get("current_room") else
                 deepcopy(ss.get("drafts", {}).get(room)))
        removed = {"room": room, "saved": deepcopy(ss["vault"]["rooms"].get(room)),
                   "draft": draft, "base": deepcopy(ss.get("base_sheets", {}).get(room)),
                   "listed": room in ss["vault"]["settings"]["rooms"]}
        candidate = deepcopy(ss["vault"])
        candidate["rooms"].pop(room, None)
        candidate["settings"]["rooms"] = [r for r in candidate["settings"]["rooms"] if r != room] or list(DEFAULT_ROOMS)
        commit(candidate, store)
    except (StorageError, ValueError, KeyError, TypeError) as exc:
        note("The room was not removed. " + str(exc), "error")
        return
    except Exception:
        note("Room removal was not confirmed. Keep your draft and reload the saved archive before retrying.", "error")
        return
    ss["removed_room"] = removed
    ss.get("drafts", {}).pop(room, None)
    ss.get("base_sheets", {}).pop(room, None)
    ss["admin_rooms"] = "\n".join(candidate["settings"]["rooms"])
    for key in ("print_rooms", "print_room_options", "custom_room_remove_choice"):
        ss.pop(key, None)
    if ss.get("current_room") == room:
        discard_editor_widget_values()
        ss.pop("current_room", None)
        ss["room_choice"] = "Choose a room"
        ss["paste"] = ""
        ss.pop("import_result", None)
    note("Custom room and current saved handoff removed. Undo is available during this session. Earlier encrypted Git history is not erased.", "success")


def undo_room_removal(store: GitHubVault | None) -> None:
    if not require_session():
        return
    ss = st.session_state
    removed = ss.get("removed_room")
    if not removed:
        return
    room = removed["room"]
    if room in custom_room_names():
        note("That room has been added again. Undo will not overwrite it.", "error")
        return
    candidate = deepcopy(ss["vault"])
    if removed["listed"] or removed["saved"] is None:
        candidate["settings"]["rooms"].append(room)
    if removed["saved"] is not None:
        candidate["rooms"][room] = deepcopy(removed["saved"])
    try:
        commit(candidate, store)
    except (ValueError, StorageError) as exc:
        note("Undo was not saved. " + str(exc), "error")
        return
    if removed["draft"] is not None:
        ss.setdefault("drafts", {})[room] = deepcopy(removed["draft"])
        ss.setdefault("base_sheets", {})[room] = deepcopy(removed["base"])
    ss.pop("removed_room", None)
    ss["admin_rooms"] = "\n".join(candidate["settings"]["rooms"])
    for key in ("print_rooms", "print_room_options", "custom_room_remove_choice"):
        ss.pop(key, None)
    note("Room restored. Any prior unsaved draft is retained separately from its saved handoff.", "success")


def remove_selected_custom_room(store: GitHubVault | None) -> None:
    if not require_admin():
        return
    room = st.session_state.get("custom_room_remove_choice")
    if room:
        remove_custom_room(room, store)


def custom_room_admin(store: GitHubVault | None) -> None:
    st.subheader("Custom rooms")
    names = custom_room_names()
    if names:
        if st.session_state.get("custom_room_remove_choice") not in names:
            st.session_state["custom_room_remove_choice"] = names[0]
        st.selectbox("Custom room to remove", names, key="custom_room_remove_choice")
        st.caption("Removes the room and its current saved handoff, not medication rules. Preset rooms are not listed here.")
        st.button("Remove selected custom room", on_click=remove_selected_custom_room, args=(store,))
    else:
        st.caption("No custom rooms to remove.")
    if st.session_state.get("removed_room"):
        st.button("Undo last room removal", key="undo_room_admin", on_click=admin_undo_room_removal, args=(store,))


def reset_infusion_rule(key: tuple[str, str, str], store: GitHubVault | None) -> None:
    if not require_admin():
        return
    ss = st.session_state
    candidate = deepcopy(ss["vault"])
    candidate["settings"]["medication_infusions"] = [r for r in candidate["settings"]["medication_infusions"]
        if (r["name"], r["route"], r["frequency"]) != key]
    try:
        commit(candidate, store)
        reapply_open_mappings()
        note("Infusion display restored to Automatic. System assignments are unchanged.", "success")
    except (ValueError, StorageError) as exc:
        note(str(exc), "error")


def edit_saved_infusion_rule(key: tuple[str, str, str], widget: str, store: GitHubVault | None) -> None:
    if not require_admin():
        return
    ss = st.session_state
    rules = ss["vault"]["settings"]["medication_infusions"]
    existing = next((r for r in rules if (r["name"], r["route"], r["frequency"]) == key), None)
    if existing is None:
        note("The selected infusion rule changed. Reload Admin before editing it.", "error")
        return
    candidate = deepcopy(ss["vault"])
    try:
        row = dict(zip(("name", "route", "frequency"), key))
        candidate["settings"]["medication_infusions"] = set_infusion_rule(rules, row, ss[widget])
        commit(candidate, store)
        reapply_open_mappings()
        for k in list(ss):
            if k.startswith("infusion_rule_mode_"):
                ss.pop(k, None)
        note("Infusion display rule updated. System assignments are unchanged.", "success")
    except (ValueError, StorageError) as exc:
        ss[widget] = existing["mode"]
        note(str(exc), "error")


def infusion_admin(store: GitHubVault | None) -> None:
    with st.expander("Infusion display choices"):
        st.caption("Automatic recognizes continuous parenteral orders and continuous nebulized/inhaled orders mapped to Respiratory, not PRN boluses. Overrides remember the exact formulation, route and frequency. No dose is copied to another order. Display grouping applies in Neurologic, Cardiovascular, Respiratory and Hematology. DVT infusion labels are retained. Named PRN and fever-control groups remain separate.")
        for index, rule in enumerate(st.session_state["vault"]["settings"]["medication_infusions"]):
            st.text(rule["name"] + " | " + rule["route"] + " | " + rule["frequency"] + " -> " + MODE_LABELS[rule["mode"]])
            key = "infusion_rule_mode_" + str(index)
            if key not in st.session_state:
                st.session_state[key] = rule["mode"]
            st.selectbox("Display choice " + str(index + 1), MODES, key=key,
                         format_func=lambda v: MODE_LABELS[v], on_change=edit_saved_infusion_rule,
                         args=((rule["name"], rule["route"], rule["frequency"]), key, store))


def admin_page(store: GitHubVault | None) -> None:
    st.title("Admin")
    if not admin_gate():
        return
    st.button("Lock Admin", on_click=lock_admin_page)
    st.caption("Admin locks when you leave this workspace, after 15 minutes without Admin activity, or after one hour. Routine handoffs remain available.")
    reset_handoffs_admin(store)
    guide_admin(store)
    from mapping_sync_ui import mapping_sync_admin
    mapping_sync_admin(store, require_admin, reload_archive, note)
    category_admin(store, require_admin, commit, reapply_open_mappings, note)
    with st.expander("Existing mapping and display settings", expanded=False):
        st.caption("A category assignment above takes priority over these earlier routing controls. Hidden-medication choices still apply.")
        ss = st.session_state
        settings = ss["vault"]["settings"]
        rules = settings["medication_mappings"]
        st.caption("Medication destinations chosen in a handoff appear here automatically. Edit these rules at any time, even with no handoff open.")
        st.subheader("Medication mappings")
        choices = [-1] + list(range(len(rules)))
        if ss.get("admin_rule_index", -1) not in choices:
            ss["admin_rule_index"] = -1
        st.selectbox("Edit a rule or add one", choices, key="admin_rule_index", on_change=select_admin_rule,
                     format_func=lambda i: "Add a new rule" if i == -1 else rules[i]["name"] + " -> " + rules[i]["destination"])
        if "mapping_name" not in ss:
            select_admin_rule()
        with st.form("medication_mapping"):
            st.text_input("Medication name / prefix", key="mapping_name", max_chars=250)
            st.selectbox("System", DESTINATIONS, key="mapping_destination", format_func=section_label)
            st.selectbox("Match", ["prefix", "exact"], key="mapping_match", format_func=lambda value: "Name starts with this text" if value == "prefix" else "Exact complete name")
            st.form_submit_button("Save mapping", on_click=save_admin_rule, args=(store,))
        if ss.get("admin_rule_index", -1) != -1:
            st.button("Delete selected mapping", on_click=remove_admin_rule, args=(store,))
        if rules:
            with st.expander("All saved mappings", expanded=True):
                for rule in rules:
                    st.text(rule["name"] + " [" + rule["match"] + "] -> " + rule["destination"])
        else:
            st.info("No saved mappings yet. Unmapped medications go to Other Medications.")
        visibility_admin(store)
        infusion_admin(store)
        gi_admin(store)
        group_admin(store)
    custom_room_admin(store)
    st.subheader("Room and diagnosis settings")
    if "admin_rooms" not in ss:
        ss["admin_rooms"] = "\n".join(settings["rooms"])
    if "admin_diagnosis_dest" not in ss:
        ss["admin_diagnosis_dest"] = settings["diagnoses_destination"]
    with st.form("admin_settings"):
        st.selectbox("Diagnosis destination", SYSTEMS, key="admin_diagnosis_dest", format_func=section_label)
        st.text_area("Rooms, one per line", key="admin_rooms", height=150)
        st.form_submit_button("Save settings", on_click=save_admin_settings, args=(store,))
    with st.expander("Section imports"):
        for key, heading in SECTION_NAMES.items():
            st.text(key * 8 + " = " + heading + (" | automatic import" if key in SUPPORTED_SECTIONS else " | not imported yet"))
        st.caption("C/D rules control the display, not bedside device status. BiPAP needs both D-block pressures. CPAP needs EPAP or PEEP. Explicit HFNC or the documented mask-plus-flow convention can add HFNC. Inferred HFNC is labeled flow-based. No previous-paste values are reused.")



def order_widget_value(field: str, value):
    if field == "occurrences":
        value = str(value).strip()
        if not value:
            return None
        if not value.isascii() or not value.isdigit():
            raise ValueError("Enter a whole-number occurrence count, or leave it blank when not supplied.")
        return int(value)
    return value.strip() if isinstance(value, str) else value


def recurring_order_change(room: str, row_id: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    current = ss["drafts"][room]["recurring_orders"]
    if current is None:
        return
    candidate = deepcopy(current)
    row = next((r for r in candidate["rows"] if r["id"] == row_id), None)
    if row is None or field not in ("name", "timing", "occurrences", "include"):
        return
    old = row[field]
    try:
        row[field] = order_widget_value(field, ss[key])
        validate_orders(candidate)
    except ValueError as exc:
        ss[key] = ("" if old is None else str(old)) if field == "occurrences" else old
        note(str(exc) + " The order was not changed.", "error")
        return
    ss["drafts"][room]["recurring_orders"] = candidate


def recurring_orders_editor(sheet: dict) -> None:
    st.subheader("Labs/Imaging")
    st.caption("R-section scheduled orders only. Counts are the Number of Occurrences in the paste, not a calculation of remaining draws.")
    data = sheet["recurring_orders"]
    if "r" in sheet["import_warnings"]:
        st.warning("The R section was skipped. Any list below is the previous snapshot for review only and is hidden from the printed handoff.")
    if data is None:
        st.info("Paste the R section and click Create / update handoff to add recurring lab and chest X-ray orders.")
        return
    chosen = selected_orders(data)
    if chosen:
        st.text(orders_text(data))
    else:
        st.caption("No included recurring orders match the selected tests. One-time and STAT orders are omitted.")
    st.caption("Matching test and schedule: highest occurrence count wins. Different schedules, specimens and panels remain separate. Older CBC and gas result displays are unchanged.")
    if not data["rows"]:
        return
    selected_ids = {row["id"] for row in chosen}
    with st.expander("Edit recurring orders / review duplicates", expanded=False):
        for index, row in enumerate(data["rows"], 1):
            status = "shown" if row["id"] in selected_ids else "excluded" if not row["include"] else "duplicate not shown"
            st.text(str(index) + ". " + order_line(row) + " [" + status + "]")
            with st.expander("Order " + str(index) + " details", expanded=False):
                for field, label in (("include", "Include order"), ("name", "Order name"),
                                     ("timing", "Timing, for example Recurring (Daily)"),
                                     ("occurrences", "Number of occurrences")):
                    key = "rorder_" + row["id"] + "_" + field
                    if key not in st.session_state:
                        st.session_state[key] = ("" if row[field] is None else str(row[field])) if field == "occurrences" else row[field]
                    kwargs = dict(key=key, on_change=recurring_order_change, args=(sheet["room"], row["id"], field, key))
                    if field == "include":
                        st.checkbox(label, **kwargs)
                    else:
                        st.text_input(label, max_chars=500 if field != "occurrences" else 8, **kwargs)



def intake_output_change(room: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room") or key not in st.session_state:
        return
    ss = st.session_state
    original = ss["drafts"][room]["intake_output"]
    if original is None or field not in IO_FIELDS + IO_META_FIELDS + ("include",):
        return
    candidate = deepcopy(original)
    candidate[field] = ss[key].strip() if isinstance(ss[key], str) else ss[key]
    try:
        validate_balance(candidate)
        ss["drafts"][room]["intake_output"] = candidate
    except ValueError as exc:
        ss[key] = original[field]
        note(str(exc), "error")


def intake_output_editor(sheet: dict) -> None:
    data = sheet["intake_output"]
    st.subheader(balance_heading(data))
    if data is None:
        st.caption("Paste the paired S section to place its totals at the top of FEN/GI.")
        return
    meta = " | ".join(x for x in (data["period"], "As of " + data["as_of"] if data["as_of"] else "", "Last filed " + data["last_filed"] if data["last_filed"] else "") if x)
    st.text(balance_text(data, sheet["dosing_weight"] if "i" not in sheet["import_warnings"] else ""))
    st.caption("mL/kg uses only the documented dosing weight. It is a total for this reporting period, not an hourly rate. Without a dosing weight or an explicit volume unit, no mL/kg is calculated.")
    if meta:
        st.caption(meta)
    for field in IO_FIELDS:
        key = "io_" + sheet["id"] + "_" + field
        if key not in st.session_state:
            st.session_state[key] = data[field]
        st.text_input(field.capitalize(), key=key, max_chars=120, on_change=intake_output_change, args=(sheet["room"], field, key))
    key = "io_" + sheet["id"] + "_include"
    if key not in st.session_state:
        st.session_state[key] = data["include"]
    st.checkbox("Show intake/output totals", key=key, on_change=intake_output_change, args=(sheet["room"], "include", key))
    st.caption("Values are copied from S. Missing values are not zero. Net is not recalculated.")
    st.caption("The time window uses the hour of the source 24-hour summary, not the time you reprint this handoff. Minutes remain visible in As of above.")


def diet_row_change(room: str, row_id: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room") or field not in ("text", "include"):
        return
    ss = st.session_state
    original = next((r for r in (ss["drafts"][room]["diet"] or {}).get("rows", []) if r["id"] == row_id), None)
    if original is None or key not in ss:
        return
    candidate = deepcopy(original)
    value = ss[key]
    candidate[field] = value.strip() if isinstance(value, str) else value
    try:
        validate_diet({"rows": [candidate]})
        original.update(candidate)
    except ValueError as exc:
        ss[key] = original[field]
        note(str(exc), "error")


def diet_editor(sheet: dict) -> None:
    data = sheet["diet"]
    if data is None:
        return
    if diet_failed(sheet):
        st.warning("X was not updated. Retained diet information is hidden until reviewed or reimported.")
    elif diet_text(data):
        st.text(diet_text(data))
    with st.expander("Edit diet / review source", expanded=False):
        st.caption("X supplies diet type. PN, label printing and other non-diet items are omitted. Tube-feed rates still come from T. Review multiple listed diets against Epic.")
        if not data["rows"]:
            st.caption("No diet order was included in the last X section.")
        for row in data["rows"]:
            st.text("Source: " + row["source"])
            for field, label in (("text", "Diet summary"), ("include", "Include diet on handoff")):
                key = "diet_" + row["id"] + "_" + field
                if key not in st.session_state:
                    st.session_state[key] = row[field]
                args = (sheet["room"], row["id"], field, key)
                if field == "include":
                    st.checkbox(label, key=key, on_change=diet_row_change, args=args)
                else:
                    st.text_input(label, key=key, max_chars=500, on_change=diet_row_change, args=args)


def feed_row_change(room: str, row_id: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room") or key not in st.session_state:
        return
    ss = st.session_state
    data = ss["drafts"][room]["feeds"]
    if data is None or field not in ("method", "formula", "rate", "include"):
        return
    original = next((row for row in data["rows"] if row["id"] == row_id), None)
    if original is None:
        return
    candidate = deepcopy(original)
    value = ss[key]
    if isinstance(value, str):
        value = value.strip()
    if field == "rate":
        value = "" if str(value).casefold() in ("", "unk", "unknown", "--") else value
        if value != original["rate"]:
            candidate["rate_source"] = "manual" if value else "unknown"
    candidate[field] = value
    try:
        validate_feeds({"rows": [candidate]})
        original.update(candidate)
    except ValueError as exc:
        ss[key] = original[field]
        note(str(exc), "error")


def device_row_change(room: str, source: str, row_id: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    if source not in ("devices", "neuro_devices") or field not in DEVICE_EDIT_FIELDS:
        return
    ss = st.session_state
    data = ss["drafts"][room][source]
    original = next((r for r in (data or {}).get("rows", []) if r["id"] == row_id), None)
    if original is None:
        return
    candidate = deepcopy(original)
    value = ss[key]
    candidate[field] = value.strip() if isinstance(value, str) else value
    try:
        validate_devices({"rows": [candidate]}, "u" if source == "devices" else "v")
        original.update(candidate)
    except ValueError as exc:
        ss[key] = original[field]
        note(str(exc), "error")


def pacemaker_change(room: str, field: str, key: str) -> None:
    if not require_session() or room != st.session_state.get("current_room") or field not in PACER_FIELDS:
        return
    ss = st.session_state
    old = ss["drafts"][room]["pacemaker"]
    if old is None:
        return
    candidate = deepcopy(old)
    try:
        value = ss[key]
        if field == "mode":
            value = normalize_mode(value)
        elif field in ("atrial_rate", "ventricular_rate", "rate"):
            value = normalize_rate(value)
        candidate[field] = value
        validate_pacemaker(candidate)
        ss["drafts"][room]["pacemaker"] = candidate
    except ValueError as exc:
        ss[key] = old[field]
        note(str(exc), "error")


def pacemaker_editor(sheet: dict) -> None:
    data = sheet["pacemaker"]
    if data is None:
        return
    with st.expander("Edit pacemaker", expanded=False):
        if any(i["action"] == "pacemaker_hidden" for i in sheet["import_warnings"].get("w", [])):
            st.warning("W was not updated. The previous pacemaker settings below are hidden until reviewed or reimported.")
        st.caption("W supplies pacer mode and atrial/ventricular rate. Blank values remain UNK. The patient heart rate and output in milliamps are not used as a pacing rate.")
        for field, label in (("mode", "Pacer mode"), ("atrial_rate", "Atrial rate (bpm)"),
                             ("ventricular_rate", "Ventricular rate (bpm)"), ("rate", "Generic set rate (bpm)"),
                             ("status", "Pacemaker status"), ("include", "Include pacemaker on handoff")):
            key = "pacer_" + sheet["id"] + "_" + field
            if key not in st.session_state:
                st.session_state[key] = data[field]
            args = (sheet["room"], field, key)
            if field == "include":
                st.checkbox(label, key=key, on_change=pacemaker_change, args=args)
            elif field == "status":
                st.selectbox(label, PACER_STATUSES, key=key, on_change=pacemaker_change, args=args)
            else:
                st.text_input(label, key=key, max_chars=100, on_change=pacemaker_change, args=args)


def devices_editor(sheet: dict) -> None:
    with st.expander("Devices / airway and EVD", expanded=False):
        st.caption("U adds the bottom device inventory. V adds EVD status to Neurologic. Removed ETTs are airway history, not a current airway. Other removed devices are excluded.")
        st.caption("Vascular line days use today's Eastern date, with the insertion date counted as Day 1.")
        if devices_markup(sheet):
            st.markdown('<div style="white-space:pre-wrap">' + devices_markup(sheet) + '</div>', unsafe_allow_html=True)
        if evd_text(sheet):
            st.text(evd_text(sheet))
        fields = (("label", "Device / location"), ("date", "Device date (as documented)"),
                  ("size", "Airway size"), ("secured", "Secure site / recorded depth"),
                  ("status", "Device / drain status"), ("include", "Include on handoff"))
        count = 0
        for source, letter in (("devices", "u"), ("neuro_devices", "v")):
            if any(i["action"].endswith("_hidden") for i in sheet["import_warnings"].get(letter, [])):
                st.warning("This device section was not updated. Retained entries are hidden until reviewed or reimported.")
            for row in (sheet[source] or {}).get("rows", []):
                count += 1
                st.text(str(count) + ". " + device_line(row))
                for field, label in fields:
                    if field == "size" and row["kind"] != "ETT":
                        continue
                    if field == "secured" and row["kind"] not in ("ETT", "Feeding tube") and not row["secured"]:
                        continue
                    if field == "status" and row["kind"] not in ("EVD", "ICP monitor", "Trach", "Drain") and not row["status"]:
                        continue
                    key = "device_" + row["id"] + "_" + field
                    if key not in st.session_state:
                        st.session_state[key] = row[field]
                    args = (sheet["room"], source, row["id"], field, key)
                    if field == "include":
                        st.checkbox(label + " " + str(count), key=key, on_change=device_row_change, args=args)
                    else:
                        st.text_input(label + " " + str(count), key=key, max_chars=600 if field == "label" else 250,
                                      on_change=device_row_change, args=args)
        if not count:
            st.caption("Paste the paired U and V sections to add documented devices. An empty section clears its old entries. No device is assumed from a blank field.")


def feeds_editor(sheet: dict) -> None:
    st.subheader("Feeds")
    data = sheet["feeds"]
    if data is None or not data["rows"]:
        st.caption("Paste the paired T section to add feeding method, formula and rate below intake/output in FEN/GI.")
        return
    if any(i["action"] == "feeds_hidden" for i in sheet["import_warnings"].get("t", [])):
        st.warning("The T section was not updated. The retained feeding entries below are hidden from the handoff until reviewed.")
    else:
        st.text(feeds_text(data))
    with st.expander("Edit feeds / review source", expanded=False):
        st.caption("Each entry belongs to one tube. Blank formula or rate prints UNK. A volume in mL is not an hourly rate.")
        for number, row in enumerate(data["rows"], 1):
            st.text("Feed " + str(number))
            if row["device"]:
                st.caption("Source device: " + row["device"])
            for field, label in (("method", "Feeding method"), ("formula", "Formula"), ("rate", "Rate (mL/hr, or blank for UNK)"), ("include", "Include this feeding entry")):
                key = "feed_" + row["id"] + "_" + field
                if key not in st.session_state:
                    st.session_state[key] = row[field]
                args = (sheet["room"], row["id"], field, key)
                if field == "method":
                    st.selectbox(label + " " + str(number), FEED_METHODS, key=key, on_change=feed_row_change, args=args)
                elif field == "include":
                    st.checkbox(label + " " + str(number), key=key, on_change=feed_row_change, args=args)
                else:
                    st.text_input(label + " " + str(number), key=key, max_chars=600 if field == "formula" else 80, on_change=feed_row_change, args=args)
            descriptions = {"primary": "T-section hourly rate", "backup": "T-section backup hourly rate", "manual": "Manually edited", "unknown": "No usable hourly rate"}
            st.caption("Rate source: " + descriptions[row["rate_source"]])
            if row["backup_intake"]:
                st.caption("Backup intake (volume only, not used as a rate): " + row["backup_intake"])


def update_gi_admin(rule_key: tuple, key: str, store: GitHubVault | None) -> None:
    if not require_admin():
        return
    ss = st.session_state
    old = next((r for r in ss["vault"]["settings"]["medication_gi_groups"] if (r["name"], r["route"], r["frequency"]) == rule_key), None)
    if old is None or key not in ss:
        return
    try:
        candidate = deepcopy(ss["vault"])
        row = dict(zip(("name", "route", "frequency"), rule_key))
        candidate["settings"]["medication_gi_groups"] = set_gi_rule(candidate["settings"]["medication_gi_groups"], row, ss[key])
        if ss[key] not in ("auto", "other"):
            candidate["settings"]["medication_groups"] = set_group_rule(candidate["settings"]["medication_groups"], row, "auto")
        commit(candidate, store)
        reapply_open_mappings()
        note("FEN/GI display choice saved.", "success")
    except (ValueError, StorageError) as exc:
        ss[key] = old["mode"]
        note(str(exc), "error")


def gi_admin(store: GitHubVault | None) -> None:
    with st.expander("FEN/GI display choices", expanded=False):
        st.caption("Automatic GI prophylaxis: famotidine, omeprazole, pantoprazole. Automatic Bowel Regimen: docusate, lactulose, polyethylene glycol, glycerin suppositories, sennosides. Diuretics: bumetanide, chlorothiazide, furosemide. Antiemetics: ondansetron (Zofran). Endocrine Medications: levothyroxine, insulin including Lantus, and metformin. These are display groups, not inferred indications.")
        st.caption("To override a default, use a medication's FEN/GI display control. Choosing another system turns off its automatic GI grouping. The original order and hidden-medication choice stay intact.")
        rules = st.session_state["vault"]["settings"]["medication_gi_groups"]
        for index, rule in enumerate(rules):
            st.text(rule["name"] + " | " + rule["route"] + " | " + rule["frequency"])
            key = "gi_rule_mode_" + str(index)
            if key not in st.session_state:
                st.session_state[key] = rule["mode"]
            st.selectbox("GI display choice " + str(index + 1), GI_MODES, key=key, format_func=lambda value: GI_MODE_LABELS[value], on_change=update_gi_admin, args=((rule["name"], rule["route"], rule["frequency"]), key, store))
        if not rules:
            st.caption("No overrides saved. The automatic defaults apply.")



def update_group_admin(rule_key: tuple, key: str, store: GitHubVault | None) -> None:
    if not require_admin():
        return
    ss = st.session_state
    old = next((r for r in ss["vault"]["settings"]["medication_groups"] if (r["name"], r["route"], r["frequency"]) == rule_key), None)
    if old is None or key not in ss:
        return
    try:
        candidate = deepcopy(ss["vault"])
        row = dict(zip(("name", "route", "frequency"), rule_key))
        candidate["settings"]["medication_groups"] = set_group_rule(candidate["settings"]["medication_groups"], row, ss[key])
        commit(candidate, store)
        reapply_open_mappings()
        note("Medication display group saved.", "success")
    except (ValueError, StorageError) as exc:
        ss[key] = old["mode"]
        note(str(exc), "error")


def save_antiepileptic_names(store: GitHubVault | None) -> None:
    if not require_admin():
        return
    ss = st.session_state
    from medications import match_name
    import re
    names = list(dict.fromkeys(match_name(line) for line in ss.get("antiepileptic_extra_names", "").splitlines() if line.strip()))
    if len(names) > 100 or any(not re.fullmatch(r"[a-z][a-z -]{1,100}", n) for n in names):
        note("Enter generic medication names only, one per line.", "error")
        return
    candidate = deepcopy(ss["vault"])
    rules = [r for r in candidate["settings"]["medication_groups"] if r.get("match") != "prefix"]
    rules.extend({"name": n, "route": "", "frequency": "", "mode": "antiepileptic", "match": "prefix"} for n in names)
    candidate["settings"]["medication_groups"] = rules
    try:
        commit(candidate, store)
        reapply_open_mappings()
        note("Additional Antiepileptic names saved. Existing per-order overrides still take priority.", "success")
    except (StorageError, ValidationError, ValueError) as exc:
        note(str(exc), "error")


def install_bmi_reference() -> None:
    if not require_admin():
        return
    try:
        download_reference()
        note("Public CDC BMI reference loaded. No patient information was sent.", "success")
    except Exception:
        note("The public CDC reference could not be downloaded. BMI values still display, but percentiles stay unavailable. Use the reference-file upload in Admin.", "error")


def upload_bmi_reference() -> None:
    if not require_admin():
        return
    file = st.session_state.get("bmi_public_reference_upload")
    if file is None:
        return
    try:
        install_reference(file.getvalue())
        note("Public CDC BMI reference validated and loaded.", "success")
    except Exception:
        note("This is not a complete supported CDC BMI reference CSV. No reference was changed.", "error")


def group_admin(store: GitHubVault | None) -> None:
    with st.expander("Antiepileptic medications", expanded=False):
        st.caption("Automatic: phenytoin, fosphenytoin, phenobarbital, clobazam, levetiracetam, valproic acid and pentobarbital. Add more generic names below. This controls display, not a medication indication.")
        if "antiepileptic_extra_names" not in st.session_state:
            st.session_state["antiepileptic_extra_names"] = "\n".join(r["name"] for r in st.session_state["vault"]["settings"]["medication_groups"] if r.get("match") == "prefix")
        st.text_area("Additional generic names, one per line", key="antiepileptic_extra_names", max_chars=10000)
        st.button("Save Antiepileptic names", on_click=save_antiepileptic_names, args=(store,))
    with st.expander("BMI reference data", expanded=False):
        st.caption("CDC BMI-for-age, ages 2 through 19. Reference only, no patient data. Data is local to this deployment, not stored in the patient archive.")
        st.caption("Reference available" if REFERENCE_PATH.exists() else "Reference not loaded yet")
        st.button("Load / refresh public CDC BMI reference", on_click=install_bmi_reference)
        st.file_uploader("Or upload CDC bmi-age-2022.csv (public reference only)", type=["csv"], key="bmi_public_reference_upload", on_change=upload_bmi_reference)
    with st.expander("Medication subgroup choices", expanded=False):
        st.caption("DVT Prophylaxis: enoxaparin, cangrelor and heparin with an explicit Units/kg/hr Dose. Fever Control: acetaminophen and ibuprofen. PRN: the requested sedative PRNs. Paralytic PRN: rocuronium, cisatracurium and vecuronium PRNs.")
        st.caption("Neurologic: melatonin/trazodone under Insomnia, baclofen under Antispasmodic, and gabapentin/pregabalin under Neuromodulation. Infusions, PRN and paralytic groups come first after observations; other category headings are alphabetical.")
        st.caption("Respiratory: Airway/Cerebral Steroids, Beta-Agonist, Anticholinergic, Methylxanthine, Corticosteroid, Airway Tone Modulator, Inhaled Corticosteroids, Pulmonary Hypertension, and Antisialorrhea Agents. Cardiovascular: Antiarrhythmics, Antihypertensives, Inotrope Infusions, Vasopressors, Adrenocortical Support, and Vasodilators. Lidocaine is automatic only for an IV infusion. Endocrine Medications is in FEN/GI display choices.")
        st.caption("These are user-defined display labels, not inferred indications or a determination that a dose is prophylactic. Original orders and hidden-medication choices are preserved. Overrides use the formulation, route and frequency.")
        rules = [r for r in st.session_state["vault"]["settings"]["medication_groups"] if r.get("match") != "prefix"]
        for index, rule in enumerate(rules):
            st.text(rule["name"] + " | " + rule["route"] + " | " + rule["frequency"])
            key = "group_rule_mode_" + str(index)
            if key not in st.session_state:
                st.session_state[key] = rule["mode"]
            st.selectbox("Medication group choice " + str(index + 1), GROUP_MODES, key=key,
                         format_func=lambda value: GROUP_MODE_LABELS[value], on_change=update_group_admin,
                         args=((rule["name"], rule["route"], rule["frequency"]), key, store))
        if not rules:
            st.caption("No overrides saved. The automatic defaults apply.")


def acknowledge_import_warning(room: str, section: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    sheet = st.session_state["drafts"][room]
    sheet["import_warnings"].pop(section, None)
    note("Review acknowledged. No clinical value was changed. The reviewed handoff will save when you change rooms.")


def import_review_editor(sheet: dict, compact: bool = False) -> None:
    summary = review_summary(sheet)
    if not summary:
        return
    if not compact:
        st.warning(summary)
    with st.expander("Review skipped or incomplete imports", expanded=False):
        st.caption("Valid sections were updated. An unreadable section keeps its previous values with this warning. Failed orders, diet, feeds, device, pacemaker and ECG imports are retained for review but hidden from print. Import warnings appear only here, not on downloaded handoffs. Do not treat skipped values as refreshed.")
        for section, items in sheet["import_warnings"].items():
            if not compact:
                for item in items:
                    st.text(diagnostic_text(item))
            label = ("Use retained orders after checking Epic" if section == 'r' else
                     "Use retained diet after checking Epic" if section == "x" and any(i["action"] == "diet_hidden" for i in items) else
                     "Use retained feeds after checking Epic" if section == 't' and any(i['action'] == 'feeds_hidden' for i in items) else
                     "Use retained pacemaker settings after checking Epic" if section == "w" and any(i["action"] == "pacemaker_hidden" for i in items) else
                     "Use retained QTc after checking Epic" if section == "z" and any(i["action"] == "ecg_hidden" for i in items) else
                     "Use retained devices after checking Epic" if section in ('u', 'v') and any(i['action'].endswith('_hidden') for i in items) else
                     "Acknowledge reviewed omissions" if any(i['action'].endswith('omitted') for i in items) else
                     "Accept retained values after checking Epic")
            st.button(label + " (" + REVIEW_SECTIONS[section] + ")", key="accept_import_" + sheet["id"] + "_" + section,
                      on_click=acknowledge_import_warning, args=(sheet["room"], section))


def send_pending_errors(store: GitHubVault | None) -> None:
    if not require_session():
        return
    ss = st.session_state
    pending = ss.setdefault("pending_error_events", {})
    if not pending:
        ss.pop("error_log_notice", None)
        return
    if store is None:
        ss["error_log_notice"] = "Technical errors are session-only. Shared storage is not enabled."
        return
    try:
        journal = ErrorJournal(store)
        for ident, record in list(pending.items()):
            sha = journal.save_new(record)
            ss.setdefault("saved_error_events", {})[ident] = {"record": record, "sha": sha}
            pending.pop(ident, None)
        ss.pop("error_log_notice", None)
        ss["error_log_saved"] = True
    except Exception:
        # Logging failure must not discard a clinical draft or leak raw details.
        ss["error_log_notice"] = "The shared error log was not saved. Your imported handoff is still available. Retry in Import errors before closing this session."


def refresh_error_log(store: GitHubVault | None) -> None:
    if not require_session():
        return
    ss = st.session_state
    if store is None:
        note("Shared error storage is not enabled. Only this session's records are available.")
        return
    try:
        records, notices = ErrorJournal(store).load_month(ss.get("error_log_month", datetime.now(timezone.utc).strftime("%Y-%m")), limit=100)
        ss["loaded_error_events"] = {x['record']['id']: x for x in records}
        ss["loaded_error_month"] = ss["error_log_month"]
        ss["error_list_notices"] = notices
    except (StorageError, ValueError):
        note("The shared error log could not be refreshed. The previous displayed list has not been changed.", "error")


def set_error_review(ident: str, status: str, store: GitHubVault | None) -> None:
    if not require_session():
        return
    ss = st.session_state
    records = dict(ss.get("saved_error_events", {}))
    records.update(ss.get("loaded_error_events", {}))
    record = records.get(ident)
    if record is None or store is None:
        note("Load the saved error record before changing its status.", "error")
        return
    try:
        updated = ErrorJournal(store).set_status(record['record'], record['sha'], status)
        for key in ('saved_error_events', 'loaded_error_events'):
            ss.setdefault(key, {})[ident] = updated
        note("Shared error review status saved.", "success")
    except (StorageError, ValueError):
        note("The review change was not saved. Another team member may have changed it. Refresh the shared log and retry.", "error")


def import_errors_page(store: GitHubVault | None) -> None:
    st.title("Import errors")
    ss = st.session_state
    st.caption("Shared technical reports in the existing shared archive. These reports contain app version, event time, section, error code and row/column positions only. No patient text, clinical values, rooms, names, MRNs, or staff identity are logged.")
    st.caption("This uses the app's existing sign-in. It is not an individual staff audit trail. Marking a report resolved does not change any handoff or remove Git history.")
    if "error_log_month" not in ss:
        ss["error_log_month"] = datetime.now(timezone.utc).strftime("%Y-%m")
    st.text_input("Error log month (UTC, YYYY-MM)", key="error_log_month", max_chars=7)
    st.button("Refresh shared errors", key="refresh_shared_errors", on_click=refresh_error_log, args=(store,), disabled=store is None)
    pending = ss.get("pending_error_events", {})
    if pending:
        st.warning(str(len(pending)) + " technical report(s) are not saved to shared storage and exist only in this session.")
        st.button("Retry saving errors", key="retry_error_upload", on_click=send_pending_errors, args=(store,), disabled=store is None)
    for message in ss.get("error_list_notices", []):
        st.warning(message)
    records = dict(ss.get("saved_error_events", {}))
    records.update(ss.get("loaded_error_events", {}))
    records.update({key: {"record": value, "sha": None} for key, value in pending.items()})
    month = ss.get("error_log_month", "")
    rows = sorted((value for value in records.values() if value["record"]["created_at"].startswith(month)), key=lambda x: x["record"]["created_at"], reverse=True)
    if not rows:
        st.info("No error records loaded for this month. Refresh to retrieve reports from other sessions.")
        return
    safe_report = [value["record"] for value in rows]
    st.download_button("Download technical error report (JSON)", json.dumps(safe_report, indent=2).encode("utf-8"),
                       "import_errors.json", "application/json")
    for value in rows:
        record = value["record"]
        ident = record["id"]
        saved = bool(value["sha"])
        title = record["created_at"] + " | " + record["status"] + " | " + ident[:12] + ("" if saved else " | NOT SAVED")
        with st.expander(title, expanded=False):
            st.caption("App version " + record["app_version"] + " | " + ident)
            for item in record["diagnostics"]:
                st.text(diagnostic_text(item))
                st.caption("Code: " + item["code"])
            status = "resolved" if record["status"] == "open" else "open"
            st.button("Mark resolved" if status == "resolved" else "Reopen", key="resolve_error_" + ident,
                      on_click=set_error_review, args=(ident, status, store), disabled=not saved or store is None)


def admin_config() -> dict:
    """Read current server secrets again in callbacks. No client-supplied hashes."""
    try:
        value = st.secrets.to_dict().get("app", {})
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def require_admin() -> bool:
    if not require_session():
        return False
    if admin_valid(st.session_state, admin_config(), touch=True):
        return True
    note("Unlock Admin with the separate Admin password before making this change.", "error")
    return False


def authenticate_admin() -> None:
    password = st.session_state.pop("admin_login_password", "")
    if not require_session():
        return
    unlock_admin(st.session_state, admin_config(), password)


def lock_admin_page() -> None:
    lock_admin(st.session_state)
    st.session_state.pop("admin_login_error", None)


def autosave_before_print_all(store: GitHubVault | None) -> bool:
    """Save current editor values before Streamlit removes the editor widgets.

    The existing guarded room-save path preserves inline mapping behavior.
    Other changed open drafts are then saved in one batch. Any failure blocks
    Print all and leaves edits available. Unchanged sheets are not re-stamped.
    """
    if not require_session():
        return False
    ss = st.session_state
    if not autosave_before_room_change(store, for_print=True):
        return False
    changed = [room for room, draft in ss.get("drafts", {}).items()
               if draft != ss["vault"]["rooms"].get(room)]
    if changed and not save_rooms(store, changed):
        return False
    return True


def workspace_changed(store: GitHubVault | None = None) -> None:
    ss = st.session_state
    if ss.get("page") != "Admin":
        lock_admin(ss)
    if ss.get("page") == "Print all":
        if not autosave_before_print_all(store):
            # Callback executes before the navigation widget is rendered.
            # Return to the editor instead of offering an unsaved print packet.
            if ss.get("authenticated"):
                ss["page"] = "Handoff"
            return
        discard_editor_widget_values()
    elif ss.get("active_workspace", "Handoff") == "Handoff":
        # Preserve a just-blurred field when moving to another workspace too,
        # without introducing a new save action for Admin / Import errors.
        room = ss.get("current_room")
        if room and room in ss.get("drafts", {}):
            try:
                ss["drafts"][room] = editor_snapshot(room)
            except (ValueError, TypeError, KeyError):
                ss["page"] = "Handoff"
                note("Correct the invalid editor value before leaving Handoff.", "error")
                return
    ss["active_workspace"] = ss.get("page", "Handoff")


def admin_gate() -> bool:
    if not require_session():
        return False
    config = admin_config()
    if admin_valid(st.session_state, config, touch=True):
        return True
    problem = admin_config_error(config)
    if problem:
        st.info(problem)
        st.caption("The setup helper adds one Admin password hash only. Keep your app password and encryption key unchanged.")
        return False
    st.caption("Enter the separate Admin password to change shared settings. You do not need it to create, edit, save, print, or clear handoffs, or to read the user guide.")
    with st.form("admin_unlock"):
        st.text_input("Admin password", type="password", key="admin_login_password", max_chars=1024)
        st.form_submit_button("Unlock Admin", on_click=authenticate_admin)
    if st.session_state.get("admin_login_error"):
        st.error(st.session_state["admin_login_error"])
    return False


def admin_visibility_rule(name: str, hidden: bool, match: str, store: GitHubVault | None) -> None:
    if require_admin():
        change_visibility_rule(name, hidden, match, store)


def admin_undo_room_removal(store: GitHubVault | None) -> None:
    if require_admin():
        undo_room_removal(store)


def load_user_guide(store: GitHubVault | None, refresh: bool = False) -> dict:
    if not require_session():
        return default_guide()
    ss = st.session_state
    if ss.get("guide_loaded") and not refresh:
        return ss["user_guide"]
    try:
        guide, sha = GuideStore(store).load() if store else (ss.get("user_guide", default_guide()), None)
    except (StorageError, ValueError):
        ss["guide_load_error"] = "The published guide could not be loaded. Any previously loaded copy is shown below. Return to Handoff to retry, or reload the published guide in Admin. No guide or handoff was overwritten."
        return ss.get("user_guide", default_guide())
    ss.update(user_guide=guide, guide_sha=sha, guide_loaded=True)
    ss.pop("guide_load_error", None)
    return guide


def refresh_user_guide(store: GitHubVault | None) -> None:
    if require_session():
        load_user_guide(store, refresh=True)


def render_smartphrase(guide: dict, key: str) -> None:
    st.subheader("Team Epic SmartPhrase")
    if guide["smartphrase_name"].strip():
        st.caption("SmartPhrase name to use in Epic")
        st.code(guide["smartphrase_name"], language=None)
    else:
        st.info("The administrator has not published the SmartPhrase name yet.")
    if guide["setup_notes"].strip():
        st.markdown(guide["setup_notes"], unsafe_allow_html=False)
    if guide["smartphrase_text"].strip():
        st.caption("Reusable source definition for Epic, not a patient's results. Use the copy control on the code box or download the text. Run it in Epic first, then paste the generated patient text into Handoff.")
        st.code(guide["smartphrase_text"], language=None, wrap_lines=False, height=240)
        st.download_button("Download SmartPhrase source", guide["smartphrase_text"].encode("utf-8"),
                           "Epic_SmartPhrase_Source.txt", "text/plain", key=key + "_source")
    else:
        st.caption("The source definition is not published yet. Ask your administrator to add your team's actual Epic SmartLinks in Admin. Sample patient results are not a source template.")


def prepare_guide_editor(guide: dict, reset: bool = False) -> None:
    ss = st.session_state
    fields = ("smartphrase_name", "smartphrase_text", "setup_notes", "instructions")
    if reset or "guide_editor_sha" not in ss or not any("guide_edit_" + field in ss for field in fields):
        ss["guide_editor_sha"] = ss.get("guide_sha")
        for field in fields:
            ss["guide_edit_" + field] = handoff_instructions(guide) if field == "instructions" else guide[field]
    else:
        for field in fields:
            ss.setdefault("guide_edit_" + field, handoff_instructions(guide) if field == "instructions" else guide[field])


def load_published_guide_into_editor(store: GitHubVault | None) -> None:
    if not require_admin():
        return
    guide = load_user_guide(store, refresh=True)
    if not st.session_state.get("guide_load_error"):
        prepare_guide_editor(guide, reset=True)
        note("Published guide loaded into the editor. The previous guide draft was replaced.")


def save_user_guide(store: GitHubVault | None) -> None:
    if not require_admin():
        return
    ss = st.session_state
    if not ss.get("guide_loaded") or ss.get("guide_load_error") or "guide_editor_sha" not in ss:
        note("Load the published guide before saving. No changes were saved.", "error")
        return
    try:
        guide = publication(ss.get("guide_edit_smartphrase_name", ""), ss.get("guide_edit_smartphrase_text", ""),
                            ss.get("guide_edit_setup_notes", ""), ss.get("guide_edit_instructions", ""))
        sha = GuideStore(store).save(guide, ss["guide_editor_sha"]) if store else None
    except (StorageError, ValueError) as exc:
        note(str(exc), "error")
        return
    ss.update(user_guide=guide, guide_sha=sha, guide_editor_sha=sha, guide_loaded=True)
    ss.pop("guide_load_error", None)
    note("Guide and SmartPhrase published to shared storage. The short instructions update when users return to Handoff." if store else
         "Guide saved in this session only. Enable the existing encrypted storage for shared persistence.", "success")


def guide_admin(store: GitHubVault | None) -> None:
    if not require_admin():
        return
    st.subheader("User instructions and Epic SmartPhrase")
    st.caption("Edit reusable teaching content here, not expanded patient results, passwords or tokens. Saving this page does not change any room handoff, clinical parser, medication rule or Epic record.")
    guide = load_user_guide(store)
    if st.session_state.get("guide_load_error"):
        st.warning(st.session_state["guide_load_error"])
    if guide["updated_at"]:
        st.caption(("Last published: " if store else "Last session-only save: ") + saved_time_text(guide["updated_at"]))
    prepare_guide_editor(guide)
    with st.form("guide_edit_form"):
        st.text_input("Epic SmartPhrase name / shortcut", key="guide_edit_smartphrase_name", max_chars=120)
        st.text_area("Reusable Epic SmartPhrase source text", key="guide_edit_smartphrase_text", height=230, max_chars=MAX_TEMPLATE)
        st.text_area("Local Epic setup notes (optional)", key="guide_edit_setup_notes", height=100, max_chars=MAX_NOTES)
        st.text_area("Short instructions shown at the top of Handoff", key="guide_edit_instructions", height=160, max_chars=MAX_INSTRUCTIONS)
        st.form_submit_button("Save instructions and SmartPhrase", on_click=save_user_guide, args=(store,))
    st.caption("Save instructions before leaving Admin. Keep the paired section dividers intact. Test template changes in Epic with synthetic data before sharing. Saving here does not install or update a SmartPhrase inside Epic.")
    st.button("Reload published guide into editor", on_click=load_published_guide_into_editor, args=(store,))
    st.caption("Reload replaces the unsaved guide draft. Copy any changes you need before reloading.")
    with st.expander("Published instructions preview", expanded=False):
        st.markdown(handoff_instructions(guide), unsafe_allow_html=False)
    st.divider()


def problem_display_change(room: str, widget: str) -> None:
    if not require_session() or room != st.session_state.get('current_room'):
        return
    sheet = deepcopy(st.session_state['drafts'][room])
    data = deepcopy(sheet.get('problem_review', empty_review()))
    data['enabled'] = bool(st.session_state[widget])
    sheet['problem_review'] = data
    validate_sheet(sheet)
    st.session_state['drafts'][room] = sheet


def problem_decision_change(room: str, key: str, fingerprint: str, status_widget: str, text_widget: str) -> None:
    if not require_session() or room != st.session_state.get('current_room'):
        return
    ss = st.session_state
    sheet = ss['drafts'][room]
    current = next((r for r in suggestions(sheet) if r['key'] == key), None)
    if current is None or current['fingerprint'] != fingerprint:
        note('The supporting information changed. Review the refreshed suggestion before applying a decision.', 'warning')
        return
    try:
        candidate = set_decision(sheet, key, fingerprint, ss[status_widget], ss[text_widget])
        validate_sheet(candidate)
    except ValueError as exc:
        ss[status_widget] = current['status']
        ss[text_widget] = current['label']
        note(str(exc), 'error')
        return
    ss['drafts'][room] = candidate


def save_problem_limits(room: str, prefix: str) -> None:
    if not require_session() or room != st.session_state.get('current_room'):
        return
    ss = st.session_state
    sheet = deepcopy(ss['drafts'][room])
    data = deepcopy(sheet.get('problem_review', empty_review()))
    limits = {}
    for key in LOW_RULES:
        value = str(ss.get(prefix + key + '_value', '')).strip()
        unit = str(ss.get(prefix + key + '_unit', '')).strip()
        if value:
            limits[key] = {'value': value, 'unit': unit}
    data['low_limits'] = limits
    try:
        validate_review(data)
        sheet['problem_review'] = data
        validate_sheet(sheet)
    except ValueError as exc:
        note(str(exc), 'error')
        return
    ss['drafts'][room] = sheet
    note('Patient-specific review limits updated. Save the handoff to retain them.', 'success')


def problem_review_editor(sheet: dict) -> None:
    st.subheader('Problems')
    st.caption('The handoff prints a compact, comma-separated Problems line. Supporting details stay here. You can edit or hide items without a required confirmation step. Medication or device triggers alone do not confirm a diagnosis.')
    data = sheet.get('problem_review', empty_review())
    key = 'problem_' + sheet['id'] + '_enabled'
    st.session_state.setdefault(key, data['enabled'])
    st.checkbox('Show the compact Problems line on the handoff', key=key,
                on_change=problem_display_change, args=(sheet['room'], key))
    items = suggestions(sheet)
    if not items:
        st.info('No automatic problems to display. This does not confirm normal results or a complete problem list.')
    for item in items:
        prefix = 'problem_' + sheet['id'] + '_' + item['key'] + '_' + item['fingerprint'][:12]
        text_key, status_key = prefix + '_text', prefix + '_status'
        st.session_state.setdefault(text_key, item['label'])
        st.session_state.setdefault(status_key, item['status'])
        with st.expander(item['label'] + (' (hidden)' if item['status'] == 'dismissed' else ''), expanded=False):
            st.text(item['evidence'])
            st.caption(item['caution'])
            args = (sheet['room'], item['key'], item['fingerprint'], status_key, text_key)
            st.text_input('Problem wording', key=text_key, max_chars=200,
                          on_change=problem_decision_change, args=args)
            st.selectbox('Display choice', PROBLEM_STATUSES, key=status_key,
                         format_func=lambda x: {'review':'Show automatic wording', 'confirmed':'Confirmed by me', 'dismissed':'Hide from handoff'}[x],
                         on_change=problem_decision_change, args=args)
    for message in limitation_notes(sheet):
        st.caption(message)
    with st.expander('Patient-specific low-result limits (optional)', expanded=False):
        st.caption('Source L / LL / LOW flags still count as low. Asterisk-flagged hemoglobin below 11.5 g/dL adds Anemia, and asterisk-flagged platelets below 175 K/uL adds Thrombocytopenia. These are your configured workflow cutoffs, not age-specific diagnostic reference ranges. A patient-specific limit below overrides the default for that component. Other asterisk-only results need a verified low limit. Missing or mismatched units prevent numeric comparison.')
        prefix = 'problem_limit_' + sheet['id'] + '_'
        with st.form('problem_limits_' + sheet['id']):
            for component in LOW_RULES:
                saved = data['low_limits'].get(component, {})
                value_key, unit_key = prefix + component + '_value', prefix + component + '_unit'
                st.session_state.setdefault(value_key, saved.get('value', ''))
                st.session_state.setdefault(unit_key, saved.get('unit', ''))
                left, right = st.columns(2)
                left.text_input(PROBLEM_LAB_LABELS[component] + ' low limit', key=value_key, max_chars=20)
                right.text_input(PROBLEM_LAB_LABELS[component] + ' source units', key=unit_key, max_chars=50)
            st.form_submit_button('Apply patient-specific limits', on_click=save_problem_limits, args=(sheet['room'], prefix))
    st.caption('Prompts skip failed imports, excluded/hidden medication orders, held or future orders, and preadmission lab results when admission is known. Kidney review uses a >50% rise between the latest two comparable creatinine results with an established order within 7 days. A fall or a same-date pair without times does not establish that rise.')



def smartphrase_publish_caption(guide: dict, session_only: bool = False, stale: bool = False) -> str:
    """Actual successful shared-guide publication, never the app build/room save."""
    if not guide.get("smartphrase_text", "").strip():
        return "SmartPhrase: not published yet."
    stamp = guide.get("updated_at")
    if not stamp:
        return "SmartPhrase: publication date not available."
    label = "SmartPhrase saved in this session only: " if session_only else "SmartPhrase published: "
    result = label + saved_time_text(stamp)
    return result + (" (last loaded copy, refresh failed)" if stale else "")


def difficult_airway_change(room: str, sheet_id: str) -> None:
    if not require_session() or room != st.session_state.get("current_room"):
        return
    ss = st.session_state
    sheet = deepcopy(ss["drafts"][room])
    if sheet["id"] != sheet_id:
        return
    try:
        sheet["difficult_airway"] = collect_airway(sheet, ss)
        validate_sheet(sheet)
    except ValueError as exc:
        note(str(exc), "error")
        return
    ss["drafts"][room] = sheet


def difficult_airway_editor(sheet: dict) -> None:
    st.subheader("Difficult airway")
    st.caption("Record the team's documented airway findings and plan. This section does not infer airway difficulty or generate a rescue plan.")
    data = sheet.get("difficult_airway") or empty_airway()
    prefix = "dairway_" + sheet["id"] + "_"
    for field in AIRWAY_FIELDS:
        st.session_state.setdefault(prefix + field, data[field])
    args = (sheet["room"], sheet["id"])
    st.checkbox("This patient has a difficult airway", key=prefix + "enabled",
                on_change=difficult_airway_change, args=args)
    if not st.session_state[prefix + "enabled"]:
        st.caption("Nothing is added to the handoff while this is off. Previously entered details are kept for this patient only.")
        return
    st.selectbox("Can the patient be ventilated with a bag-mask?", MASK_OPTIONS,
                 key=prefix + "mask_ventilation", on_change=difficult_airway_change, args=args)
    st.selectbox("Was the tracheal tube difficult to pass?", PASSAGE_OPTIONS,
                 key=prefix + "tube_passage", on_change=difficult_airway_change, args=args)
    labels = {"view": "View obtained (documented grade or description)",
              "equipment": "Technique / equipment used",
              "tube_details": "Successful route / tube details (optional)",
              "issue": "Key difficulty / brief description",
              "plan": "Agreed airway plan / who to call (optional)",
              "source": "Assessment date/time or source (optional)"}
    for field, label in labels.items():
        st.text_input(label, key=prefix + field, max_chars=AIRWAY_LIMITS[field],
                      on_change=difficult_airway_change, args=args)
    preview = dict(sheet, difficult_airway=collect_airway(sheet, st.session_state))
    st.markdown('<div style="border:2px solid #8b1e16;background:#fff0ed;padding:10px">'
                '<strong>DIFFICULT AIRWAY:</strong> ' + airway_summary(preview, True) + '</div>',
                unsafe_allow_html=True)
    st.caption("Save handoff or change rooms to save these details. New-patient reset clears this section.")


if __name__ == "__main__":
    try:
        main()
    except (ValidationError, StorageError) as error:
        st.error(str(error))
    except Exception:
        st.error("The app encountered an unexpected problem. No save is confirmed. Keep your draft and reproduce with the synthetic example when troubleshooting.")
