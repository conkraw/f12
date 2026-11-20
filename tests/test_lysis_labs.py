"""Synthetic Lysis Labs identity, recent-window and latest-two checks."""
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from lab_windows import display_clock, eligible_time
from labs import parse_labs
from lysis_labs import COMPONENTS, lysis_component, lysis_selection, lysis_summary


ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 20, 8, 0, tzinfo=ET)


def sheet(source=""):
    result = parse_labs("LABS:\nComponent\tValue\tDate\n" + source)
    assert not result.error, result.error
    return {"labs": result.data, "import_warnings": {}}


def test_sample_single_result_has_no_arrow_or_missing_test_placeholders():
    data = sheet("HGBFREE\t<8\t11/20/2026")
    assert lysis_summary(data, NOW) == "Lysis Labs:\nHGBFREE: <8 [11/20/2026]"
    selected = lysis_selection(data, NOW)
    assert list(selected) == ["HGBFREE"]
    assert selected["HGBFREE"][0] is data["labs"]["rows"][0]


def test_latest_two_not_earliest_and_latest_when_more_results_exist():
    data = sheet("LDH\t990\t11/19/2026 10:00\n"
                 "LDH\t600 (H)\t11/20/2026 07:00\n"
                 "LDH\t720\t11/20/2026 04:00\n"
                 "LDH\t850\t11/20/2026 01:00")
    assert [row["value"] for row in lysis_selection(data, NOW)["LDH"]] == ["600 (H)", "720"]
    assert lysis_summary(data, NOW) == "Lysis Labs:\nLDH: 720 -> 600 (H) [11/20/2026]"


def test_analytes_are_selected_independently_and_display_in_fixed_order():
    data = sheet("URIC ACID\t4.2\t11/20/2026 07:00\n"
                 "LDH\t600\t11/20/2026 06:00\n"
                 "URICACID\t5.1 (H)\t11/20/2026 05:00\n"
                 "HGBFREE\t<8\t11/20/2026 07:30")
    assert lysis_summary(data, NOW) == (
        "Lysis Labs:\nHGBFREE: <8 [11/20/2026]\n"
        "LDH: 600 [11/20/2026]\nUric acid: 5.1 (H) -> 4.2 [11/20/2026]")


@pytest.mark.parametrize("code", COMPONENTS)
@pytest.mark.parametrize("date,eligible", [
    ("11/19/2026 07:59:59", False),
    ("11/19/2026 08:00", True),
    ("11/19/2026 08:00:01", True),
    ("11/20/2026 08:00", True),
    ("11/20/2026 08:00:01", False),
    ("11/18/2026", False),
    ("11/19/2026", True),
    ("11/20/2026", True),
    ("11/21/2026", False),
])
def test_uses_same_24_hour_and_date_overlap_rule_as_lactate(code, date, eligible):
    data = sheet(f"{code}\t0\t{date}")
    row = data["labs"]["rows"][0]
    assert eligible_time(row, NOW, hours=24) is eligible
    assert bool(lysis_selection(data, NOW)) is eligible


@pytest.mark.parametrize("source,canonical", [
    ("hgbfree", "HGBFREE"), ("HGB FREE", "HGBFREE"),
    ("PLASMA FREE HEMOGLOBIN", "HGBFREE"), ("HEMOGLOBIN, FREE, PLASMA", "HGBFREE"),
    ("HGBFREE, PLASMA", "HGBFREE"), ("FREE HEMOGLOBIN (PLASMA)", "HGBFREE"),
    ("LDH", "LDH"), ("LDH, TOTAL", "LDH"),
    ("LACTATE DEHYDROGENASE", "LDH"), ("LACTIC ACID DEHYDROGENASE", "LDH"),
    ("LDH, SERUM", "LDH"), ("LACTATE DEHYDROGENASE (PLASMA)", "LDH"),
    ("URIC ACID", "URICACID"), ("URICACID", "URICACID"),
    ("Uric Acid, Serum", "URICACID"), ("URIC ACID PLASMA", "URICACID"),
    ("URIC ACID (PLASMA)", "URICACID"),
])
def test_explicit_assay_and_serum_plasma_aliases(source, canonical):
    assert lysis_component(source) == canonical
    data = sheet(f"{source}\t10\t11/20/2026")
    assert list(lysis_selection(data, NOW)) == [canonical]


