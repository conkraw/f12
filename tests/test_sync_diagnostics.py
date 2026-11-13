"""Synthetic failure injection. No external requests or real credentials."""
import base64
from copy import deepcopy
import json
import types

from cryptography.fernet import Fernet
import pytest
import requests

from github_store import GitHubConfig, GitHubVault, ConflictError
from mapping_sync import MappingRepository, configured_repositories, decrypt_archive
from models import new_vault, new_sheet
from security import generate_key
from sync_diagnostics import DiagnosticError, safe_error

SENTINEL = 'SYNTHETIC_PATIENT_OR_SECRET_MUST_NOT_APPEAR'


class Response:
    def __init__(self, status, data=None, headers=None):
        self.status_code = status
        self.data = data
        self.headers = headers or {}
    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return deepcopy(self.data)


class HTTP:
    def __init__(self, key, value=None):
        self.value = new_vault() if value is None else value
        self.key = key
        self.token = None
        self.overrides = {}
        self.calls = []
        self.write_status = 201
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        stage = 'archive' if '/contents/' in url else 'branch' if '/branches/' in url else 'repository'
        response = self.overrides.get(stage)
        if response is not None:
            if isinstance(response, Exception):
                raise response
            return response
        if method == 'PUT':
            return Response(self.write_status, {'content': {'sha': 'saved'}})
        if stage == 'repository':
            return Response(200, {'private': True, 'archived': False})
        if stage == 'branch':
            return Response(200, {'name': 'main'})
        token = self.token if self.token is not None else Fernet(self.key.encode()).encrypt(json.dumps(self.value).encode())
        return Response(200, {'type': 'file', 'encoding': 'base64', 'sha': 'saved',
                              'content': base64.b64encode(token).decode()})


def repository():
    key = generate_key()
    value = new_vault()
    value['rooms']['P4102'] = new_sheet('P4102')
    value['rooms']['P4102']['fields']['Diagnoses'] = SENTINEL
    http = HTTP(key, value)
    store = GitHubVault(GitHubConfig(SENTINEL, 'synthetic/data'), key, session=http)
    return MappingRepository('Synthetic app', store), http


def assert_failure(repo, http, code, step, status=None):
    checks = []
    before = deepcopy(http.value)
    with pytest.raises(DiagnosticError) as caught:
        repo.snapshot(checks=checks)
    error = caught.value
    assert error.code == code and error.step == step
    assert error.status_code == status
    assert checks[-1] == error.row()
    assert SENTINEL not in repr(checks) + str(error)
    assert repo.store.key not in repr(checks)
    assert all(call[0] == 'GET' for call in http.calls)
    assert http.value == before
    return checks


@pytest.mark.parametrize('status,code', [(401, 'TOKEN_REJECTED'), (403, 'ACCESS_FORBIDDEN'),
    (404, 'REPOSITORY_NOT_FOUND'), (429, 'RATE_LIMIT'), (500, 'SERVER_ERROR'), (301, 'REDIRECT_BLOCKED')])
def test_repository_http_failures(status, code):
    repo, http = repository()
    http.overrides['repository'] = Response(status, {'message': SENTINEL})
    checks = assert_failure(repo, http, code, 'Repository access', status)
    assert len(checks) == 1 and len(http.calls) == 1
    if status == 404:
        assert 'hidden' in checks[-1]['Detail']


@pytest.mark.parametrize('headers,code', [({'x-ratelimit-remaining': '0'}, 'RATE_LIMIT'),
    ({'Retry-After': '90'}, 'RATE_LIMIT'), ({'X-GitHub-SSO': 'required; url=' + SENTINEL}, 'SSO_REQUIRED')])
def test_safe_header_classification(headers, code):
    repo, http = repository()
    http.overrides['repository'] = Response(403, {'message': SENTINEL}, headers)
    assert_failure(repo, http, code, 'Repository access', 403)


@pytest.mark.parametrize('exc,code', [(requests.Timeout(SENTINEL), 'TIMEOUT'),
    (requests.ConnectionError(SENTINEL), 'NETWORK_ERROR')])
def test_network_failures_do_not_echo_exception(exc, code):
    repo, http = repository()
    http.overrides['branch'] = exc
    assert_failure(repo, http, code, 'Branch access')


@pytest.mark.parametrize('stage,code,step', [('branch', 'BRANCH_NOT_FOUND', 'Branch access'),
    ('archive', 'ARCHIVE_NOT_FOUND', 'Archive file access')])
def test_branch_and_file_404_are_distinguished(stage, code, step):
    repo, http = repository()
    http.overrides[stage] = Response(404, {'message': SENTINEL})
    checks = assert_failure(repo, http, code, step, 404)
    assert checks[0]['Result'] == 'Passed'


@pytest.mark.parametrize('data,code', [({'private': False}, 'REPOSITORY_NOT_PRIVATE'),
    ({'private': True, 'archived': True}, 'REPOSITORY_ARCHIVED')])
def test_private_active_requirement(data, code):
    repo, http = repository()
    http.overrides['repository'] = Response(200, data)
    assert_failure(repo, http, code, 'Private repository check')
    assert len(http.calls) == 1


@pytest.mark.parametrize('data', [[], None, ValueError(SENTINEL)])
def test_unexpected_response_is_safe(data):
    repo, http = repository()
    http.overrides['repository'] = Response(200, data)
    assert_failure(repo, http, 'RESPONSE_INVALID', 'Repository access', 200)


