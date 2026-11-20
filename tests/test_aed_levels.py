"""AED assay identity and conservative time-window checks with synthetic labs."""
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from aed_levels import (LABELS, LAB_PANEL, aed_card_rows, aed_component, aed_lab_rows,
                        aed_lab_summary, aed_selection, aed_summary)
from lab_windows import display_clock
from labs import parse_labs


ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 20, 8, 0, tzinfo=ET)


def sheet(source=""):
    result = parse_labs("LABS:\nComponent\tValue\tDate\n" + source)
    assert not result.error, result.error
    return {"labs": result.data, "import_warnings": {}}


@pytest.mark.parametrize("code", LABELS)
@pytest.mark.parametrize("date,recent,older", [
    ("11/19/2026 07:59:59", False, True),
    ("11/19/2026 08:00", True, False),
    ("11/19/2026 08:00:01", True, False),
    ("11/20/2026 07:59", True, False),
    ("11/20/2026 08:00", True, False),
    ("11/20/2026 08:00:01", False, False),
    ("11/18/2026", False, True),
    ("11/19/2026", False, True),
    ("11/20/2026", True, False),
    ("11/21/2026", False, False),
    ("01/01/2020", False, True),
])
def test_boundary_date_only_and_future_policy(code, date, recent, older):
    data = sheet(f"{code}\t1.9 (L)\t{date}")
    selected = aed_selection(data, NOW)
    assert (code in selected["recent"]) is recent
    assert (code in selected["older"]) is older
    assert bool(aed_summary(data, NOW)) is recent
    assert bool(aed_lab_rows(data, NOW)) is older


def test_supplied_date_only_structure_keeps_each_level_with_last_checked_date():
    data = sheet("PHENOBARB\t33.6\t11/19/2026\nPHENYTOIN\t1.9 (L)\t11/19/2026")
    before = deepcopy(data)
    assert aed_summary(data, NOW) == ""
    assert aed_lab_summary(data, NOW) == (
        "AED Drug Levels: Phenobarbital: 33.6 [Last checked: 11/19/2026], "
        "Phenytoin: 1.9 (L) [Last checked: 11/19/2026]")
    rows = aed_lab_rows(data, NOW)
    assert [row["component"] for row in rows] == ["PHENOBARB", "PHENYTOIN"]
    assert all(row["panel"] == LAB_PANEL for row in rows)
    rows[0]["value"] = "CHANGED DISPLAY COPY"
    assert data == before


def test_each_drug_has_independent_location_and_no_duplicate_history():
    data = sheet("PHENOBARB\t33.6\t11/20/2026 07:00\n"
                 "PHENOBARB\t40.2\t11/18/2026 09:00\n"
                 "PHENYTOIN\t1.9 (L)\t11/18/2026 10:00")
    selected = aed_selection(data, NOW)
    assert set(selected["recent"]) == {"PHENOBARB"}
    assert set(selected["older"]) == {"PHENYTOIN"}
    assert aed_summary(data, NOW) == "AED Drug Levels:\nPhenobarbital: 33.6 [11/20/2026 07:00]"
    assert aed_lab_summary(data, NOW) == "AED Drug Levels: Phenytoin: 1.9 (L) [Last checked: 11/18/2026 10:00]"


@pytest.mark.parametrize("source,code", [
    ("phenobarb", "PHENOBARB"), ("PHENOBARBITAL", "PHENOBARB"),
    ("Phenobarbital Level", "PHENOBARB"), ("PHENOBARBITAL, SERUM", "PHENOBARB"),
    ("PHENOBARBITAL (SERUM)", "PHENOBARB"), ("Phenytoin", "PHENYTOIN"),
    ("PHENYTOIN LEVEL", "PHENYTOIN"), ("PHENYTOIN TOTAL", "PHENYTOIN"),
    ("PHENYTOIN, TOTAL", "PHENYTOIN"), ("TOTAL PHENYTOIN", "PHENYTOIN"),
    ("PHENYTOIN TOTAL LEVEL", "PHENYTOIN"), ("PHENYTOIN, SERUM", "PHENYTOIN"),
    ("PHENYTOIN TOTAL, SERUM", "PHENYTOIN"),
])
def test_only_explicit_same_assay_aliases_are_normalized(source, code):
    assert aed_component(source) == code
    data = sheet(f"{source}\t1.9\t11/20/2026 07:00")
    assert code in aed_selection(data, NOW)["recent"]


@pytest.mark.parametrize("source", [
    "PHENYTOIN FREE", "PHENYTOIN, FREE", "FREE PHENYTOIN", "PHENYTOIN FREE AND TOTAL",
    "PHENYTOIN-FREE", "PHENYTOIN2", "PHENOBARB_ALT", "FOSPHENYTOIN", "VALPROATE",
    "LEVETIRACETAM", "PHENOBARBITAL METABOLITE", "PHENOBARBITAL URINE", "", None,
])
def test_different_assays_and_free_levels_are_not_merged(source):
    assert aed_component(source) == ""


def test_alias_duplicates_select_latest_timed_value_once():
    data = sheet("PHENOBARB\t40.0\t11/20/2026 04:00\n"
                 "Phenobarbital\t33.6\t11/20/2026 07:00\n"
                 "PHENOBARBITAL LEVEL\t36.2\t11/20/2026 06:00")
    assert aed_summary(data, NOW) == "AED Drug Levels:\nPhenobarbital: 33.6 [11/20/2026 07:00]"
    assert aed_lab_rows(data, NOW) == []


