"""Synthetic ECLS snapshots. No patient paste or identifying narrative is stored."""
from copy import deepcopy

import pytest

from ecls import parse_ecls, validate_ecls, ecls_text, ecls_lines, ecls_issues


BODY = """System Readings
ECMO Mode: Veno-arterial
Day: 9
Oxygenator Day: 0
Pump Flow (L/min): 2.3 LPM
Flow Goal (L/min): 2.25 L/min
Set Speed (rev/min) : 3400 Rev/Min
Blender FiO2 (%): 50 %
Sweep Gas Flow Rate (L/min): 1.2
New ECMO Sweep speed: 9 (L/min)
Cardiac Index (L/min/m2): 99
"""


def sheet(body=BODY, weight="27 kg", bsa="1 m²"):
    result = parse_ecls(body)
    assert not result.error
    return {"ecls": result.data, "dosing_weight": weight,
            "anthropometrics": {"bsa": bsa}, "import_warnings": {},
            "nutrition": {"weight": "30 kg", "include": True}}


def test_exact_fields_and_compact_calculation():
    result = parse_ecls(BODY)
    assert not result.error and not result.issues and result.recognized
    assert result.data == {"mode": "VA", "oxygenator_day": "0", "blood_flow_l_min": "2.3",
                           "rpm": "3400", "sweep_l_min": "1.2", "fio2_percent": "50"}
    assert ecls_lines(sheet()) == ["ECLS settings:", "Mode: VA [Oxy Day: 0]",
        "Blood flow: 2.3 L/min, 85.2 mL/kg/min [CI: 2.3 L/min/m²]",
        "RPM: 3400 | Sweep: 1.2 L/min | FiO₂: 50%"]


@pytest.mark.parametrize("label,expected", [("VA", "VA"), ("veno arterial", "VA"),
    ("Venoarterial", "VA"), ("VV", "VV"), ("Veno-venous", "VV"), ("venovenous", "VV")])
def test_mode_normalization(label, expected):
    assert parse_ecls(BODY.replace("Veno-arterial", label)).data["mode"] == expected


def test_units_tabs_and_thousands_normalize_without_changing_values():
    body = BODY.replace(": ", "\t").replace("3400 Rev/Min", "3,400 RPM").replace("FiO2", "FiO₂")
    assert parse_ecls(body).data == parse_ecls(BODY).data


def test_documented_zero_is_not_missing():
    body = BODY.replace("2.3 LPM", "0 LPM").replace("1.2\n", "0\n").replace("3400 Rev/Min", "0 Rev/Min")
    result = parse_ecls(body)
    assert not result.issues
    text = ecls_text(sheet(body))
    assert "Oxy Day: 0" in text
    assert "0 L/min, 0.0 mL/kg/min [CI: 0 L/min/m²]" in text
    assert "RPM: 0 | Sweep: 0 L/min" in text


@pytest.mark.parametrize("weight", ["", "0 kg", "nan kg", "27", "-27 kg"])
def test_missing_or_invalid_dosing_weight_never_uses_actual_weight(weight):
    data = sheet(weight=weight)
    text = ecls_text(data)
    assert "2.3 L/min, UNK mL/kg/min [CI: 2.3 L/min/m²]" in text
    assert "76.7" not in text
    assert len(ecls_issues(data)) == 1


@pytest.mark.parametrize("bsa", ["", "0 m²", "1", "nan m²", "1 m/kg²"])
def test_missing_or_invalid_bsa_never_uses_chart_ci_or_height(bsa):
    data = sheet(bsa=bsa)
    data["anthropometrics"].update(height="120 cm", bmi="20.83 kg/m²")
    text = ecls_text(data)
    assert "85.2 mL/kg/min [CI: UNK]" in text
    assert "99" not in text
    assert len(ecls_issues(data)) == 1


@pytest.mark.parametrize("weight", ["27000 g", "27 kg"])
def test_weight_units_from_explicit_dosing_weight(weight):
    assert "85.2 mL/kg/min" in ecls_text(sheet(weight=weight))


def test_ci_uses_reported_bsa_and_is_trimmed_to_two_decimal_places():
    text = ecls_text(sheet(bsa="0.67 m²"))
    assert "[CI: 3.43 L/min/m²]" in text


def test_measurement_import_warning_withholds_both_derived_values():
    data = sheet()
    data["import_warnings"]["i"] = [{"action": "not_updated", "code": "section_parse_failed"}]
    assert "2.3 L/min, UNK mL/kg/min [CI: UNK]" in ecls_text(data)
    assert len(ecls_issues(data)) == 2


