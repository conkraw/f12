"""Synthetic mode-history regressions. No patient records are retained."""
from copy import deepcopy
import json

import pytest

from noninvasive import read_fields
from ventilation import format_ventilation, parse_ventilation, validate_ventilation


MAIN = """Invasive Ventilation:
Mode: Vent Mode: PRVC-IMV
Resp Rate (Set): 14
Vt (Set, mL): 100
PEEP (cm H2O): 5
FiO2 set (%): 55 %
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


def history(*rows, main=MAIN):
    return main + "\nAll Vent Modes:\n" + "\n".join(rows)


def parsed(source):
    result = parse_ventilation(source)
    assert not result.error, result.error
    assert result.data is not None
    validate_ventilation(result.data)
    return result


def test_history_sort_is_chronological_and_keeps_subtypes_separate():
    result = parsed(history(
        "Vent Mode: NAVA (11/20/26 0600 : Chart Author)",
        "Vent Mode: PRVC-PS (11/19/26 2100 : Chart Author)",
        "Vent Mode: PRVC-IMV (11/20/26 1800 : Chart Author)",
        "Vent Mode: Neurally Adjusted Ventilatory Assist (11/20/26 1200 : Chart Author)",
    ))
    assert result.data["mode"] == "PRVC-IMV"
    assert result.data["values"]["FiO2 set (%)"] == "55 %"
    meta = result.data["mode_history"]
    assert meta["reported_at"] == "2026-11-20T18:00"
    assert len(meta["other_modes"]) == 2
    assert meta["other_modes"][0]["values"]["FiO2 (%)"] == "30 %"
    assert meta["other_modes"][1]["values"] == {}
    assert "Chart Author" not in json.dumps(result.data)


@pytest.mark.parametrize("full,short", [
    ("Pressure Control", "PC"),
    ("Pressure Regulated Volume Control", "PRVC"),
    ("Volume Control", "VC"),
])
def test_equivalent_display_aliases_have_only_one_history_entry(full, short):
    result = parsed(history(
        "Vent Mode: PRVC-IMV (11/20/26 1800 : Chart Author)",
        "Vent Mode: " + full + " (11/20/26 1600 : Chart Author)",
        "Vent Mode: " + short + " (11/20/26 1500 : Chart Author)",
    ))
    assert len(result.data["mode_history"]["other_modes"]) == 1


def test_latest_different_mode_uses_its_dedicated_settings_for_both_readers():
    source = history(
        "Vent Mode: PRVC-IMV (11/20/26 1700 : Chart Author)",
        "Vent Mode: NAVA (11/20/26 1800 : Chart Author)",
    )
    result = parsed(source)
    assert result.data["mode"] == "NAVA"
    assert result.data["values"]["PEEP (cm H2O)"] == "7"
    assert "Vt (Set, mL)" not in result.data["values"]
    assert read_fields(source, "C")["mode"] == "NAVA"
    assert read_fields(source, "C")["fio2"] == "30 %"
    prior = result.data["mode_history"]["other_modes"][0]
    assert prior["values"]["FiO2 set (%)"] == "55 %"


@pytest.mark.parametrize("line_ending", ["\n", "\r\n", "\r"])
def test_all_supported_line_endings_use_the_same_latest_mode(line_ending):
    source = history(
        "Vent Mode: PRVC-IMV (11/20/26 1700 : Chart Author)",
        "Vent Mode: NAVA (11/20/26 1800 : Chart Author)",
    ).replace("\n", line_ending)
    result = parsed(source)
    assert result.data["mode"] == "NAVA"
    assert result.data["mode_history"]["reported_at"] == "2026-11-20T18:00"
    assert read_fields(source, "C")["mode"] == "NAVA"


def test_new_latest_mode_without_its_own_settings_is_not_relabelled_snapshot():
    result = parsed(history(
        "Vent Mode: PRVC-IMV (11/20/26 1700 : Chart Author)",
        "Vent Mode: Pressure Control (11/20/26 1800 : Chart Author)",
    ))
    assert result.data["mode"] == "Pressure Control"
    assert result.data["values"] == {}
    assert result.data["mode_history"]["latest_confirmed"] is True
    assert "Settings not available for this mode" in format_ventilation(result.data)


def test_unknown_newest_preserves_main_snapshot_with_explicit_uncertainty():
    result = parsed(history(
        "Vent Mode: PRVC-IMV (11/20/26 1700 : Chart Author)",
        "Vent Mode: Future Experimental Mode (11/20/26 1800 : Chart Author)",
    ))
    assert result.data["mode"] == "PRVC-IMV"
    assert not result.data["mode_history"]["latest_confirmed"]
    assert result.data["mode_history"]["other_modes"][0]["values"] == {}
    assert "latest uncertain" in format_ventilation(result.data)
    assert result.issues


def test_newest_timestamp_tie_does_not_claim_a_latest_mode():
    result = parsed(history(
        "Vent Mode: PRVC-IMV (11/20/26 1800 : Chart Author)",
        "Vent Mode: NAVA (11/20/26 1800 : Chart Author)",
    ))
    assert not result.data["mode_history"]["latest_confirmed"]
    assert any("share the newest timestamp" in note for note in result.issues)


@pytest.mark.parametrize("malformed", [
    "NAVA(11/20/26 1900:AUTHOR_NAME,RRT",
    "NAVA 11/20/26 1900:AUTHOR_NAME,RRT",
    "NAVA (invalid:AUTHOR_NAME,RRT)",
    "NAVA (11/55/26 1900:AUTHOR_NAME,RRT)",
])
def test_malformed_history_keeps_author_out_of_saved_data_and_messages(malformed):
    result = parsed(history(
        "Vent Mode: PRVC-IMV (11/20/26 1800 : Chart Author)",
        "Vent Mode: " + malformed,
    ))
    assert not result.data["mode_history"]["latest_confirmed"]
    assert "AUTHOR_NAME" not in json.dumps(result.data) + " ".join(result.issues)
    assert "Chart Author" not in json.dumps(result.data)


@pytest.mark.parametrize("empty_history", ["", "\nAll Vent Modes:\n"])
def test_no_history_keeps_other_explicit_mode_settings_out_of_main(empty_history):
    source = MAIN + "\nPressure Control Settings:\nPEEP (cm H2O): 11\n" + empty_history
    result = parsed(source)
    assert "mode_history" not in result.data
    assert result.data["values"]["PEEP (cm H2O)"] == "5"
    assert read_fields(source, "C")["peep"] == "5"


def test_unknown_annotation_is_not_silently_normalized_to_another_mode():
    result = parsed(history(
        "Vent Mode: PRVC-IMV (11/20/26 1800 : Chart Author)",
        "Vent Mode: Pressure Control (Special)",
    ))
    assert result.data["mode_history"]["other_modes"][0]["mode"] == "Pressure Control (Special)"


def test_conflicting_historical_settings_do_not_discard_valid_main_snapshot():
    source = MAIN.replace("NAVA level: 2", "NAVA level: 2\nNAVA level: 3")
    result = parsed(history(
        "Vent Mode: PRVC-IMV (11/20/26 1800 : Chart Author)",
        "Vent Mode: NAVA (11/20/26 1700 : Chart Author)", main=source,
    ))
    assert result.data["values"]["FiO2 set (%)"] == "55 %"
    assert result.data["mode_history"]["other_modes"][0]["values"] == {}
    assert any("Conflicting settings" in note for note in result.issues)


def test_prior_mode_visibility_is_optional_and_does_not_mutate_saved_record():
    result = parsed(history(
        "Vent Mode: PRVC-IMV (11/20/26 1800 : Chart Author)",
        "Vent Mode: NAVA (11/20/26 1700 : Chart Author)",
    ))
    result.data["mode_history"]["other_modes"][0]["include"] = False
    before = deepcopy(result.data)
    validate_ventilation(result.data)
    assert "Mode: NAVA" not in format_ventilation(result.data)
    assert result.data == before


def test_unknown_mode_values_cannot_be_injected_into_saved_history():
    result = parsed(history(
        "Vent Mode: PRVC-IMV (11/20/26 1800 : Chart Author)",
        "Vent Mode: Unfamiliar Mode (11/20/26 1700 : Chart Author)",
    ))
    result.data["mode_history"]["other_modes"][0]["values"]["PEEP (cm H2O)"] = "5"
    with pytest.raises(ValueError):
        validate_ventilation(result.data)


def test_prior_noninvasive_mode_does_not_enter_invasive_history():
    result = parsed(history(
        "Vent Mode: PRVC-IMV (11/20/26 1800 : Chart Author)",
        "Vent Mode: NAVA NIV (11/20/26 1700 : Chart Author)",
    ))
    assert result.data["mode_history"]["other_modes"] == []
    assert "Mode: NAVA NIV" not in format_ventilation(result.data)