@pytest.mark.parametrize("dates", [
    ("11/20/2026", "11/20/2026"),
    ("11/20/2026", "11/20/2026 07:30"),
    ("11/20/2026 06:00", "11/20/2026"),
    ("11/20/2026 07:00", "11/20/2026 07:00"),
])
def test_same_date_missing_times_and_exact_ties_keep_epic_source_order(dates):
    data = sheet(f"PHENYTOIN\t1.9 (L)\t{dates[0]}\n"
                 f"TOTAL PHENYTOIN\t4.6\t{dates[1]}")
    assert aed_selection(data, NOW)["recent"]["PHENYTOIN"]["value"] == "1.9 (L)"


def test_source_first_date_only_row_is_not_skipped_for_known_recent_time():
    data = sheet("PHENOBARB\t33.6\t11/19/2026\n"
                 "Phenobarbital\t35.2\t11/19/2026 12:00")
    selected = aed_selection(data, NOW)
    assert selected["recent"] == {}
    assert selected["older"]["PHENOBARB"]["value"] == "33.6"
    assert aed_summary(data, NOW) == ""


def test_card_rows_group_aliases_without_modifying_source():
    data = sheet("PHENOBARB\t35.2\t11/18/2026 12:00\n"
                 "Phenobarbital\t33.6\t11/19/2026\n"
                 "PHENYTOIN, TOTAL\t1.9 (L)\t11/19/2026\n"
                 "PHENYTOIN FREE\t0.2\t11/19/2026")
    before = deepcopy(data)
    rows = aed_card_rows(data["labs"])
    assert list(rows) == ["PHENOBARB", "PHENYTOIN"]
    assert rows["PHENOBARB"]["value"] == "33.6"
    assert rows["PHENOBARB"]["component"] == "Phenobarbital"
    assert data == before


@pytest.mark.parametrize("value", [
    "0", "33.6", "1.9 (L)", "<0.5", ">80 (H)", "33.6 µg/mL", "1.9 mcg/mL (L)",
])
def test_units_flags_and_censoring_are_source_faithful(value):
    data = sheet(f"PHENOBARB\t{value}\t11/20/2026 07:00")
    before = deepcopy(data)
    assert aed_summary(data, NOW) == "AED Drug Levels:\nPhenobarbital: " + value + " [11/20/2026 07:00]"
    assert data == before


@pytest.mark.parametrize("value", [
    "Pending", "Canceled", "Hemolyzed", "--", "1.9 pending", "1.9 invalid", "1.9 rejected",
])
def test_nonresults_do_not_hide_previous_measured_value(value):
    data = sheet(f"PHENYTOIN\t{value}\t11/20/2026 07:30\n"
                 "PHENYTOIN\t1.9 (L)\t11/20/2026 07:00")
    assert aed_selection(data, NOW)["recent"]["PHENYTOIN"]["value"] == "1.9 (L)"


@pytest.mark.parametrize("bad_date", ["", "not a date", None, "11/31/2026", "11/20/2026 27:99"])
def test_bad_dates_are_not_reassigned_or_printed(bad_date):
    data = sheet("PHENOBARB\t33.6\t11/20/2026 07:00")
    data["labs"]["rows"][0]["date"] = bad_date
    assert aed_selection(data, NOW) == {"recent": {}, "older": {}}


def test_excluded_results_failed_import_and_missing_codes_generate_no_block():
    data = sheet("PHENOBARB\t33.6\t11/20/2026 07:00\nPHENYTOIN\t1.9\t11/19/2026")
    for row in data["labs"]["rows"]:
        row["include"] = False
    assert aed_summary(data, NOW) == aed_lab_summary(data, NOW) == ""
    for row in data["labs"]["rows"]:
        row["include"] = True
    data["import_warnings"]["g"] = [{"action": "not_imported"}]
    assert aed_selection(data, NOW) == {"recent": {}, "older": {}}
    assert aed_summary(sheet(), NOW) == ""


@pytest.mark.parametrize("now,date,recent,older", [
    (datetime(2026, 11, 2, 0, 0, tzinfo=ET), "11/01/2026 01:30", True, False),
    (datetime(2026, 11, 2, 1, 0, tzinfo=ET), "11/01/2026 01:30", False, True),
    (datetime(2026, 11, 1, 1, 45, tzinfo=ET, fold=0), "11/01/2026 01:30", False, False),
    (datetime(2026, 11, 1, 1, 45, tzinfo=ET, fold=1), "11/01/2026 01:30", True, False),
    (datetime(2026, 3, 8, 4, 0, tzinfo=ET), "03/08/2026 02:30", False, False),
    (datetime(2026, 3, 8, 4, 0, tzinfo=ET), "03/08/2026 03:30", True, False),
    (datetime(2026, 11, 1, 23, 1, tzinfo=ET), "11/01/2026", False, True),
    (datetime(2026, 3, 9, 0, 0, tzinfo=ET), "03/08/2026", True, False),
])
def test_daylight_saving_does_not_invent_a_collection_instant(now, date, recent, older):
    data = sheet(f"PHENYTOIN\t1.9\t{date}")
    selected = aed_selection(data, now)
    assert bool(selected["recent"]) is recent
    assert bool(selected["older"]) is older


def test_print_clock_aging_moves_result_without_mutating_saved_snapshot():
    data = sheet("PHENOBARB\t33.6\t11/19/2026 08:00")
    before = deepcopy(data)
    with display_clock(NOW):
        assert aed_summary(data)
        assert not aed_lab_rows(data)
    with display_clock(NOW + timedelta(seconds=1)):
        assert not aed_summary(data)
        assert aed_lab_rows(data)[0]["value"] == "33.6"
    assert data == before
