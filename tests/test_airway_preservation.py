"""6.56 airway retention. Synthetic records, callback/UI stubs, and encryption."""
from copy import deepcopy
import json
import time

import pytest

from difficult_airway import empty_airway, has_airway_details, TEXT_LIMITS
from handoff_reset import cleared_vault, census_was_reset
from models import new_sheet, new_vault, save_sheet_in, validate_vault, DEFAULT_ROOMS
from security import seal_vault, open_vault, generate_key
from github_store import StorageError, ConflictError
from admin_access import lock_admin
from test_callbacks import app, open_room
from test_print_fit_reset import Store, populated
from test_ui_smoke import equip

SOURCE = 'aaaaaaaa\nDiagnoses:\n1. SYNTHETIC NEW DIAGNOSIS\naaaaaaaa'


def airway(enabled=True, text='Synthetic airway note'):
    return dict(empty_airway(), enabled=enabled, issue=text, mask_ventilation='Yes, with difficulty',
                tube_passage='Yes', equipment='Synthetic equipment', source='Synthetic source')


def with_airway(app, data=None):
    open_room(app)
    ss = app.st.session_state
    ss['drafts']['P4102']['difficult_airway'] = airway() if data is None else deepcopy(data)
    ss['drafts']['P4102']['fields']['Diagnoses'] = 'SYNTHETIC OLD DIAGNOSIS'
    ss['paste'] = SOURCE
    return ss


def resolve(app, action):
    p = app.st.session_state['airway_update_pending']
    app.resolve_airway_update(action, p['room'], p['sheet_id'], p['request_id'])


@pytest.mark.parametrize('data', [None, empty_airway(), dict(empty_airway(), issue='   ')])
def test_empty_airway_is_not_retained_or_prompted(data, app):
    assert not has_airway_details(data)
    ss = with_airway(app, data if data is not None else empty_airway())
    app.create_handoff()
    assert 'airway_update_pending' not in ss
    assert ss['drafts']['P4102']['fields']['Diagnoses'] == 'SYNTHETIC NEW DIAGNOSIS'


@pytest.mark.parametrize('field', list(TEXT_LIMITS))
def test_hidden_text_counts_as_existing_airway(field, app):
    data = dict(empty_airway(), **{field: 'Synthetic detail'})
    assert has_airway_details(data)
    ss = with_airway(app, data)
    app.create_handoff()
    assert ss['airway_update_pending']
    assert ss['drafts']['P4102']['fields']['Diagnoses'] == 'SYNTHETIC OLD DIAGNOSIS'


@pytest.mark.parametrize('data', [dict(empty_airway(), enabled=True),
                                  dict(empty_airway(), mask_ventilation='No'),
                                  dict(empty_airway(), tube_passage='Unable to pass')])
def test_structured_answers_also_trigger_prompt(data, app):
    ss = with_airway(app, data)
    app.create_handoff()
    assert ss['airway_update_pending']


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('action', ['keep', 'delete'])
def test_choice_applies_import_once_without_changing_saved_record_until_save(app, enabled, action):
    ss = with_airway(app, airway(enabled))
    app.save_room(None)
    saved = deepcopy(ss['vault'])
    before_airway = deepcopy(ss['drafts']['P4102']['difficult_airway'])
    app.create_handoff()
    assert ss['vault'] == saved
    assert ss['drafts']['P4102']['fields']['Diagnoses'] == 'SYNTHETIC OLD DIAGNOSIS'
    pending = deepcopy(ss['airway_update_pending'])
    resolve(app, action)
    assert 'airway_update_pending' not in ss
    assert ss['paste'] == ''
    result = ss['drafts']['P4102']
    assert result['fields']['Diagnoses'] == 'SYNTHETIC NEW DIAGNOSIS'
    assert result['difficult_airway'] == (before_airway if action == 'keep' else empty_airway())
    assert ss['vault'] == saved
    app.save_room(None)
    assert ss['vault']['rooms']['P4102']['difficult_airway'] == result['difficult_airway']
    app.resolve_airway_update('delete', pending['room'], pending['sheet_id'], pending['request_id'])
    assert ss['drafts']['P4102']['difficult_airway'] == result['difficult_airway']


