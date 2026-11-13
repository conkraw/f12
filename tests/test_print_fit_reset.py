"""Synthetic auto-fit, reset, concurrency and export regressions for v6.23."""
from copy import deepcopy
from io import BytesIO
from threading import Event
from datetime import datetime, timezone
import json
import time
from user_guide import default_guide
import pytest
import fitz
from reportlab.pdfbase.pdfmetrics import stringWidth
from cryptography.fernet import Fernet
from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_compact_pn import sheet as compact_sheet
from test_rooms_infusions import med
from models import new_vault, new_sheet, validate_vault, save_sheet_in, upgrade_vault, DEFAULT_ROOMS, ValidationError
from handoff_reset import cleared_vault, census_was_reset
from github_store import StorageError, ConflictError
from security import open_vault, seal_vault, generate_key
from exports import (handoff_pdf, handoffs_pdf, print_fit_report, download_payload,
                     _select_pdf_plan, _make_pdf_plan, _plan_heights, PRINT_MARGIN, COLUMNS)
from batching import available_handoffs
from admin_access import lock_admin


class Store:
    def __init__(self, vault=None, sha='old-sha', failure=None):
        self.vault = deepcopy(vault)
        self.sha = sha
        self.calls = []
        self.failure = failure
    def save(self, candidate, sha):
        self.calls.append((deepcopy(candidate), sha))
        if self.failure:
            raise self.failure
        if sha != self.sha:
            raise ConflictError('Synthetic concurrent update')
        self.vault = deepcopy(candidate)
        self.sha = 'new-sha-' + str(len(self.calls))
        return self.sha
    def load(self):
        if self.failure:
            raise self.failure
        return deepcopy(self.vault), self.sha


def populated(app):
    ss = app.st.session_state
    first = new_sheet('P4102'); first['fields']['Diagnoses'] = 'SYNTHETIC FIRST'
    other = new_sheet('EXTRA 1'); other['fields']['Diagnoses'] = 'SYNTHETIC OTHER'
    v = save_sheet_in(save_sheet_in(new_vault(), first), other)
    v['settings']['rooms'] += ['EXTRA 1', 'EXTRA 2']
    from medications import upsert_rule, set_visibility_rule
    v['settings']['medication_mappings'] = upsert_rule([], 'example', 'Neurologic')
    v['settings']['medication_visibility'] = set_visibility_rule([], 'example hidden', True)
    ss.update(vault=v, vault_sha='old-sha', drafts=deepcopy(v['rooms']), base_sheets=deepcopy(v['rooms']),
              current_room='P4102', room_choice='P4102', paste='Unsubmitted synthetic text',
              print_rooms=['P4102', 'EXTRA 1'], print_room_options=['P4102', 'EXTRA 1'])
    ss['drafts']['UNSAVED'] = new_sheet('UNSAVED')
    ss['drafts']['UNSAVED']['fields']['Other'] = 'UNSAVED SENTINEL'
    ss['drafts']['P4102']['fields']['Neurologic'] = 'Unsaved synthetic note'
    ss['removed_room'] = {'room':'OLD REMOVAL'}
    ss['field_any_1'] = 'Widget clinical content'
    ss['cbc_any_value'] = 'Widget clinical content'
    ss['user_guide'] = default_guide()
    ss['user_guide']['smartphrase_name'] = 'SYNTHETIC_TEAM_TEMPLATE'
    ss['guide_sha'] = 'guide-sha'
    ss['pending_error_events'] = {'x': {'code':'SAFE TECHNICAL DIAGNOSTIC'}}
    return ss


def test_atomic_clear_keeps_rules_guide_errors_and_clears_every_room(app):
    ss = populated(app)
    before = deepcopy(ss['vault']); guide=deepcopy(ss['user_guide']); errs=deepcopy(ss['pending_error_events'])
    store = Store(before)
    guard=app.download_revocation()
    app.clear_all_handoffs(store)
    assert len(store.calls)==1 and store.calls[0][1]=='old-sha'
    assert ss['vault']==store.vault
    assert ss['vault']['rooms']==ss['drafts']==ss['base_sheets']=={}
    assert ss['vault']['settings']==dict(before['settings'], rooms=list(DEFAULT_ROOMS))
    assert ss['vault']['reset_generation'] and ss['vault']['reset_generation'] != before['reset_generation']
    assert ss['user_guide']==guide and ss['guide_sha']=='guide-sha'
    assert ss['pending_error_events']==errs and ss['authenticated'] and ss['admin_unlocked']
    assert ss['room_choice']=='Choose a room' and ss['paste']==''
    for key in ('current_room','removed_room','print_rooms','print_room_options','field_any_1','cbc_any_value'):
        assert key not in ss
    assert guard.is_set() and not app.download_revocation().is_set()
    assert not available_handoffs(ss['vault'],ss['drafts'])
    open_room(app,'P4102')
    assert ss['drafts']['P4102']['updated_at'] is None and ss['drafts']['P4102']['fields']['Diagnoses']==''


