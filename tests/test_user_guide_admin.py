"""Separate Admin permission, published-guide storage, and workflow regression."""
from copy import deepcopy
from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from admin_access import (admin_valid, unlock_admin, lock_admin, config_error,
                          _fingerprint, IDLE_SECONDS, MAX_SECONDS)
from security import hash_password, generate_key, seal_vault, open_vault
from models import new_vault, new_sheet, save_sheet_in
from user_guide import default_guide, validate_guide, publication, instructions_html, DEFAULT_INSTRUCTIONS
from guide_store import GuideStore, GUIDE_PATH
from github_store import GitHubVault, GitHubConfig, StorageError, ConflictError
from set_admin_password import admin_password_line, generate_admin_password_line
from test_callbacks import app, open_room, TEST_ADMIN_CONFIG
from test_ui_smoke import equip


def session(now=5000):
    return dict(authenticated=True,last_activity=now,login_at=now,idle_seconds=900)


@pytest.mark.parametrize('config', [{}, {'admin_password_hash':'plain-secret'}, {'admin_password_hash':None}])
def test_unconfigured_admin_is_closed(config):
    ss=session()
    assert config_error(config)
    assert not unlock_admin(ss,config,'anything',now=5000)
    assert not admin_valid(ss,config,now=5000)
    assert ss['authenticated']


def test_password_gate_uses_distinct_credential():
    ss=session()
    assert not unlock_admin(ss,TEST_ADMIN_CONFIG,'example-app-password',now=5000)
    assert not ss.get('admin_unlocked')
    assert unlock_admin(ss,TEST_ADMIN_CONFIG,'example-admin-password',now=5005)
    assert admin_valid(ss,TEST_ADMIN_CONFIG,now=5006)
    assert 'example-admin-password' not in str(ss)


def test_same_secret_with_different_salt_is_rejected():
    shared='example-app-password'
    config={'password_hash':TEST_ADMIN_CONFIG['password_hash'], 'admin_password_hash':hash_password(shared)}
    ss=session()
    assert not unlock_admin(ss,config,shared,now=5000)
    assert not ss.get('admin_unlocked')
    assert 'different' in ss['admin_login_error']


def test_same_hash_is_rejected():
    config={**TEST_ADMIN_CONFIG,'admin_password_hash':TEST_ADMIN_CONFIG['password_hash']}
    assert config_error(config)


def test_throttle_preserves_error_and_grants_nothing():
    ss=session()
    assert not unlock_admin(ss,TEST_ADMIN_CONFIG,'incorrect',now=5000)
    assert not unlock_admin(ss,TEST_ADMIN_CONFIG,'example-admin-password',now=5001)
    assert 'Wait' in ss['admin_login_error']
    admin_valid(ss,TEST_ADMIN_CONFIG,now=5001)
    assert ss['admin_login_error']  # Rendering the gate must not erase a failed-attempt message.


@pytest.mark.parametrize('delta', [IDLE_SECONDS, IDLE_SECONDS+1, MAX_SECONDS+1])
def test_timeout_relocks_without_erasing_room_work(delta):
    ss=session()
    ss['drafts']={'P4102':{'note':'keep'}}
    assert unlock_admin(ss,TEST_ADMIN_CONFIG,'example-admin-password',now=5000)
    ss['last_activity']=5000+delta  # Ordinary app activity does not extend Admin access.
    assert not admin_valid(ss,TEST_ADMIN_CONFIG,now=5000+delta)
    assert ss['drafts']['P4102']['note']=='keep'


def test_absolute_limit_even_with_admin_activity():
    ss=session()
    assert unlock_admin(ss,TEST_ADMIN_CONFIG,'example-admin-password',now=5000)
    ss['last_activity']=ss['admin_last_activity']=5000+MAX_SECONDS
    assert not admin_valid(ss,TEST_ADMIN_CONFIG,now=5000+MAX_SECONDS)


@pytest.mark.parametrize('changed', ['password_hash','admin_password_hash'])
def test_changed_secret_revokes_grant(changed):
    ss=session()
    assert unlock_admin(ss,TEST_ADMIN_CONFIG,'example-admin-password',now=5000)
    config={**TEST_ADMIN_CONFIG,changed:hash_password('replacement-password')}
    assert not admin_valid(ss,config,now=5001)


def test_app_logout_and_expiry_revoke_admin():
    for changed in ('authenticated','last_activity','login_at'):
        ss=session()
        assert unlock_admin(ss,TEST_ADMIN_CONFIG,'example-admin-password',now=5000)
        ss[changed]=False if changed=='authenticated' else -50000
        assert not admin_valid(ss,TEST_ADMIN_CONFIG,now=5001)


