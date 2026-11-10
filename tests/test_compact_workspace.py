"""6.53 interface contract, lazy rendering and session-isolation regressions.

Uses an instrumented widget simulation, not a live Streamlit browser. The
legacy smoke fixture intentionally traverses every panel for broad coverage.
These tests model the active panel and Streamlit's inactive-widget cleanup.
"""
from copy import deepcopy
from pathlib import Path
import time
import inspect
import pytest

from test_callbacks import app, open_room
from test_ui_smoke import equip, Panel
from models import new_sheet, new_vault, validate_sheet
from import_review import diagnostic
from user_guide import default_guide, DEFAULT_INSTRUCTIONS
from workspace_ui import (
    WORKSPACE_TABS, COMPACT_STYLES, compact_help, alert_rows, alert_lines_html,
    remember_notice, remember_import, current_import, workspace_attention,
)


def setup_active(app, monkeypatch, tab="Preview / print"):
    if not app.st.session_state.get("current_room"):
        open_room(app)
    equip(app, monkeypatch)
    ss = app.st.session_state
    ss['handoff_tab'] = tab
    ss['handoff_active_tab'] = tab
    rendered=[]
    app.st.tabs=lambda labels, **kw: [Panel(app.st, opened=label == ss['handoff_tab']) for label in labels]
    for name in ('caption','markdown','text','info','warning','error','subheader'):
        setattr(app.st,name,lambda *a,_name=name,**k: rendered.append((_name,str(a[0]) if a else '',k)))
    # A real download callback is deferred, not executed during page rendering.
    app.st.download_button=lambda label,data,*a,**k: rendered.append(('download',label,data)) or False
    return ss, rendered


def test_tab_order_and_68px_input(app, monkeypatch):
    ss, events = setup_active(app, monkeypatch)
    names=[]; inputs=[]
    base=app.st.tabs
    app.st.tabs=lambda labels,**kw: (names.extend(labels) or base(labels,**kw))
    app.st.text_area=lambda label,**kw: inputs.append((label,kw)) or ss.get(kw.get('key'),'')
    app.handoff_page(None)
    assert names[0] == 'Preview / print'
    assert names[names.index('Difficult airway')+1] == 'Alerts'
    assert 'Paste / create' not in names
    paste=next(options for name,options in inputs if name=='SmartPhrase text')
    assert paste['height'] == 68 and paste['label_visibility']=='collapsed'
    assert paste['max_chars'] == app.MAX_PASTE
    assert paste['placeholder'] == 'Paste Epic SmartPhrase here'
    assert not any('Respiratory support to RESP' in text or 'No automatic respiratory-support' in text for _,text,_ in events)


@pytest.mark.parametrize('tab', WORKSPACE_TABS)
def test_only_selected_tab_renders(app, monkeypatch, tab):
    ss, events=setup_active(app,monkeypatch,tab)
    called=[]
    handlers = {
        'Preview / print':'room_preview', 'Medications':'medication_editor',
        'Labs / Vitals':'labs_vitals_editor','Cultures':'cultures_editor',
        'Labs/Imaging':'recurring_orders_editor','Problems':'problem_review_editor',
        'Difficult airway':'difficult_airway_editor','Alerts':'handoff_alerts',
        'Edit handoff':'handoff_notes',
    }
    # A small valid synthetic order makes the medications handler observable.
    # Use the normal import path instead of constructing unvalidated orders.
    ss['paste']='bbbbbbbb\nMedications:\nMedication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin\n• acetaminophen\t10 mg\tOral\tq6h\tExample\t\t\nbbbbbbbb'
    app.create_handoff()
    ss['handoff_tab']=tab
    for label,name in handlers.items():
        monkeypatch.setattr(app,name,lambda *a,_label=label,**kw:called.append(_label))
    app.handoff_page(None)
    assert called == [tab]


@pytest.mark.parametrize('tab', WORKSPACE_TABS)
def test_no_eager_pdf_fit_on_any_tab(app, monkeypatch, tab):
    ss, events=setup_active(app,monkeypatch,tab)
    def unexpected(*a,**k): raise AssertionError('Unrequested PDF fit')
    monkeypatch.setattr(app,'print_fit_report',unexpected)
    monkeypatch.setattr(app,'handoff_pdf',unexpected)
    app.handoff_page(None)


