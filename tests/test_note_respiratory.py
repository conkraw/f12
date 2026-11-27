"""Respiratory template choices from synthetic current handoff sources."""
from copy import deepcopy
from pathlib import Path

import pytest

from devices import parse_devices
from importing import import_sections
from models import new_sheet, new_vault
from note_respiratory import (
    RESP_TEMPLATE_FILES,
    RESP_TEMPLATE_LABELS,
    RESP_TEMPLATE_NAMES,
    select_respiratory_variant,
)


def imported(c=None, d=None, sheet=None):
    source = ""
    if c is not None:
        source += "cccccccc\n" + c + "\ncccccccc\n"
    if d is not None:
        source += "dddddddd\n" + d + "\ndddddddd\n"
    result = import_sections(sheet or new_sheet("P4102"), source, new_vault()["settings"])
    assert not result.errors, result.errors
    return result.sheet


def mode_sheet(mode="PRVC", extra=""):
    return imported("Invasive Ventilation:\nVent Mode: " + mode + "\n" + extra)


def delivery(name="High flow nasal cannula", extra="O2 Flow Rate (L/min): 20 L/min"):
    return "Non-invasive Ventilation:\nO2 Delivery Method: " + name + "\n" + extra


PRESSURES = "Total Inspiratory Pressure (cm H2O): 12 cmH20\nExpiratory Positive Airway Pressure (EPAP) (cmH20): 6 cmH20"
BILEVEL = "Invasive Ventilation:\nVent Mode: Bilevel Non Invasive Ventilation\nFiO2 (%): 30 %"
MAIN_HISTORY = """Invasive Ventilation:
Vent Mode: PRVC-IMV
Resp Rate (Set): 14
Vt (Set, mL): 100
PEEP (cm H2O): 5
NAVA Ventilator Settings:
NAVA level: 2
PEEP (cm H2O): 7
CPAP Trial Settings:
Pressure Support (cm H2O): 8
PEEP (cm H2O): 6
All Vent Modes:
"""


def airway(sheet, text="ETT 4.0 mm-Status: In place", section="u"):
    parsed = parse_devices(text, section)
    assert not parsed.error, parsed.error
    sheet["devices" if section == "u" else "neuro_devices"] = parsed.data
    return sheet


def choice(sheet):
    result = select_respiratory_variant(sheet)
    assert set(result) == {"variant", "phrase", "label", "reason", "warning"}
    assert result["phrase"] == RESP_TEMPLATE_NAMES[result["variant"]]
    assert result["label"] == RESP_TEMPLATE_LABELS[result["variant"]]
    assert all(isinstance(value, str) for value in result.values())
    assert result["reason"]
    return result


def test_eight_original_template_paths_and_exact_phrase_names():
    expected = {
        "pc": "ACKRPC", "prvc": "ACKRPRVC", "avaps": "ACKRAVAPS",
        "bpap": "ACKRBPAP", "hfnc": "ACKRHFNC", "none": "ACKRNONE",
        "nava": "ACKRNAVA", "home_vent": "ACKRHOMEVENT",
    }
    assert RESP_TEMPLATE_NAMES == expected
    assert set(RESP_TEMPLATE_FILES) == set(RESP_TEMPLATE_LABELS) == set(expected)
    for variant, path in RESP_TEMPLATE_FILES.items():
        assert path == Path(__file__).parents[1] / "templates" / ("resp_" + variant + ".docx")
        assert path.is_file()


@pytest.mark.parametrize("mode,expected", [
    ("PC", "pc"),
    ("Pressure Control", "pc"),
    ("Pressure Control - Intermittent Mandatory Ventilation", "pc"),
    ("Pressure Control - Continuous Mandatory Ventilation", "pc"),
    ("SIMV/PC", "pc"),
    ("(S) PC - CMV", "pc"),
    ("PRVC", "prvc"),
    ("Volume Targeted Pressure Control - PS", "prvc"),
    ("Volume Targeted PC - IMV", "prvc"),
    ("Volume Targeted Pressure Control - Continuous Mandatory Ventilation", "prvc"),
    ("Volume Control", "prvc"),
    ("VC-CMV", "prvc"),
    ("Volume Control - Intermittent Mandatory Ventilation", "prvc"),
    ("Volume Support Ventilation", "prvc"),
    ("VSV", "prvc"),
    ("AVAPS", "avaps"),
    ("Average Volume-Assured Pressure Support", "avaps"),
    ("NAVA", "nava"),
    ("Neurally Adjusted Ventilatory Assist", "nava"),
])
def test_current_imported_mode_selects_matching_body(mode, expected):
    result = choice(mode_sheet(mode))
    assert result["variant"] == expected
    assert not result["warning"]


