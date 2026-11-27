"""Synthetic current-support routing for the supplied cardiovascular sections."""
from copy import deepcopy

import pytest

from devices import parse_devices
from ecls import parse_ecls
from models import new_sheet
from note_cardiovascular import (
    CV_TEMPLATE_FILES, CV_TEMPLATE_LABELS, CV_TEMPLATE_NAMES,
    select_cardiovascular_variant,
)
from pacemaker import parse_pacemaker
from vitals import parse_vitals


def handoff(text="", diagnoses=""):
    sheet = new_sheet("P4102")
    sheet["fields"]["Cardiovascular"] = text
    sheet["fields"]["Diagnoses"] = diagnoses
    return sheet


def with_devices(sheet, source, section="u"):
    parsed = parse_devices(source, section)
    assert not parsed.error
    assert parsed.data and parsed.data["rows"]
    sheet["devices" if section == "u" else "neuro_devices"] = parsed.data
    return sheet


def with_pacer(sheet, source="Pacer Mode: VVI\nPacer Rate: 80 bpm"):
    parsed = parse_pacemaker(source)
    assert not parsed.error
    sheet["pacemaker"] = parsed.data
    return sheet


def with_ecls(sheet, source="ECMO Mode: Veno-arterial\nPump Flow (L/min): 2.3 LPM"):
    parsed = parse_ecls(source)
    assert not parsed.error
    sheet["ecls"] = parsed.data
    return sheet


def with_pressures(sheet, source):
    parsed = parse_vitals(source)
    assert not parsed.error
    assert parsed.rows
    sheet["vitals"] = parsed.rows
    return sheet


def variant(sheet, **kwargs):
    return select_cardiovascular_variant(sheet, **kwargs)["variant"]


@pytest.mark.parametrize("key,phrase", [
    ("art", "ACKCVART"), ("art_cvl", "ACKCVARTCVL"),
    ("art_cvl_ecls", "ACKCVARTCVLECLS"),
    ("art_cvl_pacemaker", "ACKCVARTCVLPACEMAKER"),
    ("cvl", "ACKCVCVL"), ("none", "ACKCVNONE"),
])
def test_all_six_source_template_names_and_paths_are_exact(key, phrase):
    assert CV_TEMPLATE_NAMES[key] == phrase
    assert CV_TEMPLATE_FILES[key].name == "cv_" + key + ".docx"
    assert CV_TEMPLATE_FILES[key].parent.name == "templates"
    assert CV_TEMPLATE_LABELS[key]


@pytest.mark.parametrize("text,expected", [
    ("", "none"), ("Arterial line in place", "art"),
    ("Central venous line present", "cvl"),
    ("Arterial line present\nPICC present", "art_cvl"),
    ("Temporary pacing wires in place", "art_cvl_pacemaker"),
    ("On VV ECMO", "art_cvl_ecls"),
])
def test_current_explicit_statements_choose_all_six_variants(text, expected):
    result = select_cardiovascular_variant(handoff(text))
    assert result["variant"] == expected
    assert result["phrase"] == CV_TEMPLATE_NAMES[expected]
    assert set(result) == {"variant", "phrase", "label", "reason", "warning", "include_pacemaker"}
    assert result["label"] and result["reason"]
    assert result["warning"] == ""
    assert result["include_pacemaker"] is (expected == "art_cvl_pacemaker")


@pytest.mark.parametrize("source,expected", [
    ("Arterial Line 11/20/26 Radial-Status: Patent", "art"),
    ("PICC 11/20/26 Left-Status: Patent", "cvl"),
    ("CVC 11/20/26 Right IJ-Status: Patent", "cvl"),
    ("Central Venous Catheter-Status: Patent", "cvl"),
    ("Port-a-cath-Status: Accessed", "cvl"),
    ("Implanted Port-Status: Present", "cvl"),
    ("Hemodialysis Catheter-Status: Patent", "cvl"),
    ("Umbilical arterial catheter-Status: Patent", "art"),
    ("UVC-Status: Patent", "cvl"),
    ("Epicardial pacing wires-Status: Not pacing", "art_cvl_pacemaker"),
    ("Temporary wires-Status: Present", "art_cvl_pacemaker"),
    ("PIV 11/20/26 Left-Status: Patent", "none"),
    ("ECMO cannula-Status: Present", "none"),
])
@pytest.mark.parametrize("section", ["u", "v"])
def test_real_device_inventory_shapes_supply_current_evidence(source, expected, section):
    assert variant(with_devices(handoff(), source, section)) == expected


