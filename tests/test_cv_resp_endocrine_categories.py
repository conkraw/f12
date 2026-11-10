"""v6.39: user-requested display groups and streamlined UI, synthetic data only."""
from copy import deepcopy
from pathlib import Path
import ast
import json
import re
import pytest
import fitz
from cryptography.fernet import Fernet
from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_workflow_print import Store
from test_rooms_infusions import med
from test_last_admin_antiemetics import order
from medication_groups import (automatic_group, group_for, GROUP_NAMES, GROUP_SECTIONS, MODES,
                               set_group_rule, apply_group_rules, validate_group_rules)
from fen_gi import (effective_section, group_for as gi_group, automatic_group as gi_auto,
                   set_gi_rule, apply_gi_rules, fen_gi_body)
from infusions import (system_body_blocks, is_infusion, supports_infusion_display,
                       infusion_entry, cardiovascular_body, respiratory_body)
from models import (new_sheet, new_vault, fields_with_medications, save_sheet_in,
                    validate_vault, upgrade_vault)
from exports import handoff_html, handoff_text, handoff_pdf, handoffs_pdf
from security import seal_vault, open_vault
from medications import validate_medication
from github_store import StorageError

# All names below were requested by the user. Route rules are tested separately.
DEFAULTS = [
    ('scopolamine', 'antisialorrhea'), ('glycopyrrolate', 'antisialorrhea'),
    *[(n, 'antiarrhythmic') for n in ('esmolol','amiodarone','procainamide','mexiletine',
        'flecainide','propranolol','sotalol','diltiazem','verapamil','digoxin')],
    *[(n, 'antihypertensive') for n in ('enalapril','metoprolol','amlodipine','lisinopril',
        'hydrochlorothiazide','clonidine','atenolol','carvedilol','losartan','valsartan',
        'captopril','labetalol','nifedipine','isradipine')],
    ('hydrocortisone', 'adrenocortical'),
    *[(n, 'vasodilator') for n in ('nitroglycerin','nitroglycerine','nicardipine','hydralazine','enalaprilat')],
]

@pytest.mark.parametrize('name,group', DEFAULTS)
@pytest.mark.parametrize('prefix', ['', '[START ON 01/12/2026] ', '[Held by provider] '])
def test_requested_defaults_generic_case_and_annotations(name, group, prefix):
    row = med(prefix + name.upper() + ' test formulation', dose='1 mg', route='Oral', frequency='q12h', rate='', section='Other Medications')
    before = deepcopy(row)
    assert automatic_group(row) == group
    assert effective_section(row) == GROUP_SECTIONS[group]
    assert row == before

@pytest.mark.parametrize('name,group', [
    ('lidocaine','antiarrhythmic'), ('milrinone','inotrope'), ('dobutamine','inotrope'),
    ('epinephrine','inotrope'), ('dopamine','inotrope'), ('norepinephrine','vasopressor'),
    ('vasopressin','vasopressor'), ('phenylephrine','vasopressor')])
def test_iv_drips_are_categorized_and_keep_last_admin_rate(name, group):
    row = order(name=name+' infusion', dose='0-5 mcg/kg/min', admin='0.25 mcg/kg/min at 01/08/26 1200', section='Other Medications')
    before = deepcopy(row)
    assert automatic_group(row) == group
    out = cardiovascular_body('', [row], True)
    assert '<b>' + GROUP_NAMES[group] + '</b>' in out
    assert out.count(name+' infusion') == 1
    assert '<b><u>Last Admin rate: 0.25 mcg/kg/min</u></b>' in out
    assert '0-5' not in out and row == before
    assert 'CV Infusions' not in out

