"""Synthetic lumbar-drain parsing and output boundaries."""
from copy import deepcopy

import pytest

from devices import (
    devices_markup, devices_text, evd_text, is_lumbar_drain,
    lumbar_drain_text, parse_devices, validate_devices,
)
from import_review import diagnostic
from models import new_sheet, validate_sheet


SAMPLE = 'Intracranial Pressure Monitor:\nLumbar Drain-Drain Status: Clamped'


def parsed(text=SAMPLE, section='v'):
    result = parse_devices(text, section)
    assert not result.error, result.error
    validate_devices(result.data, section)
    return result


def sheet_with(u='', v=SAMPLE):
    sheet = new_sheet('P4102')
    sheet['devices'] = parsed(u, 'u').data if u else None
    sheet['neuro_devices'] = parsed(v, 'v').data if v else None
    validate_sheet(sheet)
    return sheet


@pytest.mark.parametrize('section', ['u', 'v'])
def test_explicit_sample_uses_existing_drain_kind_and_has_no_missing_or_other_warning(section):
    result = parsed(SAMPLE, section)
    row = result.data['rows'][0]
    assert row['kind'] == 'Drain'
    assert row['label'] == 'Lumbar Drain'
    assert row['status'] == 'Clamped'
    assert row['date'] == ''
    assert is_lumbar_drain(row)
    assert not result.diagnostics
    sheet = sheet_with(u=SAMPLE, v='') if section == 'u' else sheet_with()
    assert lumbar_drain_text(sheet) == 'Lumbar Drain: Clamped'
    assert not devices_text(sheet)
    assert not devices_markup(sheet)


@pytest.mark.parametrize('status', ['Open', 'Draining', 'Open to drain at 10 cm H2O', '(S) Clamped'])
def test_status_is_supplied_by_source_and_not_assumed_clamped(status):
    sheet = sheet_with(v='Lumbar Drain-Drain Status: ' + status)
    assert lumbar_drain_text(sheet) == 'Lumbar Drain: ' + status.removeprefix('(S) ')


@pytest.mark.parametrize('status', ['', '--', 'No data recorded', 'Not documented', 'unknown', 'None'])
def test_missing_status_uses_unk_and_existing_diagnostic(status):
    result = parsed('Lumbar Drain-Drain Status: ' + status)
    assert result.data['rows'][0]['status'] == 'UNK'
    assert any(item['code'] == 'device_missing_status' and item['field'] == 'device_status'
               for item in result.diagnostics)
    sheet = new_sheet('P4102')
    sheet['neuro_devices'] = result.data
    assert lumbar_drain_text(sheet) == 'Lumbar Drain: UNK'


def test_explicit_lumbar_drain_without_status_property_is_retained_as_unknown():
    result = parsed('Lumbar Drain')
    assert result.data['rows'][0]['status'] == 'UNK'
    assert any(item['code'] == 'device_missing_status' for item in result.diagnostics)


def test_repeated_conflicting_statuses_for_one_device_are_unk_not_first_or_last():
    result = parsed('Lumbar Drain-Drain Status: Clamped\nLumbar Drain-Drain Status: Open')
    assert len(result.data['rows']) == 1
    assert result.data['rows'][0]['status'] == 'UNK'
    assert any(item['code'] == 'device_conflict' and item['field'] == 'device_status'
               for item in result.diagnostics)


def test_matching_u_v_records_render_once_without_mutating_saved_rows():
    sheet = sheet_with(SAMPLE, SAMPLE)
    before = deepcopy(sheet)
    assert lumbar_drain_text(sheet) == 'Lumbar Drain: Clamped'
    assert not devices_text(sheet) and not devices_markup(sheet)
    assert sheet == before


@pytest.mark.parametrize('second_status', ['Open', ''])
def test_u_v_same_identity_with_conflicting_or_unknown_status_cannot_borrow_clamped(second_status):
    sheet = sheet_with(SAMPLE, 'Lumbar Drain-Drain Status: ' + second_status)
    assert lumbar_drain_text(sheet) == 'Lumbar Drain: UNK'
    assert not devices_text(sheet)
    assert sheet['devices']['rows'][0]['status'] == 'Clamped'


def test_distinct_devices_keep_their_own_status_and_dates():
    sheet = sheet_with(
        'Lumbar Drain 01/03/26 Left-Drain Status: Clamped',
        'Lumbar Drain 01/04/26 Right-Drain Status:',
    )
    text = lumbar_drain_text(sheet)
    assert 'Lumbar Drain 1: Clamped (Lumbar Drain Left, 01/03/26)' in text
    assert 'Lumbar Drain 2: UNK (Lumbar Drain Right, 01/04/26)' in text
    assert not devices_text(sheet)