def test_print_all_does_not_fit_before_download(app,monkeypatch):
    ss,events=setup_active(app,monkeypatch)
    ss['drafts']['P4102']['fields']['Diagnoses']='Synthetic test'
    def unexpected(*a,**k): raise AssertionError('Eager combined PDF')
    monkeypatch.setattr(app,'print_fit_report',unexpected)
    app.print_all_page(None)
    assert any(kind=='download' and callable(payload) for kind,_,payload in events)


def test_explicit_page_check_still_measures_actual_pages(app,monkeypatch):
    ss,events=setup_active(app,monkeypatch)
    seen=[]
    app.st.button=lambda label,**kw: kw.get('key')=='check_room_page_fit'
    monkeypatch.setattr(app,'render_print_fit',lambda sheets,target:seen.append((len(sheets),target)))
    app.handoff_page(None)
    assert seen==[(1,1)]


@pytest.mark.parametrize('section', ['Diagnoses','Neurologic','Respiratory','Cardiovascular','FEN / GI','Hematology','Infectious Disease'])
def test_notes_survive_tab_cleanup_and_room_autosave(app,monkeypatch,section):
    open_room(app)
    ss=app.st.session_state
    sheet=ss['drafts']['P4102']
    key=app.edit_key(sheet,section)
    ss[key]='Synthetic edited note'
    ss['handoff_active_tab']='Edit handoff';ss['handoff_tab']='Preview / print'
    app.handoff_tab_changed()
    assert ss['drafts']['P4102']['fields'][section]=='Synthetic edited note'
    # Model the cleanup of widgets not rendered on this run.
    app.discard_editor_widget_values()
    open_room(app,'P4104')
    assert ss['vault']['rooms']['P4102']['fields'][section]=='Synthetic edited note'
    assert ss['drafts']['P4104']['fields'][section]==''
    open_room(app,'P4102')
    assert ss['drafts']['P4102']['fields'][section]=='Synthetic edited note'


def test_invalid_pending_note_blocks_tab_switch(app):
    open_room(app);ss=app.st.session_state;sheet=ss['drafts']['P4102']
    before=deepcopy(sheet)
    ss[app.edit_key(sheet,'Neurologic')]='X'*(app.MAX_FIELD+1)
    ss['handoff_active_tab']='Edit handoff';ss['handoff_tab']='Preview / print'
    app.handoff_tab_changed()
    assert ss['handoff_tab']=='Edit handoff'
    assert ss['drafts']['P4102']==before
    assert ss['notice'][0]=='error'


def test_tab_change_does_not_save_archive(app):
    open_room(app);ss=app.st.session_state
    before=deepcopy(ss['vault'])
    ss['handoff_active_tab']='Medications';ss['handoff_tab']='Alerts'
    app.handoff_tab_changed()
    assert ss['vault']==before
    assert ss['handoff_active_tab']=='Alerts'


def test_create_switches_back_to_preview(app):
    open_room(app);ss=app.st.session_state
    ss['handoff_tab']='Alerts'
    ss['paste']='aaaaaaaa\nDiagnoses:\nSynthetic\naaaaaaaa'
    app.create_handoff()
    assert ss['handoff_tab']=='Preview / print'
    assert ss['paste']==''


def test_no_inactive_editor_keys_created(app,monkeypatch):
    ss,events=setup_active(app,monkeypatch)
    app.handoff_page(None)
    assert not any(k.startswith(('field_','vent_','med_draft_','cbc_','gas_','dairway_')) for k in ss)


@pytest.mark.parametrize('kind', ['info','success','warning','error'])
def test_notices_are_session_scoped_and_escaped(kind):
    sheet=new_sheet('P4102');other=new_sheet('P4104')
    first={'current_room':'P4102','room_choice':'P4102','drafts':{'P4102':sheet},'vault':new_vault()}
    second={'current_room':'P4102','room_choice':'P4102','drafts':{'P4102':sheet},'vault':new_vault()}
    remember_notice(first,kind,'<script>alert("unsafe")</script>')
    assert alert_rows(sheet,second)==[]
    assert alert_rows(other,first)==[]
    markup=alert_lines_html(alert_rows(sheet,first))
    assert '<script>' not in markup and '&lt;script&gt;' in markup
    assert 'workspace_notices' not in first['vault']