@pytest.mark.parametrize('route,freq,name', [
    ('Apply externally','Daily','lidocaine patch'), ('Topical','PRN','lidocaine cream'),
    ('Intravenous','Once','lidocaine bolus'), ('Intravenous','q1h PRN','lidocaine infusion syringe'),
    ('Infiltration','Once','lidocaine with epinephrine injection'),
    ('Intravenous','Once','epinephrine injection'), ('Intramuscular','Once','epinephrine'),
    ('Nebulization','Continuous','epinephrine nebulizer'), ('Each Nostril','PRN','phenylephrine nasal spray'),
    ('Ophthalmic','Once','phenylephrine eye drops'), ('Topical','BID','hydrocortisone ointment'),
    ('Rectal','Daily','hydrocortisone suppository'), ('Oral','Daily','norepinephrine'),
])
def test_route_and_frequency_guardrails(route, freq, name):
    row=med(name,route=route,frequency=freq,section='Other Medications')
    assert automatic_group(row) == ''
    assert effective_section(row)=='Other Medications'

@pytest.mark.parametrize('name,route', [('nitroglycerin ointment','Topical'), ('clonidine patch','Transdermal')])
def test_requested_systemic_transdermal_products_still_group(name,route):
    row=med(name,route=route,frequency='Daily')
    assert automatic_group(row) == ('vasodilator' if name.startswith('nitro') else 'antihypertensive')

@pytest.mark.parametrize('name', ['levothyroxine (Synthroid) tablet','insulin regular infusion',
                                'insulin glargine (Lantus) injection', 'Lantus injection','metformin tablet',
                                'Synthroid tablet','Levoxyl tablet'])
def test_endocrine_goes_to_fengi(name):
    row=med(name,section='Other Medications')
    before=deepcopy(row)
    assert gi_auto(row)=='endocrine' and effective_section(row)=='FEN / GI'
    sheet=new_sheet('P4102');sheet['medications']=[row]
    fields=fields_with_medications(sheet)
    assert 'Endocrine Medications' in fields['FEN / GI']
    assert sum(v.count(name) for v in fields.values())==1
    assert row==before

@pytest.mark.parametrize('name', ['epinephrinex','norepinephrinex','enalaprilater','lidocaine-like-extract',
                                'mixed formulation with insulin','levothyroxine-like-extract','metforminase'])
def test_unlisted_names_are_not_guessed(name):
    # Suffixes with punctuation are not considered separate verified medicines.
    row=med(name,route='Oral',frequency='Daily',section='Other Medications')
    assert not automatic_group(row) and not gi_auto(row)

@pytest.mark.parametrize('name,group', [('norepinephrine','vasopressor'),('epinephrine','inotrope'),
                                     ('enalapril','antihypertensive'),('enalaprilat','vasodilator'),
                                     ('hydrochlorothiazide','antihypertensive')])
def test_similar_names_do_not_collide(name,group):
    row=med(name,section='Other Medications')
    assert automatic_group(row)==group

@pytest.mark.parametrize('group', ['antisialorrhea','antiarrhythmic','antihypertensive','inotrope','vasopressor','adrenocortical','vasodilator'])
def test_new_choices_roundtrip_through_shared_rules_and_encryption(group):
    row=med('synthetic custom medicine',section='Other Medications')
    rules=set_group_rule([],row,group)
    validate_group_rules(rules)
    changed=apply_group_rules([row],rules)[0]
    validate_medication(changed)
    assert effective_section(changed)==GROUP_SECTIONS[group]
    vault=new_vault();vault['settings']['medication_groups']=rules
    sheet=new_sheet('P4301');sheet['medications']=[changed]
    vault=save_sheet_in(vault,sheet)
    validate_vault(vault)
    key=Fernet.generate_key().decode()
    assert open_vault(seal_vault(vault,key),key)==vault


def test_endocrine_rule_roundtrip_and_override():
    row=med('custom hormone',section='Other Medications')
    rules=set_gi_rule([],row,'endocrine')
    changed=apply_gi_rules([row],rules)[0]
    validate_medication(changed)
    assert effective_section(changed)=='FEN / GI'
    vault=new_vault();vault['settings']['medication_gi_groups']=rules
    s=new_sheet('P4102');s['medications']=[changed]
    vault=save_sheet_in(vault,s);key=Fernet.generate_key().decode()
    assert open_vault(seal_vault(vault,key),key)==vault