def test_volume_layout_reason_does_not_relabel_vc_as_prvc():
    result = choice(mode_sheet("Volume Control"))
    assert result["variant"] == "prvc"
    assert "volume-targeted" in result["reason"]
    assert "PRVC" not in result["reason"]


@pytest.mark.parametrize("mode", ["PC", "PRVC", "Volume Control", "VSV"])
def test_current_pmin_selects_home_vent_before_generic_control_family(mode):
    sheet = mode_sheet(mode, "Pmin: 8 cm H2O\nPmax: 25 cm H2O\nTimin: 0.5\nTimax: 1.2")
    assert choice(sheet)["variant"] == "home_vent"


@pytest.mark.parametrize("value", ["0", "8", "+8 cm H2O", "(S) 8 cm H2O"])
def test_pmin_reuses_existing_numeric_home_vent_rule(value):
    assert choice(mode_sheet("PC", "Pmin: " + value))["variant"] == "home_vent"


@pytest.mark.parametrize("value", ["", "UNK", "--", "N/A", "not documented"])
def test_blank_or_unknown_pmin_does_not_select_home_vent(value):
    assert choice(mode_sheet("PC", "Pmin: " + value))["variant"] == "pc"


@pytest.mark.parametrize("mode,expected", [("AVAPS", "avaps"), ("NAVA", "nava")])
def test_specific_invasive_modes_precede_pmin_home_vent_rule(mode, expected):
    assert choice(mode_sheet(mode, "Pmin: 8\nPmax: 25"))["variant"] == expected


@pytest.mark.parametrize("mode", ["HFOV", "HFJV", "APRV", "ASV", "PPS", "SIMV", "Unfamiliar mode"])
def test_unsupported_modes_do_not_inherit_a_different_mode_template(mode):
    sheet = new_sheet("P4102")
    sheet["ventilation"] = {"mode": mode, "values": {"Pmin": "8"}}
    result = choice(sheet)
    assert result["variant"] == "none"
    assert result["warning"]


@pytest.mark.parametrize("brand", ["Trilogy", "Astral", "LTV"])
def test_device_brand_and_tracheostomy_alone_do_not_imply_home_vent(brand):
    sheet = airway(new_sheet("P4102"), "Tracheostomy Bivona 4.0-Status: In place")
    sheet["fields"]["Respiratory"] = "Home device: " + brand
    assert choice(sheet)["variant"] == "none"
    sheet["ventilation"] = {"mode": "PC", "values": {}}
    assert choice(sheet)["variant"] == "pc"


def test_latest_confirmed_mode_wins_over_main_heading_and_old_modes():
    sheet = imported(MAIN_HISTORY + "Vent Mode: PRVC-IMV (11/20/26 1700 : Author)\nVent Mode: NAVA (11/20/26 1800 : Author)")
    assert sheet["ventilation"]["mode"] == "NAVA"
    assert choice(sheet)["variant"] == "nava"


def test_old_included_cpap_trial_and_home_values_do_not_replace_current_prvc():
    sheet = imported(MAIN_HISTORY + "\t11/20/26 1700\t11/20/26 1800\nOther\nVent Mode\tPS-CPAP\tPRVC-IMV")
    previous = sheet["ventilation"]["mode_history"]["other_modes"]
    assert previous and previous[0]["include"]
    previous[0]["values"]["Pmin"] = "8"
    assert choice(sheet)["variant"] == "prvc"


@pytest.mark.parametrize("rows", [
    "Vent Mode: PRVC-IMV (11/20/26 1700 : Author)\nVent Mode: Unfamiliar mode (11/20/26 1800 : Author)",
    "Vent Mode: PRVC-IMV (11/20/26 1800 : Author)\nVent Mode: NAVA (11/20/26 1800 : Author)",
])
def test_unconfirmed_newest_mode_never_reactivates_retained_settings(rows):
    sheet = imported(MAIN_HISTORY + rows)
    assert sheet["ventilation"]["mode_history"]["latest_confirmed"] is False
    result = choice(sheet)
    assert result["variant"] == "none" and result["warning"]


