"""Independent first-settings fallback checks using synthetic source data."""
import json

import pytest

import ventilation
from ventilation import (
    VENTILATION_HISTORY_FALLBACK_NOTE,
    has_ventilation_history,
    parse_first_reported_ventilation,
    parse_ventilation,
    select_first_reported_ventilation_source,
    select_ventilation_source,
    validate_ventilation,
)


ORIGINAL = """Invasive Ventilation:
Mode: Vent Mode: PRVC-IMV
Resp Rate (Set): 14
Vt (Set, mL): 100
PEEP (cm H2O): 5
FiO2 set (%): 55 %
Home Ventilator Settings:
Pmin:
Average Volume-Assured Pressure Support Settings:
AVAPS Target TV: Vt Set/Target ml: 999
Observed AVAPS TV: Vt (observed, mL): 888
PS Max: 24
PS Min: 6
NAVA Ventilator Settings:
NAVA level: 2
PEEP (cm H2O): 7
FiO2 (%): 30 %
CPAP Trial Settings:
Pressure Support (cm H2O): 8
PEEP (cm H2O): 6
FiO2 set (%): 21 %
Weaning Tidal Volumes: Weaning Tidal Volume Avg: 90 Min: 80 Max: 100
Weaning Tolerance: Good
"""
HISTORY = """All Vent Modes:
Vent Mode: NAVA (11/20/26 1800 : Synthetic Author)
Vent Mode: PRVC-IMV (11/20/26 1700 : Synthetic Author)
"""


def successful(source=ORIGINAL + HISTORY):
    result = parse_first_reported_ventilation(source)
    assert not result.error, result.error
    assert result.status == "included"
    assert result.data is not None
    validate_ventilation(result.data)
    return result


def fail_history(*args, **kwargs):
    raise RuntimeError("Synthetic failure in the history path")


def test_fallback_has_no_dependency_on_history_helpers_or_normal_selector(monkeypatch):
    for name in ("_history_context", "_read_mode_history", "_split_ventilation_sections", "select_ventilation_source"):
        monkeypatch.setattr(ventilation, name, fail_history)
    result = successful()
    assert result.data["mode"] == "PRVC-IMV"
    assert result.data["values"]["FiO2 set (%)"] == "55 %"
    assert "NAVA level" not in result.data["values"]
    assert result.data["mode_history"] == {
        "reported_at": "", "other_modes": [], "latest_confirmed": False,
        "notes": [VENTILATION_HISTORY_FALLBACK_NOTE],
    }
    assert VENTILATION_HISTORY_FALLBACK_NOTE in result.issues


def test_fallback_does_not_invent_dates_or_persist_history_authors():
    result = successful()
    saved = json.dumps(result.data)
    assert "2026" not in saved and "11/20" not in saved
    assert "Synthetic Author" not in saved
    assert result.data["mode_history"]["reported_at"] == ""
    assert result.data["mode_history"]["other_modes"] == []


@pytest.mark.parametrize("extra", [
    "PEEP (cm H2O): 9", "Vent Mode: NAVA", "FiO2 set (%): 80 %",
])
def test_conflicting_original_fields_are_not_resolved_by_picking_the_first(extra):
    source = ORIGINAL.replace("Home Ventilator Settings:", extra + "\nHome Ventilator Settings:") + HISTORY
    result = parse_first_reported_ventilation(source)
    assert result.error and "conflicting" in result.error
    assert result.data is None


def test_generic_conflict_is_not_hidden_by_a_valid_dedicated_nava_section():
    source = ORIGINAL.replace("Vent Mode: PRVC-IMV", "Vent Mode: NAVA", 1)
    source = source.replace("PEEP (cm H2O): 5", "PEEP (cm H2O): 5\nPEEP (cm H2O): 9", 1)
    result = parse_first_reported_ventilation(source + HISTORY)
    assert result.data is None and "conflicting" in result.error


def test_conflicting_selected_dedicated_settings_block_fallback():
    source = ORIGINAL.replace("Vent Mode: PRVC-IMV", "Vent Mode: NAVA", 1)
    source = source.replace("NAVA level: 2", "NAVA level: 2\nNAVA level: 3")
    result = parse_first_reported_ventilation(source + HISTORY)
    assert result.data is None and "conflicting" in result.error


def test_identical_original_repetitions_are_allowed():
    source = ORIGINAL.replace("PEEP (cm H2O): 5", "PEEP (cm H2O): 5\nPEEP (cm H2O): (S) 5", 1)
    assert successful(source + HISTORY).data["values"]["PEEP (cm H2O)"] == "(S) 5"


def test_missing_generic_values_are_not_borrowed_from_other_mode_blocks():
    source = ORIGINAL.replace("Vt (Set, mL): 100", "Vt (Set, mL):", 1)
    source = source.replace("FiO2 set (%): 55 %", "FiO2 set (%):", 1)
    values = successful(source + HISTORY).data["values"]
    assert "Vt (Set, mL)" not in values
    assert "Vt Set/Target ml" not in values
    assert "FiO2 (%)" not in values and "FiO2 set (%)" not in values
    assert values["PEEP (cm H2O)"] == "5"


