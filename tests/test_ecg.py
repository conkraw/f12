"""Synthetic Bazett result selection and display boundary checks."""
from copy import deepcopy
import json

import pytest

from ecg import parse_ecg, validate_ecg, format_ecg, long_qtc, ecg_text


def report(value="425", date="11/13/2026", unit="ms"):
    return f"ECG 12 lead {date}\nQ-T Interval: 280 ms\nQTC Calculation(Bazett): {value} {unit}"


def test_named_bazett_result_and_header_date_only():
    text = report("426") + "\nCalculated P Axis: 89 degrees\nConfirmed on 11/14/2026 by Synthetic Reader"
    result = parse_ecg(text)
    assert not result.error and not result.issues
    assert result.data == {"value": "426", "date": "11/13/2026"}
    assert format_ecg(result.data) == "QTc: 426 msec [11/13/2026]"
    assert "Reader" not in json.dumps(result.data)


@pytest.mark.parametrize("value, flagged", [("425", False), ("450", False), ("450.0", False), ("450.1", True), ("451", True)])
def test_strict_greater_than_450_boundary(value, flagged):
    data = parse_ecg(report(value)).data
    assert long_qtc(data) is flagged
    assert format_ecg(data).endswith(" (!)") is flagged


@pytest.mark.parametrize("date, expected", [("01/02/1999", "01/02/1999"), ("1/2/19", "01/02/2019"), ("2010-08-25", "08/25/2010")])
def test_historical_results_have_no_age_limit(date, expected):
    result = parse_ecg(report("475", date))
    assert not result.error
    assert result.data == {"value": "475", "date": expected}
    assert long_qtc(result.data)


@pytest.mark.parametrize("header", ["qTc Calculation (Bazett):", "QTC Calculation(BAZETT):", "QTc Calculation ( Bazett )："])
@pytest.mark.parametrize("unit", ["ms", "msec", "milliseconds"])
def test_casing_spacing_and_explicit_units(header, unit):
    result = parse_ecg(f"ECG 12 lead 11/13/2026\n{header} 425 {unit}")
    assert not result.error
    assert result.data == {"value": "425", "date": "11/13/2026"}


def test_explicit_unit_in_label():
    result = parse_ecg("ECG 12 lead 11/13/2026\nQTc Calculation (Bazett) (ms): 425")
    assert not result.error
    assert result.data["value"] == "425"


def test_newest_date_selected_independent_of_source_order():
    newer, older = report("425", "02/01/2026"), report("480", "01/01/2019")
    for text in (older + "\n" + newer, newer + "\n" + older):
        result = parse_ecg(text)
        assert not result.error
        assert result.data == {"value": "425", "date": "02/01/2026"}
        assert not long_qtc(result.data)


def test_known_times_resolve_results_with_same_date():
    text = report("480", "02/01/2026 08:30") + "\n" + report("425", "02/01/2026 09:45")
    result = parse_ecg(text)
    assert not result.error
    assert result.data["value"] == "425"


def test_study_date_field_and_bare_date_after_header():
    for date_line in ("Study Date: 11/13/2026", "11/13/2026", "Date/Time: 11/13/2026 09:30 AM"):
        result = parse_ecg("ECG 12 lead\n" + date_line + "\nQTc Calculation(Bazett): 425 ms")
        assert not result.error
        assert result.data["date"] == "11/13/2026"


def test_inline_result_date_stays_with_result():
    result = parse_ecg("QTc Calculation(Bazett): 425 ms [11/13/2026]")
    assert not result.error
    assert result.data == {"value": "425", "date": "11/13/2026"}


def test_missing_date_not_borrowed_from_confirmation_or_other_ecg():
    result = parse_ecg("ECG 12 lead\nQTc Calculation(Bazett): 425 ms\nConfirmed on 11/13/2026")
    assert not result.error and result.data["date"] == ""
    assert format_ecg(result.data) == "QTc: 425 msec"
    result = parse_ecg(report("480", "01/01/2019") + "\nECG 12 lead\nQTc Calculation(Bazett): 425 ms")
    assert result.error and result.data is None


def test_same_undated_value_does_not_remove_known_date():
    result = parse_ecg(report("425", "01/01/2019") + "\nECG 12 lead\nQTc Calculation(Bazett): 425 ms")
    assert not result.error and result.issues
    assert result.data == {"value": "425", "date": "01/01/2019"}


@pytest.mark.parametrize("text", ["", "ECG:", "ECG: No results found", "ECG 12 lead\nQTc Calculation(Bazett): --",
    "ECG 12 lead\nQ-T Interval: 280 ms\nQTc Calculation(Fridericia): 435 ms", "QTc: 425 ms"])
def test_absent_bazett_result_is_empty_not_other_formula(text):
    result = parse_ecg(text)
    assert not result.error and result.data is None
    assert format_ecg(result.data) == "" and not long_qtc(result.data)


@pytest.mark.parametrize("body", [report("0"), report("-20"), report("425", unit="s"), report("425", unit=""),
    report("425/450"), report("425", "11/31/2026"), report("425", "11/13/2026 25:00"),
    report("425") + "\nQTc Calculation(Bazett): 480 ms",
    report("425") + "\nStudy Date: 11/14/2026",
    report("425") + "\n" + report("480"),
    report("425") + "\n" + report("480", "11/13/2026 09:30"),
    "QTc Calculation(Bazett) 425 ms"])
def test_malformed_or_ambiguous_data_fails_without_guessing(body):
    result = parse_ecg(body)
    assert result.error and result.data is None
    assert "425/450" not in result.error


def test_equal_duplicate_results_are_unambiguous():
    result = parse_ecg(report("425") + "\n" + report("425.0"))
    assert not result.error
    assert not long_qtc(result.data)


@pytest.mark.parametrize("bad", [{}, {"value": "450", "date": "11/13/26"}, {"value": "451 ms", "date": ""},
    {"value": "451", "date": "11/31/2026"}, {"value": 451, "date": ""}, {"value": "NaN", "date": ""},
    {"value": "451", "date": "", "narrative": "not retained"}])
def test_persisted_snapshot_validated(bad):
    with pytest.raises(ValueError):
        validate_ecg(bad)


def test_rendering_does_not_modify_saved_data_and_failed_import_hides_previous():
    sheet = {"ecg": {"value": "451", "date": "11/13/2026"}, "import_warnings": {}}
    before = deepcopy(sheet)
    assert ecg_text(sheet) == "QTc: 451 msec [11/13/2026] (!)"
    assert sheet == before
    sheet["import_warnings"]["z"] = [{}]
    assert ecg_text(sheet) == ""
