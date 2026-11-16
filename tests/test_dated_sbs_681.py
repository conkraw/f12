"""Latest source-dated SBS, target provenance, and invasive-mode gating.

All source fragments and names in this module are synthetic.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import json

import pytest

from lab_windows import EASTERN, display_clock
from models import new_sheet
from sbs import (parse_sbs, sbs_display_rows, latest_sbs, latest_available_sbs,
                 recognized_vent_mode, validate_sbs)


NOW = datetime(2026, 11, 16, 12, 0, tzinfo=EASTERN)
PC = 'Pressure Control - Intermittent Mandatory Ventilation'
STAFF = 'Synthetic Staff, RN'


def source_sheet(body, mode=PC):
    with display_clock(NOW):
        parsed = parse_sbs(body, window_as_of=NOW)
    assert not parsed.error, parsed.error
    validate_sbs(parsed.data)
    sheet = new_sheet('P4102')
    sheet['sbs_observations'] = parsed.data
    sheet['neuro_vitals']['k'] = parsed.targets
    sheet['sbs_vent_mode'] = mode
    return sheet


def shown(sheet, now=NOW):
    rows = sbs_display_rows(sheet, now)
    return [(row['label'], row['value']) for row in rows]


@pytest.mark.parametrize('header', [
    'SBS Last 24 Hours: Target Arousal Level (SBS): ',
    'Target Arousal Level:\nTarget Arousal Level (SBS): ',
    'Target Arousal Level:\n',
])
def test_epic_target_preserves_label_and_discards_staff_before_storage(header):
    sheet = source_sheet(header + 'SBS -1 (11/13/26 0948 : ' + STAFF + ')')
    assert shown(sheet) == [('SBS target', '-1 (11/13/26)')]
    assert STAFF not in json.dumps(sheet)
    assert '0948' not in str(shown(sheet)) and '09:48' not in str(shown(sheet))


def test_observed_score_selects_latest_source_time_and_remains_after_24_hours():
    sheet = source_sheet('SBS Last 24 Hours:\n'
                         'SBS 2 (11/13/26 1100 : ' + STAFF + ')\n'
                         'SBS -3 (11/13/26 0900 : ' + STAFF + ')\n'
                         'SBS -1 (11/12/26 2300 : ' + STAFF + ')')
    before = deepcopy(sheet)
    assert shown(sheet) == [('SBS', '2 (11/13/26)')]
    assert shown(sheet, NOW + timedelta(days=2)) == [('SBS', '2 (11/13/26)')]
    assert latest_sbs(sheet['sbs_observations'], NOW) is None
    assert sheet == before


def test_newer_history_competes_by_recording_time_not_field_priority():
    sheet = source_sheet('SBS Last 24 Hours: SBS -2 (11/15/26 0800 : ' + STAFF + ')\n'
                         'Last SBS Ever: Target Arousal Level (SBS): SBS 0 '
                         '(11/15/26 0900 : ' + STAFF + ')')
    assert shown(sheet) == [('SBS target', '0 (11/15/26)')]
    assert STAFF not in json.dumps(sheet)


@pytest.mark.parametrize('mode', [
    '', 'Nasal cannula', 'High flow nasal cannula', 'Room air',
    'Bilevel Non Invasive Ventilation',
    'Continuous Positive Airway Pressure - Non Invasive Ventilation',
    'Average Volume-Assured Pressure Support - Non Invasive Ventilation',
    'Unknown mode',
])
@pytest.mark.parametrize('body', [
    'SBS Last 24 Hours: SBS 0 (11/16/26 0800 : ' + STAFF + ')',
    'SBS Last 24 Hours: SBS 0',
    'Last SBS Ever: SBS -1 (11/13/26 0900 : ' + STAFF + ')',
])
def test_all_sbs_paths_require_a_recognized_invasive_mode(mode, body):
    sheet = source_sheet(body, mode)
    assert not recognized_vent_mode(sheet)
    assert shown(sheet) == []


def test_failed_respiratory_import_hides_even_a_current_dated_score():
    sheet = source_sheet('SBS Last 24 Hours: SBS 0 (11/16/26 0800 : ' + STAFF + ')')
    sheet['import_warnings']['cd'] = [{'code': 'section_parse_failed'}]
    assert shown(sheet) == []


def test_old_ps_snapshot_with_noninvasive_delivery_is_not_invasive_evidence():
    sheet = source_sheet('SBS Last 24 Hours: SBS 0', 'Pressure Support - Continuous Positive Airway Pressure')
    assert recognized_vent_mode(sheet)
    sheet['ventilation'] = None
    sheet['noninvasive'] = [{'device': 'NC', 'values': {'O2 Flow': '1'}}]
    assert shown(sheet) == []


def test_source_date_without_time_is_sufficient_and_not_replaced_by_import_date():
    sheet = source_sheet('SBS Last 24 Hours: SBS 0 (11/13/26 : ' + STAFF + ')')
    assert shown(sheet) == [('SBS', '0 (11/13/26)')]
    assert sheet['sbs_observations']['readings'][0]['recorded_at'] == '11/13/2026'


def test_older_date_only_record_can_precede_newer_dated_day():
    sheet = source_sheet('SBS Last 24 Hours:\nSBS 0 (11/13/26)\nSBS -1 (11/14/26 0400)')
    assert shown(sheet) == [('SBS', '-1 (11/14/26)')]


def test_legacy_target_with_unwrapped_source_date_is_still_validated_and_dated():
    sheet = source_sheet('Target Arousal Level (SBS): SBS -1 11/14/26 0930')
    assert shown(sheet) == [('SBS target', '-1 (11/14/26)')]


def test_legacy_matrix_preserves_an_empty_score_column():
    sheet = source_sheet('Results from last 24 hours\n'
                         'Lab\tUnits\t11/15/26\n1100\t11/14/26\n1000\n'
                         'SBS\t\t-1\t')
    assert shown(sheet) == [('SBS', '-1 (11/15/26)')]


@pytest.mark.parametrize('body', [
    'SBS -1 (11/15/26)\nSBS 0 (11/15/26)',
    'SBS -1 (11/15/26)\nSBS 0 (11/15/26 0400)',
    'SBS -1 (11/15/26 0400)\nSBS 0 (11/15/26 0400)',
])
def test_unordered_conflicting_latest_scores_fail_without_exposing_source(body):
    parsed = parse_sbs('SBS Last 24 Hours:\n' + body, window_as_of=NOW)
    assert parsed.error
    assert parsed.data == {'readings': [], 'notes': []}
    assert parsed.targets == []
    assert body not in parsed.error


def test_legacy_saved_target_is_sanitized_for_output_without_mutating_archive():
    sheet = new_sheet('P4102')
    sheet['sbs_vent_mode'] = PC
    sheet['neuro_vitals']['k'] = [{
        'label': 'Target Arousal Level (SBS)',
        'value': 'SBS -2 (11/14/26 0315 : ' + STAFF + ')',
        'section': 'Neurologic', 'include': True,
    }]
    before = deepcopy(sheet)
    assert shown(sheet) == [('SBS target', '-2 (11/14/26)')]
    assert STAFF not in str(shown(sheet))
    assert sheet == before


@pytest.mark.parametrize('value', [
    'SBS -1 (11/99/26 0800 : ' + STAFF + ')',
    'SBS -1 (11/14/26 2599 : ' + STAFF + ')',
    'SBS -1 : ' + STAFF,
    'SBS -1 (unrecognized date : ' + STAFF + ')',
])
def test_unrecognized_target_attribution_cannot_be_saved_as_arbitrary_text(value):
    parsed = parse_sbs('Target Arousal Level (SBS): ' + value, window_as_of=NOW)
    assert parsed.error
    assert parsed.targets == []
    assert STAFF not in str(parsed)


def test_snapshot_and_io_dates_are_never_invented_as_observation_dates():
    sheet = source_sheet('SBS Last 24 Hours: SBS 0')
    assert shown(sheet) == [('SBS', '0')]
    assert shown(sheet, NOW + timedelta(days=4)) == [('SBS', '0')]
    assert latest_available_sbs(sheet, NOW)['recorded_at'] == ''


def test_dated_reading_does_not_resurrect_an_excluded_historical_row():
    sheet = source_sheet('SBS Last 24 Hours: SBS 0 (11/14/26 0800)\n'
                         'Last SBS Ever: SBS -1 (11/15/26 0800)')
    sheet['sbs_observations']['last_available']['include'] = False
    assert shown(sheet) == [('SBS', '0 (11/14/26)')]
    sheet['sbs_observations']['source_window']['include'] = False
    assert shown(sheet) == []


def test_invalid_historical_timestamp_does_not_discard_valid_recent_entry():
    sheet = source_sheet('SBS Last 24 Hours: SBS 0 (11/14/26 0800)\n'
                         'Last SBS Ever: SBS -1 (11/45/26 0800 : ' + STAFF + ')')
    assert shown(sheet) == [('SBS', '0 (11/14/26)')]
    assert STAFF not in json.dumps(sheet)