def test_nonempty_cached_source_mode_cannot_override_current_primary_mode():
    sheet = mode_sheet("PC")
    sheet["sbs_vent_mode"] = "NAVA"
    assert choice(sheet)["variant"] == "pc"
    sheet["ventilation"] = None
    assert choice(sheet)["variant"] == "none"


@pytest.mark.parametrize("mode", ["PS-CPAP", "PS - CPAP", "PS/CPAP", "PS CPAP", "PS – CPAP", "CPAP Trial Data", "Pressure Support - Continuous Positive Airway Pressure"])
def test_trial_without_a_current_underlying_mode_uses_basic_section(mode):
    sheet = new_sheet("P4102")
    sheet["ventilation"] = {"mode": mode, "values": {"Pmin": "8"}}
    result = choice(airway(sheet))
    assert result["variant"] == "none" and result["warning"]


@pytest.mark.parametrize("mode", ["PS-CPAP", "PS – CPAP", "Pressure Support - Continuous Positive Airway Pressure"])
def test_real_trial_source_plus_explicit_hfnc_uses_hfnc(mode):
    sheet = imported("Invasive Ventilation:\nVent Mode: " + mode + "\nPEEP (cm H2O): 5", delivery())
    assert {row["device"] for row in sheet["noninvasive"]} == {"CPAP", "HFNC"}
    assert choice(sheet)["variant"] == "hfnc"


def test_legacy_trial_snapshot_does_not_conflict_with_independent_hfnc():
    sheet = imported(d=delivery())
    sheet["ventilation"] = {"mode": "PS-CPAP", "values": {}}
    assert choice(sheet)["variant"] == "hfnc"


@pytest.mark.parametrize("mode", ["Bilevel Non Invasive Ventilation", "BiPAP", "Bi-PAP", "BI-LEVEL NIV"])
def test_named_bpap_with_documented_pressures_uses_bpap(mode):
    sheet = imported("Invasive Ventilation:\nVent Mode: " + mode, delivery("CPAP/Bi-PAP mask", PRESSURES))
    result = choice(sheet)
    assert result["variant"] == "bpap" and not result["warning"]


def test_named_bpap_and_flow_inferred_hfnc_does_not_create_device_conflict():
    sheet = imported(BILEVEL, delivery("CPAP/Bi-PAP mask", PRESSURES + "\nO2 Flow Rate (L/min): 20"))
    assert sheet["noninvasive"][1]["flow_inferred"]
    assert choice(sheet)["variant"] == "bpap"


def test_pressure_pair_and_mask_flow_alone_do_not_assert_bpap_or_hfnc():
    sheet = imported(d=delivery("CPAP/Bi-PAP mask", PRESSURES + "\nO2 Flow Rate (L/min): 20"))
    assert sheet["noninvasive"][0]["pressure_inferred"]
    assert sheet["noninvasive"][1]["flow_inferred"]
    result = choice(sheet)
    assert result["variant"] == "none" and result["warning"]


def test_explicit_hfnc_remains_usable_beside_inferred_pressure_pair():
    sheet = imported(d=delivery(extra=PRESSURES + "\nO2 Flow Rate (L/min): 20"))
    assert sheet["noninvasive"][0]["pressure_inferred"]
    assert choice(sheet)["variant"] == "hfnc"


@pytest.mark.parametrize("extra", ["O2 Flow Rate (L/min): 20 L/min", "", "O2 Flow Rate (L/min): (S) 5 L/min"])
def test_explicit_hfnc_does_not_require_a_calculated_flow(extra):
    sheet = imported(d=delivery(extra=extra))
    result = choice(sheet)
    assert result["variant"] == "hfnc" and not result["warning"]


def test_zero_flow_is_not_active_hfnc():
    assert choice(imported(d=delivery(extra="O2 Flow Rate (L/min): 0 L/min")))["variant"] == "none"


@pytest.mark.parametrize("name", ["Nasal cannula", "Low flow cannula", "Room air"])
def test_standard_cannula_or_room_air_uses_basic_without_warning(name):
    result = choice(imported(d=delivery(name, "O2 Flow Rate (L/min): 2 L/min")))
    assert result["variant"] == "none" and not result["warning"]