def test_an_unknown_other_drain_cannot_provide_lumbar_status_or_date():
    sheet = sheet_with(
        'Drain 01/03/26 Right Scalp-Drain Status: Clamped',
        'Lumbar Drain-Drain Status:',
    )
    assert lumbar_drain_text(sheet) == 'Lumbar Drain: UNK'
    assert '01/03/26' not in lumbar_drain_text(sheet)
    assert 'Right Scalp' in devices_text(sheet)


@pytest.mark.parametrize('label', [
    'Lumbar Puncture', 'Specimen from Lumbar Puncture',
    'Drain Lumbar region', 'Surgical Drain Lumbar',
    'Closed Suction Drain Lower lumbar spine', 'Lumbar Surgical Drain',
    'Drain Right Scalp',
])
def test_procedures_and_generic_surgical_drain_locations_are_not_lumbar_drains(label):
    result = parsed(label + '-Drain Status: Clamped')
    assert not is_lumbar_drain(result.data['rows'][0])
    sheet = sheet_with(v=label + '-Drain Status: Clamped')
    assert not lumbar_drain_text(sheet)
    assert label in devices_text(sheet)


def test_shared_epic_category_prefix_does_not_make_named_lumbar_drain_an_icp_monitor():
    text = 'Intracranial Pressure/Ventriculostomy Lumbar Drain-Drain Status: Clamped'
    result = parsed(text)
    assert result.data['rows'][0]['kind'] == 'Drain'
    sheet = sheet_with(SAMPLE, text)
    assert lumbar_drain_text(sheet) == 'Lumbar Drain: Clamped'
    assert not evd_text(sheet) and not devices_text(sheet)


def test_old_other_category_lumbar_record_remains_supported_without_migration():
    sheet = sheet_with()
    sheet['neuro_devices']['rows'][0]['kind'] = 'Other'
    before = deepcopy(sheet)
    validate_sheet(sheet)
    assert is_lumbar_drain(sheet['neuro_devices']['rows'][0])
    assert lumbar_drain_text(sheet) == 'Lumbar Drain: Clamped'
    assert not devices_text(sheet)
    assert sheet == before


def test_old_other_record_with_empty_status_does_not_assume_clamped():
    sheet = sheet_with()
    row = sheet['neuro_devices']['rows'][0]
    row['kind'] = 'Other'
    row['status'] = ''
    assert lumbar_drain_text(sheet) == 'Lumbar Drain: UNK'


@pytest.mark.parametrize('section', ['u', 'v'])
def test_include_control_and_removed_marker_prevent_all_lumbar_output(section):
    sheet = sheet_with(SAMPLE, '') if section == 'u' else sheet_with()
    source = 'devices' if section == 'u' else 'neuro_devices'
    sheet[source]['rows'][0]['include'] = False
    assert not lumbar_drain_text(sheet) and not devices_text(sheet)
    result = parsed('[REMOVED] Lumbar Drain-Drain Status: Clamped', section)
    assert result.data is None and not result.diagnostics


@pytest.mark.parametrize('section,action', [('u', 'devices_hidden'), ('v', 'neuro_devices_hidden')])
def test_failed_source_hides_old_lumbar_record_but_preserves_it_for_review(section, action):
    sheet = sheet_with(SAMPLE, '') if section == 'u' else sheet_with()
    source = 'devices' if section == 'u' else 'neuro_devices'
    before = deepcopy(sheet[source])
    sheet['import_warnings'][section] = [diagnostic(section, 'section_parse_failed', action=action)]
    assert not lumbar_drain_text(sheet) and not devices_text(sheet)
    assert sheet[source] == before


def test_failed_v_does_not_hide_an_independent_successful_u_lumbar_record():
    sheet = sheet_with(SAMPLE, 'Lumbar Drain-Drain Status: Open')
    sheet['import_warnings']['v'] = [diagnostic('v', 'section_parse_failed', action='neuro_devices_hidden')]
    assert lumbar_drain_text(sheet) == 'Lumbar Drain: Clamped'


def test_evd_icp_monitor_and_generic_drains_keep_existing_routes():
    text = '\n'.join((
        'Intracranial Pressure/Ventriculostomy Ventricular drainage catheter with ICP microsensor-Drain Status: Open',
        'Intracranial Pressure/Ventriculostomy Intraparenchymal ICP monitor-Status: Monitoring',
        'Drain Right Scalp-Status: To bulb suction',
        'Lumbar Drain-Drain Status: Clamped',
    ))
    sheet = sheet_with(v=text)
    assert [row['kind'] for row in sheet['neuro_devices']['rows']] == ['EVD', 'ICP monitor', 'Drain', 'Drain']
    assert evd_text(sheet) == 'EVD: Open'
    assert lumbar_drain_text(sheet) == 'Lumbar Drain: Clamped'
    inventory = devices_text(sheet)
    assert 'Intraparenchymal ICP monitor' in inventory and 'Right Scalp' in inventory
    assert 'Lumbar Drain' not in inventory and 'Ventricular drainage catheter' not in inventory