@pytest.mark.parametrize("source", [
    "Pacemaker: Yes", "Pacemaker: Off", "Pacemaker: Standby",
    "Pacemaker: Not pacing", "Pacemaker: Disconnected", "Mode: VVI\nRate: 0 bpm",
])
def test_present_pacemaker_selects_its_template_even_when_inactive_or_settings_incomplete(source):
    sheet = with_pacer(handoff(), source)
    result = select_cardiovascular_variant(sheet)
    assert result["variant"] == "art_cvl_pacemaker"
    assert result["include_pacemaker"] is True


@pytest.mark.parametrize("source", ["Pacemaker: No", "Pacemaker: Removed", "Mode: Removed", "Mode: Not present"])
def test_absent_pacemaker_does_not_select_specialized_template(source):
    assert variant(with_pacer(handoff(), source)) == "none"


def test_ecls_takes_priority_and_retains_current_pacemaker_without_requiring_both_lines():
    result = select_cardiovascular_variant(with_ecls(with_pacer(handoff(), "Pacemaker: Standby")))
    assert result["variant"] == "art_cvl_ecls"
    assert result["include_pacemaker"] is True
    assert "also" in result["reason"]
    sheet = with_ecls(handoff())
    assert select_cardiovascular_variant(sheet)["include_pacemaker"] is False


@pytest.mark.parametrize("source,expected", [
    ("ECMO Mode: Veno-arterial", "art_cvl_ecls"),
    ("ECMO Mode: VV", "art_cvl_ecls"),
    ("Pump Flow (L/min): 2.3 LPM", "art_cvl_ecls"),
    ("Set Speed (rev/min): 3400 Rev/Min", "art_cvl_ecls"),
    ("Oxygenator Day: 2", "none"),
    ("Pump Flow (L/min): 0 LPM", "none"),
    ("Sweep Gas Flow Rate (L/min): 0.5 L/min", "none"),
])
def test_ecls_uses_recorded_current_mode_or_pumping_fields_without_inferring_from_day(source, expected):
    assert variant(with_ecls(handoff(), source)) == expected


@pytest.mark.parametrize("kind", ["Arterial Line", "PICC", "Epicardial pacing wires"])
@pytest.mark.parametrize("status", [
    "Removed", "Not currently present", "No longer present", "Not currently in place", "Absent", "No",
    "Planned", "To be placed tomorrow", "Historical", "Remote", "Prior", "Previously",
])
def test_removed_historical_planned_and_absent_device_statuses_do_not_supply_presence(kind, status):
    assert variant(with_devices(handoff(), kind + "-Status: " + status)) == "none"


def test_explicit_saved_none_status_is_absent_but_parser_missing_status_is_not_removal():
    sheet = with_devices(handoff(), "PICC-Status: None")
    assert sheet["devices"]["rows"][0]["status"] == ""
    assert variant(sheet) == "cvl"
    sheet["devices"]["rows"][0]["status"] = "None"
    assert variant(sheet) == "none"


@pytest.mark.parametrize("source,expected", [
    ("Arterial Line-Status: Not removed", "art"),
    ("PICC-Status: UNK", "cvl"),
    ("Pacer wires-Status: Off", "art_cvl_pacemaker"),
    ("Pacemaker-Status: Standby", "art_cvl_pacemaker"),
])
def test_current_devices_with_nonabsence_status_are_retained(source, expected):
    assert variant(with_devices(handoff(), source)) == expected


def test_removed_old_line_does_not_cancel_distinct_current_replacement():
    sheet = with_devices(handoff(), "Arterial Line Left-Status: Removed\nArterial Line Right-Status: Patent")
    assert variant(sheet) == "art"


