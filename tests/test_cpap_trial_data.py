"""PS-CPAP headings and rate suppression use synthetic source records."""
from copy import deepcopy

import pytest

from clinical_style import clinical_markup
from ventilation import format_ventilation, parse_first_reported_ventilation, parse_ventilation


PS_CPAP = "Pressure Support - Continuous Positive Airway Pressure"
VALUES = {
    "Resp Rate (Set)": "12",
    "Resp Rate Observed": "Avg: 18 Min: 12 Max: 25",
    "Pressure Support (cm H2O)": "8",
    "PEEP (cm H2O)": "5",
    "FiO2 set (%)": "30",
    "Weaning Tidal Volume": "Avg: 110 Min: 90 Max: 130",
    "Weaning Tolerance": "Good",
}


@pytest.mark.parametrize("mode", [PS_CPAP, "PS-CPAP", "PS - CPAP", "(S) " + PS_CPAP])
def test_current_and_legacy_cpap_records_have_trial_title_without_rate(mode):
    data = {"mode": mode, "values": deepcopy(VALUES)}
    before = deepcopy(data)
    text = format_ventilation(data)
    assert text.startswith("CPAP Trial Data\nMode: PS-CPAP\n")
    assert "RR" not in text and "Respiratory Rate" not in text
    assert "Pressure Support: 8 cm H2O" in text
    assert "Set PEEP: 5 cm H2O" in text
    assert "FiO2: 30 %" in text
    assert "Weaning TV: 90–130 mL" in text
    assert "Weaning Tolerance: Good" in text
    assert data == before


def test_history_cpap_title_is_scoped_and_other_modes_keep_rate():
    data = {
        "mode": "PRVC-IMV", "values": {"Resp Rate (Set)": "16"},
        "mode_history": {
            "reported_at": "2026-11-22T06:00", "latest_confirmed": True, "notes": [],
            "other_modes": [{"mode": PS_CPAP, "values": deepcopy(VALUES),
                             "reported_at": "2026-11-22T05:00"}],
        },
    }
    main, trial = format_ventilation(data).split("\n---\n")
    assert main.startswith("Mode: PRVC-IMV (11/22/26 06:00)")
    assert "Set RR: 16" in main and "CPAP Trial Data" not in main
    assert trial.startswith("CPAP Trial Data\nMode: PS-CPAP (11/22/26 05:00)")
    assert "RR" not in trial
    data["mode_history"]["other_modes"][0]["include"] = False
    assert "CPAP Trial Data" not in format_ventilation(data)


def test_template_heading_without_reported_cpap_mode_does_not_create_trial():
    source = """Mode: Vent Mode: PRVC-IMV
Resp Rate (Set): 16
Vt (Set, mL): 100
PEEP (cm H2O): 5
CPAP Trial Settings:
Pressure Support (cm H2O): 8
PEEP (cm H2O): 5
All Vent Modes:
"""
    parsed = parse_ventilation(source)
    assert not parsed.error
    text = format_ventilation(parsed.data)
    assert "CPAP Trial Data" not in text
    assert "Set RR: 16" in text


def test_niv_cpap_does_not_become_invasive_trial():
    result = parse_ventilation("Vent Mode: Continuous Positive Airway Pressure - Non Invasive Ventilation")
    assert result.status == "excluded" and result.data is None


def test_trial_heading_uses_shared_rich_text_emphasis():
    assert clinical_markup("CPAP Trial Data\nMode: PS-CPAP") == "<b>CPAP Trial Data</b>\nMode: PS-CPAP"


def test_title_does_not_count_as_a_setting_for_history_fallback():
    result = parse_first_reported_ventilation("Vent Mode: PS-CPAP\nResp Rate (Set): 12\nAll Vent Modes:\n")
    assert result.data is None
    assert result.error == "No first reported ventilator settings were available in this paste."
