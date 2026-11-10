from style_assert_helpers import without_style_tags
from recovery_helpers import assert_retained
"""Version 6.15 synthetic regressions. No live records or GitHub calls."""
from copy import deepcopy
from io import BytesIO
import json
import uuid
import pytest
from pypdf import PdfReader
from cryptography.fernet import Fernet
from models import new_sheet, new_vault, upgrade_vault, validate_sheet, fields_with_medications, SCHEMA_VERSION, ValidationError
from fluid_balance import parse_balance, validate_balance, balance_text, empty_balance
from fen_gi import (automatic_group, effective_section, group_for, fen_gi_body,
    set_gi_rule, apply_gi_rules, gi_key, validate_gi_rules)
from parser import parse_smartphrase
from importing import import_sections
from exports import handoff_html, handoff_text, handoff_pdf, handoffs_pdf, field_markup
from infusions import neuro_body
from batching import available_handoffs
from security import seal_vault, open_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_rooms_infusions import med
from test_workflow_print import Store, change_room

BALANCE = '''Intake/Output Summary (Last 24 hours) at 1/7/2026 0614
Last data filed at 1/7/2026 0500
Gross per 24 hour
Intake\t1200.5 ml
Output\t950 ml
Net\t250.5 ml'''


def wrap(letter, body):
    return letter*12+'\n'+body+'\n'+letter.upper()*12+'\n'


def io_sheet():
    result=import_sections(new_sheet('P4102'),wrap('s',BALANCE),new_vault()['settings'])
    assert not result.errors,result.errors
    return result.sheet


def populated():
    sheet=io_sheet()
    sheet['fields']['FEN / GI']='Separate nutrition note'
    sheet['medications']=[
        med('pantoprazole (Protonix) injection 10 mg','10 mg','Intravenous','Daily','', 'Other Medications'),
        med('polyethylene glycol (PEG) 3350 powder 8.5 g','8.5 g','Per NJ Tube','Daily','', 'Other Medications'),
        med('sennosides syrup 2.5 mL','2.5 mL','Per NJ Tube','q24h','', 'Other Medications'),
        med('sennosides syrup 5 mL','5 mL','Per NJ Tube','Nightly','', 'Other Medications'),
        med('Synthetic IV fluid infusion','25 mL/hr','Intravenous','Continuous','25 mL/hr','FEN / GI'),
    ]
    return sheet


def test_source_totals_unchanged_and_top():
    s=populated(); before=deepcopy(s);text=fields_with_medications(s)['FEN / GI']
    assert text.startswith('Intake/Output:\nIntake: 1200.5 ml\nOutput: 950 ml\nNet: 250.5 ml\n-----\nGI prophylaxis')
    assert text.index('GI prophylaxis') < text.index('Bowel Regimen') < text.index('Separate nutrition note') < text.index('Synthetic IV fluid')
    assert text.count('sennosides')==2 and 'q24h' in text and 'Nightly' in text
    assert s==before


@pytest.mark.parametrize('value',['0 ml','-42.5 mL','+3.25 mL','1,234.50 ml','.5 L','100 cc','0','—','--','N/A'])
def test_volume_preserved_not_recalculated(value):
    r=parse_balance(BALANCE.replace('250.5 ml',value))
    assert not r.error
    assert r.data['net']==value
    if value not in ('—','--','N/A'):
        assert 'Net: '+value in balance_text(r.data)
    else: assert 'Net: --' in balance_text(r.data)


@pytest.mark.parametrize('field',['Intake','Output','Net'])
def test_missing_total_is_not_zero_or_calculated(field):
    r=parse_balance('\n'.join(l for l in BALANCE.splitlines() if not l.startswith(field+'\t')))
    assert not r.error and r.issues
    assert field+': --' in balance_text(r.data)


@pytest.mark.parametrize('body',['','Intake/Output:', 'Fluid balance:', 'No results found', 'None'])
def test_empty_s_clears(body):
    old=io_sheet();r=import_sections(old,wrap('s',body),new_vault()['settings'])
    assert not r.errors,r.errors
    assert r.sheet['intake_output'] is None
    assert old['intake_output'] is not None


def test_omitted_s_and_old_h_do_not_change_or_duplicate():
    old=io_sheet();body=wrap('a','Diagnoses:\n1. Synthetic example')+wrap('h','INTAKE/OUTPUT:\nIntake\t9999 ml\nOutput\t1 ml\nNet\t9998 ml')
    r=import_sections(old,body,new_vault()['settings'])
    assert not r.errors and r.sheet['intake_output']==old['intake_output']
    text=fields_with_medications(r.sheet)['FEN / GI']
    assert '9999' not in text and text.count('Intake:')==1


