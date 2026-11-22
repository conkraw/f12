"""Synthetic circumference extraction, last-measurement selection, and display."""
from copy import deepcopy

import pytest

from circumferences import (
    circumferences_text,
    empty_circumferences,
    parse_circumferences,
    validate_circumferences,
)


def test_epic_repeated_label_retains_only_measurement_and_its_date():
    source = (
        "NUTRITION:\n11/19/26\t6.3 kg (<1%, Z= -3.38)\n"
        'Head Circumference: Head Circumference: 42.5 cm (16.73") '
        "(11/20/26 0400 : Synthetic Staff Member, RN)\n"
        "\nAbdominal Circumference:  \n"
    )
    parsed = parse_circumferences(source)
    assert parsed.data == {"head": {"value_cm": "42.5", "date": "2026-11-20"}, "abdominal": None}
    assert not parsed.issues
    assert "6.3 kg (<1%, Z= -3.38)" in parsed.remainder
    assert "Circumference" not in parsed.remainder
    assert "Synthetic Staff Member" not in repr(parsed)
    assert circumferences_text(parsed.data, "10 m.o.") == "Head circumference: 42.5 cm [11/20/26]"


@pytest.mark.parametrize("label", ["Abdominal Circumference", "Abdominal Girth", "Abd. girth", "abd circumference"])
@pytest.mark.parametrize("spacing", [" ", "\n", "\n\n"])
def test_abdominal_aliases_and_next_line_values(label, spacing):
    parsed = parse_circumferences(label + ":" + spacing + "35 cm (11/22/2026 16:00)")
    assert not parsed.issues
    assert parsed.data["abdominal"] == {"value_cm": "35", "date": "2026-11-22"}
    assert circumferences_text(parsed.data, "22 y.o.") == "Abdominal girth: 35 cm [11/22/26]"


@pytest.mark.parametrize("value,expected", [("425 mm", "42.5"), ("42.500 cm", "42.5"), ("16.5 in", "41.91"), ('16.5"', "41.91"), ("425 millimetres", "42.5")])
def test_explicit_units_normalize_to_centimeters(value, expected):
    parsed = parse_circumferences("Head Circumference: " + value)
    assert not parsed.issues
    assert parsed.data["head"] == {"value_cm": expected, "date": ""}


@pytest.mark.parametrize("age", ["0 days", "10 days", "5 wk.o.", "10 m.o.", "23 months", "1 y.o.", "1 year 11 months", "23.99 months"])
def test_head_display_is_limited_to_patients_known_to_be_under_two(age):
    parsed = parse_circumferences("Head Circumference: 42 cm\nAbdominal Circumference: 35 cm")
    before = deepcopy(parsed.data)
    text = circumferences_text(parsed.data, age)
    assert "Head circumference: 42 cm" in text
    assert "Abdominal girth: 35 cm" in text
    assert parsed.data == before


@pytest.mark.parametrize("age", ["", "2 y.o.", "24 months", "2 years 0 months", "18 years", "104 weeks", "unknown"])
def test_head_display_not_allowed_at_two_or_when_age_is_uncertain(age):
    parsed = parse_circumferences("Head Circumference: 42 cm\nAbdominal Circumference: 35 cm")
    assert circumferences_text(parsed.data, age) == "Abdominal girth: 35 cm"


def test_latest_date_wins_regardless_of_source_order():
    for entries in [
        ["42 cm (11/19/26 0800)", "43 cm (11/22/26 0400)", "42.5 cm (11/20/26 1000)"],
        ["43 cm (11/22/26 0400)", "42 cm (11/19/26 0800)", "42.5 cm (11/20/26 1000)"],
    ]:
        parsed = parse_circumferences("\n".join("Head Circumference: " + entry for entry in entries))
        assert not parsed.issues
        assert parsed.data["head"] == {"value_cm": "43", "date": "2026-11-22"}


def test_latest_time_on_same_day_wins():
    parsed = parse_circumferences(
        "Abdominal girth: 40 cm (11/22/26 4:00 PM)\n"
        "Abdominal girth: 39 cm (11/22/26 12:00 AM)\n"
        "Abdominal girth: 38 cm (11/22/26 0400)"
    )
    assert parsed.data["abdominal"] == {"value_cm": "40", "date": "2026-11-22"}
    assert not parsed.issues


def test_next_line_date_is_associated_only_with_that_measurement():
    parsed = parse_circumferences(
        "Date of Admission: 11/01/2026\nHead Circumference:\n42.5 cm\n"
        "(11/20/26 0400 : Synthetic Staff Member, RN)\nAbdominal Circumference: 35 cm"
    )
    assert parsed.data["head"]["date"] == "2026-11-20"
    assert parsed.data["abdominal"]["date"] == ""
    assert "Date of Admission: 11/01/2026" in parsed.remainder
    assert "Synthetic Staff" not in repr(parsed)


