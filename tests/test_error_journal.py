"""Encrypted error journal tests. HTTP responses are simulated, not live GitHub."""
import base64
from copy import deepcopy
import json
import pytest
import requests
from cryptography.fernet import Fernet
from error_store import ErrorJournal, new_error_event, validate_event, event_path, PREFIX
from import_review import diagnostic
from github_store import StorageError, ConflictError
from test_github import Response, store_with, checks
from test_callbacks import app, open_room
from test_import_recovery import CBC, ORDERS, wrap


def event():
    return new_error_event([diagnostic('q', 'cbc_multiple_values', line=8, column=2, field='HCT', action='cell_omitted')])


def encrypted_response(record, key, sha='record-sha'):
    token = Fernet(key.encode()).encrypt(json.dumps(record).encode())
    return Response(200, dict(type='file', encoding='base64', content=base64.b64encode(token).decode(), sha=sha))


def test_error_payload_encrypted_and_create_only_no_vault_overwrite():
    store, http = store_with(checks() + [Response(201, {'content': {'sha': 'saved'}})])
    record = event()
    assert ErrorJournal(store).save_new(record) == 'saved'
    method, url, args = http.calls[-1]
    assert method == 'PUT' and PREFIX in url and not url.endswith('/handoff-v1.enc')
    assert 'sha' not in args['json']
    token = base64.b64decode(args['json']['content'])
    assert json.loads(Fernet(store.key.encode()).decrypt(token)) == record
    assert record['id'] in url  # Random event ID, never a room ID.
    assert 'HCT' not in json.dumps(http.calls) and 'cbc_multiple_values' not in json.dumps(http.calls)
    assert args['allow_redirects'] is False


def test_unique_events_cannot_overwrite_other_users_reports():
    first, second = event(), event()
    assert first['id'] != second['id'] and event_path(first) != event_path(second)
    store, http = store_with(checks() + [Response(201, {'content': {'sha': 'one'}})] + checks() + [Response(201, {'content': {'sha': 'two'}})])
    journal = ErrorJournal(store)
    journal.save_new(first)
    journal.save_new(second)
    assert http.calls[2][1] != http.calls[5][1]
    assert 'sha' not in http.calls[2][2]['json'] and 'sha' not in http.calls[5][2]['json']


def test_retry_after_uncertain_write_is_idempotent_and_never_reopens_resolved():
    record = event()
    store, http = store_with([])
    already_saved = deepcopy(record)
    already_saved['status'] = 'resolved'
    http.responses = checks() + [Response(422), encrypted_response(already_saved, store.key)]
    assert ErrorJournal(store).save_new(record) == 'record-sha'
    assert sum(method == 'PUT' for method, _, _ in http.calls) == 1


def test_branch_conflict_without_file_retries_once_create_only():
    store, http = store_with(checks() + [Response(409), Response(404), Response(201, {'content': {'sha': 'saved'}})])
    assert ErrorJournal(store).save_new(event()) == 'saved'
    assert all('sha' not in args['json'] for method, _, args in http.calls if method == 'PUT')


def test_conflicting_existing_record_never_overwritten():
    record = event()
    store, http = store_with([])
    other = deepcopy(record)
    other['diagnostics'][0]['code'] = 'cbc_invalid_cell'
    http.responses = checks() + [Response(409), encrypted_response(other, store.key)]
    with pytest.raises(ConflictError):
        ErrorJournal(store).save_new(record)
    assert sum(method == 'PUT' for method, _, _ in http.calls) == 1


def test_public_repo_blocks_error_logging():
    store, http = store_with([Response(200, {'private': False})])
    with pytest.raises(StorageError):
        ErrorJournal(store).save_new(event())
    assert len(http.calls) == 1


@pytest.mark.parametrize('status', [401, 403, 302, 500])
def test_failed_log_write_does_not_leak_content(status):
    store, _ = store_with(checks() + [Response(status)])
    with pytest.raises(StorageError):
        ErrorJournal(store).save_new(event())


def test_network_failure_report_has_no_exception_contents():
    store, _ = store_with(checks() + [requests.ConnectionError('PRIVATE_TOKEN')])
    with pytest.raises(StorageError) as err:
        ErrorJournal(store).save_new(event())
    assert 'PRIVATE_TOKEN' not in str(err.value)


def test_shared_review_requires_sha_and_conflicts_refuse_update():
    store, http = store_with(checks() + [Response(409)])
    original = event()
    with pytest.raises(ConflictError):
        ErrorJournal(store).set_status(original, 'old-sha', 'resolved')
    assert original['status'] == 'open'
    assert http.calls[-1][2]['json']['sha'] == 'old-sha'


def test_resolve_and_reopen_changes_only_review_state():
    record = event()
    store, _ = store_with(checks() + [Response(200, {'content': {'sha': 'next'}})])
    changed = ErrorJournal(store).set_status(record, 'prior', 'resolved')
    assert changed['record']['diagnostics'] == record['diagnostics']
    assert changed['record']['id'] == record['id']
    assert record['status'] == 'open' and changed['record']['status'] == 'resolved'
    assert changed['sha'] == 'next'


def test_load_month_decrypts_via_fixed_paths_not_supplied_external_urls():
    record = event()
    path = event_path(record)
    store, http = store_with([])
    http.responses = checks() + [Response(200, [{'name': path.rsplit('/', 1)[-1], 'type': 'file', 'download_url': 'https://untrusted.invalid/secret'}]), encrypted_response(record, store.key)]
    records, notices = ErrorJournal(store).load_month(record['created_at'][:7])
    assert records == [{'record': record, 'sha': 'record-sha'}] and not notices
    assert 'untrusted.invalid' not in repr(http.calls)