def test_pending_choice_does_not_copy_raw_source_into_request_or_archive(app):
    ss = with_airway(app)
    ss['paste'] += '\nhhhhhhhh\nRAW_SOURCE_ONLY_SENTINEL\nhhhhhhhh'
    app.create_handoff()
    assert 'RAW_SOURCE_ONLY_SENTINEL' not in repr(ss['airway_update_pending'])
    assert 'RAW_SOURCE_ONLY_SENTINEL' not in json.dumps(ss['vault'])


def test_keep_then_second_import_prompts_again(app):
    ss = with_airway(app)
    app.create_handoff(); resolve(app, 'keep')
    ss['paste'] = SOURCE
    app.create_handoff()
    assert ss['airway_update_pending']


def test_delete_then_second_import_does_not_prompt(app):
    ss = with_airway(app)
    app.create_handoff(); resolve(app, 'delete')
    ss['paste'] = SOURCE
    app.create_handoff()
    assert 'airway_update_pending' not in ss


def test_cancel_preserves_existing_airway_and_paste(app):
    ss = with_airway(app)
    before = deepcopy(ss['drafts']['P4102'])
    app.create_handoff(); resolve(app, 'cancel')
    assert ss['drafts']['P4102']['difficult_airway'] == before['difficult_airway']
    assert ss['drafts']['P4102']['fields'] == before['fields']
    assert ss['paste'] == SOURCE and 'airway_update_pending' not in ss


@pytest.mark.parametrize('source', ['', 'not a supported section',
                                   'aaaaaaaa\nDiagnoses:\n1. A\naaaaaaaa\naaaaaaaa\nDiagnoses:\n1. B\naaaaaaaa'])
def test_invalid_import_never_deletes_existing_airway_or_prompts(app, source):
    ss = with_airway(app); ss['paste'] = source
    before = deepcopy(ss['drafts']['P4102']['difficult_airway'])
    app.create_handoff()
    assert 'airway_update_pending' not in ss
    assert ss['drafts']['P4102']['difficult_airway'] == before
    assert ss['import_result']['errors']


def test_current_airway_widget_is_captured_before_prompt(app):
    ss = with_airway(app)
    s = ss['drafts']['P4102']
    ss['dairway_' + s['id'] + '_issue'] = 'Synthetic most recent widget edit'
    app.create_handoff(); resolve(app, 'keep')
    assert ss['drafts']['P4102']['difficult_airway']['issue'] == 'Synthetic most recent widget edit'


def test_deleted_airway_cannot_reappear_from_old_widgets(app):
    ss = with_airway(app)
    s = ss['drafts']['P4102']
    for field, value in s['difficult_airway'].items():
        ss['dairway_' + s['id'] + '_' + field] = value
    app.create_handoff(); resolve(app, 'delete')
    assert not any(k.startswith('dairway_') for k in ss)
    app.save_room(None)
    assert not has_airway_details(ss['vault']['rooms']['P4102']['difficult_airway'])


@pytest.mark.parametrize('change', ['draft', 'airway_widget', 'paste', 'settings', 'saved_room', 'reset'])
def test_stale_pending_choice_refuses_to_delete_newer_data(app, change):
    ss = with_airway(app)
    app.create_handoff()
    original = deepcopy(ss['drafts']['P4102']['difficult_airway'])
    if change == 'draft':
        ss['drafts']['P4102']['fields']['Neurologic'] = 'Synthetic newer edit'
    elif change == 'airway_widget':
        ss['dairway_' + ss['drafts']['P4102']['id'] + '_issue'] = 'Synthetic new airway edit'
    elif change == 'paste':
        ss['paste'] += '\n'
    elif change == 'settings':
        ss['vault']['settings']['rooms'].append('EXTRA')
    elif change == 'saved_room':
        ss['vault'] = save_sheet_in(ss['vault'], new_sheet('P4102'))
    else:
        ss['vault'] = cleared_vault(ss['vault'])
    resolve(app, 'delete')
    assert ss['drafts']['P4102']['difficult_airway'] == original
    assert ss['notice'][0] == 'error'
    assert 'airway_update_pending' not in ss


@pytest.mark.parametrize('identity', ['room', 'sheet_id', 'request_id'])
def test_stale_button_identity_cannot_resolve_another_request(app, identity):
    ss = with_airway(app); app.create_handoff()
    p = ss['airway_update_pending']
    args = {k: p[k] for k in ('room', 'sheet_id', 'request_id')}
    args[identity] = 'wrong'
    app.resolve_airway_update('delete', **args)
    assert ss['airway_update_pending'] is p
    assert has_airway_details(ss['drafts']['P4102']['difficult_airway'])


