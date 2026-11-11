"""6.62 removes special airway retention. All records and imports are synthetic."""
from copy import deepcopy
import json

import pytest

from difficult_airway import empty_airway
from handoff_reset import cleared_vault, census_was_reset
from models import new_sheet, new_vault, save_sheet_in, validate_vault, DEFAULT_ROOMS
from security import seal_vault, open_vault, generate_key
from github_store import StorageError, ConflictError
from test_callbacks import app, open_room
from test_print_fit_reset import Store, populated


SOURCE = 'aaaaaaaa\nDiagnoses:\n1. SYNTHETIC NEW DIAGNOSIS\naaaaaaaa'


def airway(enabled=True, text='Synthetic airway note'):
    return dict(empty_airway(), enabled=enabled, issue=text,
                mask_ventilation='Yes, with difficulty', tube_passage='Yes',
                equipment='Synthetic equipment', source='Synthetic source')


def with_airway(app, data):
    open_room(app)
    ss = app.st.session_state
    if data is not None:
        ss['drafts']['P4102']['difficult_airway'] = deepcopy(data)
    ss['drafts']['P4102']['fields']['Diagnoses'] = 'SYNTHETIC OLD DIAGNOSIS'
    ss['paste'] = SOURCE
    return ss


@pytest.mark.parametrize('data', [None, empty_airway(), airway(True), airway(False),
                                  dict(empty_airway(), enabled=True),
                                  dict(empty_airway(), mask_ventilation='No'),
                                  dict(empty_airway(), tube_passage='Unable to pass')])
def test_import_updates_directly_and_preserves_current_manual_airway(app, data):
    ss = with_airway(app, data)
    before = deepcopy(ss['drafts']['P4102'])
    app.create_handoff()
    result = ss['drafts']['P4102']
    assert result['fields']['Diagnoses'] == 'SYNTHETIC NEW DIAGNOSIS'
    assert result.get('difficult_airway') == before.get('difficult_airway')
    assert 'airway_update_pending' not in ss and ss['paste'] == ''
    assert not ss['import_result']['errors'] and not ss['vault']['rooms']


@pytest.mark.parametrize('enabled', [True, False])
def test_direct_update_does_not_change_saved_record_until_normal_save(app, enabled):
    ss = with_airway(app, airway(enabled))
    app.save_room(None)
    saved = deepcopy(ss['vault'])
    ss['paste'] = SOURCE
    app.create_handoff()
    assert ss['vault'] == saved
    assert ss['drafts']['P4102']['fields']['Diagnoses'] == 'SYNTHETIC NEW DIAGNOSIS'
    app.save_room(None)
    assert ss['vault']['rooms']['P4102']['fields']['Diagnoses'] == 'SYNTHETIC NEW DIAGNOSIS'
    assert ss['vault']['rooms']['P4102']['difficult_airway'] == airway(enabled)


@pytest.mark.parametrize('enabled', [True, False])
def test_current_airway_widgets_are_captured_before_direct_import(app, enabled):
    ss = with_airway(app, airway(not enabled))
    prefix = 'dairway_' + ss['drafts']['P4102']['id'] + '_'
    ss[prefix + 'enabled'] = enabled
    ss[prefix + 'issue'] = 'Synthetic most recent widget edit'
    app.create_handoff()
    result = ss['drafts']['P4102']['difficult_airway']
    assert result['enabled'] is enabled
    assert result['issue'] == 'Synthetic most recent widget edit'
    assert ss['drafts']['P4102']['fields']['Diagnoses'] == 'SYNTHETIC NEW DIAGNOSIS'
    assert not any(key.startswith('dairway_') for key in ss)
    app.save_room(None)
    assert ss['vault']['rooms']['P4102']['difficult_airway'] == result


def test_repeated_imports_remain_direct_and_preserve_manual_airway(app):
    ss = with_airway(app, airway())
    for diagnosis in ('SYNTHETIC FIRST UPDATE', 'SYNTHETIC SECOND UPDATE'):
        ss['paste'] = SOURCE.replace('SYNTHETIC NEW DIAGNOSIS', diagnosis)
        app.create_handoff()
        assert ss['drafts']['P4102']['fields']['Diagnoses'] == diagnosis
        assert ss['drafts']['P4102']['difficult_airway'] == airway()
        assert 'airway_update_pending' not in ss


@pytest.mark.parametrize('source', ['', 'not a supported section',
                                   'aaaaaaaa\nDiagnoses:\n1. A\naaaaaaaa\n'
                                   'aaaaaaaa\nDiagnoses:\n1. B\naaaaaaaa'])
def test_invalid_import_keeps_existing_airway_without_prompt(app, source):
    ss = with_airway(app, airway())
    ss['paste'] = source
    before = deepcopy(ss['drafts']['P4102'])
    app.create_handoff()
    assert ss['drafts']['P4102'] == before
    assert 'airway_update_pending' not in ss
    assert ss['import_result']['errors']