@pytest.mark.parametrize("body", ["", "No data recorded", "System Readings", "System Readings\nECMO Mode: --\nOxygenator Day: --"])
def test_absent_or_explicit_empty_snapshot(body):
    result = parse_ecls(body)
    assert not result.error and result.data is None and result.clear_only
    assert ecls_text({"ecls": result.data}) == ""
    assert not ecls_text({})


def test_missing_settings_are_unknown_and_never_filled_from_unrelated_values():
    data = sheet("ECMO Mode: VA\nDay: 9\nFlow Goal (L/min): 2\nFiO2 (%): 100\nCardiac Index (L/min/m2): 9")
    assert data["ecls"]["oxygenator_day"] == ""
    text = ecls_text(data)
    assert "Mode: VA [Oxy Day: UNK]" in text
    assert "Blood flow: UNK" in text
    assert "RPM: UNK | Sweep: UNK | FiO₂: UNK" in text


@pytest.mark.parametrize("before,after,key", [
    ("2.3 LPM", "-2.3 LPM", "blood_flow_l_min"),
    ("2.3 LPM", "2300 mL/min", "blood_flow_l_min"),
    ("2.3 LPM", "2 to 3 LPM", "blood_flow_l_min"),
    ("50 %", "150 %", "fio2_percent"),
    ("50 %", "NaN %", "fio2_percent"),
    ("3400 Rev/Min", "3400.5 Rev/Min", "rpm"),
    ("Oxygenator Day: 0", "Oxygenator Day: -1", "oxygenator_day"),
    ("Veno-arterial", "unrecognized source narrative", "mode"),
])
def test_invalid_field_is_omitted_with_static_warning(before, after, key):
    result = parse_ecls(BODY.replace(before, after))
    assert not result.error and result.issues
    assert result.data[key] == ""
    assert after not in str(result.data) + str(result.issues) + result.error


def test_no_source_narrative_stored_or_echoed():
    body = BODY + "Unrecognized label: SYNTHETIC SECRET\nWitness: SYNTHETIC SECRET\n"
    result = parse_ecls(body)
    assert result.data == parse_ecls(BODY).data
    assert "SYNTHETIC SECRET" not in str(result)


def test_repeat_populated_snapshots_rejected_even_if_identical():
    result = parse_ecls(BODY + BODY)
    assert result.data is None and "More than one" in result.error


def test_second_report_without_supported_settings_does_not_resurface_old_report():
    result = parse_ecls(BODY + "System Readings\nDay: 1\n")
    assert result.data is None and "More than one" in result.error


def test_duplicate_empty_header_and_terminal_delimiter_are_safe():
    result = parse_ecls("System Readings\n" + BODY + "adadadadadad\n")
    assert not result.error and result.data == parse_ecls(BODY).data


def test_conflicting_field_rejects_snapshot():
    result = parse_ecls(BODY + "Pump Flow (L/min): 2.6\n")
    assert result.data is None and "Conflicting" in result.error


def test_identical_duplicate_field_is_not_a_conflict():
    result = parse_ecls(BODY + "Pump Flow (L/min): 2.30\n")
    assert not result.error and result.data == parse_ecls(BODY).data


@pytest.mark.parametrize("flag", [{"action": "ecls_hidden"}, {"action": "not_imported"},
    {"action": "not_updated"}, {"action": "field_unknown", "code": "section_boundary"}])
def test_hidden_or_unreliable_ad_does_not_print_previous_settings(flag):
    data = sheet()
    data["import_warnings"]["ad"] = [flag]
    assert ecls_text(data) == ""


def test_field_warning_does_not_hide_valid_settings():
    data = sheet()
    data["import_warnings"]["ad"] = [{"action": "field_unknown", "code": "ecls_incomplete"}]
    assert "2.3 L/min" in ecls_text(data)


@pytest.mark.parametrize("changes", [{"source_text": "forbidden"}, {"mode": "narrative"},
    {"rpm": 3400}, {"rpm": "3400.5"}, {"fio2_percent": "101"}, {"blood_flow_l_min": "nan"},
    {"blood_flow_l_min": "-1"}, {"oxygenator_day": "1.5"}])
def test_validation_rejects_unstructured_or_invalid_values(changes):
    data = deepcopy(parse_ecls(BODY).data)
    data.update(changes)
    with pytest.raises(ValueError):
        validate_ecls(data)


def test_invalid_input_returns_static_error():
    assert parse_ecls(None).error
    assert parse_ecls("x" * 20001).error