def test_auth_callback_removes_plaintext_and_retains_draft(app):
    ss=app.st.session_state
    open_room(app)
    before=deepcopy(ss['drafts'])
    lock_admin(ss)
    ss['admin_login_password']='example-admin-password'
    app.authenticate_admin()
    assert ss['admin_unlocked']
    assert 'admin_login_password' not in ss
    assert ss['drafts']==before


@pytest.mark.parametrize('page', ['Handoff','Print all','Instructions / SmartPhrase','Import errors'])
def test_leaving_admin_locks_it(app,page):
    ss=app.st.session_state
    ss['page']=page
    app.workspace_changed()
    assert not ss.get('admin_unlocked')
    assert ss['authenticated']


@pytest.mark.parametrize('name,args', [
    ('save_admin_rule',(None,)),('remove_admin_rule',(None,)),('save_admin_settings',(None,)),
    ('select_admin_rule',()),('reset_infusion_rule',(('example','iv','continuous'),None)),
    ('edit_saved_infusion_rule',(('example','iv','continuous'),'x',None)),
    ('update_gi_admin',(('example','oral','daily'),'x',None)),
    ('update_group_admin',(('example','iv','daily'),'x',None)),
    ('remove_selected_custom_room',(None,)), ('admin_undo_room_removal',(None,)),
    ('admin_visibility_rule',('example',True,'exact',None)),
    ('save_user_guide',(None,)),('load_published_guide_into_editor',(None,)),
])
def test_callbacks_cannot_bypass_locked_admin(app,name,args):
    ss=app.st.session_state
    lock_admin(ss)
    before=deepcopy(ss['vault'])
    getattr(app,name)(*args)
    assert ss['vault']==before
    assert 'user_guide' not in ss
    assert ss['notice'][0]=='error'


def test_regular_handoff_and_instruction_access_do_not_require_admin(app,monkeypatch):
    lock_admin(app.st.session_state)
    open_room(app)
    ss=app.st.session_state
    ss['paste']='aaaaaaaa\nDiagnoses:\n1. Synthetic example\naaaaaaaa'
    app.create_handoff()
    app.save_room(None)
    assert ss['vault']['rooms']['P4102']['fields']['Diagnoses']=='Synthetic example'
    downloads=equip(app,monkeypatch)
    app.handoff_page(None)
    assert not any(name=='Download user guide (HTML)' for name,_ in downloads)
    assert not ss.get('admin_unlocked')


def test_locked_admin_does_not_render_shared_editors(app,monkeypatch):
    ss=app.st.session_state
    equip(app,monkeypatch)
    lock_admin(ss)
    app.admin_page(None)
    assert 'admin_login_password' in ss
    assert 'guide_edit_instructions' not in ss
    assert 'mapping_name' not in ss


def test_missing_config_never_falls_back_to_app_password(app,monkeypatch):
    equip(app,monkeypatch)
    app.st.secrets=SimpleNamespace(to_dict=lambda:{'app':{'password_hash':TEST_ADMIN_CONFIG['password_hash']}})
    app.admin_page(None)
    assert 'guide_edit_instructions' not in app.st.session_state


def test_default_is_patient_free_and_does_not_invent_smartlinks():
    doc=default_guide()
    validate_guide(doc)
    assert doc['smartphrase_name']==doc['smartphrase_text']==''
    assert 'Create / update handoff' in doc['instructions']
    assert 'Save handoff' in doc['instructions']
    assert 'Print all' in doc['instructions']
    assert 'Streamlit' in doc['instructions']
    assert 'PICUHANDOFFSMARTPHRASE' in doc['instructions']
    assert 'next room to save automatically' in doc['instructions']
    assert len(doc['instructions'].split()) < 120
    assert 'Instructions / SmartPhrase' not in doc['instructions']


@pytest.mark.parametrize('field,value', [
    ('smartphrase_name','a\nb'), ('smartphrase_text','\x00'),
    ('instructions',''),('instructions',' '*5), ('smartphrase_name','x'*121),
    ('smartphrase_text','x'*80001),('setup_notes','x'*8001), ('updated_at','no date'),
    ('updated_at','2026-01-01T00:00:00'),('schema',True),
])
def test_invalid_guide_content_fails_validation(field,value):
    doc=default_guide(); doc[field]=value
    with pytest.raises(ValueError): validate_guide(doc)


