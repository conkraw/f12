"""6.42 regressions. Synthetic data only. No live storage or clinical validation."""
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo
import json
import pytest
from pypdf import PdfReader
from cryptography.fernet import Fernet
from categories import *
from medication_groups import automatic_group
from fen_gi import effective_section
from models import new_sheet, new_vault, validate_sheet, validate_vault, upgrade_vault, fields_with_medications
from medications import validate_medication
from exports import handoff_html, handoff_text, handoff_pdf, handoffs_pdf
from lab_windows import display_clock
from labs import parse_labs
from security import seal_vault, open_vault
from test_rooms_infusions import med
from test_callbacks import app, open_room
from test_workflow_print import Store
from github_store import StorageError, ConflictError
from category_ui import local_target
from batching import available_handoffs

NOW=datetime(2026,11,8,22,0,tzinfo=ZoneInfo('America/New_York'))
DEFAULTS=[('dexamethasone','airway_cerebral_steroid','Intravenous'),
          ('albuterol','beta_agonist','Nebulization'), ('ipratropium','anticholinergic','Nebulization'),
          ('aminophylline','methylxanthine','Intravenous'), ('methylprednisolone','corticosteroid','Intravenous'),
          ('prednisone','corticosteroid','Oral'), ('prednisolone','corticosteroid','Per G Tube'),
          ('bethanechol','airway_tone','Per NJ Tube'), ('budesonide','inhaled_corticosteroid','Nebulization'),
          ('fluticasone','inhaled_corticosteroid','Inhalation'), ('mometasone','inhaled_corticosteroid','Inhalation'),
          ('sildenafil','pulmonary_hypertension','Per NJ Tube')]

@pytest.mark.parametrize('name,expected,route',DEFAULTS)
@pytest.mark.parametrize('prefix',['','[START ON 11/9/2026] ','[Held by provider] ','Followed by: '])
def test_defaults_exact_single_destination_source_unchanged(name,expected,route,prefix):
    row=med(prefix+name.upper()+' product', '2 mg', route,'q6h',rate='',section='Other Medications')
    before=deepcopy(row)
    assert automatic_group(row)==expected and effective_section(row)=='Respiratory'
    blocks=medication_blocks('Respiratory','',[row])
    assert sum(isinstance(x,dict) and x['id']==row['id'] for _,x in blocks)==1
    assert not medication_blocks('Neurologic','',[row]) and row==before

@pytest.mark.parametrize('name,route',[
    ('budesonide oral capsule','Oral'), ('mometasone cream','Topical'),
    ('fluticasone nasal spray','Nasal'), ('dexamethasone ophthalmic','Ophthalmic'),
    ('prednisolone eye drops','Ophthalmic'), ('mometasone otic','Otic'),
    ('budesonide-formoterol inhaler','Inhalation'),('ipratropium-albuterol nebulizer','Nebulization'),
    ('albuterolin fake','Nebulization')])
def test_nonmatching_products_not_silently_recategorized(name,route):
    row=med(name, route=route,frequency='Daily',section='Other Medications')
    assert not automatic_group(row)


def configured():
    settings=new_vault()['settings']
    settings=save_category(settings,'Bronchodilators','Respiratory',ident='custom:parent')
    settings=save_category(settings,'Short acting','Respiratory',parent='custom:parent',ident='custom:child')
    return settings


def test_category_and_subcategory_one_order_once_all_exports():
    settings=configured()
    settings=set_category_rule(settings,'albuterol','custom:child')
    s=new_sheet('P4102');s['medications']=apply_category_rules([med('albuterol test',route='Nebulization',frequency='q4h')],settings)
    before=deepcopy(s)
    for output in (handoff_text(s),handoff_html(s),PdfReader(BytesIO(handoff_pdf(s))).pages[0].extract_text()):
        assert output.count('albuterol test')==1
        assert 'Bronchodilators' in output and 'Short acting' in output
        assert 'Beta-Agonist' not in output
    assert s==before


def test_definition_rename_and_parent_move_keep_medication_once():
    settings=configured();settings=set_category_rule(settings,'albuterol','custom:child')
    row=med('albuterol test',route='Nebulization',frequency='q6h')
    row=apply_category_rules([row],settings)[0]
    settings=save_category(settings,'New parent','Cardiovascular',ident='custom:parent',order=70)
    updated=apply_category_rules([row],settings)[0]
    assert updated['category_path']['parent_name']=='New parent'
    assert effective_section(updated)=='Cardiovascular'
    assert not medication_blocks('Respiratory','',[updated])
    blocks=medication_blocks('Cardiovascular','',[updated])
    assert blocks[0]==('heading','New parent') and blocks[1]==('subheading','Short acting')
    assert all(updated[k]==row[k] for k in row if k!='category_path')