@pytest.mark.parametrize("mode,expected,absent", [
    ("NAVA", {"NAVA level": "2", "PEEP (cm H2O)": "7", "FiO2 (%)": "30 %"}, "Resp Rate (Set)"),
    ("PS-CPAP", {"Pressure Support (cm H2O)": "8", "PEEP (cm H2O)": "6", "FiO2 set (%)": "21 %"}, "Vt (Set, mL)"),
    ("AVAPS", {"Vt Set/Target ml": "999", "PEEP (cm H2O)": "5", "FiO2 set (%)": "55 %"}, "NAVA level"),
])
def test_dedicated_settings_are_scoped_to_the_original_mode(mode, expected, absent):
    source = ORIGINAL.replace("Vent Mode: PRVC-IMV", "Vent Mode: " + mode, 1)
    result = successful(source + HISTORY)
    assert result.data["mode"] == mode
    for label, value in expected.items():
        assert result.data["values"][label] == value
    assert absent not in result.data["values"]


def test_explicit_mode_settings_follow_only_the_initial_mode():
    source = ORIGINAL.replace("Vent Mode: PRVC-IMV", "Vent Mode: Pressure Control", 1)
    source += "PC Settings:\nPIP Set (cm H2O): 18\nPEEP (cm H2O): 4\n"
    source += "PRVC Settings:\nVt (Set, mL): 777\nPEEP (cm H2O): 12\n"
    result = successful(source + HISTORY)
    assert result.data["mode"] == "Pressure Control"
    assert result.data["values"] == {"PIP Set (cm H2O)": "18", "PEEP (cm H2O)": "4"}


def test_other_explicit_mode_settings_do_not_conflict_with_the_first_snapshot():
    source = ORIGINAL + "Pressure Control Settings:\nPEEP (cm H2O): 19\n" + HISTORY
    assert successful(source).data["values"]["PEEP (cm H2O)"] == "5"


@pytest.mark.parametrize("flag", ["No", "Off", "False", "(S) OFF"])
def test_off_control_is_preserved_and_invasive_fallback_declines(flag):
    source = ORIGINAL.replace("Resp Rate (Set): 14", "Ventilator On: " + flag + "\nResp Rate (Set): 14", 1) + HISTORY
    assert "Ventilator On: " + flag in select_first_reported_ventilation_source(source)
    result = parse_first_reported_ventilation(source)
    assert result.data is None and result.error
    assert result.status == "excluded"


def test_conflicting_original_on_controls_are_not_dropped():
    source = "Ventilator On: Yes\nVentilator On: Off\n" + ORIGINAL + HISTORY
    result = parse_first_reported_ventilation(source)
    assert result.data is None and "conflicting" in result.error


@pytest.mark.parametrize("mode", ["NAVA NIV", "BiLevel", "Unknown synthetic mode", ""])
def test_unsupported_initial_mode_cannot_be_recovered_from_history(mode):
    source = ORIGINAL.replace("Vent Mode: PRVC-IMV", "Vent Mode: " + mode, 1) + HISTORY
    result = parse_first_reported_ventilation(source)
    assert result.error and result.data is None


def test_mode_without_any_settings_declines_fallback():
    result = parse_first_reported_ventilation("Mode: Vent Mode: PRVC\n" + HISTORY)
    assert result.error and result.data is None


@pytest.mark.parametrize("unused_field", ["PIP Set (cm H2O): 20", "NAVA level: 2", "Mean Airway Pressure: 10"])
def test_fields_not_displayed_for_initial_mode_do_not_count_as_usable_settings(unused_field):
    result = parse_first_reported_ventilation("Mode: Vent Mode: PRVC\n" + unused_field + "\n" + HISTORY)
    assert result.error and result.data is None


def test_empty_authoritative_nava_block_does_not_restore_generic_values():
    source = "Mode: Vent Mode: NAVA\nPEEP (cm H2O): 5\nNAVA Ventilator Settings:\n" + HISTORY
    result = parse_first_reported_ventilation(source)
    assert result.error and result.data is None


def test_history_and_later_settings_are_never_reused_as_original_settings():
    source = "Mode: Vent Mode: PRVC\n" + HISTORY + "PRVC Settings:\nPEEP (cm H2O): 17\n"
    result = parse_first_reported_ventilation(source)
    assert result.error and result.data is None
    assert "17" not in select_first_reported_ventilation_source(source)


@pytest.mark.parametrize("line_ending", ["\n", "\r\n", "\r"])
def test_history_detection_and_fallback_accept_pasted_line_endings(line_ending):
    source = (ORIGINAL + HISTORY.replace("All Vent Modes:", " (S) aLL  Vent   Modes: ")).replace("\n", line_ending)
    assert has_ventilation_history(source)
    assert successful(source).data["mode"] == "PRVC-IMV"


def test_absent_history_never_calls_history_context_in_normal_legacy_path(monkeypatch):
    monkeypatch.setattr(ventilation, "_history_context", fail_history)
    source = "Mode: Vent Mode: PRVC\nPEEP (cm H2O): 5\n"
    assert not has_ventilation_history(source)
    assert not has_ventilation_history(None)
    assert "Vent Mode: PRVC" in select_ventilation_source(source)
    result = parse_ventilation(source)
    assert not result.error and result.data["mode"] == "PRVC"
    assert "mode_history" not in result.data
