"""6.48: recent SBS priority and explicitly documented ventilator-mode fallback.

All source fragments and archive data in this module are synthetic.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from io import BytesIO
import json
import pytest
from pypdf import PdfReader
from cryptography.fernet import Fernet

from importing import import_sections
from models import (new_sheet, new_vault, validate_sheet, automatic_vitals,
                    apply_respiratory, upgrade_vault, SCHEMA_VERSION)
from sbs import (parse_sbs, validate_sbs, sbs_display_rows, recognized_vent_mode,
                 latest_available_sbs, validate_last_available)
from lab_windows import EASTERN, display_clock
from ventilator_modes import MODE_SPECS
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf
from security import generate_key, seal_vault, open_vault
from test_callbacks import app, open_room

NOW = datetime(2026, 11, 9, 16, 0, tzinfo=EASTERN)
PC = 'Pressure Control - Intermittent Mandatory Ventilation'
SAMPLE = 'Target Arousal Level:\nSBS Last 24 Hours:\nLast SBS Ever: Target Arousal Level (SBS): SBS -1'


def block(key, body):
    return key * 24 + '\n' + body + '\n' + key * 24


def imported(k=SAMPLE, mode=PC, old=None, d=None, c_extra='', extra=''):
    text = block('k', k) if k is not None else ''
    if mode is not None:
        text += '\n' + block('c', 'Invasive Ventilation:\nMode: Vent Mode: ' + mode + '\n' + c_extra)
    if d is not None:
        text += '\n' + block('d', 'Non-invasive Ventilation:\n' + d)
    text += extra
    with display_clock(NOW):
        result = import_sections(old or new_sheet('P4102'), text, new_vault()['settings'])
    assert not result.errors, result.errors
    validate_sheet(result.sheet)
    return result.sheet


def neuro(sheet, at=NOW):
    with display_clock(at):
        return automatic_vitals(sheet)['Neurologic']


@pytest.mark.parametrize('mode', list(MODE_SPECS))
def test_every_user_supplied_mode_allows_the_historical_target(mode):
    sheet = imported(mode=mode)
    assert recognized_vent_mode(sheet) == mode
    assert neuro(sheet).startswith('SBS target: -1 (last available)\nCAPD: None')
    assert sheet['sbs_observations']['readings'] == []
    assert sheet['sbs_observations']['source_window']['value'] == ''


@pytest.mark.parametrize('mode', sorted({v[0] for v in MODE_SPECS.values()} | {
    'PC', 'VC', 'PC - IMV', 'PC - CMV', 'VC - IMV', 'VC - CMV', 'PS - CPAP',
    'Volume Targeted PC - IMV', 'Volume Targeted PC - CMV', 'Volume Targeted PC - PS',
    'Pressure Control', 'Volume Control', 'Pressure Regulated Volume Control'}))
def test_display_abbreviations_and_existing_generic_families_are_supported(mode):
    assert 'SBS target: -1 (last available)' in neuro(imported(mode=mode))


@pytest.mark.parametrize('mode', ['', 'None', 'No data recorded', 'Unknown mode', 'HFNC', 'Nasal cannula', 'Room air', 'Off'])
def test_empty_placeholder_oxygen_and_unknown_mode_do_not_allow_history(mode):
    assert neuro(imported(mode=mode)).startswith('SBS: None\n')


@pytest.mark.parametrize('delivery', ['High flow nasal cannula', 'Nasal cannula', 'Trach tube', 'Endotracheal tube', 'Other (Comment) (HME)'])
def test_delivery_label_without_a_mode_cannot_enable_history(delivery):
    sheet = imported(mode=None, d='O2 Delivery Method: ' + delivery)
    assert not recognized_vent_mode(sheet)
    assert neuro(sheet).startswith('SBS: None\n')


def test_pressure_inferred_bipap_without_mode_cannot_enable_history():
    d='Total Inspiratory Pressure (cm H2O): 12 cmH20\nExpiratory Positive Airway Pressure (EPAP) (cmH20): 6 cmH20'
    sheet=imported(mode='', d=d)
    assert sheet['noninvasive'][0]['pressure_inferred']
    assert neuro(sheet).startswith('SBS: None\n')


@pytest.mark.parametrize('mode', ['(S) ' + PC, '(s) PC - IMV'])
def test_epic_changed_setting_marker_not_part_of_mode(mode):
    assert '(last available)' in neuro(imported(mode=mode))


@pytest.mark.parametrize('flag', ['No', 'Off', 'False'])
def test_explicit_ventilator_off_blocks_historical_score(flag):
    sheet=imported(c_extra='Ventilator On: ' + flag)
    assert not recognized_vent_mode(sheet)
    assert neuro(sheet).startswith('SBS: None\n')


@pytest.mark.parametrize('value', [-3,-2,-1,0,1,2])
def test_recent_snapshot_always_beats_history_even_without_vent(value):
    for mode in (PC, ''):
        s=imported(k=f'SBS Last 24 Hours: SBS {value}\nLast SBS Ever: SBS 2', mode=mode)
        assert neuro(s).startswith(f'SBS: {value}\n')
        assert '(last available)' not in neuro(s)


def test_recent_timestamped_value_beats_even_newer_ever_field():
    s=imported(k='SBS Last 24 Hours: SBS 0 [11/09/2026 1500]\nLast SBS Ever: SBS -1 [11/09/2026 1530]')
    assert neuro(s).startswith('SBS: 0\n')


@pytest.mark.parametrize('hours, expected', [(-24,'SBS: 0\n'),(-24.1,'SBS: -1 (last available)'),(0,'SBS: 0\n')])
def test_actual_recent_timestamp_boundary_before_fallback(hours,expected):
    stamp=(NOW+timedelta(hours=hours)).strftime('%m/%d/%Y %H:%M')
    s=imported(k=f'SBS Last 24 Hours: SBS 0 [{stamp}]\nLast SBS Ever: SBS -1')
    assert neuro(s).startswith(expected)


def test_blank_recent_uses_zero_history_without_inventing_date():
    s=imported(k='SBS Last 24 Hours:\nLast SBS Ever: SBS 0')
    assert neuro(s).startswith('SBS: 0 (last available)\n')
    assert s['sbs_observations']['last_available']['recorded_at']==''


def test_historical_target_preserved_separate_from_observed_sbs():
    s=imported()
    assert s['sbs_observations']['last_available']['kind']=='target'
    assert 'SBS: -1' not in neuro(s)


def test_history_keeps_recording_time_when_supplied():
    s=imported(k='SBS Last 24 Hours:\nLast SBS Ever: SBS -2 [11/07/2026 08:00]')
    assert 'SBS: -2 (last available) [11/07/2026 08:00]' in neuro(s)


def test_multiple_dated_historical_rows_select_newest_not_lowest_score():
    s=imported(k='SBS Last 24 Hours:\nLast SBS Ever:\nSBS -3 [11/07/26 0800]\nSBS 1 [11/08/26 0900]\nSBS -1 [11/06/26 0800]')
    assert neuro(s).startswith('SBS: 1 (last available) [11/08/26 0900]')


@pytest.mark.parametrize('historical', ['SBS 0 [11/10/2026 1000]', 'SBS 7', 'SBS <script>0</script>', 'SBS -1\nSBS 0'])
def test_future_invalid_and_unordered_history_not_used(historical):
    s=imported(k='SBS Last 24 Hours:\nLast SBS Ever: '+historical)
    assert neuro(s).startswith('SBS: None\n')


def test_bad_historical_data_does_not_block_good_recent_value():
    s=imported(k='SBS Last 24 Hours: 0\nLast SBS Ever: SBS <script>2</script>')
    assert neuro(s).startswith('SBS: 0\n')
    assert '<script>' not in json.dumps(s)


def test_unknown_legacy_mode_does_not_become_recognized_by_keyword_substring():
    s=imported(mode='Not Pressure Control')
    assert not recognized_vent_mode(s)


def test_failed_k_hides_both_recent_and_fallback_without_hiding_capd():
    old=imported()
    with display_clock(NOW):
        result=import_sections(old,block('k','SBS Last 24 Hours: SBS 99\nLast SBS Ever: SBS -1')+'\n'+block('y','CAPD: 9'),new_vault()['settings'])
    assert result.errors and 'k' in result.sheet['import_warnings']
    assert 'SBS' not in neuro(result.sheet) and 'CAPD: 9' in neuro(result.sheet)


def test_failed_respiratory_import_disables_fallback_but_not_recent_score():
    s=imported()
    s['import_warnings']['cd']=[{'bad': 'not used by the direct gate'}]
    assert sbs_display_rows(s,NOW)[0]['value']=='None'
    s['sbs_observations']['source_window']['value']='0'
    assert sbs_display_rows(s,NOW)[0]['value']=='0'


def test_clear_or_replace_c_d_removes_old_fallback_condition():
    original=imported()
    assert '(last available)' in neuro(original)
    cleared=imported(k=None,mode='',old=original)
    assert neuro(cleared).startswith('SBS: None\n')
    d_only=imported(k=None,mode=None,d='O2 Delivery Method: High flow nasal cannula\nO2 Flow Rate (L/min): 10 L/min',old=original)
    assert neuro(d_only).startswith('SBS: None\n')
    assert '(last available)' in neuro(original)


def test_k_only_update_uses_existing_mode_and_explicit_empty_k_clears_history():
    original=imported()
    s=imported(k='SBS Last 24 Hours:\nLast SBS Ever: SBS 0',mode=None,old=original)
    assert neuro(s).startswith('SBS: 0 (last available)\n')
    cleared=imported(k='Target Arousal Level:',mode=None,old=s)
    assert 'SBS' not in neuro(cleared)


def test_current_snapshot_expires_into_separately_labelled_history():
    s=imported(k='SBS Last 24 Hours: SBS 0\nLast SBS Ever: SBS -1')
    assert neuro(s,NOW+timedelta(hours=25)).startswith('SBS: -1 (last available)\n')
    assert s['sbs_observations']['source_window']['value']=='0'


def test_saved_legacy_target_with_known_mode_can_be_used_without_invented_time():
    s=imported(k='Target Arousal Level:\nTarget Arousal Level (SBS): SBS -2')
    assert neuro(s).startswith('SBS target: -2 (last available)\n')


def test_legacy_ventilation_record_does_not_require_new_mode_metadata():
    s=imported()
    s.pop('sbs_vent_mode')
    assert '(last available)' in neuro(s)


def test_old_observation_history_can_supply_fallback_when_no_ever_field():
    s=imported(k='SBS observations:\nSBS: -2 [11/07/26 0800]\nSBS: 1 [11/08/26 0700]')
    assert neuro(s).startswith('SBS: 1 (last available) [11/08/26 0700]')


def test_excluded_history_not_resurrected():
    s=imported()
    s['sbs_observations']['last_available']['include']=False
    assert neuro(s).startswith('SBS: None\n')
    s['sbs_observations']['source_window']['include']=False
    assert 'SBS' not in neuro(s)


def test_order_is_one_sbs_then_capd_then_wat_in_every_output():
    extra='\n'+block('y','CAPD: 7')+'\n'+block('l','WAT Score:\nWAT-1 total score (0-12): 2')
    s=imported(k='SBS Last 24 Hours:\nLast SBS Ever: SBS -1',extra=extra)
    before=deepcopy(s)
    outputs=[handoff_text(s,NOW),handoff_html(s,NOW)]
    for pdf in (handoff_pdf(s,NOW),handoffs_pdf([s],NOW)):
        outputs.append('\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages))
    for text in outputs:
        assert text.count('SBS: -1 (last available)')==1
        assert text.index('SBS: -1 (last available)')<text.index('CAPD: 7')<text.index('WAT-1')
        assert 'Last SBS Ever' not in text
    assert s==before


def test_encrypted_roundtrip_and_migration_preserve_existing_data():
    old=new_vault(); old['schema']=31
    old['rooms']['P4102']=new_sheet('P4102')
    old['rooms']['P4102']['fields']['Neurologic']='Unchanged note'
    old['rooms']['P4102']['updated_at']='2026-11-09T15:00:00+00:00'
    before=deepcopy(old)
    key=generate_key()
    token=Fernet(key.encode()).encrypt(json.dumps(old).encode())
    loaded=open_vault(token,key)
    assert old==before and loaded['schema']==SCHEMA_VERSION==32
    assert loaded['rooms']==old['rooms'] and loaded['settings']==old['settings']
    loaded['rooms']['P4102']=imported(old=loaded['rooms']['P4102'])
    assert open_vault(seal_vault(loaded,key),key)==loaded


@pytest.mark.parametrize('field,value',[('value','99'),('value',-1),('recorded_at','yesterday'),('kind','made up'),('include','true')])
def test_historical_metadata_validation(field,value):
    row={'value':'-1','recorded_at':'','kind':'score','include':True};row[field]=value
    with pytest.raises(ValueError):validate_last_available(row)


def test_history_callback_validates_and_respects_room(app):
    open_room(app);ss=app.st.session_state
    ss['drafts']['P4102']=imported();before=deepcopy(ss['drafts']['P4102'])
    ss['history_test']='0'
    app.sbs_history_change('P4104','value','history_test')
    assert ss['drafts']['P4102']==before
    app.sbs_history_change('P4102','value','history_test')
    assert ss['drafts']['P4102']['sbs_observations']['last_available']['value']=='0'
    ss['history_test']='99'
    app.sbs_history_change('P4102','value','history_test')
    assert ss['history_test']=='0'


def test_clearing_ventilator_in_editor_disables_fallback(app):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=imported()
    app.clear_ventilation()
    assert neuro(ss['drafts']['P4102']).startswith('SBS: None\n')


def test_remove_pressure_device_also_disables_mode_gate(app):
    open_room(app);ss=app.st.session_state
    ss['drafts']['P4102']=imported(mode='Bilevel Non Invasive Ventilation',d='Total Inspiratory Pressure (cm H2O): 12 cmH20\nExpiratory Positive Airway Pressure (EPAP) (cmH20): 6 cmH20')
    app.remove_support_device('P4102','BiPAP')
    assert neuro(ss['drafts']['P4102']).startswith('SBS: None\n')


def test_programmatic_respiratory_replacement_clears_history_gate():
    s=imported()
    updated=apply_respiratory(s,None,[])
    assert neuro(updated).startswith('SBS: None\n')


def test_newest_known_old_observation_wins_over_still_older_ever_value():
    s=imported(k='SBS Last 24 Hours: SBS 0 [11/08/2026 08:00]\nLast SBS Ever: SBS -1 [11/07/2026 10:00]')
    assert neuro(s).startswith('SBS: 0 (last available) [11/08/2026 08:00]')


def test_historical_record_does_not_use_window_report_time_as_observation_time():
    s=imported(k='SBS Last 24 Hours: SBS 0')
    before=deepcopy(s)
    result=neuro(s,NOW+timedelta(hours=25))
    assert result.startswith('SBS: 0 (last available)\n')
    assert '2026' not in result and s==before