@pytest.mark.parametrize("mode", [
    "Continuous Positive Airway Pressure - Non Invasive Ventilation",
    "Average Volume-Assured Pressure Support - Non Invasive Ventilation",
    "Neurally Adjusted Ventilatory Assist - Non Invasive Ventilation",
])
def test_niv_modes_without_matching_supplied_body_keep_basic_section(mode):
    sheet = imported("Invasive Ventilation:\nVent Mode: " + mode + "\nPEEP (cm H2O): 6", delivery("CPAP/Bi-PAP mask", PRESSURES))
    result = choice(sheet)
    assert result["variant"] == "none" and result["warning"]
    assert "NIV" in result["reason"]


def test_explicit_bpap_and_explicit_hfnc_conflict_is_not_resolved_by_list_order():
    sheet = imported(BILEVEL, delivery(extra=PRESSURES + "\nO2 Flow Rate (L/min): 20"))
    assert not any(row["flow_inferred"] or row["pressure_inferred"] for row in sheet["noninvasive"])
    first = choice(sheet)
    sheet["noninvasive"].reverse()
    assert choice(sheet) == first
    assert first["variant"] == "none" and first["warning"]


@pytest.mark.parametrize("change", ["hidden", "removed", "status", "invalid_pressure"])
def test_hidden_removed_or_invalid_pressure_entry_does_not_supply_bpap(change):
    sheet = imported(BILEVEL, delivery("CPAP/Bi-PAP mask", PRESSURES))
    row = sheet["noninvasive"][0]
    if change == "hidden":
        row["include"] = False
    elif change == "removed":
        row["removed"] = True
    elif change == "status":
        row["status"] = "No longer present"
    else:
        row["values"]["IPAP"] = "UNK"
    assert choice(sheet)["variant"] == "none"


@pytest.mark.parametrize("status", ["No", "Off", "False"])
def test_real_ventilator_off_import_does_not_use_retained_primary_mode(status):
    sheet = mode_sheet("PRVC", "Ventilator On: " + status)
    assert sheet["ventilation"]["mode"] == "PRVC" and sheet["sbs_vent_mode"] == ""
    result = choice(sheet)
    assert result["variant"] == "none" and result["warning"]


def test_ventilator_off_can_leave_independently_named_hfnc_current():
    sheet = imported(BILEVEL + "\nVentilator On: No", delivery(extra=PRESSURES + "\nO2 Flow Rate (L/min): 20"))
    assert [row["device"] for row in sheet["noninvasive"]] == ["HFNC"]
    assert choice(sheet)["variant"] == "hfnc"


@pytest.mark.parametrize("status", ["Removed", "Previously removed", "Not currently present", "No longer present", "Not currently in place", "Extubated"])
def test_removed_or_absent_airway_status_blocks_retained_mode(status):
    result = choice(airway(mode_sheet(), "ETT 4.0 mm-Status: " + status))
    assert result["variant"] == "none" and result["warning"]


def test_current_new_airway_overrides_removed_old_ett_history():
    sheet = airway(mode_sheet(), "[REMOVED] ETT 4.0 mm-Status: Removed\nTracheostomy Bivona 4.0-Status: In place")
    assert choice(sheet)["variant"] == "prvc"


def test_hidden_removed_airway_does_not_override_current_mode():
    sheet = airway(mode_sheet(), "[REMOVED] ETT 4.0 mm-Status: Removed")
    sheet["devices"]["rows"][0]["include"] = False
    assert choice(sheet)["variant"] == "prvc"


@pytest.mark.parametrize("section", ["u", "v"])
@pytest.mark.parametrize("flag", [
    {"action": "not_updated"}, {"action": "previous_retained"},
    {"action": "not_imported"}, {"code": "section_boundary", "action": "nothing_changed"},
    {"action": "section_boundary"},
])
def test_failed_device_import_cannot_let_retained_ett_veto_current_hfnc(section, flag):
    sheet = airway(imported(d=delivery()), section=section)
    sheet["import_warnings"][section] = [flag]
    assert choice(sheet)["variant"] == "hfnc"


@pytest.mark.parametrize("section,hidden", [("u", "devices_hidden"), ("v", "neuro_devices_hidden")])
def test_device_hidden_recovery_flag_is_respected(section, hidden):
    sheet = airway(imported(d=delivery()), section=section)
    sheet["import_warnings"][section] = [{"action": hidden}]
    assert choice(sheet)["variant"] == "hfnc"


