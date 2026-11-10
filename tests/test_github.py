import base64
import json
from copy import deepcopy
import pytest
import requests
from github_store import GitHubConfig, GitHubVault, StorageError, ConflictError
from models import new_vault, new_sheet, save_sheet_in, apply_diagnoses, ValidationError
from security import generate_key, seal_vault, open_vault


class Response:
    def __init__(self, status, data=None):
        self.status_code, self.data = status, data
    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class HTTP:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def store_with(responses, key=None):
    http = HTTP(responses)
    store = GitHubVault(GitHubConfig('synthetic-token','synthetic/data'), key or generate_key(), session=http)
    return store, http


def checks():
    return [Response(200, {'private':True, 'archived':False}), Response(200, {'name':'main'})]


def test_new_private_repo_missing_vault():
    store, http = store_with(checks()+[Response(404)])
    vault, sha = store.load()
    assert vault == new_vault() and sha is None


def test_encrypted_payload_and_generic_metadata():
    key = generate_key()
    store, http = store_with(checks()+[Response(201,{'content':{'sha':'new-sha'}})], key)
    vault = save_sheet_in(new_vault(), apply_diagnoses(new_sheet('P4102'),'PRIVATE_SENTINEL','Diagnoses'))
    assert store.save(vault, None) == 'new-sha'
    method,url,kwargs = http.calls[-1]
    transmitted = json.dumps(http.calls)
    assert 'PRIVATE_SENTINEL' not in transmitted and 'P4102' not in transmitted
    token = base64.b64decode(kwargs['json']['content'])
    assert open_vault(token,key) == vault
    assert 'sha' not in kwargs['json']
    assert kwargs['allow_redirects'] is False


def test_read_existing():
    key=generate_key()
    vault=new_vault()
    payload=base64.b64encode(seal_vault(vault,key)).decode()
    store,http=store_with(checks()+[Response(200,{'type':'file','encoding':'base64','content':payload,'sha':'existing-sha'})],key)
    assert store.load() == (vault,'existing-sha')


@pytest.mark.parametrize('status', [409,422])
def test_stale_save_no_retry(status):
    store,http=store_with(checks()+[Response(status)])
    with pytest.raises(ConflictError):
        store.save(new_vault(),'old-sha')
    assert len(http.calls)==3 and http.calls[-1][2]['json']['sha']=='old-sha'


def test_public_repository_rejected_before_data_read_or_write():
    store,http=store_with([Response(200,{'private':False})])
    with pytest.raises(StorageError):
        store.save(new_vault(),None)
    assert len(http.calls)==1


def test_archived_repository_rejected():
    store,_=store_with([Response(200,{'private':True,'archived':True})])
    with pytest.raises(StorageError):
        store.load()


def test_missing_branch_not_mistaken_for_empty_vault():
    store,http=store_with([Response(200,{'private':True}),Response(404)])
    with pytest.raises(StorageError):
        store.load()
    assert len(http.calls)==2


@pytest.mark.parametrize('status',[401,403,302,500])
def test_failed_access(status):
    store,_=store_with([Response(status)])
    with pytest.raises(StorageError):
        store.load()


def test_network_errors_do_not_echo_response_or_token():
    store,_=store_with([requests.ConnectionError('PRIVATE_SENTINEL')])
    with pytest.raises(StorageError) as err:
        store.load()
    assert 'PRIVATE_SENTINEL' not in str(err.value)


def test_corrupt_encrypted_archive_is_not_an_empty_archive():
    store,_=store_with(checks()+[Response(200,{'type':'file','encoding':'base64','content':base64.b64encode(b'bad').decode(),'sha':'sha'})])
    with pytest.raises(ValidationError):
        store.load()


def test_plain_http_api_rejected():
    with pytest.raises(StorageError):
        GitHubVault(GitHubConfig('token','owner/repo',api_base='http://example.com'),generate_key())