@pytest.mark.parametrize('error',[StorageError('Offline'), ConflictError('Concurrent'), RuntimeError('Unknown error')])
def test_clear_failures_keep_archive_drafts_widgets_and_downloads(app,error):
    ss=populated(app); before={k:deepcopy(ss[k]) for k in ('vault','drafts','base_sheets','paste','removed_room','room_choice')}
    guard=app.download_revocation(); store=Store(failure=error)
    app.clear_all_handoffs(store)
    for key,value in before.items(): assert ss[key]==value
    assert ss['field_any_1']=='Widget clinical content' and not guard.is_set()
    assert ss['notice'][0]=='error' and 'not confirmed' in ss['notice'][1]


@pytest.mark.parametrize('state',['locked','expired_admin','logged_out','same_password'])
def test_clear_needs_app_session_not_independent_admin_auth(app,state):
    ss=populated(app); before=deepcopy(ss['vault']);store=Store(before)
    if state=='locked': lock_admin(ss)
    if state=='expired_admin': ss['admin_last_activity']=time.monotonic()-901
    if state=='logged_out': ss['authenticated']=False
    if state=='same_password': ss['admin_grant_hash']='invalid-grant'
    app.clear_all_handoffs(store)
    if state == 'logged_out':
        assert not store.calls
        assert not ss
    else:
        assert len(store.calls) == 1 and not store.vault['rooms']
        assert not ss['drafts'] and not ss['vault']['rooms']


def test_session_only_clear_does_not_claim_github_save(app):
    ss=populated(app);app.clear_all_handoffs(None)
    assert not ss['vault']['rooms'] and ss['notice'][0]=='info'
    assert 'Session-only' in ss['notice'][1]


def test_reset_pure_function_is_nonmutating_and_preserves_all_settings_except_rooms():
    v=new_vault();v['rooms']['EXTRA']=new_sheet('EXTRA');v['settings']['rooms']=['EXTRA']
    before=deepcopy(v); a=cleared_vault(v); b=cleared_vault(v)
    assert v==before and not a['rooms'] and a['reset_generation']!=b['reset_generation']
    assert a['settings']==dict(v['settings'], rooms=list(DEFAULT_ROOMS))
    validate_vault(a)


def test_stale_writer_cannot_resurrect_cleared_handoffs_and_reload_discards_drafts(app):
    ss=populated(app); previous=deepcopy(ss['vault'])
    remote=cleared_vault(previous)
    store=Store(remote,sha='cleared-elsewhere')
    app.save_all_rooms(store)
    assert store.vault==remote and ss['drafts']
    app.reload_archive(store)
    assert ss['vault']==remote and ss['vault_sha']=='cleared-elsewhere'
    assert not ss['drafts'] and not ss['base_sheets'] and ss['room_choice']=='Choose a room'
    assert 'older open drafts were discarded' in ss['notice'][1]
    app.save_all_rooms(store)
    assert store.vault==remote


def test_regular_reload_still_keeps_unsaved_drafts(app):
    ss=populated(app);before=deepcopy(ss['drafts'])
    remote=deepcopy(ss['vault']);remote['rooms']['P4104']=new_sheet('P4104')
    app.reload_archive(Store(remote,sha='newer'))
    assert ss['drafts']==before and ss['vault']==remote


def test_unsubmitted_new_custom_room_is_removed_after_remote_reset(app):
    ss=populated(app);assert ss['base_sheets'].get('UNSAVED') is None
    remote=cleared_vault(ss['vault']);app.reload_archive(Store(remote,sha='newer'))
    assert 'UNSAVED' not in ss['drafts'] and 'UNSAVED' not in ss['vault']['settings']['rooms']


def test_reset_retry_after_unacknowledged_remote_success_is_safe(app):
    ss=populated(app);remote=cleared_vault(ss['vault'])
    app.clear_all_handoffs(Store(failure=StorageError('Response lost')))
    assert ss['drafts']
    app.reload_archive(Store(remote,sha='newer'))
    assert ss['vault']==remote and not ss['drafts']


def test_old_download_generator_revoked_on_reset(app):
    ss=populated(app);generator=download_payload([ss['drafts']['P4102']], 'pdf', cancelled=app.download_revocation())
    app.clear_all_handoffs(None)
    with pytest.raises(ValueError,match='cleared'):generator()


def test_old_download_generator_revoked_on_logout(app):
    ss=populated(app);generator=download_payload([ss['drafts']['P4102']], 'html', cancelled=app.download_revocation())
    app.clear_session()
    with pytest.raises(ValueError,match='cleared'):generator()