def test_partial_device_recovery_keeps_valid_ett_and_support_conflict():
    sheet = airway(imported(d=delivery()))
    sheet["import_warnings"]["u"] = [{"action": "field_unknown", "code": "device_date_invalid"}]
    result = choice(sheet)
    assert result["variant"] == "none" and result["warning"]


@pytest.mark.parametrize("status", ["Historical", "Prior", "Previously removed", "No"])
def test_historical_or_absent_saved_airway_status_does_not_veto_current_hfnc(status):
    sheet = airway(imported(d=delivery()), "ETT 4.0 mm-Status: " + status)
    assert choice(sheet)["variant"] == "hfnc"


@pytest.mark.parametrize("change", ["hidden_snapshot", "failed_cd", "failed_c", "failed_d"])
def test_hidden_or_failed_respiratory_source_does_not_select_retained_mode(change):
    sheet = mode_sheet()
    if change == "hidden_snapshot":
        sheet["ventilation"]["include"] = False
    else:
        sheet["import_warnings"][change.removeprefix("failed_")] = [{"action": "not_updated"}]
    assert choice(sheet)["variant"] == "none"


@pytest.mark.parametrize("text", ["Room air", "Currently extubated", "Not currently intubated", "No longer intubated", "Ventilator Off", "Off the ventilator"])
def test_current_explicit_status_can_veto_retained_ventilation(text):
    sheet = mode_sheet()
    sheet["fields"]["Respiratory"] = text
    assert choice(sheet)["variant"] == "none"


@pytest.mark.parametrize("text", [
    "History of room air", "PMH:\nExtubated", "Plan:\nRoom air",
    "Plan to be extubated tomorrow", "Extubated tomorrow", "No current room air",
    "Not currently extubated", "Possible room air tomorrow", "Room air requested",
    "Room air: No", "Extubated: No", "Room air not tolerated",
    "Room air is not currently tolerated", "Extubated: not yet", "Room air: None.",
])
def test_history_negation_or_future_status_does_not_veto_current_ventilation(text):
    sheet = mode_sheet()
    sheet["fields"]["Respiratory"] = text
    assert choice(sheet)["variant"] == "prvc"


def test_explicit_current_clause_after_history_is_used():
    sheet = mode_sheet()
    sheet["fields"]["Respiratory"] = "History of intubation, now room air"
    assert choice(sheet)["variant"] == "none"


@pytest.mark.parametrize("text", ["Extubated, no longer on the ventilator", "Extubated, not requiring respiratory support"])
def test_current_extubation_is_not_negated_by_a_separate_no_support_statement(text):
    sheet = mode_sheet()
    sheet["fields"]["Respiratory"] = text
    assert choice(sheet)["variant"] == "none"


def test_current_room_air_and_explicit_hfnc_is_a_conflict():
    sheet = imported(d=delivery())
    sheet["fields"]["Respiratory"] = "Room air"
    result = choice(sheet)
    assert result["variant"] == "none" and result["warning"]


def test_current_ett_and_extubation_statement_is_a_conflict():
    sheet = airway(mode_sheet())
    sheet["fields"]["Respiratory"] = "Not currently intubated"
    result = choice(sheet)
    assert result["variant"] == "none" and result["warning"]


def test_airway_without_mode_never_guesses_pressure_or_volume_control():
    result = choice(airway(new_sheet("P4102")))
    assert result["variant"] == "none" and result["warning"]


def test_medications_cannot_supply_a_respiratory_mode():
    sheet = new_sheet("P4102")
    sheet["medications"] = [{"name": "Albuterol", "route": "Nebulization", "frequency": "Continuous"}]
    assert choice(sheet)["variant"] == "none"


def test_selector_does_not_change_source_settings_history_values_or_flags():
    sheet = imported(MAIN_HISTORY + "Vent Mode: PS-CPAP (11/20/26 1700 : Author)\nVent Mode: PRVC-IMV (11/20/26 1800 : Author)")
    airway(sheet)
    sheet["ventilation"]["values"]["Pmin"] = "(S) 8 cm H2O"
    settings = {"diagnoses_destination": "Assessment", "other": ["kept"]}
    before_sheet, before_settings = deepcopy(sheet), deepcopy(settings)
    result = select_respiratory_variant(sheet, settings=settings)
    assert result["variant"] == "home_vent"
    assert sheet == before_sheet and settings == before_settings


def test_empty_handoff_has_basic_body_without_unneeded_warning():
    result = choice(new_sheet("P4102"))
    assert result["variant"] == "none" and not result["warning"]