def test_changed_current_room_cannot_apply_prompt_to_new_patient(app):
    ss = with_airway(app); app.create_handoff()
    p = deepcopy(ss['airway_update_pending'])
    ss['current_room'] = 'P4104'; ss['drafts']['P4104'] = new_sheet('P4104')
    app.resolve_airway_update('delete', p['room'], p['sheet_id'], p['request_id'])
    assert has_airway_details(ss['drafts']['P4102']['difficult_airway'])
    assert 'difficult_airway' not in ss['drafts']['P4104']
    assert 'airway_update_pending' not in ss


@pytest.mark.parametrize('action', ['save', 'save_all', 'room', 'other_room'])
def test_pending_choice_blocks_saving_or_room_switch_until_resolved(app, action):
    ss = with_airway(app); app.create_handoff()
    if action == 'save':
        app.save_room(None)
    elif action == 'save_all':
        app.save_all_rooms(None)
    else:
        ss['room_choice'] = 'P4104' if action == 'room' else 'Other room'
        app.room_changed(None)
        assert ss['current_room'] == ss['room_choice'] == 'P4102'
    assert ss['airway_update_pending'] and not ss['vault']['rooms']
    assert ss['notice'][0] == 'error'


def test_resolved_choice_autosaves_when_changing_rooms(app):
    ss = with_airway(app); app.create_handoff(); resolve(app, 'keep')
    open_room(app, 'P4104')
    assert ss['vault']['rooms']['P4102']['fields']['Diagnoses'] == 'SYNTHETIC NEW DIAGNOSIS'
    assert has_airway_details(ss['vault']['rooms']['P4102']['difficult_airway'])


@pytest.mark.parametrize('action', ['keep', 'delete', 'cancel'])
def test_expired_prompt_callback_cannot_modify_shared_data(app, action):
    ss = with_airway(app); app.create_handoff()
    p = deepcopy(ss['airway_update_pending'])
    store = Store(deepcopy(ss['vault']), sha=None)
    ss['last_activity'] = time.monotonic() - 1000
    app.resolve_airway_update(action, p['room'], p['sheet_id'], p['request_id'], store)
    assert not ss and not store.calls


def test_choice_ui_contains_keep_delete_cancel_not_admin_password(app, monkeypatch):
    ss = with_airway(app); app.create_handoff()
    equip(app, monkeypatch)
    buttons = []; captions = []
    app.st.button = lambda label, **kw: buttons.append((label, kw)) or False
    app.st.caption = lambda text, **kw: captions.append(text)
    assert app.airway_update_control(None)
    assert [x[0] for x in buttons] == ['Keep airway and update', 'Delete airway and update', 'Cancel update']
    assert all(x[1]['on_click'] == app.resolve_airway_update for x in buttons)
    assert any('Synthetic airway note' in x for x in captions)
    assert has_airway_details(ss['drafts']['P4102']['difficult_airway'])


def saved_fixture():
    v = new_vault()
    for room, enabled in [('P4102', True), ('EXTRA AIRWAY', False)]:
        s = new_sheet(room)
        s['difficult_airway'] = airway(enabled)
        s['fields']['Diagnoses'] = 'REMOVE_OTHER_DATA_SENTINEL'
        s['fields']['Airway'] = 'ORDINARY_AIRWAY_FIELD_NOT_RETAINED'
        s['admission_date'] = '11/09/2026'
        v = save_sheet_in(v, s)
    other = new_sheet('EXTRA EMPTY'); other['fields']['Diagnoses'] = 'REMOVE_OTHER_DATA_SENTINEL'
    v = save_sheet_in(v, other)
    v['settings']['rooms'] += ['EXTRA AIRWAY', 'EXTRA EMPTY']
    return v


