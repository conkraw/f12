"""6.47 regressions. Synthetic data and simulated UI/storage only."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import fitz
import pytest
from admin_access import lock_admin
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from github_store import ConflictError, StorageError
from infusions import render_body_blocks
from lab_windows import id_drug_levels, display_clock, laboratory_data, window_help
from labs import parse_labs
from models import new_sheet, new_vault, fields_with_medications, DEFAULT_ROOMS
from security import generate_key, seal_vault, open_vault
from user_guide import DEFAULT_INSTRUCTIONS, default_guide, handoff_instructions
from test_callbacks import app, open_room
from test_print_fit_reset import populated, Store
from test_ui_smoke import equip

NOW = datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc)  # 14:00 Eastern

def level_sheet(rows):
    sheet = new_sheet('P4102')
    sheet['fields']['Diagnoses'] = 'Synthetic review sample'
    source = 'LABS:\nComponent\tValue\tDate\n' + '\n'.join('\t'.join(r) for r in rows)
    parsed = parse_labs(source)
    assert not parsed.error
    sheet['labs'] = parsed.data
    return sheet

@pytest.mark.parametrize('date,eligible', [
    ('11/09/2026 14:00', True), ('11/09/2026 13:59', True),
    ('11/08/2026 14:00', True), ('11/08/2026 14:01', True),
    ('11/08/2026 13:59', False), ('11/07/2026 23:59', False),
    ('11/09/2026 14:01', False), ('11/10/2026', False),
    ('11/09/2026', True), ('11/08/2026', True),
    ('11/07/2026', False), ('10/14/2026', False),
])
def test_vanco_rolling_window_uses_current_eastern_time(date, eligible):
    s = level_sheet([('VANCOTROUGH', '12.4', date)])
    before = deepcopy(s)
    assert bool(id_drug_levels(s, NOW)) == eligible
    assert s == before
    assert s['labs']['rows'][0]['date'] == date

@pytest.mark.parametrize('name', ['VANCOTROUGH', 'vancotrough', 'Vancomycin trough', 'VANCOMYCIN, TROUGH'])
def test_vanco_alias_latest_only_and_no_old_fallback(name):
    s = level_sheet([(name, '15.2', '11/09/2026 13:30'),
                     (name, '13.7', '11/08/2026 17:00'),
                     (name, '44.4', '10/14/2026')])
    result = id_drug_levels(s, NOW)
    assert '15.2' in result and '13.7' not in result and '44.4' not in result
    s['labs']['rows'][0]['include'] = False
    assert '13.7' in id_drug_levels(s, NOW)
    s['labs']['rows'][1]['include'] = False
    assert not id_drug_levels(s, NOW)


def test_recent_vanco_preserves_source_units_flags_and_zero():
    s = level_sheet([('VANCOTROUGH', '0', '11/09/2026 13:00')])
    assert 'Vancomycin trough: 0 ' in id_drug_levels(s, NOW)
    s['labs']['rows'][0]['value'] = '21.5 mg/L (H)'
    assert '21.5 mg/L (H)' in id_drug_levels(s, NOW)


def test_vanco_only_old_hides_drug_heading_in_all_exports():
    s = level_sheet([('VANCOTROUGH', '10.8', '10/14/2026')])
    before = deepcopy(s)
    for text in (handoff_html(s, NOW), handoff_text(s, NOW)):
        assert 'Vancomycin trough' not in text and 'Drug Levels' not in text
    with fitz.open(stream=handoff_pdf(s, NOW), filetype='pdf') as pdf:
        text = '\n'.join(p.get_text() for p in pdf)
        assert 'Vancomycin trough' not in text and 'Drug Levels' not in text
    assert s == before


def test_recent_vanco_visible_once_under_id_not_lab_tree():
    s = level_sheet([('VANCOTROUGH', '12.4', '11/09/2026 13:00'), ('CK', '100', '11/09/2026')])
    with display_clock(NOW):
        fields = fields_with_medications(s)
        assert 'Drug Levels\nVancomycin trough: 12.4' in fields['Infectious Disease']
        assert 'VANCOTROUGH' not in fields['Lab Results / Trends']
        assert all(r['component'] != 'VANCOTROUGH' for r in laboratory_data(s)['rows'])
    assert handoff_html(s, NOW).count('Vancomycin trough:') == 1
    with fitz.open(stream=handoffs_pdf([s], NOW), filetype='pdf') as pdf:
        assert '\n'.join(p.get_text() for p in pdf).count('Vancomycin trough:') == 1


def test_vanco_reages_without_mutating_raw_data():
    s = level_sheet([('VANCOTROUGH', '12.4', '11/09/2026 13:00')])
    before = deepcopy(s)
    assert id_drug_levels(s, NOW)
    assert not id_drug_levels(s, datetime(2026, 11, 10, 19, tzinfo=timezone.utc))
    assert s == before


def test_failed_lab_import_does_not_print_retained_trough():
    s = level_sheet([('VANCOTROUGH', '12.4', '11/09/2026 13:00')])
    s['import_warnings']['g'] = {'synthetic': True}
    assert not id_drug_levels(s, NOW)


def test_window_help_describes_vanco_recent_ntprobnp_all_time():
    text = window_help(new_sheet('P4102'), NOW)
    assert 'vancomycin trough: rolling 24 hours' in text
    assert 'NT-proBNP: latest from all supplied dates' in text


@pytest.mark.parametrize('label', ['Bowel Regimen', 'DVT Prophylaxis', 'GI Prophylaxis', 'Diuretics', 'Fever Control'])
def test_empty_group_label_bold_none_normal(label):
    result = render_body_blocks([('empty_group', label)], rich=True)
    assert result == '<b>' + label + ':</b> None'
    assert render_body_blocks([('empty_group', label)]) == label + ': None'
    html = handoff_html(new_sheet('P4102'), NOW)
    assert '<b>' + label + ':</b> None' in html


def test_empty_group_label_html_is_escaped():
    text = render_body_blocks([('empty_group', '<script>')], rich=True)
    assert '<script>' not in text and '<b>&lt;script&gt;:</b> None' in text


def test_required_empty_labels_are_bold_in_pdf():
    with fitz.open(stream=handoff_pdf(new_sheet('P4102'), NOW), filetype='pdf') as pdf:
        spans = [s for p in pdf for b in p.get_text('dict')['blocks'] if 'lines' in b
                 for ln in b['lines'] for s in ln['spans']]
        bold = ' '.join(s['text'] for s in spans if 'Bold' in s['font'])
        for label in ('Bowel Regimen:', 'DVT Prophylaxis:', 'GI Prophylaxis:'):
            assert label in bold


def test_legacy_guide_displays_short_text_without_changing_publication():
    g = default_guide()
    g.update(instructions='# Create a handoff you can check and trust\n\nOLD LONG BODY',
             smartphrase_name='PICUHANDOFFSMARTPHRASE', smartphrase_text='TEAM SOURCE',
             updated_at='2026-11-09T17:00:00+00:00')
    before = deepcopy(g)
    assert handoff_instructions(g) == DEFAULT_INSTRUCTIONS
    assert g == before
    assert len(handoff_instructions(g).split()) < 120


def test_admin_custom_instructions_remain_supported():
    g = default_guide(); g['instructions'] = 'Local short instructions.'
    assert handoff_instructions(g) == 'Local short instructions.'


def test_instructions_are_visible_before_room_selection_no_old_tab(app, monkeypatch):
    equip(app, monkeypatch)
    seen = []
    app.st.caption = lambda text, **kw: seen.append(text)
    app.handoff_page(None)
    assert any('SmartPhrase author Streamlit' in t and 'PICUHANDOFFSMARTPHRASE' in t for t in seen)
    assert not app.st.session_state.get('current_room')
    source = Path(app.__file__).read_text()
    assert '["Handoff", "Print all", "Admin", "Import errors"]' in source
    assert 'def instructions_page(' not in source


def test_legacy_guide_editor_loads_short_workflow_preserves_source_stamp(app):
    ss = app.st.session_state
    g = default_guide(); g['instructions'] = '# Create a handoff you can check and trust\nOLD'
    g['smartphrase_text'] = 'SOURCE UNCHANGED'
    g['updated_at'] = '2026-11-09T16:00:00+00:00'
    before = deepcopy(g)
    app.prepare_guide_editor(g, reset=True)
    assert ss['guide_edit_instructions'] == DEFAULT_INSTRUCTIONS
    assert ss['guide_edit_smartphrase_text'] == 'SOURCE UNCHANGED'
    assert g == before


def test_handoff_delete_control_available_for_empty_census(app, monkeypatch):
    equip(app, monkeypatch)
    labels = []
    app.st.form_submit_button = lambda label, **kw: labels.append(label)
    app.handoff_page(None)
    assert 'Delete all handoff data' in labels
    assert 'delete_all_password' not in app.st.session_state


def test_delete_all_from_handoff_writes_once_and_preserves_settings(app):
    ss = populated(app); lock_admin(ss)
    before = deepcopy(ss['vault']); guide = deepcopy(ss['user_guide'])
    ss['sbs_test_value'] = '-1'
    ss['dairway_test_issue'] = 'SYNTHETIC AIRWAY'
    ss['problem_test_notes'] = 'SYNTHETIC NOTES'
    store = Store(before); old_download = app.download_revocation()
    ss['delete_all_password'] = 'example-admin-password'
    app.delete_all_from_handoff(store)
    assert len(store.calls) == 1 and store.vault['rooms'] == {}
    assert ss['drafts'] == ss['base_sheets'] == ss['vault']['rooms'] == {}
    assert ss['vault']['settings'] == dict(before['settings'], rooms=list(DEFAULT_ROOMS))
    assert ss['user_guide'] == guide
    assert ss['paste'] == '' and ss['room_choice'] == 'Choose a room'
    assert old_download.is_set()
    assert not ss.get('admin_unlocked') and 'delete_all_password' not in ss
    for key in ('sbs_test_value', 'dairway_test_issue', 'problem_test_notes', 'removed_room'):
        assert key not in ss


@pytest.mark.parametrize('password', ['', 'wrong', 'example-app-password'])
def test_handoff_delete_no_longer_checks_legacy_admin_password(app, password):
    ss = populated(app); lock_admin(ss)
    before = deepcopy(ss['vault']); store = Store(before)
    ss['delete_all_password'] = password
    app.delete_all_from_handoff(store)
    assert len(store.calls) == 1 and not ss['vault']['rooms'] and not ss['drafts']
    assert 'delete_all_password' not in ss and not ss.get('admin_unlocked')
    assert ss['notice'][0] == 'success'


@pytest.mark.parametrize('failure', [StorageError('Offline'), ConflictError('Stale'), RuntimeError('Unknown')])
def test_handoff_delete_failure_keeps_open_work_and_relocks(app, failure):
    ss = populated(app); lock_admin(ss)
    before = {k: deepcopy(ss[k]) for k in ('vault', 'drafts', 'base_sheets', 'paste', 'removed_room')}
    store = Store(failure=failure)
    ss['delete_all_password'] = 'example-admin-password'
    app.delete_all_from_handoff(store)
    for k, v in before.items(): assert ss[k] == v
    assert not ss.get('admin_unlocked') and 'delete_all_password' not in ss
    assert 'not confirmed' in ss['notice'][1]


def test_handoff_delete_empty_census_and_session_mode(app):
    ss = app.st.session_state; lock_admin(ss)
    ss['vault']['settings']['rooms'].append('EXTRA')
    ss['delete_all_password'] = 'example-admin-password'
    app.delete_all_from_handoff(None)
    assert not ss['vault']['rooms']
    assert ss['vault']['settings']['rooms'] == list(DEFAULT_ROOMS)
    assert 'Session-only' in ss['notice'][1]
    assert 'not erased' in ss['notice'][1]


def test_handoff_delete_no_session_never_calls_store(app):
    ss = populated(app); ss['authenticated'] = False
    ss['delete_all_password'] = 'example-admin-password'
    store = Store(deepcopy(ss['vault']))
    app.delete_all_from_handoff(store)
    assert not store.calls and 'delete_all_password' not in ss


def test_v646_archive_roundtrip_no_schema_or_settings_change():
    v = new_vault(); v['rooms']['P4102'] = new_sheet('P4102')
    v['rooms']['P4102']['labs'] = level_sheet([('VANCOTROUGH', '12.4', '10/14/2026')])['labs']
    key = generate_key()
    out = open_vault(seal_vault(v, key), key)
    assert out == v


def test_main_moves_old_instruction_workspace_to_handoff_without_losing_draft(app, monkeypatch):
    from test_callbacks import TEST_ADMIN_CONFIG
    open_room(app)
    ss = app.st.session_state
    ss['drafts']['P4102']['fields']['Other'] = 'SYNTHETIC UNSAVED NOTE'
    before = deepcopy(ss['drafts'])
    ss['page'] = 'Instructions / SmartPhrase'
    # Workspace migration runs after the existing daily-start choice.
    app.continue_patient_list()
    equip(app, monkeypatch)
    monkeypatch.setattr(app, 'load_config', lambda: ({'idle_minutes':15, **TEST_ADMIN_CONFIG}, None))
    app.main()
    assert ss['page'] == 'Handoff'
    assert ss['drafts'] == before


def test_delete_control_missing_admin_configuration_keeps_reset_available(app, monkeypatch):
    from types import SimpleNamespace
    equip(app, monkeypatch)
    app.st.secrets = SimpleNamespace(to_dict=lambda: {'app': {}})
    buttons = []
    app.st.form_submit_button = lambda label, **kwargs: buttons.append(label)
    app.delete_handoffs_control(None)
    assert 'Delete all handoff data' in buttons
