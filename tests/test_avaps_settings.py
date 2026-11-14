"""Synthetic AVAPS source-field and mode-specific display checks."""
from copy import deepcopy

import pytest

from noninvasive import parse_respiratory
from ventilation import LABELS, format_ventilation, parse_ventilation, unwrap_vent_line


MODE = "Average Volume-Assured Pressure Support"
FIELDS = """Average Volume-Assured Pressure Support Settings:
AVAPS Respiratory Rate: AVAPS rate (cm H2O/min): 14
AVAPS Target TV: Vt Set/Target ml: 90
Observed AVAPS TV: Vt (observed, mL): 190 mL
PS Max: Pressure Support Max (cm H2O): 24 cm H2O
PS Min: Pressure Support Min (cm H2O): 9 cm H2O"""
BODY = """Invasive Ventilation:
Mode: Vent Mode: Average Volume-Assured Pressure Support
Respiratory Rate:
Set PIP:
Observed PIP: No data recorded
Set TV:
Observed TV: No data recorded
Set PEEP:
Inspiratory Time:
FiO2:
Pressure Support:
Home Ventilator Settings:
Pmin:
Pmax:
Timin:
Timax:
""" + FIELDS
EXPECTED = """Mode: AVAPS
AVAPS rate: 14 cm H2O/min
Target TV: 90 mL
Observed TV: 190 mL
PS Min: 9 cm H2O
PS Max: 24 cm H2O"""


def parsed(source=BODY):
    result = parse_ventilation(source)
    assert not result.error, result.error
    assert result.data is not None
    return result


def test_nested_avaps_fields_are_retained_separately_and_displayed():
    result = parsed()
    assert result.data["mode"] == MODE
    assert result.data["values"] == {
        "AVAPS rate (cm H2O/min)": "14",
        "Vt Set/Target ml": "90",
        "AVAPS Observed TV (mL)": "190 mL",
        "Pressure Support Min (cm H2O)": "9 cm H2O",
        "Pressure Support Max (cm H2O)": "24 cm H2O",
    }
    before = deepcopy(result.data)
    assert format_ventilation(result.data) == EXPECTED
    assert result.data == before
    assert "Resp Rate (Set)" not in result.data["values"]
    assert "Vt (Set, mL)" not in result.data["values"]
    assert all("Vt (Set, mL)" not in issue for issue in result.issues)


def test_new_editor_fields_are_appended_after_existing_labels():
    assert LABELS[:19] == (
        "Vent Mode", "Resp Rate (Set)", "Vt (Set, mL)", "Vt (observed, mL)",
        "PEEP (cm H2O)", "Mean Airway Pressure", "Insp Time (sec)",
        "PIP Observed (cm H2O)", "Pressure Support (cm H2O)",
        "Trigger Sensitivity Flow (L/min)", "FiO2 (%)", "PIP Set (cm H2O)",
        "Vt Insp ml", "Vt Exp ml", "FiO2 set (%)", "Pmin", "Pmax", "Ti Min", "Ti Max",
    )


@pytest.mark.parametrize("source,field,value", [
    ("AVAPS Respiratory Rate: AVAPS rate (cm H2O/min): 14", "AVAPS rate (cm H2O/min)", "14"),
    ("AVAPS Target TV: Vt Set/Target ml: 90", "Vt Set/Target ml", "90"),
    ("Observed AVAPS TV: Vt (observed, mL): 190 mL", "AVAPS Observed TV (mL)", "190 mL"),
    ("Observed AVAPS TV: Vt (observed, mL) Avg: 150 Min: 120 Max: 190", "AVAPS Observed TV (mL)", "Avg: 150 Min: 120 Max: 190"),
    ("PS Min: Pressure Support Min (cm H2O): 9 cm H2O", "Pressure Support Min (cm H2O)", "9 cm H2O"),
    ("PS Max: Pressure Support Max (cm H2O): 24 cm H2O", "Pressure Support Max (cm H2O)", "24 cm H2O"),
    ("AVAPS Respiratory Rate: 18", "AVAPS Respiratory Rate", "18"),
    ("AVAPS Target TV: 90", "Vt Set/Target ml", "90"),
    ("Observed AVAPS TV: 190", "AVAPS Observed TV (mL)", "190"),
    ("PS Min: 0", "Pressure Support Min (cm H2O)", "0"),
    ("PS Max: 24", "Pressure Support Max (cm H2O)", "24"),
])
def test_supported_wrappers(source, field, value):
    assert unwrap_vent_line(source) == field + ": " + value
    result = parsed("Vent Mode: AVAPS\n" + source)
    assert result.data["values"][field] == value