def test_modifying_builtin_category_changes_default_without_new_rule():
    s=new_vault()['settings'];s=save_category(s,'Airway / Cerebral','Neurologic',ident='group:airway_cerebral_steroid')
    r=apply_category_rules([med('dexamethasone',frequency='q6h')],s)[0]
    assert effective_section(r)=='Neurologic' and r['category_path']['name']=='Airway / Cerebral'


@pytest.mark.parametrize('bad', [
    {'name':''}, {'name':'a\nb'}, {'name':'x'*81}, {'section':'bad'}, {'order':-1},
    {'order':1000},{'order':True},{'parent':'missing'}, {'parent':'custom:child'},])
def test_invalid_definitions_leave_settings_untouched(bad):
    settings=configured();before=deepcopy(settings)
    kwargs=dict(name='New',section='Respiratory',parent='',ident='custom:new',order=100);kwargs.update(bad)
    with pytest.raises(ValueError):save_category(settings,**kwargs)
    assert settings==before


def test_no_cycles_duplicates_or_third_level():
    settings=configured()
    for kwargs in [dict(name='Bronchodilators',section='Respiratory'),
        dict(name='Loop',section='Respiratory',ident='custom:parent',parent='custom:child'),
        dict(name='Third',section='Respiratory',parent='custom:child')]:
        with pytest.raises(ValueError):save_category(settings,**kwargs)


def test_delete_checks_rules_children_and_builtins():
    settings=configured()
    with pytest.raises(ValueError):delete_category(settings,'custom:parent')
    with pytest.raises(ValueError):delete_category(settings,'group:beta_agonist')
    settings=set_category_rule(settings,'albuterol','custom:child')
    with pytest.raises(ValueError):delete_category(settings,'custom:child')
    settings=set_category_rule(settings,'albuterol','auto')
    settings=delete_category(settings,'custom:child');settings=delete_category(settings,'custom:parent')
    assert not any(c['id'].startswith('custom:') for c in catalog(settings))


def test_single_rule_replaces_prior_target_and_more_specific_wins():
    settings=configured();settings=set_category_rule(settings,'albuterol','custom:parent')
    settings=set_category_rule(settings,'ALBUTEROL','custom:child')
    assert len(settings['medication_category_rules'])==1
    settings=set_category_rule(settings,'albuterol test','group:anticholinergic','exact','Nebulization','q4h')
    a=med('albuterol test',route='Nebulization',frequency='q4h')
    b=med('albuterol test',route='Nebulization',frequency='q4h PRN')
    rows=apply_category_rules([a,b],settings)
    assert rows[0]['category_path']['id']=='group:anticholinergic'
    assert rows[1]['category_path']['id']=='custom:child'
    blocks=medication_blocks('Respiratory','',rows)
    assert sum(isinstance(x,dict) for _,x in blocks)==2


def test_longest_prefix_route_frequency_exact_and_empty_filter():
    settings=configured()
    for name,target,route,freq in [('albuterol','custom:parent','',''),
        ('albuterol HFA','custom:child','',''),('albuterol HFA','group:beta_agonist','Inhalation','q6h')]:
        settings=set_category_rule(settings,name,target,route=route,frequency=freq)
    assert matching_target(med('albuterol HFA test',route='Inhalation',frequency='q6h'),settings)=='group:beta_agonist'
    assert matching_target(med('albuterol HFA test',route='Inhalation',frequency='q4h'),settings)=='custom:child'
    assert matching_target(med('albuterolin'),settings)==''


def test_uncategorized_system_assignment_disables_legacy_group():
    settings=set_category_rule(new_vault()['settings'],'dexamethasone','system:Neurologic')
    row=apply_category_rules([med('dexamethasone',frequency='q6h')],settings)[0]
    assert effective_section(row)=='Neurologic'
    assert all(k!='heading' for k,_ in medication_blocks('Neurologic','',[row]))
    assert not medication_blocks('Respiratory','',[row])


@pytest.mark.parametrize('field,value',[('hidden',True),('include',False)])
def test_mapping_never_restores_hidden_or_excluded(field,value):
    settings=configured();settings=set_category_rule(settings,'albuterol','custom:child')
    r=med('albuterol test');r[field]=value
    s=new_sheet('P4102');s['medications']=apply_category_rules([r],settings)
    assert 'albuterol test' not in handoff_text(s) and 'Short acting' not in handoff_html(s)


def test_safe_html_labels_and_preserved_rate_emphasis():
    settings=save_category(new_vault()['settings'],'<script>Label</script>','Respiratory',ident='custom:x')
    settings=set_category_rule(settings,'albuterol','custom:x')
    r=med('albuterol continuous',dose='4 mg/hr',route='Nebulization',frequency='Continuous',rate='1 mL/hr')
    s=new_sheet('P4102');s['medications']=apply_category_rules([r],settings)
    text=handoff_html(s)
    assert '<script>Label</script>' not in text and '&lt;script&gt;Label&lt;/script&gt;' in text
    assert '<b>albuterol continuous</b>' in text and '<b><u>' in text