@pytest.mark.parametrize("source", [
    "HGB", "HEMOGLOBIN", "HB", "HGB_ISTAT", "HGBFREE_ALT", "HGBFREE2",
    "HEMOGLOBIN URINE", "FREE HEMOGLOBIN URINE", "HGBFREE, URINE",
    "LDH ISOENZYMES", "LDH, ISOENZYMES", "LDH1", "LDH-1", "LDH, BODY FLUID",
    "LACTATE", "LACTIC ACID", "URIC ACID, URINE", "URIC ACID URINE",
    "URICACID URINE", "URIC ACID 24 HOUR URINE", "URICACID2", "", None,
])
def test_other_assays_do_not_match(source):
    assert lysis_component(source) == ""


def test_alias_results_share_one_assay_selection_without_changing_source_labels():
    data = sheet("LDH\t700\t11/20/2026 02:00\n"
                 "Lactate Dehydrogenase\t600\t11/20/2026 07:00\n"
                 "LDH, SERUM\t650\t11/20/2026 05:00")
    before = deepcopy(data)
    assert lysis_summary(data, NOW) == "Lysis Labs:\nLDH: 650 -> 600 [11/20/2026]"
    assert data == before


@pytest.mark.parametrize("dates", [
    ("11/20/2026", "11/20/2026", "11/20/2026"),
    ("11/20/2026", "11/20/2026 07:00", "11/20/2026 06:00"),
    ("11/20/2026 04:00", "11/20/2026", "11/20/2026 07:00"),
    ("11/20/2026 07:00", "11/20/2026 07:00", "11/20/2026 07:00"),
])
def test_same_date_missing_times_and_ties_keep_source_order(dates):
    data = sheet("\n".join(f"LDH\t{value}\t{date}" for value, date in zip((600, 700, 800), dates)))
    assert [row["value"] for row in lysis_selection(data, NOW)["LDH"]] == ["600", "700"]
    assert "700 -> 600" in lysis_summary(data, NOW)


def test_newest_source_date_supplies_display_date_without_invented_time():
    data = sheet("URIC ACID\t4.2\t01/02/2026 07:00\nURICACID\t5.1\t01/01/2026 12:00")
    now = datetime(2026, 1, 2, 8, 0, tzinfo=ET)
    assert lysis_summary(data, now) == "Lysis Labs:\nUric acid: 5.1 -> 4.2 [1/2/2026]"


@pytest.mark.parametrize("value", ["0", "<8", "< 8", "600 (H)", "700 U/L", "5.1 mg/dL (H)", ">100 (HH)"])
def test_source_values_units_flags_and_censoring_are_preserved(value):
    data = sheet(f"HGBFREE\t{value}\t11/20/2026")
    before = deepcopy(data)
    assert lysis_summary(data, NOW) == "Lysis Labs:\nHGBFREE: " + value + " [11/20/2026]"
    assert data == before


@pytest.mark.parametrize("value", ["Pending", "Canceled", "Hemolyzed", "--", "1.2 pending", "1.2 invalid", "1.2 rejected"])
def test_nonresults_are_omitted_without_consuming_latest_two_slots(value):
    data = sheet(f"LDH\t{value}\t11/20/2026 07:30\n"
                 "LDH\t600\t11/20/2026 07:00\nLDH\t700\t11/20/2026 06:00")
    assert lysis_summary(data, NOW) == "Lysis Labs:\nLDH: 700 -> 600 [11/20/2026]"


@pytest.mark.parametrize("date", ["", "not a date", None, "11/31/2026", "11/20/2026 29:00"])
def test_malformed_dates_are_omitted(date):
    data = sheet("HGBFREE\t<8\t11/20/2026")
    data["labs"]["rows"][0]["date"] = date
    assert lysis_summary(data, NOW) == ""


def test_excluded_rows_failed_g_import_and_missing_assays_have_no_generated_block():
    data = sheet("HGBFREE\t<8\t11/20/2026\nLDH\t700\t11/20/2026")
    for row in data["labs"]["rows"]:
        row["include"] = False
    assert lysis_summary(data, NOW) == ""
    for row in data["labs"]["rows"]:
        row["include"] = True
    data["import_warnings"]["g"] = [{"action": "not_imported"}]
    assert lysis_selection(data, NOW) == {}
    assert lysis_summary(sheet("NA\t140\t11/20/2026"), NOW) == ""
    assert lysis_summary(sheet(), NOW) == ""


def test_context_clock_ages_values_out_without_changing_saved_snapshot():
    data = sheet("LDH\t600\t11/19/2026 08:00\nLDH\t700\t11/19/2026 07:59")
    before = deepcopy(data)
    with display_clock(NOW):
        assert lysis_summary(data) == "Lysis Labs:\nLDH: 600 [11/19/2026]"
    with display_clock(NOW + timedelta(seconds=1)):
        assert lysis_summary(data) == ""
    assert data == before