def test_import_notices_are_quiet_but_available(app,monkeypatch):
    ss,events=setup_active(app,monkeypatch)
    ss['import_result']={'room':'P4102','errors':[],'notices':['Synthetic informational detail'],'imported':['Diagnoses']}
    app.handoff_page(None)
    assert not any(kind=='info' for kind,_,_ in events)
    assert not any('Synthetic informational detail' in text for _,text,_ in events)
    rows=alert_rows(ss['drafts']['P4102'],ss)
    assert ('info','Synthetic informational detail') in rows


def test_alerts_tab_contains_plain_lines_not_blue_boxes(app,monkeypatch):
    ss,events=setup_active(app,monkeypatch,'Alerts')
    ss['import_result']={'room':'P4102','errors':['Synthetic warning'],'notices':['Synthetic note'],'imported':['Diagnoses']}
    app.handoff_page(None)
    assert any(kind=='markdown' and 'Synthetic warning' in text and 'handoff-alert-line' in text for kind,text,_ in events)
    assert not any(kind=='info' for kind,_,_ in events)


def test_empty_alerts_tab_says_no_alerts(app,monkeypatch):
    ss,events=setup_active(app,monkeypatch,'Alerts')
    app.handoff_page(None)
    assert any('No alerts.' in text for _,text,_ in events)


@pytest.mark.parametrize('field', ['guide_load_error','error_log_notice'])
def test_operational_warnings_collected(field):
    sheet=new_sheet('P4102');ss={field:'Synthetic issue'}
    assert ('warning','Synthetic issue') in alert_rows(sheet,ss)


def test_failed_save_still_has_short_visible_status(app,monkeypatch):
    ss,events=setup_active(app,monkeypatch)
    remember_notice(ss,'error','Save was not confirmed. Network unavailable.')
    app.handoff_page(None)
    assert any('Action not completed. See Alerts.' in text for _,text,_ in events)
    assert ('error','Save was not confirmed. Network unavailable.') in alert_rows(ss['drafts']['P4102'],ss)


def test_invalid_other_room_still_visible(app,monkeypatch):
    ss,events=setup_active(app,monkeypatch)
    ss['room_choice']='Other room'
    remember_notice(ss,'error','Invalid room number.')
    app.handoff_page(None)
    assert any('Invalid room number.' in text for _,text,_ in events)


def test_conflicting_save_stays_blocked_and_reported(app,monkeypatch):
    ss,events=setup_active(app,monkeypatch)
    ss['base_sheets']['P4102'] = new_sheet('P4102')
    app.handoff_page(None)
    assert any('Saved record changed.' in text for _,text,_ in events)
    before=deepcopy(ss['vault']);app.save_room(None)
    assert ss['vault']==before and ss['notice'][0]=='error'


def test_failed_import_is_not_reported_as_success():
    sheet=new_sheet('P4102')
    ss={'import_result':{'room':'P4102','errors':['Unreadable'],'notices':[],'imported':[]}}
    assert workspace_attention(sheet,ss)=='Import not completed. See Alerts.'


def test_partial_import_keeps_details_without_falsely_claiming_total_failure():
    sheet=new_sheet('P4102')
    ss={'import_result':{'room':'P4102','errors':['Skipped'],'notices':[],'imported':['Diagnoses']}}
    assert workspace_attention(sheet,ss)==''
    assert ('warning','Skipped') in alert_rows(sheet,ss)


def test_review_buttons_still_required_to_acknowledge(app,monkeypatch):
    ss,events=setup_active(app,monkeypatch,'Alerts')
    sheet=ss['drafts']['P4102'];sheet['import_warnings']['i']=[diagnostic('i','section_parse_failed')]
    before=deepcopy(sheet);buttons=[]
    app.st.button=lambda label,**kw: buttons.append((label,kw)) or False
    app.handoff_page(None)
    assert sheet==before
    assert any(kw.get('key','').startswith('accept_import_') for _,kw in buttons)
    assert not any(kind=='warning' and text.startswith('IMPORT REVIEW') for kind,text,_ in events)