def level_sheet():
    s=new_sheet('P4102');s['labs']=parse_labs('LABS:\nComponent\tValue\tDate\nTHEOPH\t8.2 (L)\t11/08/2026 1200').data
    s['medications']=[med('aminophylline FIRST',dose='5 mg',frequency='q12h',rate='',section='Other Medications'),
                      med('aminophylline SECOND',dose='2 mg',frequency='q24h',rate='',section='Other Medications'),
                      med('albuterol INHALER',dose='2 puff',route='Inhalation',frequency='q6h',rate='',section='Other Medications')]
    return s


@pytest.mark.parametrize('fmt',['text','html','pdf'])
def test_theophylline_once_directly_under_first_visible_drug(fmt):
    s=level_sheet();before=deepcopy(s)
    with display_clock(NOW):
        value={'text':handoff_text,'html':handoff_html,'pdf':handoff_pdf}[fmt](s)
    if isinstance(value,bytes):value='\n'.join(p.extract_text() for p in PdfReader(BytesIO(value)).pages)
    assert value.count('Theophylline level:')==1
    assert value.index('FIRST') < value.index('Theophylline level:') < value.index('SECOND')
    assert '8.2 (L)' in value and s==before


@pytest.mark.parametrize('hidden',[False,True])
def test_theophylline_missing_stale_or_hidden_not_recreated(hidden):
    s=level_sheet()
    for row in s['medications']:row['hidden']=hidden
    with display_clock(NOW):
        text=handoff_text(s)
        assert text.count('Theophylline level:')==1
        if hidden:assert not theophylline_anchor(s)
    s['labs']['rows'][0]['date']='11/01/2026'
    with display_clock(NOW):assert 'Theophylline level:' not in handoff_text(s)
    s['labs']['rows']=[]
    with display_clock(NOW):assert 'Theophylline level:' not in handoff_text(s)


def test_level_follows_drug_to_subcategory_and_not_to_another_room():
    settings=configured();settings=set_category_rule(settings,'aminophylline','custom:child')
    a=level_sheet();a['medications']=apply_category_rules(a['medications'],settings)
    b=new_sheet('P4104');b['medications']=[med('aminophylline NO_RESULT',frequency='q12h')]
    with display_clock(NOW):
        pdf=PdfReader(BytesIO(handoffs_pdf([a,b])))
    assert len(pdf.pages)==2 and pdf.pages[0].extract_text().count('Theophylline level:')==1
    assert 'Theophylline level:' not in pdf.pages[1].extract_text()


def test_encrypted_roundtrip_and_original26_migration_preserve_source():
    original=new_vault();original['schema']=26;original['rooms']['P4102']=level_sheet()
    before=deepcopy(original);key=Fernet.generate_key().decode()
    token=Fernet(key.encode()).encrypt(json.dumps(original).encode())
    restored=open_vault(token,key)
    assert restored['schema']==33 and restored['rooms']==before['rooms'] and original==before
    restored['settings']=configured()
    restored['settings']=set_category_rule(restored['settings'],'aminophylline','custom:child')
    restored['rooms']['P4102']['medications']=apply_category_rules(restored['rooms']['P4102']['medications'],restored['settings'])
    assert open_vault(seal_vault(restored,key),key)==restored


def test_saved_closed_rooms_get_latest_category_definitions_for_batch_print():
    v=new_vault();v['rooms']['P4102']=level_sheet();v['settings']=configured()
    v['settings']=set_category_rule(v['settings'],'aminophylline','custom:child')
    before=deepcopy(v);s=available_handoffs(v,{})['P4102']
    assert s['medications'][0]['category_path']['name']=='Short acting' and v==before


def test_inline_category_saved_without_saving_draft_patient_fields(app):
    open_room(app);ss=app.st.session_state;r=med('albuterol synthetic',route='Nebulization',frequency='q6h')
    ss['drafts']['P4102']['medications']=[r];ss['drafts']['P4102']['fields']['Other']='UNSAVED_SENTINEL'
    ss['selection']='group:beta_agonist';store=Store()
    app.medication_category_change('P4102',r['id'],'selection',store)
    assert ss['vault']['settings']['medication_category_rules'][0]['target']=='group:beta_agonist'
    assert store.calls[0][0]['rooms']=={} and 'UNSAVED_SENTINEL' not in str(store.calls[0][0])
    assert local_target(ss['drafts']['P4102']['medications'][0],ss['vault']['settings'])=='group:beta_agonist'
    assert effective_section(ss['drafts']['P4102']['medications'][0])=='Respiratory'