def test_date_first_history_rows_choose_latest_without_consuming_weight():
    parsed = parse_circumferences(
        "Head Circumference:\n11/21/26 0800 42 cm\n11/22/26 0400 42.5 cm\n"
        "Weight: 6.3 kg\nBMI: 17.54"
    )
    assert parsed.data["head"] == {"value_cm": "42.5", "date": "2026-11-22"}
    assert not parsed.issues
    assert parsed.remainder == "Weight: 6.3 kg\nBMI: 17.54"


def test_two_labeled_measurements_on_one_line_stay_distinct():
    parsed = parse_circumferences("Head Circumference: 42 cm (11/20/26) Abdominal girth: 35 cm (11/22/26)")
    assert not parsed.issues
    assert parsed.data == {"head": {"value_cm": "42", "date": "2026-11-20"}, "abdominal": {"value_cm": "35", "date": "2026-11-22"}}


@pytest.mark.parametrize("missing", ["", "None", "No data recorded", "--", "Not measured"])
def test_missing_measurement_stays_missing(missing):
    parsed = parse_circumferences("Head Circumference: " + missing + "\nAbdominal Circumference: \nHeight: 58 cm")
    assert parsed.data == empty_circumferences()
    assert parsed.remainder == "Height: 58 cm"
    assert not parsed.issues


@pytest.mark.parametrize("bad", [
    "0 cm", "-42 cm", "500 cm", "42", "NaN cm", "42-43 cm", "42 cm - 43 cm",
    "42 cm (13/01/26)", "42 cm (02/30/2026)", "42 cm (11/20)", "42 cm (11/20/26 2500)",
    "42 cm (11/20/26 0400) (11/21/26 0400)", "42 cm (16.53\") (entered in error)",
    '42.5 cm (20.00")', "42.5 cm (43 cm)", "42 cm (estimated)",
])
def test_invalid_measurements_or_dates_are_omitted_with_static_issue(bad):
    parsed = parse_circumferences("Head Circumference: " + bad)
    assert parsed.data["head"] is None
    assert parsed.issues
    assert bad not in " ".join(parsed.issues)
    assert "Head Circumference" not in parsed.remainder


def test_latest_invalid_reading_never_falls_back_to_an_older_value():
    parsed = parse_circumferences("Head Circumference: 42 cm (11/20/26)\nHead Circumference: 999 cm (11/22/26)")
    assert parsed.data["head"] is None
    assert parsed.issues


def test_old_invalid_reading_does_not_suppress_a_valid_newer_date():
    parsed = parse_circumferences("Head Circumference: 999 cm (11/20/26)\nHead Circumference: 42 cm (11/22/26)")
    assert parsed.data["head"] == {"value_cm": "42", "date": "2026-11-22"}
    assert parsed.issues


@pytest.mark.parametrize("entries", [
    "Head Circumference: 42 cm\nHead Circumference: 43 cm",
    "Head Circumference: 42 cm (11/20/26)\nHead Circumference: 43 cm",
    "Head Circumference: 42 cm (11/20/26 0400)\nHead Circumference: 43 cm (11/20/26 0400)",
    "Head Circumference: 42 cm (11/20/26)\nHead Circumference: 43 cm (11/20/26 0400)",
])
def test_conflicting_measurements_without_comparable_times_are_not_guessed(entries):
    parsed = parse_circumferences(entries)
    assert parsed.data["head"] is None
    assert parsed.issues


def test_duplicate_equivalent_values_are_unambiguous():
    parsed = parse_circumferences("Head Circumference: 42.5 cm\nHead Circumference: 425 mm (11/20/26)")
    assert not parsed.issues
    assert parsed.data["head"] == {"value_cm": "42.5", "date": "2026-11-20"}


@pytest.mark.parametrize("data", [
    {}, {"head": None}, {"head": None, "abdominal": None, "other": None},
    {"head": {"value_cm": "42.50", "date": ""}, "abdominal": None},
    {"head": {"value_cm": "0", "date": ""}, "abdominal": None},
    {"head": {"value_cm": "42.5", "date": "11/20/26"}, "abdominal": None},
    {"head": {"value_cm": "42.5", "date": "2026-02-30"}, "abdominal": None},
    {"head": {"value_cm": "42.5", "date": "", "nurse": "Name"}, "abdominal": None},
])
def test_saved_data_validation_rejects_unexpected_or_unnormalized_content(data):
    with pytest.raises(ValueError):
        validate_circumferences(data)


def test_unrelated_dates_values_and_labels_are_never_inferred():
    source = "11/22/26 6.3 kg\nBMI: 17.54 kg/m²\nHeight: 58 cm\nDate of Admission: 10/29/26"
    parsed = parse_circumferences(source)
    assert parsed.data == empty_circumferences()
    assert parsed.remainder == source
    assert not parsed.issues


@pytest.mark.parametrize("head", ["", "42.5 cm"])
def test_a_following_dated_weight_is_not_consumed_as_a_circumference_date(head):
    parsed = parse_circumferences("Head Circumference: " + head + "\n11/22/26 6.3 kg (<1%, Z= -3.38)")
    assert parsed.remainder == "11/22/26 6.3 kg (<1%, Z= -3.38)"
    assert not parsed.issues
    assert parsed.data["head"] == ({"value_cm": "42.5", "date": ""} if head else None)

