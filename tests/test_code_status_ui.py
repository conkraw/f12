"""Code-status editing, autosave and complete room replacement use synthetic data."""
from copy import deepcopy

from code_status import code_status_text
from import_review import diagnostic
from test_callbacks import app, open_room
from test_ui_smoke import equip


def test_code_status_editor_opens_legacy_sheet_and_preserves_no_order(app, monkeypatch):
    open_room(app)
    sheet = app.st.session_state['drafts']['P4102']
    assert 'code_status' not in sheet
    equip(app, monkeypatch)
    app.neuro_weight_editor(sheet)
    key = 'demo_' + sheet['id'] + '_code_status'
    assert app.st.session_state[key] == ''
    app.st.session_state[key] = 'No Order'
    app.demographic_change('P4102', 'code_status', key)
    assert code_status_text(sheet) == 'Code Status: No Order'


def test_invalid_manual_status_keeps_previous_value(app):
    open_room(app)
    sheet = app.st.session_state['drafts']['P4102']
    sheet['code_status'] = 'Full Code'
    key = 'demo_' + sheet['id'] + '_code_status'
    app.st.session_state[key] = 'Full Code\nUnrelated field'
    app.demographic_change('P4102', 'code_status', key)
    assert sheet['code_status'] == app.st.session_state[key] == 'Full Code'
    assert app.st.session_state['notice'][0] == 'error'


def test_verified_manual_status_clears_failed_ae_warning(app):
    open_room(app)
    sheet = app.st.session_state['drafts']['P4102']
    sheet['import_warnings']['ae'] = [diagnostic('ae', 'section_parse_failed', action='code_status_hidden')]
    key = 'demo_' + sheet['id'] + '_code_status'
    app.st.session_state[key] = 'DNR / DNI'
    app.demographic_change('P4102', 'code_status', key)
    assert 'ae' not in sheet['import_warnings']
    assert code_status_text(sheet) == 'Code Status: DNR / DNI'


def test_pending_status_is_captured_before_print_all_save(app):
    open_room(app)
    sheet = app.st.session_state['drafts']['P4102']
    sheet['fields']['Diagnoses'] = 'Synthetic case'
    app.st.session_state['demo_' + sheet['id'] + '_code_status'] = 'No Order'
    snapshot = app.editor_snapshot('P4102')
    assert snapshot['code_status'] == 'No Order'
    assert 'code_status' not in sheet
    app.save_room(None)
    assert app.st.session_state['vault']['rooms']['P4102']['code_status'] == 'No Order'


def test_replacement_clears_old_status_and_widget_from_selected_room_only(app):
    open_room(app, 'P4104')
    other = app.st.session_state['drafts']['P4104']
    other['code_status'] = 'Full Code'
    open_room(app)
    baseline = deepcopy(app.st.session_state['drafts']['P4104'])
    old = app.st.session_state['drafts']['P4102']
    old['code_status'] = 'DNR / DNI'
    key = 'demo_' + old['id'] + '_code_status'
    app.st.session_state[key] = 'DNR / DNI'
    app.st.session_state['paste'] = 'aaaaaaaa\nDiagnoses:\n1. New synthetic case\naaaaaaaa'
    app.create_handoff()
    assert not app.st.session_state['drafts']['P4102'].get('code_status')
    assert key not in app.st.session_state
    assert app.st.session_state['drafts']['P4104'] == baseline


def test_notes_preview_displays_code_status_in_demographics(app, monkeypatch):
    open_room(app)
    sheet = app.st.session_state['drafts']['P4102']
    sheet['code_status'] = 'No Order'
    equip(app, monkeypatch)
    rendered = []
    monkeypatch.setattr(app.st, 'markdown', lambda value, **kwargs: rendered.append(value))
    app.handoff_notes(sheet)
    assert any('Code Status:' in value and 'No Order' in value for value in rendered)