@pytest.mark.parametrize("text", [
    "No arterial line", "No current central line", "Not currently on ECMO", "Possible current ECMO",
    "History of PICC", "h/o pacemaker", "PMH: VA ECMO", "Prior arterial line",
    "PICC line planned", "Arterial line insertion planned", "ECMO cannulation planned",
    "Temporary pacing wires to be placed tomorrow", "ECMO?", "Consider ECMO", "No current pacemaker",
    "PICC removed", "Pacemaker is not present", "ECMO off", "Off VA ECMO",
    "Decannulated from VV ECMO", "ECMO no longer running", "ECMO support not indicated",
    "ECMO not currently needed", "ECMO support is not currently required",
    "ECMO cannula in place", "VA ECMO cannula", "No arterial line, PICC or pacemaker",
    "Not pacemaker dependent", "Not pacemaker-dependent", "Pacemaker is not dependent",
])
def test_noncurrent_or_unestablished_prose_does_not_create_support(text):
    assert variant(handoff(text)) == "none"


def test_historical_and_planned_heading_scopes_end_only_at_current_section():
    assert variant(handoff("Past history:\nPICC\nECMO")) == "none"
    assert variant(handoff("Planned devices:\nPICC\nPacemaker")) == "none"
    assert variant(handoff("History:\nECMO\nCurrent lines:\nPICC")) == "cvl"
    assert variant(handoff("Prior PICC, now arterial line present")) == "art"
    assert variant(handoff("No arterial line, central line present")) == "cvl"


@pytest.mark.parametrize("text", ["Not pacemaker dependent", "Not pacemaker-dependent", "Pacemaker is not dependent"])
def test_dependency_statement_cannot_remove_a_current_pacemaker(text):
    assert variant(with_pacer(handoff(text))) == "art_cvl_pacemaker"


@pytest.mark.parametrize("text", ["ECMO off", "Off VA ECMO", "ECMO support not indicated", "ECMO not currently needed", "Decannulated from VV ECMO"])
def test_current_ecls_cessation_overrides_retained_settings(text):
    result = select_cardiovascular_variant(with_ecls(handoff(text)))
    assert result["variant"] == "none"
    assert result["warning"]


@pytest.mark.parametrize("source,expected", [
    ("Arterial Line BP Min: 80/40 Max: 112/65", "art"),
    ("Last Arterial BP: Arterial Line BP: 108/60", "art"),
    ("Arterial Line MAP (mmHg) Avg: 63 mmHg Min: 52 mmHg Max: 75 mmHg", "art"),
    ("Last Arterial MAP: 72 mmHg", "art"),
    ("CVP (mean) Avg: 8 mmHg Min: 4 mmHg Max: 11 mmHg", "cvl"),
    ("Last CVP: CVP (mean): 8 mmHg", "cvl"),
    ("CVP: 0 mmHg", "cvl"),
    ("CVP: 5 mmHg\nLast Arterial MAP: 72 mmHg", "art_cvl"),
    ("BP: 98/54\nMAP: 70 mmHg", "none"),
])
def test_real_source_labeled_pressure_rows_supply_fallback_evidence(source, expected):
    assert variant(with_pressures(handoff(), source)) == expected


@pytest.mark.parametrize("label", ["ART BP", "Last ART MAP", "CVP", "Last CVP"])
@pytest.mark.parametrize("value", ["", "UNK", "None", "not measured", "removed 11/21/26", "Prior 8 mmHg", "8 mmHg planned", "error 12", "1e3 mmHg"])
def test_blank_unusable_or_noncurrent_pressure_values_are_not_evidence(label, value):
    sheet = handoff()
    sheet["vitals"] = [{"label": label, "value": value, "section": "Cardiovascular", "include": True}]
    assert variant(sheet) == "none"


@pytest.mark.parametrize("text", ["Lines: None", "Vascular access: None", "No current invasive lines", "Arterial line removed\nCentral line removed"])
def test_explicit_current_line_absence_overrides_retained_pressure_monitoring(text):
    result = select_cardiovascular_variant(with_pressures(handoff(text), "CVP: 8 mmHg\nLast Arterial MAP: 72 mmHg"))
    assert result["variant"] == "none"
    assert result["warning"]


def test_status_removal_overrides_matching_pressure_evidence():
    sheet = with_pressures(with_devices(handoff(), "PICC-Status: Removed"), "CVP: 8 mmHg")
    assert variant(sheet) == "none"