def test_clonidine_can_remain_in_neurologic_without_changing_source():
    row=med('clonidine suspension',route='Per NJ Tube',frequency='q6h',section='Neurologic')
    assert effective_section(row)=='Cardiovascular'
    rules=set_group_rule([],row,'other')
    row2=apply_group_rules([row],rules)[0]
    assert effective_section(row2)=='Neurologic'
    assert {k:v for k,v in row2.items() if k!='group_mode'}==row


def test_explicit_gi_choice_beats_automatic_system_category():
    row=med('hydrocortisone tablet',route='Oral',frequency='Daily',section='Cardiovascular')
    row=apply_gi_rules([row],set_gi_rule([],row,'endocrine'))[0]
    assert not group_for(row) and effective_section(row)=='FEN / GI'
    assert 'Endocrine Medications' in fen_gi_body('',[row],None)


def sample_sheet():
    s=new_sheet('P4102');s['fields']['Diagnoses']='Synthetic category layout example'
    s['medications']=[
        order('esmolol infusion',admin='25 mcg/kg/min at 01/08/26 1200'),
        med('sotalol solution',dose='5 mg',route='Oral',frequency='q8h',rate='',section='Other Medications'),
        med('amlodipine tablet',dose='2.5 mg',route='Oral',frequency='Daily',rate='',section='Other Medications'),
        order('milrinone infusion',admin='0.5 mcg/kg/min at 01/08/26 1200'),
        order('norepinephrine infusion',admin='0.03 mcg/kg/min at 01/08/26 1200'),
        med('hydrocortisone injection',dose='5 mg',frequency='q8h',rate='',section='Other Medications'),
        order('nicardipine infusion',admin='0.5 mcg/kg/min at 01/08/26 1200'),
        med('glycopyrrolate solution',dose='0.5 mg',route='Per G Tube',frequency='TID',rate='',section='Other Medications'),
        med('scopolamine patch',dose='1 patch',route='Transdermal',frequency='q72h',rate='',section='Other Medications'),
        med('levothyroxine tablet',dose='25 mcg',route='Oral',frequency='Daily',rate='',section='Other Medications'),
        order('insulin regular infusion',dose='0.05 Units/kg/hr',admin='0.04 Units/kg/hr at 01/08/26 1200',section='Other Medications'),
        med('Lantus injection',dose='4 Units',route='Subcutaneous',frequency='Nightly',rate='',section='Other Medications'),
        med('metformin tablet',dose='500 mg',route='Oral',frequency='BID',rate='',section='Other Medications'),
    ]
    return s


def test_outputs_category_order_no_duplicates_and_infusion_emphasis():
    s=sample_sheet();before=deepcopy(s)
    f=fields_with_medications(s)
    cv=f['Cardiovascular']
    labels=['Antiarrhythmics','Antihypertensives','Inotrope Infusions','Vasopressors','Adrenocortical Support','Vasodilators']
    assert [cv.index(n) for n in labels]==sorted(cv.index(n) for n in labels)
    assert 'CV Infusions' not in cv
    h=handoff_html(s);t=handoff_text(s)
    pdf=handoff_pdf(s)
    with fitz.open(stream=pdf,filetype='pdf') as d:
        txt='\n'.join(p.get_text() for p in d)
        assert len(d)==1
    for label in labels+['Antisialorrhea Agents','Endocrine Medications']:
        assert label in h and label in t and label in txt
    for row in s['medications']:
        assert sum(v.count(row['name']) for v in f.values())==1
        assert h.count(row['name'])==1
    assert '<b>insulin regular infusion</b>' in h
    assert '<b><u>Last Admin rate: 0.04 Units/kg/hr</u></b>' in h
    assert s==before

@pytest.mark.parametrize('hidden,include',[(True,True),(False,False)])
def test_new_groups_do_not_restore_hidden_orders(hidden,include):
    s=sample_sheet()
    for r in s['medications']:r.update(hidden=hidden,include=include)
    text=handoff_text(s)
    for row in s['medications']:assert row['name'] not in text
    for label in ['Endocrine Medications','Vasopressors','Antisialorrhea Agents']:assert label not in text