def test_direct_import_does_not_persist_unsupported_source_text(app):
    ss = with_airway(app, airway())
    ss['paste'] += '\nhhhhhhhh\nINTAKE/OUTPUT:\nRAW_SOURCE_ONLY_SENTINEL\nhhhhhhhh'
    app.create_handoff()
    app.save_room(None)
    assert 'RAW_SOURCE_ONLY_SENTINEL' not in json.dumps(ss['vault'])
    assert 'RAW_SOURCE_ONLY_SENTINEL' not in json.dumps(ss['drafts'])
    assert ss['paste'] == '' and 'airway_update_pending' not in ss


@pytest.mark.parametrize('action', ['import', 'save', 'save_all', 'room'])
def test_obsolete_pending_choice_is_discarded_without_blocking_work(app, action):
    ss = with_airway(app, airway())
    ss['airway_update_pending'] = {'room': 'P4102', 'legacy': 'obsolete choice'}
    if action == 'import':
        app.create_handoff()
        assert ss['drafts']['P4102']['fields']['Diagnoses'] == 'SYNTHETIC NEW DIAGNOSIS'
    elif action == 'save':
        app.save_room(None)
    elif action == 'save_all':
        app.save_all_rooms(None)
    else:
        open_room(app, 'P4104')
        assert ss['current_room'] == 'P4104'
    assert 'airway_update_pending' not in ss
    if action != 'import':
        assert ss['vault']['rooms']['P4102']['difficult_airway'] == airway()


def saved_fixture():
    vault = new_vault()
    for room, enabled in [('P4102', True), ('EXTRA AIRWAY', False)]:
        sheet = new_sheet(room)
        sheet['difficult_airway'] = airway(enabled)
        sheet['fields']['Diagnoses'] = 'REMOVE_OTHER_DATA_SENTINEL'
        sheet['fields']['Airway'] = 'ORDINARY_AIRWAY_FIELD_NOT_RETAINED'
        vault = save_sheet_in(vault, sheet)
    vault['settings']['rooms'].append('EXTRA AIRWAY')
    return vault


def test_reset_removes_entire_airway_records_and_roundtrips_without_mutation():
    vault = saved_fixture()
    before = deepcopy(vault)
    result = cleared_vault(vault)
    assert vault == before
    assert result['rooms'] == {}
    assert result['settings'] == dict(before['settings'], rooms=list(DEFAULT_ROOMS))
    assert census_was_reset(before, result)
    assert 'Synthetic airway note' not in json.dumps(result)
    validate_vault(result)
    key = generate_key()
    assert open_vault(seal_vault(result, key), key) == result


def test_confirmed_reset_clears_saved_unsaved_and_widget_airway_details(app):
    ss = populated(app)
    for index, sheet in enumerate(ss['vault']['rooms'].values()):
        sheet['difficult_airway'] = airway(enabled=bool(index))
    for sheet in ss['drafts'].values():
        sheet['difficult_airway'] = airway(text='Synthetic unsaved airway note')
    widget = 'dairway_' + ss['drafts']['P4102']['id'] + '_issue'
    ss[widget] = 'Synthetic latest airway widget'
    ss['airway_update_pending'] = {'legacy': 'obsolete choice'}
    before = deepcopy(ss['vault'])
    store = Store(before)
    guard = app.download_revocation()
    app.clear_all_handoffs(store)
    assert len(store.calls) == 1 and store.calls[0][0]['rooms'] == {}
    assert ss['vault'] == store.vault
    assert ss['vault']['rooms'] == ss['drafts'] == ss['base_sheets'] == {}
    assert ss['vault']['settings'] == dict(before['settings'], rooms=list(DEFAULT_ROOMS))
    assert widget not in ss and 'airway_update_pending' not in ss
    assert guard.is_set()
    open_room(app)
    assert not ss['drafts']['P4102'].get('difficult_airway')


@pytest.mark.parametrize('failure', [StorageError('Synthetic offline'),
                                     ConflictError('Synthetic conflict'),
                                     RuntimeError('Synthetic unexpected failure')])
def test_unconfirmed_reset_preserves_all_airway_data_and_current_widgets(app, failure):
    ss = with_airway(app, airway())
    app.save_room(None)
    ss['drafts']['P4102']['difficult_airway']['issue'] = 'Synthetic unsaved airway edit'
    widget = 'dairway_' + ss['drafts']['P4102']['id'] + '_issue'
    ss[widget] = 'Synthetic latest airway widget'
    before = {key: deepcopy(ss[key]) for key in ('vault', 'drafts', 'base_sheets', widget)}
    guard = app.download_revocation()
    app.clear_all_handoffs(Store(failure=failure))
    assert all(ss[key] == value for key, value in before.items())
    assert not guard.is_set() and ss['notice'][0] == 'error'


def test_remote_full_reset_discards_stale_airway_before_another_save(app):
    ss = with_airway(app, airway())
    app.save_room(None)
    remote = cleared_vault(ss['vault'])
    store = Store(remote, sha='new-reset-sha')
    app.save_room(store)
    assert store.vault == remote and ss['drafts']['P4102']['difficult_airway'] == airway()
    app.reload_archive(store)
    assert not ss['drafts'] and not ss['vault']['rooms']
    app.save_all_rooms(store)
    assert store.vault == remote