@pytest.mark.parametrize("typography", ["cm H2O", "cmH2O", "cm H₂O", "cmH₂O", "cm H20", "cmH20"])
def test_pressure_unit_typography_is_supported_in_nested_labels(typography):
    source = BODY.replace("cm H2O", typography)
    assert format_ventilation(parsed(source).data) == EXPECTED


def test_case_spacing_and_setting_markers_do_not_change_values():
    source = BODY.replace("AVAPS Respiratory Rate: AVAPS rate (cm H2O/min): 14",
                          "avaps respiratory rate: (S) AVAPS RATE (cm H2O/min): (S) 14")
    source = source.replace("AVAPS Target TV:", "avaps   target tv:")
    source = source.replace("Observed AVAPS TV:", "observed avaps tv:")
    result = parsed(source)
    assert result.data["values"]["AVAPS rate (cm H2O/min)"] == "(S) 14"
    assert format_ventilation(result.data) == EXPECTED


def test_real_set_rate_is_distinct_from_avaps_rate():
    result = parsed(BODY + "\nResp Rate (Set): 20")
    text = format_ventilation(result.data)
    assert "Set RR: 20\nAVAPS rate: 14 cm H2O/min" in text
    assert "Set RR: 14" not in text and "14 breaths/min" not in text
    assert not any("Resp Rate (Set)" in issue for issue in result.issues)


def test_scalar_avaps_respiratory_rate_retains_its_own_label():
    result = parsed(BODY.replace("AVAPS Respiratory Rate: AVAPS rate (cm H2O/min): 14", "AVAPS Respiratory Rate: 18"))
    text = format_ventilation(result.data)
    assert "AVAPS Respiratory Rate: 18" in text
    assert "Set RR:" not in text and "AVAPS rate:" not in text


def test_explicit_rate_units_are_not_duplicated_or_converted():
    result = parsed(BODY.replace("(cm H2O/min): 14", "(cm H2O/min): 1.5 cm H2O/min"))
    line = format_ventilation(result.data).splitlines()[1]
    assert line == "AVAPS rate: 1.5 cm H2O/min"
    assert line.count("cm H2O/min") == 1


def test_conflicting_rate_units_keep_both_units_and_request_review():
    result = parsed(BODY.replace("(cm H2O/min): 14", "(cm H2O/min): 14 breaths/min"))
    assert "AVAPS rate (cm H2O/min): 14 breaths/min" in format_ventilation(result.data)
    assert any("cm H2O/min unit" in issue for issue in result.issues)
    assert result.data["values"]["AVAPS rate (cm H2O/min)"] == "14 breaths/min"


def test_target_preferred_for_avaps_without_overwriting_generic_set_volume():
    result = parsed(BODY + "\nVt (Set, mL): 85 mL")
    assert result.data["values"]["Vt (Set, mL)"] == "85 mL"
    text = format_ventilation(result.data)
    assert "Target TV: 90 mL" in text and "Observed TV: 190 mL" in text
    assert "Set TV:" not in text


def test_conventional_avaps_fields_remain_usable_without_new_section():
    result = parsed("Vent Mode: AVAPS\nResp Rate (Set): 20\nVt (Set, mL): 85\nVt (observed, mL): 100 mL\nPEEP (cm H2O): 7\nFiO2 (%): 40 %")
    assert format_ventilation(result.data) == "Mode: AVAPS\nSet RR: 20\nSet TV: 85 mL\nObserved TV: 100 mL\nSet PEEP: 7 cm H2O\nFiO2: 40 %"


def test_dedicated_and_generic_observed_volumes_do_not_conflict():
    result = parsed(BODY.replace("Observed TV: No data recorded", "Observed TV: Vt (observed, mL): 70 mL"))
    assert result.data["values"]["Vt (observed, mL)"] == "70 mL"
    assert result.data["values"]["AVAPS Observed TV (mL)"] == "190 mL"
    assert "Observed TV: 190 mL" in format_ventilation(result.data)
    assert "Observed TV: 70 mL" not in format_ventilation(result.data)