def test_keep_reset_retains_only_airway_in_new_blank_room_records():
    v = saved_fixture(); original = deepcopy(v)
    reset = cleared_vault(v, keep_difficult_airway=True)
    assert v == original
    assert set(reset['rooms']) == {'P4102', 'EXTRA AIRWAY'}
    assert reset['settings'] == dict(v['settings'], rooms=list(DEFAULT_ROOMS) + ['EXTRA AIRWAY'])
    assert census_was_reset(v, reset)
    assert 'REMOVE_OTHER_DATA_SENTINEL' not in json.dumps(reset)
    assert 'ORDINARY_AIRWAY_FIELD_NOT_RETAINED' not in json.dumps(reset)
    for room, s in reset['rooms'].items():
        expected = new_sheet(room)
        for key in expected:
            if key not in ('id', 'created_at', 'updated_at'):
                assert s[key] == expected[key]
        assert s['id'] != original['rooms'][room]['id']
        assert s['difficult_airway'] == original['rooms'][room]['difficult_airway']
        assert s['updated_at']
    validate_vault(reset)


def test_full_reset_still_removes_every_airway_and_custom_room():
    v = saved_fixture(); reset = cleared_vault(v)
    assert not reset['rooms'] and reset['settings']['rooms'] == list(DEFAULT_ROOMS)
    assert 'Synthetic airway note' not in json.dumps(reset)


@pytest.mark.parametrize('data', [None, empty_airway(), dict(empty_airway(), issue='  ')])
def test_keep_reset_does_not_keep_empty_custom_rooms(data):
    v = saved_fixture(); v['rooms']['EXTRA AIRWAY']['difficult_airway'] = data
    reset = cleared_vault(v, keep_difficult_airway=True)
    assert 'EXTRA AIRWAY' not in reset['rooms']
    assert 'EXTRA AIRWAY' not in reset['settings']['rooms']


def test_keep_reset_can_respect_explicitly_cleared_draft_airway():
    reset = cleared_vault(saved_fixture(), keep_difficult_airway=True,
                          airway_by_room={'P4102': empty_airway()})
    assert not reset['rooms']


@pytest.mark.parametrize('bad', [{'EXTRA': {'enabled': True}}, {'bad\nroom': airway()}, [], {'P4102': 'bad'}])
def test_bad_keep_data_refuses_reset(bad):
    with pytest.raises(ValueError):
        cleared_vault(saved_fixture(), keep_difficult_airway=True, airway_by_room=bad)


def prepare_keep_app(app):
    ss = populated(app)
    v = saved_fixture()
    ss.update(vault=v, vault_sha='old-sha', drafts=deepcopy(v['rooms']), base_sheets=deepcopy(v['rooms']),
              current_room='P4102', room_choice='P4102')
    return ss


@pytest.mark.parametrize('admin', [False, True])
def test_keep_reset_commits_once_includes_unsaved_airway_and_preserves_settings(app, admin):
    ss = prepare_keep_app(app)
    if not admin: lock_admin(ss)
    original = deepcopy(ss['vault']); guide = deepcopy(ss['user_guide'])
    s = ss['drafts']['P4102']
    ss['dairway_' + s['id'] + '_issue'] = 'LATEST UNSAVED AIRWAY'
    unsaved = new_sheet('EXTRA UNSAVED'); unsaved['difficult_airway'] = airway()
    ss['drafts']['EXTRA UNSAVED'] = unsaved
    store = Store(original)
    guard = app.download_revocation()
    app.clear_keep_airway_from_handoff(store)
    assert len(store.calls) == 1 and ss['vault'] == store.vault
    assert ss['vault']['rooms']['P4102']['difficult_airway']['issue'] == 'LATEST UNSAVED AIRWAY'
    assert set(ss['vault']['rooms']) == {'P4102', 'EXTRA AIRWAY', 'EXTRA UNSAVED'}
    assert not ss['drafts'] and not ss['base_sheets'] and ss['paste'] == ''
    assert guard.is_set() and not app.download_revocation().is_set()
    assert ss['user_guide'] == guide
    assert ss.get('admin_unlocked', False) == admin
    assert not any(k.startswith('dairway_') for k in ss)
    open_room(app)
    ss['paste'] = SOURCE; app.create_handoff()
    assert ss['airway_update_pending']