@pytest.mark.parametrize("action", ["pacemaker_hidden", "not_updated", "not_imported", "previous_retained", "section_boundary"])
def test_failed_or_hidden_pacemaker_snapshot_is_not_resurrected(action):
    sheet = with_pacer(handoff())
    sheet["import_warnings"]["w"] = [{"action": action}]
    assert variant(sheet) == "none"


@pytest.mark.parametrize("action", ["ecls_hidden", "not_updated", "not_imported", "previous_retained", "section_boundary"])
def test_failed_or_hidden_ecls_snapshot_is_not_resurrected(action):
    sheet = with_ecls(handoff())
    sheet["import_warnings"]["ad"] = [{"action": action}]
    assert variant(sheet) == "none"


@pytest.mark.parametrize("section,hidden", [("u", "devices_hidden"), ("v", "neuro_devices_hidden")])
@pytest.mark.parametrize("failure", ["hidden", "not_updated", "not_imported", "previous_retained", "boundary", "section_boundary"])
def test_failed_device_imports_are_not_used(section, hidden, failure):
    sheet = with_devices(handoff(), "Arterial Line-Status: Patent", section)
    sheet["import_warnings"][section] = [{"action": hidden if failure == "hidden" else failure, "code": "section_boundary" if failure == "boundary" else ""}]
    assert variant(sheet) == "none"


def test_partial_field_warnings_do_not_hide_valid_current_records():
    sheet = with_ecls(with_pacer(handoff(), "Pacemaker: Yes"))
    sheet["import_warnings"] = {"w": [{"action": "field_unknown"}], "ad": [{"action": "field_unknown"}]}
    result = select_cardiovascular_variant(sheet)
    assert result["variant"] == "art_cvl_ecls" and result["include_pacemaker"]
    sheet = with_devices(handoff(), "Arterial Line-Status: Patent")
    sheet["import_warnings"]["u"] = [{"action": "field_unknown"}]
    assert variant(sheet) == "art"


def test_excluded_devices_pacemaker_or_measurements_are_not_current_note_evidence():
    sheet = with_devices(with_pacer(with_pressures(handoff(), "CVP: 8 mmHg")), "Arterial Line-Status: Patent")
    sheet["devices"]["rows"][0]["include"] = False
    sheet["pacemaker"]["include"] = False
    sheet["vitals"][0]["include"] = False
    assert variant(sheet) == "none"


def test_failed_vitals_import_does_not_revive_retained_arterial_or_cvp_values():
    sheet = with_pressures(handoff(), "CVP: 8 mmHg\nLast Arterial MAP: 72 mmHg")
    sheet["import_warnings"]["e"] = [{"action": "previous_retained"}]
    assert variant(sheet) == "none"


def test_configured_diagnoses_are_in_scope_but_failed_or_unrelated_fields_are_not():
    sheet = handoff()
    sheet["fields"]["Goals / Follow-up"] = "PICC present"
    assert variant(sheet) == "none"
    assert variant(sheet, settings={"diagnoses_destination": "Goals / Follow-up"}) == "cvl"
    sheet["import_warnings"]["a"] = [{"action": "previous_retained"}]
    assert variant(sheet, settings={"diagnoses_destination": "Goals / Follow-up"}) == "none"


def test_invalid_support_snapshots_fail_closed_with_static_review_warning():
    sheet = handoff()
    sheet["pacemaker"] = {"mode": "VVI"}
    sheet["ecls"] = {"mode": "VA"}
    result = select_cardiovascular_variant(sheet)
    assert result["variant"] == "none"
    assert "pacemaker record" in result["warning"] and "ECLS record" in result["warning"]


def test_medications_do_not_establish_support_and_routing_never_mutates_inputs():
    sheet = handoff()
    sheet["medications"] = {"continuous": [{"name": "Epinephrine", "dose": "0.04 mcg/kg/min"}], "scheduled": [{"name": "Milrinone"}]}
    before = deepcopy(sheet)
    assert variant(sheet) == "none"
    assert sheet == before
    supported = with_ecls(with_pacer(with_devices(handoff(), "Arterial Line-Status: Patent")))
    before = deepcopy(supported)
    select_cardiovascular_variant(supported)
    assert supported == before