@pytest.mark.parametrize('error',[StorageError('Offline'),ConflictError('Changed elsewhere')])
def test_failed_inline_category_write_retains_all_drafts_and_settings(app,error):
    open_room(app);ss=app.st.session_state;r=med('aminophylline',frequency='q12h')
    ss['drafts']['P4102']['medications']=[r];before=deepcopy(ss['drafts']);vault=deepcopy(ss['vault']);ss['selection']='group:methylxanthine'
    app.medication_category_change('P4102',r['id'],'selection',Store(error))
    assert ss['drafts']==before and ss['vault']==vault and ss['selection']=='auto'


def test_renaming_medication_does_not_keep_previous_assignment(app):
    open_room(app);ss=app.st.session_state;r=med('aminophylline test',frequency='q12h')
    ss['vault']['settings']=set_category_rule(ss['vault']['settings'],r['name'],'group:methylxanthine','exact',r['route'],r['frequency'])
    ss['drafts']['P4102']['medications']=apply_category_rules([r],ss['vault']['settings'])
    ss['rename']='unmapped new product'
    app.medication_row_change('P4102',r['id'],'name','rename')
    assert 'category_path' not in ss['drafts']['P4102']['medications'][0]


def test_nesting_builtin_category_reuses_its_automatic_drug_rules():
    settings=save_category(new_vault()['settings'],'Bronchodilators','Respiratory',ident='custom:b')
    settings=save_category(settings,'Beta-Agonist','Respiratory',parent='custom:b',ident='group:beta_agonist',order=10)
    r=apply_category_rules([med('albuterol',route='Nebulization',frequency='q4h')],settings)[0]
    assert not settings.get('medication_category_rules')
    assert r['category_path']['parent_name']=='Bronchodilators'
    b=medication_blocks('Respiratory','',[r])
    assert b[:2]==[('heading','Bronchodilators'),('subheading','Beta-Agonist')]


def test_admin_definition_callback_saves_and_requires_admin_again(app,monkeypatch):
    from test_ui_smoke import equip
    from category_ui import category_admin
    equip(app,monkeypatch)
    callbacks={}
    def capture(label,**kw):callbacks[label]=kw;return False
    monkeypatch.setattr(app.st,'form_submit_button',capture)
    category_admin(None,app.require_admin,app.commit,app.reapply_open_mappings,app.note)
    ss=app.st.session_state
    ss.update(category_edit_name='New test category',category_edit_section='Hematology',category_edit_parent='',category_edit_order=100)
    save=callbacks['Save category'];save['on_click'](*save['args'])
    assert any(c['name']=='New test category' for c in catalog(ss['vault']['settings']))
    before=deepcopy(ss['vault']);ss['admin_unlocked']=False
    ss.update(category_edit_name='Blocked change',category_edit_section='Respiratory',category_edit_parent='',category_edit_order=20)
    save['on_click'](*save['args'])
    assert ss['vault']==before


def test_admin_mapping_callback_replaces_target_and_does_not_need_open_room(app,monkeypatch):
    from test_ui_smoke import equip
    from category_ui import category_admin
    equip(app,monkeypatch);callbacks={}
    def capture(label,**kw):callbacks[label]=kw;return False
    monkeypatch.setattr(app.st,'form_submit_button',capture)
    category_admin(None,app.require_admin,app.commit,app.reapply_open_mappings,app.note)
    ss=app.st.session_state
    ss.update(category_rule_name='test medicine',category_rule_match='prefix',category_rule_route='',category_rule_frequency='',category_rule_target='group:beta_agonist')
    save=callbacks['Save category assignment'];save['on_click'](*save['args'])
    assert len(ss['vault']['settings']['medication_category_rules'])==1 and ss['drafts']=={}
    ss.update(category_rule_name='test medicine',category_rule_match='prefix',category_rule_route='',category_rule_frequency='',category_rule_target='group:methylxanthine')
    save['on_click'](*save['args'])
    assert len(ss['vault']['settings']['medication_category_rules'])==1
    assert ss['vault']['settings']['medication_category_rules'][0]['target']=='group:methylxanthine'


def test_shared_category_callback_failure_keeps_definitions_and_all_patient_rows(app,monkeypatch):
    from test_ui_smoke import equip
    from category_ui import category_admin
    equip(app,monkeypatch);callbacks={}
    def capture(label,**kw):callbacks[label]=kw;return False
    monkeypatch.setattr(app.st,'form_submit_button',capture)
    category_admin(Store(StorageError('Offline')),app.require_admin,app.commit,app.reapply_open_mappings,app.note)
    ss=app.st.session_state;before=deepcopy(ss['vault'])
    ss.update(category_edit_name='Not saved',category_edit_section='Respiratory',category_edit_parent='',category_edit_order=10)
    save=callbacks['Save category'];save['on_click'](*save['args'])
    assert ss['vault']==before and ss['notice'][0]=='error'