def test_template_whitespace_and_raw_smartlinks_are_unchanged():
    source='aaaaaaaa\nDiagnoses:\n@REAL_LINK@\n\t  keep spacing  \n'
    doc=publication('.TEAM',source,'','Learner instructions')
    assert doc['smartphrase_text']==source
    assert doc['updated_at']
    assert '"' not in doc['smartphrase_name']


def test_html_escapes_every_shared_field():
    payload='<script>alert(1)</script>'
    doc=publication(payload,payload,payload,payload)
    html=instructions_html(doc)
    assert '<script>' not in html
    assert html.count('&lt;script&gt;')==4


class Response:
    def __init__(self,status,data): self.status_code=status;self.data=data
    def json(self): return self.data


class Remote:
    """HTTP transport simulation only, not live GitHub."""
    def __init__(self): self.calls=[];self.guide=None;self.sha=None;self.fail=None
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,deepcopy(kwargs)))
        if url.endswith('/repos/example/private'):
            return Response(200,{'private':True,'archived':False})
        if '/branches/' in url: return Response(200,{})
        assert url.endswith('/contents/'+GUIDE_PATH)
        if method=='GET':
            if self.guide is None:return Response(404,{})
            return Response(200,{'type':'file','encoding':'base64','content':self.guide,'sha':self.sha})
        if self.fail: return Response(self.fail,{})
        assert method=='PUT'
        payload=kwargs['json']
        if payload.get('sha') != self.sha: return Response(409,{})
        self.guide=payload['content'];self.sha='version-'+str(len(self.calls))
        return Response(201,{'content':{'sha':self.sha}})


def remote_store():
    remote=Remote()
    vault=GitHubVault(GitHubConfig(token='synthetic',repository='example/private'),generate_key(),session=remote)
    return vault,remote


def test_guide_round_trip_encrypted_and_separate_path():
    vault,remote=remote_store(); store=GuideStore(vault)
    doc,sha=store.load();assert doc==default_guide() and sha is None
    doc=publication('.TEAM','@LINK@\t\n','setup','steps')
    result=store.save(doc,sha)
    assert store.load()==(doc,result)
    assert b'@LINK@' not in base64.b64decode(remote.guide)
    assert all('handoff-v1.enc' not in url for _,url,_ in remote.calls)
    assert remote.calls[-2][0]=='GET'
    puts=[kwargs['json'] for method,_,kwargs in remote.calls if method=='PUT']
    assert puts[0]['message']=='Update encrypted user guide'
    assert 'smartphrase_text' not in json.dumps(puts)


def test_guide_rejects_stale_editor_without_overwriting():
    vault,remote=remote_store();store=GuideStore(vault)
    first=publication('.ONE','@1@','','steps')
    sha=store.save(first,None)
    latest=publication('.TWO','@2@','','steps')
    newsha=store.save(latest,sha)
    with pytest.raises(ConflictError): store.save(first,sha)
    assert store.load()==(latest,newsha)


@pytest.mark.parametrize('mode',['tampered','wrong-key','invalid-schema','oversize','invalid-base64'])
def test_bad_guide_cannot_be_loaded(mode):
    vault,remote=remote_store();store=GuideStore(vault)
    store.save(default_guide(),None)
    if mode=='tampered': remote.guide=base64.b64encode(b'invalid').decode()
    elif mode=='wrong-key': vault.key=generate_key()
    elif mode=='invalid-schema':
        remote.guide=base64.b64encode(Fernet(vault.key.encode()).encrypt(b'{"schema":99}')).decode()
    elif mode=='oversize': remote.guide='a'*1500000
    else:remote.guide='@!invalid!'
    with pytest.raises(StorageError): store.load()


def prepare_editor(app,store=None):
    doc=app.load_user_guide(store)
    app.prepare_guide_editor(doc)
    app.st.session_state.update(guide_edit_smartphrase_name='.TEAM',guide_edit_smartphrase_text='@LINK@',
                               guide_edit_setup_notes='Ask local Epic support.',guide_edit_instructions=DEFAULT_INSTRUCTIONS)


def test_publish_does_not_touch_rooms_mappings_times_or_sha(app):
    vault,remote=remote_store()
    ss=app.st.session_state
    open_room(app); app.save_room(None)
    before=deepcopy(ss['vault']);roomsha=ss['vault_sha']='room-sha'
    prepare_editor(app,vault)
    app.save_user_guide(vault)
    assert ss['vault']==before and ss['vault_sha']==roomsha
    assert ss['user_guide']['smartphrase_name']=='.TEAM'
    assert ss['guide_sha'] and ss['user_guide']['updated_at']
    doc,sha=GuideStore(vault).load()
    assert doc==ss['user_guide'] and sha==ss['guide_sha']