def test_full_paste_with_h_and_s_uses_only_s():
    body=wrap('h','INTAKE/OUTPUT:\nIntake\t9 ml\nOutput\t8 ml\nNet\t1 ml')+wrap('s',BALANCE)
    r=import_sections(new_sheet('P4102'),body,new_vault()['settings'])
    assert not r.errors and r.sheet['intake_output']['intake']=='1200.5 ml'


@pytest.mark.parametrize('body',[BALANCE+'\nIntake\t999 ml',BALANCE+'\nUnknown heading',BALANCE.replace('950 ml','950 ml/hr'), BALANCE.replace('1200.5 ml','wrong'), BALANCE+'\nIntake/Output Summary (Last 24 hours) at 1/8/2026 0614'])
def test_malformed_s_rejects_entire_proposal(body):
    old=populated();before=deepcopy(old)
    r=import_sections(old,wrap('a','Diagnoses:\n1. Replacement')+wrap('s',body),new_vault()['settings'])
    assert_retained(r, before, "s")
    assert old==before


def test_repeat_identical_totals_only_once():
    r=parse_balance(BALANCE+'\nIntake\t1200.5 ml');assert not r.error
    assert balance_text(r.data).count('Intake:')==1


def test_empty_unmatched_s_does_not_clear():
    old=io_sheet();r=import_sections(old,'s'*10+'\n'+BALANCE,new_vault()['settings'])
    assert_retained(r, old, "s")
    assert old["intake_output"]


@pytest.mark.parametrize('name,group',[
 ('famotidine (Pepcid) suspension 4 mg','prophylaxis'),('omeprazole capsule 10 mg','prophylaxis'),
 ('pantoprazole injection 10 mg','prophylaxis'),('FAMOTIDINE injection 5 mg','prophylaxis'),
 ('[Held by provider] pantoprazole injection 10 mg','prophylaxis'),
 ('Followed by: [START ON 1/8/2026] omeprazole capsule 5 mg','prophylaxis'),
 ('docusate sodium liquid 25 mg','bowel'),('lactulose solution 5 mL','bowel'),
 ('polyethylene glycol (PEG) 3350 powder 17 g','bowel'),('sennosides syrup 2.5 mL','bowel'),
 ('glycerin pediatric rectal supp 0.5 suppository','bowel'),('glycerin suppository','bowel'),
])
def test_requested_names_group_without_mapping(name,group):
    row=med(name,section='Other Medications')
    assert automatic_group(row)==group and effective_section(row)=='FEN / GI'


@pytest.mark.parametrize('name',['esomeprazole','famotidinee','glycerin topical cream','sodium lactate infusion','Synthetic drug in glycerin','dexamethasonex','omeprazolex','sodium chloride','senna extract'])
def test_no_unrequested_or_substring_classification(name):
    row=med(name,section='Other Medications')
    assert not automatic_group(row) and effective_section(row)=='Other Medications'


def test_glycerin_rectal_route_without_form_in_name():
    assert automatic_group(med('glycerin',route='Rectal'))=='bowel'


@pytest.mark.parametrize('section',['Neurologic','Respiratory','Cardiovascular','Infectious Disease','Other Medications','FEN / GI'])
def test_automatic_display_never_duplicates_an_order(section):
    s=new_sheet('P4102');s['medications']=[med('famotidine UNIQUE',section=section)]
    before=deepcopy(s);fields=fields_with_medications(s)
    assert sum(v.count('famotidine UNIQUE') for v in fields.values())==1
    assert 'famotidine UNIQUE' in fields['FEN / GI']
    assert s==before
    if section=='Neurologic': assert 'famotidine UNIQUE' not in neuro_body('',s['medications'])


def test_hidden_and_excluded_are_not_restored_by_grouping():
    s=populated();s['medications'][0]['hidden']=True;s['medications'][1]['include']=False
    t=fields_with_medications(s)['FEN / GI']
    assert 'pantoprazole' not in t and 'GI prophylaxis' not in t
    assert 'polyethylene glycol' not in t and 'sennosides' in t
    assert s['medications'][0]['name'].startswith('pantoprazole')


