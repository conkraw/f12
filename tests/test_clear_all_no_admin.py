"""6.51 reset-access regressions. Synthetic records and UI/storage stubs only."""
from copy import deepcopy
import inspect
import time

import pytest

from admin_access import lock_admin
from github_store import ConflictError, StorageError
from handoff_reset import cleared_vault
from models import DEFAULT_ROOMS, new_vault
from test_callbacks import app
from test_print_fit_reset import Store, populated
from test_ui_smoke import equip


def forbid_admin_check(*args, **kwargs):
    raise AssertionError('Patient reset must not consult Admin authentication')


@pytest.mark.parametrize('entrypoint', ['clear_all_handoffs', 'delete_all_from_handoff'])
@pytest.mark.parametrize('admin_state', ['locked', 'expired', 'unlocked'])
def test_signed_in_reset_never_needs_or_changes_admin_grant(app, monkeypatch, entrypoint, admin_state):
    ss = populated(app)
    if admin_state == 'locked':
        lock_admin(ss)
    elif admin_state == 'expired':
        ss['admin_last_activity'] = time.monotonic() - 1000
    grant_keys = ('admin_unlocked', 'admin_grant_hash', 'admin_login_at', 'admin_last_activity')
    before_grant = {key: ss.get(key) for key in grant_keys}
    before = deepcopy(ss['vault'])
    guide = deepcopy(ss['user_guide'])
    events = deepcopy(ss['pending_error_events'])
    for name in ('require_admin', 'admin_config', 'admin_valid', 'unlock_admin'):
        monkeypatch.setattr(app, name, forbid_admin_check)
    store = Store(before)
    getattr(app, entrypoint)(store)
    assert len(store.calls) == 1
    assert store.vault['rooms'] == ss['vault']['rooms'] == ss['drafts'] == ss['base_sheets'] == {}
    assert ss['vault']['settings'] == dict(before['settings'], rooms=list(DEFAULT_ROOMS))
    assert ss['vault']['reset_generation'] != before['reset_generation']
    assert ss['authenticated'] is True
    assert {key: ss.get(key) for key in grant_keys} == before_grant
    assert ss['user_guide'] == guide and ss['pending_error_events'] == events
    assert ss['room_choice'] == 'Choose a room' and ss['paste'] == ''


@pytest.mark.parametrize('entrypoint', ['clear_all_handoffs', 'delete_all_from_handoff'])
@pytest.mark.parametrize('invalid_session', ['logged_out', 'idle_expired', 'absolute_expired'])
def test_reset_still_rejects_invalid_app_session(app, entrypoint, invalid_session):
    ss = populated(app)
    store = Store(deepcopy(ss['vault']))
    original = deepcopy(store.vault)
    if invalid_session == 'logged_out':
        ss['authenticated'] = False
    elif invalid_session == 'idle_expired':
        ss['last_activity'] = time.monotonic() - 1000
    else:
        ss['login_at'] = time.monotonic() - 8 * 3600 - 1
    getattr(app, entrypoint)(store)
    assert not store.calls and store.vault == original
    assert not ss


@pytest.mark.parametrize('failure', [StorageError('Offline'), ConflictError('Stale'), RuntimeError('Unexpected')])
def test_password_free_reset_failure_retains_open_work(app, failure):
    ss = populated(app)
    lock_admin(ss)
    before = {key: deepcopy(ss[key]) for key in ('vault', 'vault_sha', 'drafts', 'base_sheets', 'paste', 'room_choice')}
    guard = app.download_revocation()
    app.delete_all_from_handoff(Store(failure=failure))
    for key, value in before.items():
        assert ss[key] == value
    assert not guard.is_set()
    assert ss['notice'][0] == 'error' and 'not confirmed' in ss['notice'][1]
    assert not ss.get('admin_unlocked')


def test_control_renders_full_reset_without_admin_secrets_or_airway_retention(app, monkeypatch):
    equip(app, monkeypatch)
    lock_admin(app.st.session_state)
    fields, submits, warnings, captions = [], [], [], []
    app.st.text_input = lambda label, **kw: fields.append(label)
    app.st.form_submit_button = lambda label, **kw: submits.append((label, kw)) or False
    app.st.warning = lambda text, **kw: warnings.append(text)
    app.st.caption = lambda text, **kw: captions.append(text)
    monkeypatch.setattr(app, 'admin_config', forbid_admin_check)
    app.delete_handoffs_control(None)
    assert not fields and len(submits) == 1
    label, opts = submits[0]
    assert label == 'Delete all handoff data'
    assert opts['on_click'] == app.delete_all_from_handoff
    assert opts['args'] == (None,)
    assert any("every patient's saved handoff" in text for text in warnings)
    assert any('including difficult-airway details' in text for text in warnings)
    assert not any('keep difficult airway' in text.lower() for text in captions + warnings)
    assert any('No Admin password is required' in text for text in captions)
    assert 'delete_all_password' not in app.st.session_state


def test_reset_discards_obsolete_password_but_does_not_unlock_admin(app):
    ss = populated(app)
    lock_admin(ss)
    ss['delete_all_password'] = 'obsolete-widget-value'
    app.delete_all_from_handoff(None)
    assert 'delete_all_password' not in ss and not ss.get('admin_unlocked')
    assert not ss['drafts'] and not ss['vault']['rooms']


def test_empty_archive_reset_is_available_to_non_admin(app):
    ss = app.st.session_state
    lock_admin(ss)
    before = deepcopy(ss['vault'])
    store = Store(before, sha=None)
    app.delete_all_from_handoff(store)
    assert len(store.calls) == 1 and not store.vault['rooms']
    assert store.vault['settings']['rooms'] == list(DEFAULT_ROOMS)


def test_admin_edit_still_blocked_after_non_admin_reset(app):
    ss = populated(app)
    lock_admin(ss)
    store = Store(deepcopy(ss['vault']))
    app.delete_all_from_handoff(store)
    assert len(store.calls) == 1
    before = deepcopy(ss['vault'])
    app.save_admin_settings(store)
    assert len(store.calls) == 1 and ss['vault'] == before
    assert ss['notice'][0] == 'error' and 'Admin password' in ss['notice'][1]


def test_stale_user_cannot_save_deleted_census_and_reload_removes_drafts(app):
    ss = populated(app)
    lock_admin(ss)
    remote = cleared_vault(ss['vault'])
    store = Store(remote, sha='cleared-by-another-user')
    app.save_all_rooms(store)
    assert store.vault == remote and ss['drafts']
    app.reload_archive(store)
    assert not ss['drafts'] and ss['vault'] == remote
    assert 'The shared handoffs were cleared.' in ss['notice'][1]
    app.save_all_rooms(store)
    assert store.vault == remote


def test_no_auto_reset_during_render_or_login(app, monkeypatch):
    equip(app, monkeypatch)
    ss = populated(app)
    lock_admin(ss)
    before = deepcopy(ss['vault'])
    store = Store(before)
    app.delete_handoffs_control(store)
    assert not store.calls and ss['vault'] == before
    assert 'require_session' in inspect.getsource(app.clear_all_handoffs)
    assert 'require_admin' not in inspect.getsource(app.clear_all_handoffs)