def test_failed_publish_preserves_published_and_draft_values(app):
    vault,remote=remote_store(); ss=app.st.session_state
    prepare_editor(app,vault)
    before=deepcopy(ss['user_guide']);remote.fail=500
    app.save_user_guide(vault)
    assert ss['user_guide']==before
    assert ss['guide_edit_smartphrase_text']=='@LINK@'
    assert ss['guide_sha'] is None
    assert ss['notice'][0]=='error'


def test_refresh_does_not_silently_rebase_unsaved_admin_draft(app):
    vault,remote=remote_store();ss=app.st.session_state
    prepare_editor(app,vault)
    GuideStore(vault).save(publication('.REMOTE','@REMOTE@','','steps'),None)
    app.refresh_user_guide(vault)
    assert ss['guide_editor_sha'] is None
    app.save_user_guide(vault)
    assert ss['notice'][0]=='error'
    assert ss['guide_edit_smartphrase_text']=='@LINK@'
    assert ss['user_guide']['smartphrase_text']=='@REMOTE@'
    app.load_published_guide_into_editor(vault)
    assert ss['guide_edit_smartphrase_text']=='@REMOTE@'
    app.save_user_guide(vault)
    assert ss['notice'][0]=='success'


def test_failed_guide_load_does_not_block_handoff(app,monkeypatch):
    class Broken:
        def __init__(self,store): pass
        def load(self): raise StorageError('Unavailable.')
    monkeypatch.setattr(app,'GuideStore',Broken)
    open_room(app)
    app.load_user_guide(object())
    assert app.st.session_state['guide_load_error']
    app.st.session_state['paste']='aaaaaaaa\nDiagnoses:\n1. Synthetic\naaaaaaaa'
    app.create_handoff();app.save_room(None)
    assert app.st.session_state['vault']['rooms']['P4102']['fields']['Diagnoses']=='Synthetic'


def test_clinical_archive_schema_is_unchanged():
    v=new_vault();v=save_sheet_in(v,new_sheet('P4104'))
    key=generate_key()
    assert open_vault(seal_vault(v,key),key)==v
    assert 'user_guide' not in v and 'admin_password_hash' not in str(v)


def test_admin_setup_only_prints_one_hashed_setting(monkeypatch,capsys,tmp_path):
    import set_admin_password as helper
    values=iter(['unique-admin-secret','unique-admin-secret'])
    monkeypatch.setattr(helper.getpass,'getpass',lambda prompt:next(values))
    monkeypatch.chdir(tmp_path)
    generate_admin_password_line()
    out=capsys.readouterr().out
    assert 'unique-admin-secret' not in out
    line=next(s for s in out.splitlines() if s.startswith('admin_password_hash = '))
    from security import verify_password
    assert verify_password('unique-admin-secret',line.split('"')[1])
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('password,confirmation',[('short','short'),('long-enough-password','not-the-same')])
def test_helper_rejects_invalid_passwords(password,confirmation):
    with pytest.raises(ValueError): admin_password_line(password,confirmation)


def test_smartphrase_view_never_reuses_room_paste(app,monkeypatch):
    open_room(app); ss=app.st.session_state; ss['paste']='NOT_A_TEMPLATE'
    equip(app,monkeypatch)
    outputs=[];app.st.code=lambda text,**kw:outputs.append(text)
    app.handoff_page(None)
    assert not any('NOT_A_TEMPLATE' in str(x) for x in outputs)
    assert ss['paste']=='NOT_A_TEMPLATE'


def test_return_to_admin_rehydrates_published_values_after_widget_cleanup(app):
    ss=app.st.session_state
    prepare_editor(app)
    app.save_user_guide(None)
    expected=deepcopy(ss['user_guide'])
    for key in list(ss):
        if key.startswith('guide_edit_'):ss.pop(key)
    app.prepare_guide_editor(expected)
    assert ss['guide_edit_instructions']==expected['instructions']
    assert ss['guide_edit_smartphrase_text']=='@LINK@'


def test_gate_cooldown_error_is_visible_after_failed_login(app,monkeypatch):
    ss=app.st.session_state
    equip(app,monkeypatch)
    errors=[];app.st.error=errors.append
    lock_admin(ss)
    ss['admin_login_password']='incorrect'
    app.authenticate_admin()
    app.admin_gate()
    assert any('not accepted' in error for error in errors)