def test_archive_shape_and_encoding_failures():
    repo, http = repository()
    http.overrides['archive'] = Response(200, {'type': 'dir', 'content': SENTINEL})
    assert_failure(repo, http, 'ARCHIVE_RESPONSE_INVALID', 'Archive file access', 200)
    http.overrides['archive'] = Response(200, {'type': 'file', 'encoding': 'base64', 'sha': 'sha', 'content': '!!'})
    assert_failure(repo, http, 'ARCHIVE_ENCODING_INVALID', 'Archive encoding')


@pytest.mark.parametrize('case,code,step', [
    ('keyformat', 'KEY_FORMAT_INVALID', 'Encryption key format'),
    ('wrongkey', 'DECRYPTION_FAILED', 'Decrypt archive'),
    ('corrupt', 'DECRYPTION_FAILED', 'Decrypt archive'),
    ('json', 'ARCHIVE_JSON_INVALID', 'Archive JSON'),
    ('size', 'ARCHIVE_TOO_LARGE', 'Archive size'),
    ('schema', 'ARCHIVE_SCHEMA_MISMATCH', 'Archive schema'),
    ('category', 'MAPPING_SETTINGS_INVALID', 'Categories and subcategories'),
    ('groups', 'MAPPING_SETTINGS_INVALID', 'Medication groups'),
    ('gi', 'MAPPING_SETTINGS_INVALID', 'FEN / GI groups'),
    ('assignment', 'MAPPING_SETTINGS_INVALID', 'Category assignments'),
    ('patient', 'ARCHIVE_VALIDATION_FAILED', 'Complete archive validation'),
])
def test_archive_failure_stage(case, code, step):
    repo, http = repository()
    if case == 'keyformat': repo.store.key = 'invalid'
    elif case == 'wrongkey': repo.store.key = generate_key()
    elif case == 'corrupt': http.token = b'not-encrypted'
    elif case == 'json': http.token = Fernet(http.key.encode()).encrypt(SENTINEL.encode())
    elif case == 'size': http.token = b'x' * 800001
    elif case == 'schema': http.value['schema'] = 33
    elif case == 'category': http.value['settings']['medication_categories'] = [SENTINEL]
    elif case == 'groups': http.value['settings']['medication_groups'] = [SENTINEL]
    elif case == 'gi': http.value['settings']['medication_gi_groups'] = [SENTINEL]
    elif case == 'assignment': http.value['settings']['medication_category_rules'] = [SENTINEL]
    elif case == 'patient': http.value['rooms']['P4102']['id'] = SENTINEL
    checks = assert_failure(repo, http, code, step)
    if case == 'schema':
        assert '33' in checks[-1]['Detail'] and '34' in checks[-1]['Detail']


def test_non_numeric_schema_is_not_echoed():
    repo, http = repository()
    http.value['schema'] = SENTINEL
    assert_failure(repo, http, 'ARCHIVE_SCHEMA_MISMATCH', 'Archive schema')


def test_success_has_all_steps_and_mapping_only_snapshot():
    repo, http = repository()
    checks = []
    snap = repo.snapshot(checks=checks)
    assert len(checks) >= 15
    assert all(check['Result'] == 'Passed' for check in checks)
    assert SENTINEL not in repr(checks) + repr(snap.mappings)
    assert all(call[0] == 'GET' for call in http.calls)
    assert http.value['rooms']['P4102']['fields']['Diagnoses'] == SENTINEL


@pytest.mark.parametrize('field,value', [('repository', 'https://github.com/' + SENTINEL),
    ('branch', ' main '), ('label', ''), ('token', 123)])
def test_configuration_identifies_entry_and_field_without_echo(field, value):
    repo, http = repository()
    entry = {'label': 'App 2', 'repository': 'synthetic/second', 'branch': 'main'}
    entry[field] = value
    with pytest.raises(DiagnosticError) as caught:
        configured_repositories(repo.store, {'mapping_sync': {'repositories': [entry]}})
    assert caught.value.code == 'CONFIG_INVALID'
    assert 'entry 1.' + field in caught.value.step
    assert SENTINEL not in str(caught.value)


@pytest.mark.parametrize('operation', ['backup', 'save'])
def test_write_denial_identifies_operation_without_exposing_response(operation):
    repo, http = repository()
    http.write_status = 403
    with pytest.raises(DiagnosticError) as caught:
        if operation == 'backup': repo.backup(http.value, 'sha')
        else: repo.save(http.value, 'sha')
    assert caught.value.code == 'ACCESS_FORBIDDEN'
    assert caught.value.step == ('Write encrypted mapping backup' if operation == 'backup' else 'Save merged mappings')
    assert SENTINEL not in str(caught.value)


def test_write_conflict_is_compatible_with_existing_stop_logic():
    repo, http = repository()
    http.write_status = 409
    with pytest.raises(ConflictError) as caught:
        repo.save(http.value, 'sha')
    assert caught.value.status_code == 409


def test_unknown_exception_text_is_never_in_report():
    error = safe_error(KeyError(SENTINEL), 'Build mapping comparison')
    assert error.code == 'UNEXPECTED_ERROR'
    assert SENTINEL not in str(error) + repr(error.row())
