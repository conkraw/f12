"""Version 6.11 regressions. Synthetic data only; storage callbacks use a fake store."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
import re
import uuid
import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader
from test_callbacks import app, open_room
from test_ui_smoke import equip
from models import (DEFAULT_ROOMS, PRESET_NUMBERS, SCHEMA_VERSION, new_vault, new_sheet,
                    normalize_room, save_sheet_in, upgrade_vault, validate_vault,
                    fields_with_medications, ValidationError)
from infusions import (is_infusion, set_infusion_rule, validate_infusion_rules,
                       apply_infusion_rules, neuro_body, infusion_entry, infusion_key)
from medications import parse_medications, validate_medication, upsert_rule
from importing import import_sections
from batching import available_handoffs
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from security import open_vault, seal_vault
from github_store import StorageError


def med(name='Example medicine infusion',dose='1.2 mcg/kg/hr (Dosing Weight)',route='Intravenous',frequency='Continuous',rate='3.48 mL/hr',section='Neurologic'):
    row={'id':uuid.uuid4().hex,'name':name,'dose':dose,'route':route,'frequency':frequency,
         'last_rate':rate,'rate_time':'01/02/2026 1000','custom_text':'','section':section,
         'include':True,'hidden':False,'warnings':[]}
    validate_medication(row)
    return row


@pytest.mark.parametrize('number', PRESET_NUMBERS)
def test_each_preset_alias_has_capital_p(number):
    assert normalize_room(number)==normalize_room('p'+number)==normalize_room('P'+number)=='P'+number
    assert 'P'+number in DEFAULT_ROOMS


@pytest.mark.parametrize('room', ['4307','P4307','TEST-1','OVERFLOW 2'])
def test_custom_names_are_not_rewritten_as_other_beds(room):
    assert normalize_room(room.lower())==room


def legacy_ten():
    v=new_vault();v['schema']=10;v.pop("reset_generation", None);v["settings"].pop("medication_groups", None);v["settings"].pop("medication_gi_groups", None);v['settings'].pop('medication_infusions')
    v['settings']['rooms']=['P4102','4201','4213','4307']
    s=new_sheet('P4201');s.pop("feeds", None);s.pop("devices", None);s.pop("neuro_devices", None);s.pop("pacemaker", None);s.pop("diet", None);s.pop("import_warnings", None);s.pop("intake_output", None);s.pop("recurring_orders", None);s.pop("cbc", None);s.pop('blood_gas');s['room']='4201';s['fields']['Diagnoses']='SYNTHETIC old record'
    s['medications']=[med()]
    v['rooms']['4201']=s
    v['settings']['medication_mappings']=upsert_rule([],'example','Neurologic')
    return v


def test_preset_key_upgrade_preserves_entire_sheet_except_room_and_original_input():
    old=legacy_ten();before=deepcopy(old);new=upgrade_vault(old)
    assert old==before and new['schema']==SCHEMA_VERSION==34
    assert new['settings']['rooms']==['P4102','P4201','P4213','4307']
    assert new['rooms']['P4201']==dict(old['rooms']['4201'],room='P4201',blood_gas=None,cbc=None,recurring_orders=None,intake_output=None,import_warnings={},feeds=None,devices=None,neuro_devices=None,pacemaker=None,diet=None)
    assert new['settings']['medication_mappings']==old['settings']['medication_mappings']
    validate_vault(new)


def test_old_archive_decrypts_with_same_key_and_new_room_labels():
    old=legacy_ten();key=Fernet.generate_key().decode()
    token=Fernet(key.encode()).encrypt(json.dumps(old).encode())
    new=open_vault(token,key)
    assert new==upgrade_vault(old)
    assert open_vault(seal_vault(new,key),key)==new


def test_duplicate_preset_alias_sheets_do_not_silently_merge():
    old=legacy_ten();old['rooms']['P4201']=new_sheet('P4201');old['rooms']['P4201'].pop("feeds", None);old['rooms']['P4201'].pop("devices", None);old['rooms']['P4201'].pop("neuro_devices", None);old['rooms']['P4201'].pop("pacemaker", None);old['rooms']['P4201'].pop("diet", None);old['rooms']['P4201'].pop("import_warnings", None);old['rooms']['P4201'].pop("intake_output", None);old['rooms']['P4201'].pop("recurring_orders", None);old['rooms']['P4201'].pop("cbc", None);old['rooms']['P4201'].pop('blood_gas');before=deepcopy(old)
    with pytest.raises(ValidationError,match='aliases'):
        upgrade_vault(old)
    assert old==before


def test_session_room_upgrade_renames_selection_drafts_and_bases(app):
    ss=app.st.session_state;v=legacy_ten();saved=deepcopy(v['rooms']['4201'])
    draft=deepcopy(saved);draft['fields']['Tasks']='UNSAVED'
    ss.update(vault=v,current_room='4201',room_choice='4201',drafts={'4201':draft},base_sheets={'4201':saved},admin_rooms='4201')
    app.upgrade_existing_session()
    assert ss['current_room']==ss['room_choice']=='P4201'
    assert ss['drafts']['P4201']['fields']['Tasks']=='UNSAVED'
    assert ss['base_sheets']['P4201']==ss['vault']['rooms']['P4201']
    assert 'admin_rooms' not in ss
    app.save_room(None)
    assert ss['vault']['rooms']['P4201']['fields']['Tasks']=='UNSAVED'


class Store:
    def __init__(self,fail=False): self.saved=None;self.fail=fail
    def save(self,candidate,sha):
        if self.fail:raise StorageError('Synthetic failure')
        self.saved=deepcopy(candidate);return 'confirmed-sha'


def custom(app):
    open_room(app,'4307');ss=app.st.session_state
    ss['drafts']['4307']['fields']['Diagnoses']='SYNTHETIC custom handoff'
    app.save_room(None)
    return ss


def test_remove_custom_clears_saved_draft_print_choices_without_touching_rules(app):
    ss=custom(app);ss['vault']['settings']['medication_mappings']=upsert_rule([],'example','Neurologic')
    ss['print_rooms']=['4307'];ss['print_room_options']=['4307'];store=Store()
    app.remove_custom_room('4307',store)
    assert '4307' not in ss['vault']['rooms'] and '4307' not in ss['drafts']
    assert '4307' not in ss['base_sheets'] and 'current_room' not in ss
    assert ss['room_choice']=='Choose a room' and ss['paste']==''
    assert not available_handoffs(ss['vault'],ss['drafts'])
    assert 'print_rooms' not in ss and ss['removed_room']['room']=='4307'
    assert store.saved['settings']['medication_mappings'][0]['name']=='example'
    app.save_all_rooms(store)
    assert '4307' not in ss['vault']['rooms']


def test_remove_inactive_custom_keeps_other_room_open(app):
    ss=custom(app);open_room(app,'P4102');ss['paste']='UNSUBMITTED'
    app.remove_custom_room('4307',None)
    assert ss['current_room']=='P4102' and ss['paste']=='UNSUBMITTED'
    assert ss['drafts']['P4102']['room']=='P4102'


def test_remove_configuration_only_custom_room(app):
    ss=app.st.session_state;ss['vault']['settings']['rooms'].append('OVERFLOW')
    app.remove_custom_room('OVERFLOW',None)
    assert 'OVERFLOW' not in app.custom_room_names()
    app.undo_room_removal(None)
    assert 'OVERFLOW' in ss['vault']['settings']['rooms']


def test_preset_cannot_be_removed_through_custom_control(app):
    open_room(app,'4201');ss=app.st.session_state;before=deepcopy(ss['drafts'])
    app.remove_custom_room('4201',None)
    assert ss['drafts']==before and 'P4201' in ss['vault']['settings']['rooms']
    assert ss['notice'][0]=='error'


def test_failed_delete_keeps_draft_widgets_and_saved_record(app):
    ss=custom(app);before=deepcopy(ss['vault']);key=app.edit_key(ss['drafts']['4307'],'Tasks');ss[key]='PENDING'
    app.remove_custom_room('4307',Store(True))
    assert ss['vault']==before and ss['current_room']=='4307' and ss[key]=='PENDING'
    assert 'removed_room' not in ss and ss['notice'][0]=='error'


def test_remove_refuses_known_changed_saved_record(app):
    ss=custom(app);ss['vault']['rooms']['4307']['fields']['Tasks']='Other session'
    app.remove_custom_room('4307',None)
    assert '4307' in ss['vault']['rooms'] and ss['notice'][0]=='error'


def test_undo_restores_saved_and_pending_edit_separately(app):
    ss=custom(app);saved=deepcopy(ss['vault']['rooms']['4307'])
    ss[app.edit_key(ss['drafts']['4307'],'Tasks')]='Pending edit'
    app.remove_custom_room('4307',None);app.undo_room_removal(None)
    assert ss['vault']['rooms']['4307']==saved
    assert ss['drafts']['4307']['fields']['Tasks']=='Pending edit'
    open_room(app,'4307');app.save_room(None)
    assert ss['vault']['rooms']['4307']['fields']['Tasks']=='Pending edit'


def test_undo_does_not_overwrite_readded_room(app):
    ss=custom(app);app.remove_custom_room('4307',None);open_room(app,'4307')
    ss['drafts']['4307']['fields']['Tasks']='New occupant'
    app.undo_room_removal(None)
    assert ss['drafts']['4307']['fields']['Tasks']=='New occupant' and ss['notice'][0]=='error'


def test_undo_failed_storage_keeps_recovery_available(app):
    ss=custom(app);app.remove_custom_room('4307',None);app.undo_room_removal(Store(True))
    assert 'removed_room' in ss and '4307' not in ss['vault']['rooms']


@pytest.mark.parametrize('route',['Intravenous','IV','Intra-arterial','Epidural','Subcutaneous'])
def test_continuous_parenteral_order_is_automatic_infusion(route):
    assert is_infusion(med(route=route))


@pytest.mark.parametrize('frequency',['q30 min PRN','q6h','Once','Continuous PRN',''])
def test_product_name_and_pump_rate_do_not_make_bolus_infusion(frequency):
    assert not is_infusion(med(name='Example NCS infusion syringe',frequency=frequency))


@pytest.mark.parametrize('route',['Nebulization','Oral','Per NJ Tube',''])
def test_nonparenteral_or_missing_route_is_not_automatic_infusion(route):
    assert not is_infusion(med(route=route))


def test_manual_override_and_reset_are_explicit():
    row=med(frequency='');row['infusion_mode']='infusion';assert is_infusion(row)
    row['infusion_mode']='other';assert not is_infusion(row)
    row['infusion_mode']='auto';assert not is_infusion(row)
    row['infusion_mode']='unexpected'
    with pytest.raises(ValueError):validate_medication(row)


def test_override_rule_never_copies_doses_or_rate_and_keeps_prn_separate():
    row=med();rules=set_infusion_rule([],row,'other')
    changed=med(dose='0.4 mcg/kg/hr',rate='1 mL/hr');bolus=med(frequency='q30 min PRN',dose='20 mcg')
    applied=apply_infusion_rules([changed,bolus],rules)
    assert applied[0]['infusion_mode']=='other' and applied[0]['dose']=='0.4 mcg/kg/hr'
    assert applied[0]['last_rate']=='1 mL/hr' and applied[1].get('infusion_mode','auto')=='auto'
    assert set_infusion_rule(rules,row,'auto')==[]
    assert set(rules[0])=={'name','route','frequency','mode'}


def test_invalid_rule_duplicate_rejected():
    rules=set_infusion_rule([],med(),'infusion')
    with pytest.raises(ValueError):validate_infusion_rules(rules+rules)


def test_infusion_group_below_neuro_vitals_above_notes_and_other_meds():
    s=new_sheet('P4102');s['neuro_vitals']['k']=[{'label':'Target Arousal Level (SBS)','value':'SBS -1','system':'Neurologic','include':True}]
    # Build observations with the actual parser, so tests do not guess row schemas.
    from observations import parse_neuro
    s['neuro_vitals']['k']=parse_neuro('Target Arousal Level:\nTarget Arousal Level (SBS): SBS -1','k').rows
    s['fields']['Neurologic']='NOTE_SENTINEL'
    s['medications']=[med(name='BOLUS',frequency='q30 min PRN'),med(name='INFUSION_NAME')]
    text=fields_with_medications(s)['Neurologic']
    assert 'Target Arousal' not in text
    assert text.index('CAPD:')<text.index('Infusions')<text.index('INFUSION_NAME')<text.index('NOTE_SENTINEL')<text.index('Other Medications')<text.index('BOLUS')
    html=handoff_html(s)
    assert '<b>INFUSION_NAME</b>' in html and '<b><u>Dose: 1.2 mcg/kg/hr</u></b>' in html
    assert 'Recorded rate: 3.48 mL/hr' in html
    assert 'Infusions' in handoff_text(s)


def test_other_systems_not_grouped_and_hidden_infusions_not_printed():
    s=new_sheet('P4102');s['medications']=[med(name='HIDDEN_MARKER'),med(name='CARDIAC_MARKER',section='Cardiovascular')]
    s['medications'][0]['hidden']=True
    assert 'HIDDEN_MARKER' not in handoff_html(s) and '\nInfusions\n' not in handoff_text(s) and 'CV Infusions' in handoff_text(s)
    assert 'CARDIAC_MARKER' in handoff_text(s)


def test_preserve_held_future_custom_and_empty_dose():
    r=med(name='[Held by provider] [START ON 1/2/2026] Example')
    assert '[Held by provider]' in infusion_entry(r,True) and '[START ON' not in infusion_entry(r)
    assert '[START ON 1/2/2026]' in r['name']
    r['dose']='';out=infusion_entry(r,True)
    assert 'Dose:' not in out and '<b><u>Recorded rate: 3.48 mL/hr</u></b>' in out
    r['custom_text']='CUSTOM <script>unsafe</script>'
    out=infusion_entry(r,True)
    assert '<script>' not in out and '&lt;script&gt;' in out and 'Recorded rate:' not in out


def test_pdf_text_and_bold_name_are_present_with_separate_dose_and_rate():
    import fitz
    s=new_sheet('P4201');s['medications']=[med(name='SYNTHETICDRIP')]
    data=handoff_pdf(s);doc=fitz.open(stream=data,filetype='pdf')
    assert len(doc)==1
    spans=[span for block in doc[0].get_text('dict')['blocks'] if 'lines' in block for line in block['lines'] for span in line['spans']]
    assert any('SYNTHETICDRIP' in span['text'] and 'Bold' in span['font'] for span in spans)
    text=' '.join(p.extract_text() for p in PdfReader(BytesIO(data)).pages)
    assert 'Dose:' in text and 'Recorded rate:' in text and 'P4201' in text


def test_long_infusion_content_not_clipped():
    s=new_sheet('P4102');s['medications']=[med(name=f'SYNTHETIC_{i}_MEDICATION',dose='0.7 mcg/kg/hr') for i in range(35)]
    data=handoff_pdf(s);reader=PdfReader(BytesIO(data));text=' '.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages)>1
    for i in range(35):assert f'SYNTHETIC_{i}_MEDICATION' in re.sub(r'\s+', '', text)


def test_manual_choice_callback_saves_rule_and_reimports_it(app):
    open_room(app);ss=app.st.session_state;row=med();ss['drafts']['P4102']['medications']=[row]
    ss['inf_choice']='other';store=Store()
    app.medication_row_change('P4102',row['id'],'infusion_mode','inf_choice',store)
    assert store.saved['rooms']=={} and store.saved['settings']['medication_infusions'][0]['mode']=='other'
    assert not is_infusion(ss['drafts']['P4102']['medications'][0])
    ss['paste']='bbbbbbbb\nMedications:\n• Example medicine infusion\t0.3 mcg/kg/hr\tIntravenous\tContinuous\nbbbbbbbb'
    app.create_handoff();r=ss['drafts']['P4102']['medications'][0]
    assert r['dose']=='0.3 mcg/kg/hr' and r['infusion_mode']=='other'


def test_failed_infusion_choice_does_not_move_order(app):
    open_room(app);ss=app.st.session_state;row=med();ss['drafts']['P4102']['medications']=[row];ss['choice']='other'
    before=deepcopy(row)
    app.medication_row_change('P4102',row['id'],'infusion_mode','choice',Store(True))
    assert ss['drafts']['P4102']['medications'][0]==before
    assert ss['choice']=='auto' and ss['vault']['settings']['medication_infusions']==[]


def test_pending_choice_is_remembered_before_room_switch(app):
    open_room(app);ss=app.st.session_state;r=med();ss['drafts']['P4102']['medications']=[r]
    ss['med_draft_'+r['id']+'_infusion_mode']='other';ss['room_choice']='P4104'
    app.open_room()
    assert ss['vault']['settings']['medication_infusions'][0]['mode']=='other'
    assert ss['vault']['rooms']['P4102']['medications'][0]['infusion_mode']=='other'


def test_manual_infusion_choice_does_not_change_destination(app):
    open_room(app);ss=app.st.session_state;r=med(section='Other Medications');ss['drafts']['P4102']['medications']=[r]
    ss['choice']='infusion';app.medication_row_change('P4102',r['id'],'infusion_mode','choice',None)
    assert ss['drafts']['P4102']['medications'][0]['section']=='Other Medications'
    assert not ss['vault']['settings']['medication_mappings']


def test_ui_new_controls_render_without_duplicate_keys(app,monkeypatch):
    ss=custom(app);ss['drafts']['4307']['medications']=[med(),med(frequency='q30 min PRN')]
    equip(app,monkeypatch);app.handoff_page(None)


def test_admin_without_handoff_can_remove_custom_and_reset_infusion(app,monkeypatch):
    ss=app.st.session_state;ss['vault']['settings']['rooms'].append('EXTRA')
    r=med();ss['vault']['settings']['medication_infusions']=set_infusion_rule([],r,'other')
    equip(app,monkeypatch);app.admin_page(None)
    app.reset_infusion_rule(infusion_key(r),None)
    assert ss['vault']['settings']['medication_infusions']==[]
    app.remove_custom_room('EXTRA',None)
    assert 'EXTRA' not in app.custom_room_names()


def test_admin_can_change_saved_choice_without_an_open_handoff(app):
    ss=app.st.session_state;r=med();ss['vault']['settings']['medication_infusions']=set_infusion_rule([],r,'other')
    ss['admin_display']='infusion'
    app.edit_saved_infusion_rule(infusion_key(r),'admin_display',None)
    assert ss['vault']['settings']['medication_infusions'][0]['mode']=='infusion'
    assert not ss['drafts']
    ss['admin_display']='auto';app.edit_saved_infusion_rule(infusion_key(r),'admin_display',None)
    assert not ss['vault']['settings']['medication_infusions']


def test_admin_choice_storage_failure_retains_old_choice(app):
    ss=app.st.session_state;r=med();ss['vault']['settings']['medication_infusions']=set_infusion_rule([],r,'other')
    ss['admin_display']='infusion';app.edit_saved_infusion_rule(infusion_key(r),'admin_display',Store(True))
    assert ss['admin_display']=='other' and ss['vault']['settings']['medication_infusions'][0]['mode']=='other'


def test_same_event_changed_frequency_does_not_inherit_old_infusion_override(app):
    open_room(app);ss=app.st.session_state;r=med();r['infusion_mode']='infusion'
    ss['vault']['settings']['medication_infusions']=set_infusion_rule([],r,'infusion')
    ss['drafts']['P4102']['medications']=[r]
    ss['med_draft_'+r['id']+'_frequency']='q30 min PRN'
    ss['med_draft_'+r['id']+'_infusion_mode']='infusion'
    snapshot=app.editor_snapshot('P4102')
    assert snapshot['medications'][0]['infusion_mode']=='auto'
    assert not is_infusion(snapshot['medications'][0])


def test_extremely_long_custom_infusion_can_continue_without_endless_pagination():
    s=new_sheet('P4102');r=med();r['custom_text']='STARTTOKEN '+('Long synthetic custom entry. '*120)+' ENDTOKEN'
    s['medications']=[r]
    pages=PdfReader(BytesIO(handoff_pdf(s))).pages
    text=''.join(p.extract_text() for p in pages)
    assert 'STARTTOKEN' in text and 'ENDTOKEN' in text and 1 <= len(pages) < 10
    # Adaptive widths can now fit this once-multipage example on one page.


def test_expired_remove_and_undo_callbacks_do_not_write(app):
    ss=custom(app);ss['authenticated']=False;store=Store()
    app.remove_custom_room('4307',store)
    assert store.saved is None


def test_empty_rule_set_still_allows_automatic_neuro_grouping_on_saved_sheet():
    s=new_sheet('P4102');s['medications']=[med()]
    assert 'Infusions' in fields_with_medications(s)['Neurologic']
    assert not new_vault()['settings']['medication_infusions']