def test_output_only_removal_dosing_qualifier_and_held_label_preserved():
    s=io_sheet();s['medications']=[med('[Held by provider] famotidine','1 mg/kg (Dosing Weight)')]
    text=fields_with_medications(s)['FEN / GI']
    assert '(Dosing Weight)' not in text and '[Held by provider]' in text and '1 mg/kg' in text
    assert '(Dosing Weight)' in s['medications'][0]['dose']


def test_custom_wording_and_escaping():
    s=populated();s['medications'][0]['custom_text']='<script>test</script> 2 mg/kg (Dosing Weight)'
    html=handoff_html(s)
    assert '<script>test</script>' not in html and '&lt;script&gt;test&lt;/script&gt;' in html
    assert '<b>GI prophylaxis</b>' in html and '<b>Bowel Regimen</b>' in html


@pytest.mark.parametrize('mode',['auto','prophylaxis','bowel','other'])
def test_saved_group_choice_roundtrip(mode):
    row=med('famotidine',route='Oral',frequency='Daily',section='Other Medications')
    rules=set_gi_rule([],row,mode)
    rows=apply_gi_rules([row],rules)
    assert rows[0].get('gi_mode','auto')==mode
    assert rules==[] if mode=='auto' else len(rules)==1
    if mode=='other': assert effective_section(rows[0])=='Other Medications'
    v=new_vault();s=new_sheet('P4102');s['medications']=rows;v['rooms'][s['room']]=s;v['settings']['medication_gi_groups']=rules
    key=Fernet.generate_key().decode();assert open_vault(seal_vault(v,key),key)==v


def test_gi_override_is_form_route_frequency_specific():
    row=med('famotidine',route='Oral',frequency='Daily')
    others=[deepcopy(row) for _ in range(3)]
    others[0]['route']='Intravenous';others[1]['frequency']='q12h';others[2]['name']='famotidine suspension'
    rules=set_gi_rule([],row,'other')
    assert all(effective_section(r)=='FEN / GI' for r in apply_gi_rules(others,rules))


def test_latest_archive_migration_preserves_original_fields_and_settings():
    old=new_vault();old['schema']=14;old.pop("reset_generation", None);old["settings"].pop("medication_groups", None);old['settings'].pop('medication_gi_groups')
    s=new_sheet('P4102');s.pop("feeds", None);s.pop("devices", None);s.pop("neuro_devices", None);s.pop("pacemaker", None);s.pop("diet", None);s.pop("import_warnings", None);s.pop('intake_output');s['fields']['FEN / GI']='Preserve this note'
    old['rooms'][s['room']]=s;original=deepcopy(old)
    new=upgrade_vault(old)
    assert old==original and new['schema']==SCHEMA_VERSION==33
    assert new['rooms'][s['room']]==dict(s,intake_output=None,import_warnings={},feeds=None,devices=None,neuro_devices=None,pacemaker=None,diet=None)
    assert new['settings']==dict(old['settings'],medication_gi_groups=[], medication_groups=[])
    key=Fernet.generate_key().decode()
    cipher=Fernet(key.encode()).encrypt(json.dumps(old).encode())
    assert open_vault(cipher,key)==new


def test_invalid_new_fields_and_choices_fail_validation():
    s=io_sheet();s['intake_output']['unexpected']='discard?'
    with pytest.raises(ValidationError):validate_sheet(s)
    with pytest.raises(ValueError):validate_gi_rules([{'mode':'other'}])


def test_s_only_sheet_is_not_lost_from_print_all():
    s=io_sheet();assert list(available_handoffs(new_vault(),{'P4102':s}))==['P4102']
    s['intake_output']['include']=False
    assert not available_handoffs(new_vault(),{'P4102':s})


def test_all_exports_match_order_and_keep_repeat_doses():
    s=populated();before=deepcopy(s)
    fields=fields_with_medications(s);text=fields['FEN / GI']
    html=without_style_tags(handoff_html(s));txt=handoff_text(s)
    pdf=PdfReader(BytesIO(handoff_pdf(s)))
    pdftext='\n'.join(p.extract_text() for p in pdf.pages)
    for result in (text,html,txt,pdftext):
        assert result.index('Intake: 1200.5 ml') < result.index('GI prophylaxis') < result.index('Bowel Regimen')
        assert result.count('sennosides syrup')==2
    assert len(pdf.pages)==1 and s==before
    two=deepcopy(s);two['id']=uuid.uuid4().hex;two['room']='P4104';two['intake_output']['net']='-7 ml'
    packet=PdfReader(BytesIO(handoffs_pdf([s,two])))
    assert len(packet.pages)==2 and 'Net: -7 ml' not in packet.pages[0].extract_text()
    assert 'Net: -7 ml' in packet.pages[1].extract_text()