def test_v17_encrypted_migration_preserves_every_prior_setting_and_sheet():
    v=new_vault();v.pop('reset_generation');v['schema']=17
    v['rooms']['P4102']=new_sheet('P4102');v['rooms']['P4102'].pop('feeds');v['rooms']['P4102'].pop("devices", None);v['rooms']['P4102'].pop("neuro_devices", None);v['rooms']['P4102'].pop("pacemaker", None);v['rooms']['P4102'].pop("diet", None);v['rooms']['P4102']['fields']['Other']='Do not alter'
    before=deepcopy(v);key=generate_key();data=Fernet(key.encode()).encrypt(json.dumps(v).encode())
    out=open_vault(data,key)
    assert out['rooms']=={room: dict(sheet, feeds=None,devices=None,neuro_devices=None,pacemaker=None,diet=None) for room, sheet in v['rooms'].items()} and out['settings']==v['settings'] and v==before
    assert out['schema']==34 and out['reset_generation']==''
    assert open_vault(seal_vault(out,key),key)==out


@pytest.mark.parametrize('invalid',[None,True,12,'not a token','x'*32,{},'f'*33])
def test_invalid_reset_generation_is_rejected(invalid):
    v=new_vault();v['reset_generation']=invalid
    with pytest.raises(ValidationError):validate_vault(v)


def long_column(n=60):
    s=new_sheet('P4102');s['fields']['Diagnoses']='Synthetic print fit example'
    s['fields']['Neurologic']='\n'.join(f'NEURO_ITEM_{i:03d} Detailed synthetic handoff note.' for i in range(n))
    return s


def test_tighter_spacing_and_widths_rescue_two_page_case_without_changing_content():
    s=long_column(36);before=deepcopy(s)
    report=print_fit_report(s)
    doc=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    assert len(doc)==report['page_count']==1
    assert report['tight_spacing'] and report['balanced_columns']
    text=''.join(p.get_text() for p in doc)
    for i in range(36): assert text.count(f'NEURO_ITEM_{i:03d}')==1
    assert before==s


@pytest.mark.parametrize('target',[1,2])
@pytest.mark.parametrize('n',[0,20,40,70,140,300])
def test_actual_preflight_count_matches_export_and_keeps_all_notes(target,n):
    s=long_column(n);report=print_fit_report(s,target)
    doc=fitz.open(stream=handoff_pdf(s,target_pages=target),filetype='pdf')
    assert len(doc)==report['page_count']
    assert report['target_met']==(len(doc)<=target)
    assert report['font_size']>=6.5
    text=''.join(p.get_text() for p in doc)
    for i in range(n): assert text.count(f'NEURO_ITEM_{i:03d}')==1
    for page in doc:
        for rect in page.get_text('blocks'):
            assert 0 <= rect[0] < rect[2] <= 792.1 and 0 <= rect[1] < rect[3] <= 612.1


def test_two_page_target_keeps_larger_type_when_possible():
    s=long_column(40);report=print_fit_report(s,2)
    assert report['page_count']==2 and report['font_size']==8.0 and report['target_met']


def test_very_long_sheet_uses_more_pages_not_truncation():
    s=long_column(300);report=print_fit_report(s)
    assert report['page_count']>2 and not report['target_met']


def test_balanced_column_headings_fit():
    plan,_=_select_pdf_plan(long_column(36),792,612)
    assert abs(sum(plan['widths'])-plan['width'])<.01
    for (label,_),width in zip(COLUMNS,plan['widths']):
        assert stringWidth(label,'Times-Bold',8) <= width-5


@pytest.mark.parametrize('target',[0,3,True,'1',None])
def test_invalid_target_is_not_silently_accepted(target):
    with pytest.raises(ValueError): print_fit_report(new_sheet('P4102'),target)


def test_batch_starts_each_room_on_new_page_and_matches_preflight():
    a=long_column(36);b=long_column(140);b['room']='P4104'
    count_a=print_fit_report(a)['page_count'];count_b=print_fit_report(b)['page_count']
    doc=fitz.open(stream=handoffs_pdf([a,b]),filetype='pdf')
    assert len(doc)==count_a+count_b
    assert 'Room P4102' in doc[0].get_text() and 'Room P4104' in doc[count_a].get_text()


def test_labs_and_medication_data_unchanged_by_layout():
    s=compact_sheet();before=deepcopy(s)
    for target in (1,2):
        report=print_fit_report(s,target)
        text=''.join(p.get_text() for p in fitz.open(stream=handoff_pdf(s,target_pages=target),filetype='pdf'))
        assert report['page_count']<=target
        for token in ('Hepatic','Coagulation','Pediatric 2-in-1 PN','fat emulsion','[Held by provider]'):
            assert token in text
    assert s==before


def test_admin_reset_remains_protected_without_extra_confirmation(app,monkeypatch):
    populated(app);equip(app,monkeypatch);calls=[]
    app.st.button=lambda label,**kwargs:calls.append((label,kwargs))
    app.admin_page(None)
    reset=[item for item in calls if item[0]=='Delete all handoff data']
    assert len(reset)==1 and reset[0][1]['on_click']==app.clear_all_handoffs
    lock_admin(app.st.session_state);calls.clear();app.admin_page(None)
    assert not any('Delete all handoff data' in label for label,_ in calls)


def test_ui_shows_pdf_page_target_and_no_example_buttons(app,monkeypatch):
    open_room(app);equip(app,monkeypatch);app.handoff_page(None)
    assert app.st.session_state['room_print_target']==1