def test_unlisted_cardiovascular_drip_stays_in_cv_infusions():
    row=med('nitroprusside infusion',section='Cardiovascular')
    assert 'CV Infusions' in cardiovascular_body('',[row])
    assert not automatic_group(row)


def test_changing_system_remembers_opt_out_for_clonidine(app):
    open_room(app);ss=app.st.session_state
    row=med('clonidine suspension',route='Oral',frequency='q6h',section='Neurologic')
    ss['drafts']['P4102']['medications']=[row]
    key='med_draft_'+row['id']+'_section';ss[key]='Neurologic'
    app.medication_row_change('P4102',row['id'],'section',key,None)
    edited=ss['drafts']['P4102']['medications'][0]
    assert effective_section(edited)=='Neurologic'
    assert any(r['mode']=='other' for r in ss['vault']['settings']['medication_groups'])


def test_group_callback_persists_shared_rule(app):
    open_room(app);ss=app.st.session_state
    row=med('custom cardiac medication',section='Cardiovascular')
    ss['drafts']['P4102']['medications']=[row]
    store=Store();ss['vault_sha']='old-sha'
    key='med_draft_'+row['id']+'_group_mode';ss[key]='vasodilator'
    app.medication_row_change('P4102',row['id'],'group_mode',key,store)
    assert group_for(ss['drafts']['P4102']['medications'][0])=='vasodilator'
    assert ss['vault']['settings']['medication_groups'][0]['mode']=='vasodilator'


def test_ui_removes_requested_controls_not_save_info(app,monkeypatch):
    open_room(app);ss=app.st.session_state
    ss['drafts']['P4102']=sample_sheet()
    downloads=equip(app,monkeypatch);output=[]
    for name in ('markdown','caption','warning','error'):
        monkeypatch.setattr(app.st,name,lambda text,*a,_n=name,**k:output.append((_n,str(text))))
    app.handoff_page(None)
    assert [l for l,d in downloads]==['Download this handoff (PDF)']
    text='\n'.join(t for _,t in output)
    assert '<th>PDF pages</th>' not in text and 'Body text' not in text
    assert 'PDF page count is checked' not in text
    assert 'GitHub' not in text and 'Use synthetic data unless' not in text
    assert any('Last saved' in t for _,t in output)


def test_print_all_has_pdf_only(app,monkeypatch):
    open_room(app);app.st.session_state['drafts']['P4102']=sample_sheet()
    downloads=equip(app,monkeypatch)
    app.print_all_page(None)
    assert [l for l,d in downloads]==['Download all selected handoffs (PDF)']
    assert downloads[0][1].startswith(b'%PDF')


def test_overflow_alert_remains_without_diagnostics(app,monkeypatch):
    equip(app,monkeypatch);calls=[]
    monkeypatch.setattr(app,'print_fit_report',lambda *a:dict(page_count=2,target_met=False,font_size=6.5,tight_spacing=True,balanced_columns=True))
    monkeypatch.setattr(app.st,'warning',lambda t:calls.append(t))
    app.render_print_fit([new_sheet('P4102')],1)
    assert len(calls)==1 and '2 pages' in calls[0]


def test_routine_ui_has_no_provider_branding_and_transport_is_intact():
    root=Path(__file__).parents[1]
    for filename in ('app.py','save_status.py','user_guide.py','guide_store.py','error_store.py'):
        tree=ast.parse((root/filename).read_text())
        # Exclude docstrings. Configuration headers/identifiers are not rewritten.
        docstrings={id(n.body[0].value) for n in ast.walk(tree) if hasattr(n,'body') and isinstance(n.body,list) and n.body and isinstance(n.body[0],ast.Expr) and isinstance(n.body[0].value,ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n,ast.Constant) and isinstance(n.value,str) and id(n) not in docstrings:
                assert 'GitHub' not in n.value, (filename,n.value)
    source=(root/'github_store.py').read_text()
    assert 'X-GitHub-Api-Version' in source and 'https://api.github.com' in source
    assert 'seal_vault' in source and 'open_vault' in source