def test_import_alerts_survive_switching_rooms(app):
    open_room(app);ss=app.st.session_state
    first=ss['drafts']['P4102']
    data={'room':'P4102','errors':[],'notices':['Room-specific note'],'imported':['Diagnoses']}
    remember_import(ss,first,data)
    open_room(app,'P4104')
    assert not any('Room-specific' in text for _,text in alert_rows(ss['drafts']['P4104'],ss))
    open_room(app,'P4102')
    assert ('info','Room-specific note') in alert_rows(ss['drafts']['P4102'],ss)


def test_new_patient_cannot_inherit_previous_alerts(app):
    open_room(app);ss=app.st.session_state;old=ss['drafts']['P4102']
    remember_import(ss,old,{'room':'P4102','notices':['Old occupant'],'errors':[],'imported':[]})
    app.start_new_patient()
    assert not any('Old occupant' in text for _,text in alert_rows(ss['drafts']['P4102'],ss))


def test_clear_all_removes_ephemeral_ui_messages(app):
    open_room(app);ss=app.st.session_state;sheet=ss['drafts']['P4102']
    remember_notice(ss,'info','Old notice')
    remember_import(ss,sheet,{'room':'P4102','notices':['Old import'],'errors':[],'imported':[]})
    app.clear_all_handoffs(None)
    assert not ss.get('workspace_imports') and not ss.get('workspace_notices')
    assert ss['drafts']=={}


def test_notice_and_import_memory_is_bounded():
    ss={}
    for i in range(110):
        sheet=new_sheet('P4102')
        ss.update(current_room='P4102',room_choice='P4102',drafts={'P4102':sheet})
        remember_notice(ss,'info','Example')
        remember_import(ss,sheet,{'room':'P4102','notices':['Example'],'errors':[],'imported':[]})
    assert len(ss['workspace_notices'])==100
    assert len(ss['workspace_imports'])==100


def test_alerts_deduplicate_repeated_messages():
    sheet=new_sheet('P4102');ss={'import_result':{'room':'P4102','errors':['Same','Same'],'notices':['Same'],'imported':[]}}
    assert alert_rows(sheet,ss)==[('warning','Same')]


def test_custom_guide_not_silently_rewritten():
    guide=default_guide();guide['instructions']='Local instructions\nKeep these exactly.'
    assert compact_help(guide)==guide['instructions']
    assert len(compact_help(default_guide()))<len(DEFAULT_INSTRUCTIONS)


@pytest.mark.parametrize('elapsed,expected', [(0,False),(29,False),(31,False),(299,False),(301,True)])
def test_nonclinical_guide_refresh_throttled(app,monkeypatch,elapsed,expected):
    ss,events=setup_active(app,monkeypatch)
    now=time.monotonic();ss['handoff_guide_checked']=now-elapsed
    called=[]
    monkeypatch.setattr(app,'load_user_guide',lambda store,refresh=False: called.append(refresh) or default_guide())
    app.handoff_page(object())
    assert called==[expected]


def test_requirement_matches_stateful_tab_api(app):
    root=Path(__file__).parents[1]
    assert 'streamlit>=1.55,<2' in (root/'requirements.txt').read_text()
    assert '.open' in inspect.getsource(app.handoff_page)


def test_small_type_scoped_to_alerts_not_print():
    assert '.handoff-alert-lines { font-size: .75rem;' in COMPACT_STYLES
    assert 'iframe' not in COMPACT_STYLES
    assert '<style' in COMPACT_STYLES


def test_medication_edit_survives_lazy_cleanup_and_save(app):
    open_room(app);ss=app.st.session_state
    ss['paste']='bbbbbbbb\nMedications:\nMedication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin\n• acetaminophen\t10 mg\tOral\tq6h\tExample\t\t\nbbbbbbbb'
    app.create_handoff()
    med=ss['drafts']['P4102']['medications'][0]
    ss['med_draft_'+med['id']+'_dose']='12 mg'
    ss['handoff_active_tab']='Medications';ss['handoff_tab']='Alerts'
    app.handoff_tab_changed();app.discard_editor_widget_values();app.save_room(None)
    assert ss['vault']['rooms']['P4102']['medications'][0]['dose']=='12 mg'