@pytest.mark.parametrize("inner_label", [
    "Vt (observed, mL)", "Vt Exp ml", "Vt Insp ml", "Vte", "Vti",
    "Observed Tve", "Observed Tvi", "Vt (exhaled, mL)", "Vt expired ml",
    "Vt expiratory ml", "Vt (inspired, mL)",
])
@pytest.mark.parametrize("suffix,stored,display", [
    (": 190 mL", "190 mL", "190 mL"),
    (": Avg: 150 Min: 120 Max: 190", "Avg: 150 Min: 120 Max: 190", "Avg: 150 Min: 120 Max: 190 mL"),
    (" Avg: 150 Min: 120 Max: 190", "Avg: 150 Min: 120 Max: 190", "Avg: 150 Min: 120 Max: 190 mL"),
])
def test_all_observed_aliases_and_ranges_remain_in_avaps_scope(inner_label, suffix, stored, display):
    source = "Vent Mode: Pressure Control\nObserved TV: Vt (observed, mL): 70 mL\nObserved AVAPS TV: " + inner_label + suffix
    result = parsed(source)
    assert result.data["values"] == {
        "Vt (observed, mL)": "70 mL",
        "AVAPS Observed TV (mL)": stored,
    }
    assert "Observed TV: 70 mL" in format_ventilation(result.data)
    assert "190" not in format_ventilation(result.data)
    result.data["mode"] = "AVAPS"
    assert "Observed TV: " + display in format_ventilation(result.data)
    assert "Observed TV: 70 mL" not in format_ventilation(result.data)


def test_unexpected_nested_label_cannot_escape_avaps_observation_scope():
    source = "Vent Mode: Pressure Control\nResp Rate (Set): 20\nObserved AVAPS TV: Resp Rate (Set): 190"
    result = parsed(source)
    assert result.data["values"]["Resp Rate (Set)"] == "20"
    assert result.data["values"]["AVAPS Observed TV (mL)"] == "Resp Rate (Set): 190"
    assert "Set RR: 20" in format_ventilation(result.data)
    assert "190" not in format_ventilation(result.data)


@pytest.mark.parametrize("mode", ["Pressure Control - Intermittent Mandatory Ventilation", "Volume Targeted Pressure Control - Continuous Mandatory Ventilation"])
def test_stale_avaps_fields_are_not_rendered_in_other_modes(mode):
    source = BODY.replace(MODE, mode, 1).replace("Observed TV: No data recorded", "Observed TV: Vt (observed, mL): 70 mL")
    result = parsed(source)
    text = format_ventilation(result.data)
    assert "AVAPS" not in text and "Target TV:" not in text and "PS Min:" not in text and "PS Max:" not in text
    assert "190" not in text
    if mode.startswith("Pressure Control"):
        assert "Observed TV: 70 mL" in text
    assert result.data["values"]["AVAPS Observed TV (mL)"] == "190 mL"


def test_average_observation_does_not_replace_target_or_invent_range():
    source = BODY.replace("Vt (observed, mL): 190 mL", "Vt (observed, mL) Avg: 150 Min: 120 Max: 190")
    text = format_ventilation(parsed(source).data)
    assert "Target TV: 90 mL" in text
    assert "Observed TV: Avg: 150 Min: 120 Max: 190 mL" in text


@pytest.mark.parametrize("placeholder", ["", "--", "No data recorded", "N/A", "None"])
def test_absent_new_fields_are_omitted(placeholder):
    source = "Vent Mode: AVAPS\n" + "\n".join(label + ": " + placeholder for label in (
        "AVAPS Respiratory Rate", "AVAPS Target TV", "Observed AVAPS TV", "PS Min", "PS Max"))
    result = parsed(source)
    assert result.data["values"] == {}
    assert format_ventilation(result.data) == "Mode: AVAPS"


@pytest.mark.parametrize("extra", [
    "AVAPS rate (cm H2O/min): 15",
    "AVAPS Target TV: 95",
    "Observed AVAPS TV: 195 mL",
    "PS Min: 10 cm H2O",
    "PS Max: 25 cm H2O",
])
def test_conflicting_repeated_dedicated_fields_reject_the_section(extra):
    result = parse_ventilation(BODY + "\n" + extra)
    assert result.error and result.data is None


def test_identical_repeated_dedicated_values_are_allowed():
    result = parsed(BODY + "\nAVAPS Target TV: 90\nPS Max: 24 cm H2O")
    assert format_ventilation(result.data) == EXPECTED


def test_invasive_avaps_does_not_borrow_fio2_or_become_noninvasive():
    result = parse_respiratory(BODY, "Non-invasive Ventilation:\nO2 Delivery Method: Trach tube, Other (Comment) (home vent)\nFiO2 (%): 40 %")
    assert not result.error and result.devices == []
    assert format_ventilation(result.invasive) == EXPECTED
    assert "FiO2" not in format_ventilation(result.invasive)


def test_explicit_avaps_niv_stays_out_of_invasive_display():
    result = parse_ventilation(BODY.replace(MODE, MODE + " - Non Invasive Ventilation", 1))
    assert not result.error and result.status == "excluded" and result.data is None


def test_avaps_subsection_does_not_identify_an_unknown_mode():
    result = parse_ventilation(BODY.replace(MODE, "Unknown synthetic mode", 1))
    assert not result.error and result.status == "unknown" and result.data is None