def setup(app):
    open_room(app);s=populated();app.st.session_state['drafts']['P4102']=s
    return app.st.session_state,s


def test_io_edit_autosaves_on_room_change(app):
    ss,s=setup(app);key='io_'+s['id']+'_net';ss[key]='-15.5 ml'
    change_room(app)
    assert ss['vault']['rooms']['P4102']['intake_output']['net']=='-15.5 ml'
    assert ss['current_room']=='P4104'


def test_invalid_io_edit_rolls_back(app):
    ss,s=setup(app);key='io_'+s['id']+'_intake';ss[key]='not numeric'
    app.intake_output_change('P4102','intake',key)
    assert ss[key]=='1200.5 ml' and ss['notice'][0]=='error'


def test_gi_choice_persists_and_can_be_reset(app):
    ss,s=setup(app);row=s['medications'][0];key='med_draft_'+row['id']+'_gi_mode'
    ss[key]='other';app.medication_row_change('P4102',row['id'],'gi_mode',key)
    assert ss['vault']['settings']['medication_gi_groups'][0]['mode']=='other'
    assert effective_section(ss['drafts']['P4102']['medications'][0])=='Other Medications'
    ss[key]='auto';app.medication_row_change('P4102',row['id'],'gi_mode',key)
    assert ss['vault']['settings']['medication_gi_groups']==[]
    assert effective_section(ss['drafts']['P4102']['medications'][0])=='FEN / GI'


def test_system_override_disables_automatic_group_and_stays_saved(app):
    ss,s=setup(app);row=s['medications'][0];key='med_draft_'+row['id']+'_section'
    ss[key]='Neurologic';app.medication_row_change('P4102',row['id'],'section',key)
    new=ss['drafts']['P4102']['medications'][0]
    assert new['section']=='Neurologic' and new['gi_mode']=='other'
    assert 'pantoprazole' in fields_with_medications(ss['drafts']['P4102'])['Neurologic']


def test_ui_effective_destination_does_not_create_unsolicited_mapping(app,monkeypatch):
    ss,s=setup(app);equip(app,monkeypatch);app.handoff_page(None)
    assert ss['med_draft_'+s['medications'][0]['id']+'_category_target']=='auto'
    assert effective_section(s['medications'][0])=='FEN / GI'
    snap=app.editor_snapshot('P4102')
    assert snap['medications'][0]['section']==s['medications'][0]['section']=='Other Medications'
    change_room(app)
    assert not ss['vault']['settings']['medication_mappings']


def test_pending_group_widget_saved_on_room_change(app):
    ss,s=setup(app);row=s['medications'][0]
    ss['med_draft_'+row['id']+'_gi_mode']='other'
    change_room(app)
    assert ss['vault']['settings']['medication_gi_groups'][0]['mode']=='other'
    assert effective_section(ss['vault']['rooms']['P4102']['medications'][0])=='Other Medications'


def test_failed_gi_save_does_not_move_or_hide_orders(app):
    from github_store import StorageError
    ss,s=setup(app);before=deepcopy(ss['drafts']);row=s['medications'][0];key='med_draft_'+row['id']+'_gi_mode';ss[key]='other'
    app.medication_row_change('P4102',row['id'],'gi_mode',key,Store(StorageError('Synthetic fail')))
    assert ss['drafts']==before and ss[key]=='auto' and ss['notice'][0]=='error'


def test_full_ui_renders_without_duplicate_keys_and_admin_without_room(app,monkeypatch):
    ss,s=setup(app);downloads=equip(app,monkeypatch);app.handoff_page(None)
    assert any(data.startswith(b'%PDF') for _,data in downloads if isinstance(data,bytes))
    ss.pop('current_room');equip(app,monkeypatch);app.admin_page(None)


def test_repeated_import_and_empty_s_do_not_change_med_fields_or_other_sections():
    s=populated();r=import_sections(s,wrap('s',BALANCE),new_vault()['settings']);assert not r.errors
    assert r.sheet==s
    r2=import_sections(s,wrap('s',''),new_vault()['settings'])
    assert r2.sheet['intake_output'] is None
    assert {k:v for k,v in r2.sheet.items() if k!='intake_output'}=={k:v for k,v in s.items() if k!='intake_output'}