def test_difficult_airway_edit_survives_lazy_cleanup(app):
    open_room(app);ss=app.st.session_state;sheet=ss['drafts']['P4102']
    prefix='dairway_'+sheet['id']+'_'
    ss[prefix+'enabled']=True
    ss[prefix+'issue']='Synthetic limited mouth opening'
    ss['handoff_active_tab']='Difficult airway';ss['handoff_tab']='Preview / print'
    app.handoff_tab_changed();app.discard_editor_widget_values();app.save_room(None)
    record=ss['vault']['rooms']['P4102']['difficult_airway']
    assert record['enabled'] and record['issue']=='Synthetic limited mouth opening'


def test_workspace_message_data_does_not_enter_archive(app):
    open_room(app);ss=app.st.session_state;sheet=ss['drafts']['P4102']
    remember_notice(ss,'info','WORKSPACE_NOTICE_SENTINEL')
    remember_import(ss,sheet,{'room':'P4102','errors':[],'notices':['WORKSPACE_IMPORT_SENTINEL'],'imported':[]})
    app.save_room(None)
    assert 'WORKSPACE_NOTICE_SENTINEL' not in str(ss['vault'])
    assert 'WORKSPACE_IMPORT_SENTINEL' not in str(ss['vault'])


def test_success_after_failed_action_replaces_old_notice(app):
    open_room(app);ss=app.st.session_state;sheet=ss['drafts']['P4102']
    remember_notice(ss,'error','Save failed')
    assert workspace_attention(sheet,ss)
    remember_notice(ss,'success','Saved')
    assert workspace_attention(sheet,ss)==''
    assert alert_rows(sheet,ss)==[('success','Saved')]


def test_failed_reset_keeps_alerts_and_drafts(app):
    from github_store import StorageError
    open_room(app);ss=app.st.session_state;sheet=ss['drafts']['P4102']
    remember_import(ss,sheet,{'room':'P4102','notices':['Keep me'],'errors':[],'imported':[]})
    before=deepcopy(ss['drafts']);records=deepcopy(ss['workspace_imports'])
    class Failing:
        def save(self,*a,**k): raise StorageError('Synthetic offline')
    app.clear_all_handoffs(Failing())
    assert ss['drafts']==before and ss['workspace_imports']==records


def test_signout_discards_new_ui_state(app):
    open_room(app);ss=app.st.session_state;sheet=ss['drafts']['P4102']
    remember_import(ss,sheet,{'room':'P4102','notices':['Delete me'],'errors':[],'imported':[]})
    remember_notice(ss,'error','Delete me too')
    app.clear_session()
    assert not ss


def test_import_log_is_snapshot_not_mutable_external_reference():
    sheet=new_sheet('P4102');ss={}
    result={'room':'P4102','notices':['Original'],'errors':[],'imported':[],'raw_text':'NEVER_KEEP'}
    remember_import(ss,sheet,result);result['notices'][0]='Changed'
    stored=current_import(sheet,ss)
    assert stored['notices']==['Original']
    assert 'NEVER_KEEP' not in str(ss)


def test_input_remains_present_on_every_tab(app,monkeypatch):
    for tab in WORKSPACE_TABS:
        ss,events=setup_active(app,monkeypatch,tab)
        labels=[];old=app.st.text_area
        app.st.text_area=lambda label,*a,**kw: labels.append(label) or old(label,*a,**kw)
        app.handoff_page(None)
        assert labels.count('SmartPhrase text')==1


@pytest.mark.parametrize('key',['room_print_target','all_print_target'])
def test_print_target_survives_inactive_widget_cleanup(app,monkeypatch,key):
    equip(app,monkeypatch);ss=app.st.session_state
    ss[key]=2
    assert app.print_target_control(key)==2
    ss.pop(key)
    equip(app,monkeypatch)
    assert app.print_target_control(key)==2
    assert ss['workspace_'+key]==2
