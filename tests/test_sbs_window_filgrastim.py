from style_assert_helpers import without_style_tags
"""6.46: source-scoped SBS boundaries and filgrastim placement. Synthetic data only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import pytest
from pypdf import PdfReader
from cryptography.fernet import Fernet
from sbs import parse_sbs, sbs_display_rows, validate_sbs, snapshot_reference
from models import new_sheet, new_vault, automatic_vitals, fields_with_medications, upgrade_vault, SCHEMA_VERSION
from importing import import_sections
from lab_windows import EASTERN, display_clock
from categories import catalog, placement, apply_category_rules, set_category_rule, save_category
from medication_groups import group_for
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf
from security import open_vault, seal_vault, generate_key
from test_rooms_infusions import med
from test_callbacks import app, open_room

NOW = datetime(2026, 11, 9, 12, 14, tzinfo=EASTERN)
SOURCE = '''Target Arousal Level:
SBS Last 24 Hours:  
Last SBS Ever: Target Arousal Level (SBS): SBS -1'''

def block(letter, text):
    return letter * 24 + '\n' + text + '\n' + letter * 24

def imported(body, old=None, extra=''):
    with display_clock(NOW):
        result = import_sections(old or new_sheet('P4102'), block('k', body) + extra, new_vault()['settings'])
    assert not result.errors, result.errors
    return result.sheet

def text_at(sheet, now=NOW):
    with display_clock(now):
        return automatic_vitals(sheet)['Neurologic']


def test_exact_user_k_structure_empty_recent_never_uses_historical_target():
    sheet = imported(SOURCE)
    assert text_at(sheet).startswith('SBS: None\nCAPD: None')
    assert sheet['neuro_vitals']['k'] == []
    assert sheet['sbs_observations']['readings'] == []
    assert 'SBS -1' not in json.dumps(sheet['sbs_observations'])

@pytest.mark.parametrize('old', ['-3', '-1', '0', '2', '0 [11/09/2026 12:00]', '<script>1</script>'])
def test_historical_values_are_never_read_even_when_current_date_is_attached(old):
    body = 'SBS Last 24 Hours:\nLast SBS Ever: SBS ' + old
    assert 'SBS: None' in text_at(imported(body))

@pytest.mark.parametrize('value', [-3, -2, -1, 0, 1, 2])
@pytest.mark.parametrize('wrapper', ['', 'SBS: ', 'State Behavioral Scale (SBS): '])
def test_single_scoped_value_needs_no_invented_observation_time(value, wrapper):
    s = imported('Target Arousal Level:\nSBS Last 24 Hours: ' + wrapper + str(value) + '\nLast SBS Ever: SBS 2')
    assert text_at(s).startswith('SBS: ' + str(value) + '\nCAPD: None')
    data = s['sbs_observations']
    assert data['readings'] == []
    assert data['source_window']['value'] == str(value)
    assert data['source_window']['reported_as_of'] == NOW.astimezone(timezone.utc).isoformat()
    assert data['source_window']['reference'] == 'import'

@pytest.mark.parametrize('missing', ['', ' ', '--', 'None', 'No data recorded', 'Not assessed', 'N/A'])
def test_missing_current_value_clears_old_snapshot(missing):
    old = imported('SBS: 0 [11/09/26 11:00]')
    before = deepcopy(old)
    s = imported('SBS Last 24 Hours: ' + missing + '\nLast SBS Ever: SBS -1', old)
    assert 'SBS: None' in text_at(s)
    assert old == before
    assert not s['sbs_observations']['readings']

@pytest.mark.parametrize('header', ['SBS Last 24 Hours:', 'SBS last 24 hours:', 'SBS Past 24 Hrs:', 'Last 24 Hours SBS:', 'SBS Last 24 Hours：'])
def test_recent_header_forms_and_multiline_content(header):
    s = imported('Target Arousal Level:\n' + header + '\nSBS: 0\nLast SBS Ever:\nSBS: -3')
    assert text_at(s).startswith('SBS: 0\n')


def test_same_line_historical_boundary():
    s = imported('SBS Last 24 Hours: 0 Last SBS Ever: SBS -3')
    assert text_at(s).startswith('SBS: 0\n')


def test_ever_only_does_not_refresh_timed_old_reading():
    old = imported('SBS: 1 [11/09/26 10:00]')
    s = imported('Last SBS Ever: SBS 1 [11/09/26 10:00]', old)
    assert text_at(s).startswith('SBS: None\n')

@pytest.mark.parametrize('label', ['Target Arousal Level (SBS): ', 'Target SBS: ', 'Goal SBS: '])
def test_explicit_target_in_current_window_keeps_target_label(label):
    s = imported('SBS Last 24 Hours: ' + label + 'SBS -1\nLast SBS Ever: SBS 0')
    assert text_at(s).startswith('SBS target: -1\nCAPD: None')
    assert 'SBS: -1' not in text_at(s)


def test_scoped_timed_readings_choose_latest_not_first_and_ignore_ever():
    body = ('SBS Last 24 Hours:\nSBS: -2 [11/09/26 1200]\nSBS: 0 [11/09/26 1000]\n'
            'SBS: 1 [11/08/26 0800]\nLast SBS Ever: SBS 2 [11/09/26 1210]')
    s = imported(body)
    assert text_at(s).startswith('SBS: -2\n')
    assert len(s['sbs_observations']['readings']) == 3

@pytest.mark.parametrize('hours, result', [(-24, '0'), (-24.02, 'None'), (-2, '0'), (0, '0'), (.02, 'None')])
def test_timed_source_scoped_observations_still_enforce_actual_24h(hours, result):
    when = (NOW + timedelta(hours=hours)).strftime('%m/%d/%Y %H:%M')
    s = imported('SBS Last 24 Hours: SBS 0 [' + when + ']\nLast SBS Ever: SBS -1')
    assert text_at(s).startswith('SBS: ' + result + '\n')

@pytest.mark.parametrize('hours, result', [(0, '0'), (23.99, '0'), (24, '0'), (24.01, 'None'), (-1, 'None')])
def test_report_snapshot_expiry_is_separate_from_observation_time(hours, result):
    s = imported('SBS Last 24 Hours: 0\nLast SBS Ever: SBS -1')
    before = deepcopy(s)
    assert text_at(s, NOW + timedelta(hours=hours)).startswith('SBS: ' + result + '\n')
    assert s == before


def test_full_phrase_report_time_used_without_inventing_measurement_time():
    io = '\n' + block('s', 'Intake/Output Summary (Last 24 hours) at 11/9/2026 1100\nLast data filed at 11/9/2026 0900\nGross per 24 hour\nIntake\t200 ml\nOutput\t100 ml\nNet\t100 ml')
    s = imported('SBS Last 24 Hours: 0\nLast SBS Ever: SBS -1', extra=io)
    window = s['sbs_observations']['source_window']
    assert window['reference'] == 'smartphrase'
    assert window['reported_as_of'] == '2026-11-09T16:00:00+00:00'
    assert not s['sbs_observations']['readings']


def test_snapshot_reference_prefers_s_and_does_not_use_last_data_filed():
    blocks = {'s': 'Intake/Output Summary (Last 24 hours) at 11/9/2026 1200\nLast data filed at 11/9/2026 1000',
              'h': 'Intake/Output Summary (Last 24 hours) at 11/9/2026 1100'}
    when, source = snapshot_reference(blocks)
    assert when.hour == 12 and source == 'smartphrase'


def test_source_scope_survives_unrelated_updates_but_explicit_empty_k_clears():
    old = imported('SBS Last 24 Hours: 0\nLast SBS Ever: SBS -1')
    with display_clock(NOW + timedelta(hours=1)):
        result = import_sections(old, block('y', 'CAPD: 9'), new_vault()['settings'])
    assert result.sheet['sbs_observations'] == old['sbs_observations']
    assert 'SBS: 0\nCAPD: 9' in text_at(result.sheet)
    empty = imported('Target Arousal Level:', result.sheet)
    assert sbs_display_rows(empty, NOW) == []

@pytest.mark.parametrize('body', ['SBS: -4', 'SBS: 3', 'SBS: 0.5', 'SBS: -1\nSBS: 0',
    'SBS: 0 [11/09/26 1200]\nSBS: -1', 'SBS: 0 [11/09/26]\nSBS: -1',
    'SBS: 0 [11/09/26 1200]\nSBS: -1 [11/09/26 1200]',
    'SBS: <script>0</script>', 'SBS Last 24 Hours: 0'])
def test_invalid_recent_value_does_not_fallback_or_block_capd(body):
    old = imported('SBS Last 24 Hours: 1\nLast SBS Ever: SBS -1')
    source = block('k', 'SBS Last 24 Hours: ' + body + '\nLast SBS Ever: SBS -1') + '\n' + block('y', 'CAPD: 0')
    with display_clock(NOW):
        result = import_sections(old, source, new_vault()['settings'])
    assert result.errors and 'k' in result.skipped
    assert sbs_display_rows(result.sheet, NOW) == []
    assert 'CAPD: 0' in text_at(result.sheet)
    assert result.sheet['sbs_observations'] == old['sbs_observations']
    assert '<script>' not in str(result.diagnostics)


def test_multiple_identical_untimed_values_are_one_score():
    s = imported('SBS Last 24 Hours:\nSBS: 0\nSBS: 0\nLast SBS Ever: SBS -1')
    assert text_at(s).count('SBS: 0') == 1


def test_date_only_scoped_reading_does_not_bypass_timestamp_requirement():
    s = imported('SBS Last 24 Hours: SBS -1 [11/08/26]\nLast SBS Ever: SBS 0')
    assert text_at(s).startswith('SBS: None\n')
    assert s['sbs_observations']['readings'][0]['recorded_at'] == '11/08/26'

@pytest.mark.parametrize('value', ['', '0', '-1'])
def test_output_paths_have_no_historical_fallback_and_keep_order(value):
    s = imported('SBS Last 24 Hours: ' + value + '\nLast SBS Ever: SBS 2', extra='\n' + block('y', 'CAPD: 9') + '\n' + block('l', 'WAT Score:\nWAT-1 total score (0-12): 1'))
    before = deepcopy(s)
    expected = 'SBS: ' + (value or 'None')
    outputs = [handoff_text(s, NOW), without_style_tags(handoff_html(s, NOW))]
    outputs += ['\n'.join(pg.extract_text() for pg in PdfReader(BytesIO(pdf)).pages)
                for pdf in [handoff_pdf(s, NOW), handoffs_pdf([s], NOW)]]
    for output in outputs:
        assert expected in output
        assert output.index(expected) < output.index('CAPD: 9') < output.index('WAT-1')
        assert 'Last SBS Ever' not in output and 'SBS: 2' not in output
    assert s == before

@pytest.mark.parametrize('name', ['filgrastim injection 33 mcg', 'filgrastim-aafi (Nivestym) injection 33 mcg',
    '[START ON 11/10/2026] filgrastim-sndz injection', 'tbo-filgrastim injection',
    'Nivestym injection', 'NEUPOGEN injection', 'Zarxio injection'])
def test_filgrastim_defaults_to_one_hematology_destination(name):
    row = med(name, dose='33 mcg', frequency='q24h', section='Other Medications')
    assert group_for(row) == 'gcsf'
    assigned = apply_category_rules([row], new_vault()['settings'])
    where = placement(assigned[0])
    assert where['section'] == 'Hematology' and where['name'] == 'G-CSF Stimulator'
    s = new_sheet('P4102'); s['medications'] = assigned
    fields = fields_with_medications(s)
    expected_name = name.removeprefix('[START ON 11/10/2026] ')
    assert fields['Hematology'].count(expected_name) == 1
    assert '[START ON' not in fields['Hematology']
    assert expected_name not in fields['Other Medications']
    assert assigned[0]['name'] == name

@pytest.mark.parametrize('name', ['pegfilgrastim injection', 'sargramostim injection', 'filgrastimxyz', 'Example drug with filgrastim'])
def test_unrequested_growth_factors_or_embedded_names_not_automapped(name):
    assert group_for(med(name, frequency='q24h')) != 'gcsf'


def test_hidden_and_explicit_mappings_remain_authoritative():
    row = med('filgrastim-aafi (Nivestym) 33 mcg', frequency='q24h', section='Other Medications')
    settings = set_category_rule(new_vault()['settings'], 'filgrastim-aafi', 'system:Other Medications')
    assigned = apply_category_rules([row], settings)
    assert placement(assigned[0])['section'] == 'Other Medications'
    row['hidden'] = True
    s = new_sheet('P4102'); s['medications'] = apply_category_rules([row], new_vault()['settings'])
    assert 'filgrastim' not in handoff_text(s, NOW)


def test_migration_adds_group_without_overwriting_custom_settings_or_rooms():
    v = new_vault(); v['schema'] = 30
    v['settings']['medication_categories'] = [c for c in catalog(v['settings']) if c['id'] != 'group:gcsf']
    v['settings']['medication_categories'][0]['name'] = 'Local label'
    v['rooms']['P4102'] = imported(SOURCE)
    # This old-schema fixture needs no new source-window fields.
    v['rooms']['P4102'].pop('sbs_observations', None)
    before = deepcopy(v)
    key = generate_key()
    token = Fernet(key.encode()).encrypt(json.dumps(v).encode())
    restored = open_vault(token, key)
    assert restored['schema'] == SCHEMA_VERSION ==34 and v == before
    assert restored['rooms'] == before['rooms']
    old_settings = deepcopy(restored['settings'])
    old_settings['medication_categories'] = [c for c in old_settings['medication_categories'] if c['id'] != 'group:gcsf']
    assert old_settings == before['settings']
    assert open_vault(seal_vault(restored, key), key) == restored


def test_scoped_snapshot_encrypted_roundtrip_does_not_reset_age():
    v = new_vault(); v['rooms']['P4102'] = imported('SBS Last 24 Hours: 0\nLast SBS Ever: SBS -1')
    key = generate_key(); restored = open_vault(seal_vault(v, key), key)
    assert restored == v
    assert text_at(restored['rooms']['P4102'], NOW + timedelta(hours=25)).startswith('SBS: None\n')


def test_window_edit_callback_preserves_report_time_and_guards_rooms(app):
    open_room(app); ss = app.st.session_state
    ss['drafts']['P4102'] = imported(SOURCE)
    before = deepcopy(ss['drafts']['P4102'])
    ss['edit_window'] = '0'
    app.sbs_window_change('P4104', 'value', 'edit_window')
    assert ss['drafts']['P4102'] == before
    app.sbs_window_change('P4102', 'value', 'edit_window')
    after = ss['drafts']['P4102']
    assert after['sbs_observations']['source_window']['value'] == '0'
    assert after['sbs_observations']['source_window']['reported_as_of'] == before['sbs_observations']['source_window']['reported_as_of']
    ss['edit_window'] = '9'
    app.sbs_window_change('P4102', 'value', 'edit_window')
    assert ss['drafts']['P4102'] == after


def test_manual_timed_observation_replaces_source_window_provenance(app):
    open_room(app); ss = app.st.session_state
    ss['drafts']['P4102'] = imported('SBS Last 24 Hours: Target Arousal Level (SBS): SBS -3\nLast SBS Ever: SBS -1')
    ss['score_key'] = '0'; ss['time_key'] = '11/09/26 1100'
    app.sbs_add_reading('P4102', 'score_key', 'time_key')
    s = ss['drafts']['P4102']
    assert 'source_window' not in s['sbs_observations']
    assert text_at(s).startswith('SBS: 0\n')