@pytest.mark.parametrize('failure', [StorageError('Offline'), ConflictError('Stale'), RuntimeError('Unexpected')])
def test_keep_reset_write_failure_keeps_every_draft_widget_and_download(app, failure):
    ss = prepare_keep_app(app)
    s = ss['drafts']['P4102']
    ss['dairway_' + s['id'] + '_issue'] = 'LATEST UNSAVED AIRWAY'
    before = deepcopy({k:ss[k] for k in ('vault','drafts','base_sheets','paste','vault_sha','room_choice')})
    guard = app.download_revocation()
    app.clear_keep_airway_from_handoff(Store(failure=failure))
    for key, value in before.items(): assert ss[key] == value
    assert ss['dairway_' + s['id'] + '_issue'] == 'LATEST UNSAVED AIRWAY'
    assert not guard.is_set() and ss['notice'][0] == 'error'


def test_keep_reset_rejects_local_stale_room_before_saving(app):
    ss = prepare_keep_app(app)
    ss['vault']['rooms']['P4102']['difficult_airway']['issue'] = 'NEWER SAVED AIRWAY'
    store = Store(ss['vault'])
    app.clear_keep_airway_from_handoff(store)
    assert not store.calls and ss['drafts']
    assert ss['notice'][0] == 'error'
    assert ss['vault']['rooms']['P4102']['difficult_airway']['issue'] == 'NEWER SAVED AIRWAY'


def test_full_reset_remains_allowed_when_local_drafts_stale(app):
    ss = prepare_keep_app(app)
    ss['vault']['rooms']['P4102']['difficult_airway']['issue'] = 'NEWER SAVED AIRWAY'
    store = Store(ss['vault'])
    app.delete_all_from_handoff(store)
    assert len(store.calls) == 1 and not ss['vault']['rooms']


@pytest.mark.parametrize('action', ['clear_all_handoffs', 'clear_keep_airway_from_handoff'])
def test_both_resets_clear_pending_import(app, action):
    ss = with_airway(app); app.create_handoff()
    getattr(app, action)(None)
    assert 'airway_update_pending' not in ss


def test_other_session_reload_discards_stale_drafts_after_keep_reset(app):
    ss = prepare_keep_app(app)
    new = cleared_vault(ss['vault'], keep_difficult_airway=True)
    store = Store(new, sha='other-user-reset')
    app.save_all_rooms(store)
    assert store.vault == new
    app.reload_archive(store)
    assert not ss['drafts'] and ss['vault'] == new
    open_room(app)
    assert has_airway_details(ss['drafts']['P4102']['difficult_airway'])
    assert not ss['drafts']['P4102']['fields']['Diagnoses']


@pytest.mark.parametrize('keep', [True, False])
def test_encrypted_roundtrip_after_reset_retains_only_selected_data(keep):
    key = generate_key(); before = saved_fixture()
    original = open_vault(seal_vault(before, key), key)
    assert original == before
    reset = cleared_vault(original, keep_difficult_airway=keep)
    token = seal_vault(reset, key)
    assert b'Synthetic airway' not in token
    restored = open_vault(token, key)
    assert restored == reset
    assert bool(restored['rooms']) is keep


def test_second_preserving_reset_then_full_delete(app):
    ss = prepare_keep_app(app)
    app.clear_keep_airway_from_handoff(None)
    first = deepcopy(ss['vault'])
    app.clear_keep_airway_from_handoff(None)
    assert ss['vault']['reset_generation'] != first['reset_generation']
    for room in first['rooms']:
        assert ss['vault']['rooms'][room]['difficult_airway'] == first['rooms'][room]['difficult_airway']
    app.delete_all_from_handoff(None)
    assert not ss['vault']['rooms']


def test_keep_control_and_full_delete_render_without_password_or_side_effects(app, monkeypatch):
    ss = prepare_keep_app(app); equip(app, monkeypatch); lock_admin(ss)
    buttons = []; fields = []
    app.st.form_submit_button = lambda label, **kw: buttons.append((label, kw)) or False
    app.st.text_input = lambda label, **kw: fields.append(label)
    before = deepcopy(ss['vault']); store = Store(before)
    app.delete_handoffs_control(store)
    assert [x[0] for x in buttons] == ['Delete all handoff data', 'Clear handoffs, keep difficult airway']
    assert not fields and not store.calls and ss['vault'] == before


def test_keep_reset_empty_archive_is_no_op_except_reset_generation(app):
    ss = app.st.session_state
    store = Store(deepcopy(ss['vault']), sha=None)
    app.clear_keep_airway_from_handoff(store)
    assert len(store.calls) == 1 and not ss['vault']['rooms']
    assert ss['vault']['settings']['rooms'] == list(DEFAULT_ROOMS)