def test_load_failure_not_silently_empty():
    store, _ = store_with(checks() + [Response(500)])
    with pytest.raises(StorageError):
        ErrorJournal(store).load_month('2026-01')


def test_missing_log_is_empty_not_error():
    store, _ = store_with(checks() + [Response(404)])
    assert ErrorJournal(store).load_month('2026-01') == ([], [])


def test_month_listing_limit_is_explicit():
    first, second = event(), event()
    entries = [dict(name=event_path(item).rsplit('/', 1)[-1], type='file') for item in (first, second)]
    entries.sort(key=lambda x:x['name'], reverse=True)
    latest = first if entries[0]['name'] in event_path(first) else second
    store, http = store_with([])
    http.responses = checks() + [Response(200, entries), encrypted_response(latest, store.key)]
    records, notices = ErrorJournal(store).load_month(latest['created_at'][:7], limit=1)
    assert len(records) == 1 and any('newest 1' in x for x in notices)


@pytest.mark.parametrize('month', ['../secrets', '2026-13', 'MRN', '2026/01', '2026-01-01'])
def test_invalid_months_do_not_make_requests(month):
    store, http = store_with([])
    with pytest.raises(StorageError):
        ErrorJournal(store).load_month(month)
    assert not http.calls


def test_wrong_key_is_reported_without_record_loss():
    record = event()
    store, http = store_with([])
    path = event_path(record)
    http.responses = checks() + [Response(200, [dict(type='file', name=path.rsplit('/', 1)[-1])]), encrypted_response(record, Fernet.generate_key().decode())]
    rows, notices = ErrorJournal(store).load_month(record['created_at'][:7])
    assert not rows and notices


@pytest.mark.parametrize('key,value', [('raw_text', 'PRIVATE'), ('room', 'P4102'), ('patient_name','PRIVATE'), ('mrn', '12345'), ('stacktrace', 'PRIVATE')])
def test_error_record_rejects_unexpected_patient_or_source_fields(key, value):
    record = event()
    record[key] = value
    with pytest.raises(ValueError):
        validate_event(record)


def test_app_queues_errors_and_applies_other_sections_when_log_fails(app, monkeypatch):
    open_room(app)
    ss = app.st.session_state
    ss['paste'] = wrap('a', 'Diagnoses:\n1. PRIVATE_DIAGNOSIS') + '\n' + wrap('q', CBC)
    class FailingJournal:
        def __init__(self, store): pass
        def save_new(self, record): raise StorageError('PRIVATE_EXCEPTION')
    monkeypatch.setattr(app, 'ErrorJournal', FailingJournal)
    app.create_handoff(object())
    assert ss['drafts']['P4102']['fields']['Diagnoses'] == 'PRIVATE_DIAGNOSIS'
    assert ss['paste'] == '' and ss['pending_error_events']
    assert 'PRIVATE_DIAGNOSIS' not in json.dumps(ss['pending_error_events'])
    assert '29.4' not in json.dumps(ss['pending_error_events'])
    assert 'PRIVATE_EXCEPTION' not in ss['error_log_notice']
    assert 'not saved' in ss['error_log_notice']


def test_app_retry_keeps_event_id_and_does_not_touch_handoff(app, monkeypatch):
    open_room(app)
    ss = app.st.session_state
    record = event()
    ss['pending_error_events'] = {record['id']: record}
    before = deepcopy(ss['drafts'])
    seen = []
    class SavingJournal:
        def __init__(self, store): pass
        def save_new(self, rec): seen.append(rec['id']); return 'confirmed'
    monkeypatch.setattr(app, 'ErrorJournal', SavingJournal)
    app.send_pending_errors(object())
    assert seen == [record['id']] and not ss['pending_error_events']
    assert ss['drafts'] == before
    assert ss['saved_error_events'][record['id']]['sha'] == 'confirmed'


def test_session_only_reports_never_claim_remote_save(app):
    open_room(app)
    app.st.session_state['paste'] = wrap('q', CBC)
    app.create_handoff()
    assert 'session-only' in app.st.session_state['error_log_notice']
    assert not app.st.session_state.get('error_log_saved')


def test_error_review_page_and_flagged_editor_render(app, monkeypatch):
    from test_ui_smoke import equip
    open_room(app)
    app.st.session_state['paste'] = wrap('q', CBC)
    app.create_handoff()
    equip(app, monkeypatch)
    app.handoff_page(None)
    equip(app, monkeypatch)
    app.import_errors_page(None)


def test_acknowledging_review_changes_flag_only(app):
    open_room(app)
    ss = app.st.session_state
    ss['paste'] = wrap('q', CBC)
    app.create_handoff()
    data = deepcopy(ss['drafts']['P4102']['cbc'])
    app.acknowledge_import_warning('P4102', 'q')
    assert ss['drafts']['P4102']['cbc'] == data
    assert not ss['drafts']['P4102']['import_warnings']


def test_cross_room_review_callback_cannot_clear_other_room(app):
    open_room(app)
    ss = app.st.session_state
    ss['paste'] = wrap('q', CBC)
    app.create_handoff()
    before = deepcopy(ss['drafts'])
    app.acknowledge_import_warning('P4104', 'q')
    assert ss['drafts'] == before
