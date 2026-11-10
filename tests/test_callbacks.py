"""Callback tests with a widget stub. These are not live browser tests."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import types
import time
import pytest
from models import new_vault, new_sheet, save_sheet_in
from security import hash_password
from admin_access import _fingerprint

# Existing callback tests represent an already unlocked administrator.
# The new security tests explicitly remove the grant and test all denial paths.
TEST_ADMIN_CONFIG = {"password_hash": hash_password("example-app-password"),
                     "admin_password_hash": hash_password("example-admin-password")}



@pytest.fixture
def app(monkeypatch):
    stub = types.ModuleType('streamlit')
    stub.session_state = {}
    stub.secrets = types.SimpleNamespace(to_dict=lambda: {'app': TEST_ADMIN_CONFIG.copy()})
    stub.set_page_config = lambda **kwargs: None
    stub.fragment = lambda **kwargs: (lambda function: function)
    monkeypatch.setitem(sys.modules, 'streamlit', stub)
    path = Path(__file__).parents[1] / 'app.py'
    spec = importlib.util.spec_from_file_location('app_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stub.session_state.update(vault=new_vault(), vault_sha=None, drafts={}, base_sheets={},
                             authenticated=True, last_activity=time.monotonic(), login_at=time.monotonic())
    stub.session_state.update(admin_unlocked=True, admin_grant_hash=_fingerprint(TEST_ADMIN_CONFIG),
                              admin_login_at=time.monotonic(), admin_last_activity=time.monotonic())
    return module


def open_room(app, room='P4102'):
    app.st.session_state['room_choice'] = room
    app.open_room()


def test_room_selection_separate_drafts(app):
    open_room(app)
    ss=app.st.session_state
    ss['drafts']['P4102']['fields']['Diagnoses']='First room example'
    open_room(app,'P4104')
    assert ss['drafts']['P4104']['fields']['Diagnoses']==''
    open_room(app)
    assert ss['drafts']['P4102']['fields']['Diagnoses']=='First room example'


def test_one_click_create_does_not_save_raw_paste(app):
    open_room(app)
    ss=app.st.session_state
    ss['paste']='aaaaaaaa\nDiagnoses:\n1. Example\naaaaaaaa\nhhhhhhhh\nINTAKE/OUTPUT:\nRAW_NOT_SAVED\nhhhhhhhh'
    app.create_handoff()
    assert ss['drafts']['P4102']['fields']['Diagnoses']=='Example'
    assert ss['paste']==''
    assert ss['vault']['rooms']=={}
    app.save_room(None)
    assert 'RAW_NOT_SAVED' not in str(ss['vault'])


def test_replace_diagnosis_needs_no_confirmation(app):
    open_room(app)
    ss=app.st.session_state
    ss['drafts']['P4102']['fields']['Diagnoses']='Existing'
    ss['paste']='aaaaaaaa\nDiagnoses:\n1. New\naaaaaaaa'
    app.create_handoff()
    assert ss['drafts']['P4102']['fields']['Diagnoses']=='New'


def test_room_switch_clears_import_result_and_paste(app):
    open_room(app)
    app.st.session_state['paste']='aaaaaaaa\nDiagnoses:\n1. Example\naaaaaaaa'
    app.create_handoff()
    open_room(app,'P4104')
    assert 'import_result' not in app.st.session_state
    assert app.st.session_state['paste']==''


def test_new_patient_is_blank_without_confirmation_and_not_saved(app):
    open_room(app)
    ss=app.st.session_state
    app.save_room(None)
    old=deepcopy(ss['vault']['rooms']['P4102'])
    app.start_new_patient()
    assert ss['drafts']['P4102']['id']!=old['id']
    assert ss['vault']['rooms']['P4102']==old
    assert not ss['drafts']['P4102']['medications'] and ss['drafts']['P4102']['ventilation'] is None


def test_save_needs_no_review_checkbox(app):
    open_room(app)
    app.save_room(None)
    assert 'P4102' in app.st.session_state['vault']['rooms']


def test_stale_room_cannot_overwrite_after_reload(app):
    open_room(app)
    ss=app.st.session_state
    newer=new_sheet('P4102')
    newer['fields']['Diagnoses']='Newer saved example'
    ss['vault']=save_sheet_in(ss['vault'],newer)
    app.save_room(None)
    assert ss['vault']['rooms']['P4102']['fields']['Diagnoses']=='Newer saved example'
    assert ss['notice'][0]=='error'


def test_logout_clears_data(app):
    open_room(app)
    app.clear_session()
    assert app.st.session_state=={}


def test_expired_callback_cannot_save(app):
    open_room(app)
    ss=app.st.session_state
    ss['last_activity']=time.monotonic()-1000
    class MustNotSave:
        def save(self,*args):
            raise AssertionError('Expired sessions must not write')
    app.save_room(MustNotSave())
    assert app.st.session_state=={}


def test_all_save_is_atomic_on_local_conflict(app):
    open_room(app)
    ss=app.st.session_state
    ss['drafts']['P4102']['fields']['Diagnoses']='Draft one'
    open_room(app,'P4104')
    ss['drafts']['P4104']['fields']['Diagnoses']='Draft two'
    changed=new_sheet('P4104')
    changed['fields']['Diagnoses']='Other session'
    ss['vault']=save_sheet_in(ss['vault'],changed)
    app.save_all_rooms(None)
    assert ss['vault']['rooms']['P4102']['fields']['Diagnoses']=='Draft one'
    assert ss['notice'][0]=='error'
    assert ss['vault']['rooms']['P4104']['fields']['Diagnoses']=='Other session'


def test_all_save_writes_both_rooms_without_confirmation(app):
    open_room(app)
    ss=app.st.session_state
    ss['drafts']['P4102']['fields']['Diagnoses']='Draft one'
    open_room(app,'P4104')
    ss['drafts']['P4104']['fields']['Diagnoses']='Draft two'
    app.save_all_rooms(None)
    assert len(ss['vault']['rooms'])==2
    assert ss['base_sheets']==ss['vault']['rooms']


def test_other_room_open_sets_canonical_selection(app):
    ss=app.st.session_state
    ss.update(room_choice='Other room',other_room='p4301')
    app.open_room()
    assert ss['current_room']=='P4301' and ss['room_choice']=='P4301'


def test_room_field_edit_survives_navigation_widget_cleanup(app):
    open_room(app)
    ss=app.st.session_state
    sheet=ss['drafts']['P4102']
    key=app.edit_key(sheet,'Respiratory')
    ss[key]='Keep this manual note'
    app.update_field('P4102','Respiratory',key)
    ss.pop(key,None)
    open_room(app,'P4104')
    open_room(app,'P4102')
    assert ss['drafts']['P4102']['fields']['Respiratory']=='Keep this manual note'
