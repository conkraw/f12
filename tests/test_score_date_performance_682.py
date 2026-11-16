"""Score-date compatibility and deterministic checks on repeated render work.

These checks use synthetic records and function-call counts, not wall-time
thresholds that would vary with the execution host.
"""
from copy import deepcopy
import cProfile
from datetime import datetime
import json

import pytest

from capd import parse_capd
from exports import handoff_html
from lab_windows import EASTERN, display_clock
import labs
from models import automatic_vitals, new_sheet, validate_sheet
from observations import parse_neuro
from pdf_cache import SessionPdfCache
import sbs
import score_dates


NOW = datetime(2026, 11, 16, 12, 0, tzinfo=EASTERN)
STAFF = "SYNTHETIC_DATE_TEST_STAFF"

COMMON_CASES = [
    ("11/16/2026", datetime(2026, 11, 16), False),
    ("11/16/26", datetime(2026, 11, 16), False),
    ("1/2/26", datetime(2026, 1, 2), False),
    ("2/29/2024", datetime(2024, 2, 29), False),
    ("02/29/00", datetime(2000, 2, 29), False),
    ("12/31/68", datetime(2068, 12, 31), False),
    ("01/01/69", datetime(1969, 1, 1), False),
    ("01/01/1968", datetime(1968, 1, 1), False),
    ("12/31/2069", datetime(2069, 12, 31), False),
    ("11/16/26 0000", datetime(2026, 11, 16), True),
    ("11/16/26 0730", datetime(2026, 11, 16, 7, 30), True),
    ("11/16/26 2359", datetime(2026, 11, 16, 23, 59), True),
    ("11/16/2026 0:00", datetime(2026, 11, 16), True),
    ("11/16/2026 23:59", datetime(2026, 11, 16, 23, 59), True),
    ("11/16/2026 23:59:59", datetime(2026, 11, 16, 23, 59, 59), True),
    ("11/16/26 06:30:00", datetime(2026, 11, 16, 6, 30), True),
    ("11/16/26 12:00 AM", datetime(2026, 11, 16), True),
    ("11/16/26 12:00 PM", datetime(2026, 11, 16, 12), True),
    ("11/16/26 1:05 PM", datetime(2026, 11, 16, 13, 5), True),
    ("11/16/26 11:59PM", datetime(2026, 11, 16, 23, 59), True),
    ("11/16/26 01:05am", datetime(2026, 11, 16, 1, 5), True),
    ("11/16/26 11:59 pm", datetime(2026, 11, 16, 23, 59), True),
    (" 11/16/2026 06:30 ", datetime(2026, 11, 16, 6, 30), True),
]


@pytest.mark.parametrize("source,expected,timed", COMMON_CASES)
def test_common_score_dates_match_previous_parser_without_format_trials(monkeypatch, source, expected, timed):
    previous = labs.date_parts(source)
    assert previous == (expected, timed)

    def no_format_trials(value):
        pytest.fail("A common score date reached the format-trial parser.")

    monkeypatch.setattr(score_dates, "_legacy_date_parts", no_format_trials)
    assert score_dates.date_parts(source) == previous


@pytest.mark.parametrize("source", [
    "11/16/26 7:5", "11/16/2026 7:5:3", "11/16/26 730",
    "11/16/26 1:5 PM", "11/16/26\t07:05", "11/16/26  07:05",
    "11/ 6/26", "11/16/26\n07:05",
])
def test_unusual_accepted_legacy_dates_remain_readable(source):
    assert score_dates.date_parts(source) == labs.date_parts(source)


@pytest.mark.parametrize("source", [
    "", "02/29/2026", "02/29/1900", "02/29/2100", "02/30/24",
    "04/31/26", "13/01/26", "00/10/26", "01/00/26", "11/16/026",
    "11/16/20266", "11/16/0", "01/01/0000", "2026-11-16",
    "11/16/26 2400", "11/16/26 2360", "11/16/26 0061",
    "11/16/26 23:59:60", "11/16/26 12:60 PM", "11/16/26 00:30 PM",
    "11/16/26 13:00 AM", "11/16/26 12:00:30 PM",
    "11/16/26 07:30 copied by " + STAFF,
])
def test_invalid_calendar_time_and_unrecognized_suffix_stay_invalid(source):
    with pytest.raises(ValueError):
        labs.date_parts(source)
    with pytest.raises(ValueError):
        score_dates.date_parts(source)


def _dated_sheet():
    with display_clock(NOW):
        observed = sbs.parse_sbs(
            "SBS Last 24 Hours:\nSBS 0 (11/16/26 0730 : " + STAFF + ", RN)\n"
            "SBS -1 (11/16/26 0830 : " + STAFF + ", RN)", window_as_of=NOW)
        capd = parse_capd("CAPD: 6 (11/15/26 0400 : " + STAFF + ", RN)")
        wat = parse_neuro("WAT Score:\nWAT-1: 2 (11/16/26 0900 : " + STAFF + ", RN)", "l")
    assert not observed.error and not capd.error and not wat.error
    sheet = new_sheet("P4102")
    sheet["sbs_vent_mode"] = "Pressure Control - Intermittent Mandatory Ventilation"
    sheet["sbs_observations"] = observed.data
    sheet["neuro_vitals"]["k"] = observed.targets
    sheet["neuro_vitals"]["y"] = capd.rows
    sheet["neuro_vitals"]["l"] = wat.rows
    return sheet


def _profile_without_legacy_date_trials(operation):
    profile = cProfile.Profile()
    profile.enable()
    try:
        result = operation()
    finally:
        profile.disable()
    count = sum(entry.callcount for entry in profile.getstats()
                if entry.code == labs.date_parts.__code__)
    assert count == 0, "Canonical score processing called the format-trial date parser."
    return result


def test_score_import_validation_and_preview_avoid_repeated_date_format_trials():
    sheet = _profile_without_legacy_date_trials(_dated_sheet)
    before = deepcopy(sheet)
    _profile_without_legacy_date_trials(lambda: validate_sheet(sheet))
    with display_clock(NOW):
        output = _profile_without_legacy_date_trials(lambda: handoff_html(sheet, NOW))
        scores = automatic_vitals(sheet)["Neurologic"]
    assert scores == "SBS: -1 (11/16/26)\nCAPD: 6 (11/15/26)\nWAT-1: 2 (11/16/26)"
    assert STAFF not in output and STAFF not in json.dumps(sheet)
    assert sheet == before


def test_unchanged_pdf_reuse_checks_scores_without_legacy_date_format_trials():
    sheet = _dated_sheet()
    cache = SessionPdfCache()
    prepared = cache.prepare(sheet, NOW)
    result = _profile_without_legacy_date_trials(lambda: cache.prepare(sheet, NOW))
    assert result is prepared
    assert cache.stats["builds"] == 1 and cache.stats["hits"] == 1


def test_date_only_and_timed_midnight_keep_distinct_precision():
    untimed = score_dates.date_parts("11/16/26")
    timed = score_dates.date_parts("11/16/26 0000")
    assert untimed[0] == timed[0]
    assert untimed[1] is False and timed[1] is True
    with pytest.raises(ValueError):
        score_dates.latest_score([
            {"value": "1", "recorded_at": "11/16/26", "include": True},
            {"value": "2", "recorded_at": "11/16/26 0000", "include": True},
        ])
