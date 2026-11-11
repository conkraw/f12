"""v6.17: user-defined display groups, source preservation, Ca and multi-format output.

All fixtures are synthetic. The grouping labels do not assert clinical indications.
"""
from copy import deepcopy
from io import BytesIO
import json
import re
import uuid
import pytest
import fitz
from cryptography.fernet import Fernet
from pypdf import PdfReader
from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_rooms_infusions import med
from test_workflow_print import Store, change_room
from medication_groups import (MODES, automatic_group, group_for, group_mode_for,
    set_group_rule, apply_group_rules, validate_group_rules, is_prn)
from fen_gi import effective_section, automatic_group as auto_gi, set_gi_rule, apply_gi_rules
from infusions import is_infusion, system_body_blocks, neuro_body, cardiovascular_body
from models import new_sheet, new_vault, fields_with_medications, validate_vault, upgrade_vault, SCHEMA_VERSION
from medications import parse_medications
from importing import import_sections
from exports import handoff_html, handoff_pdf, handoffs_pdf, handoff_text, field_markup
from labs import parse_labs, result_cards, canonical
from security import seal_vault, open_vault
from github_store import StorageError, ConflictError


@pytest.mark.parametrize('name,group', [
    ('enoxaparin (Lovenox) syringe', 'dvt'), ('cangrelor (Kengreal) infusion', 'antiplatelet'),
    ('acetaminophen injection', 'fever'), ('ibuprofen suspension', 'fever'),
    ('fentaNYL NCS infusion syringe', 'sedative_prn'), ('midazolam PF', 'sedative_prn'),
    ('ketamine injection', 'sedative_prn'), ('morphine PF', 'sedative_prn'),
    ('HYDROmorphone injection', 'sedative_prn'), ('rocuronium injection', 'paralytic_prn'),
    ('cisatracurium injection', 'paralytic_prn'), ('vecuronium injection', 'paralytic_prn'),
])
@pytest.mark.parametrize('prefix', ['', '[Held by provider] ', '[START ON 01/02/2027] ', 'Followed by: '])
def test_named_rules_respect_known_prefixes_and_case(name,group,prefix):
    r=med(prefix+name, frequency='q1h PRN', section='Other Medications')
    before=deepcopy(r)
    assert automatic_group(r)==group
    assert effective_section(r)==('Hematology' if group in ('dvt', 'antiplatelet') else 'Neurologic')
    assert r==before


@pytest.mark.parametrize('dose', ['0 Units/kg/hr', '1 unit/kg/hr', '10 Units/kg/hr (Dosing Weight)',
    '10 Units / kg / hr', '5-20 UNITS/kg/hr', '0.25 units/kg/hour', '12 units/kg/h', '10units/kg/hr'])
def test_heparin_qualification_checks_explicit_ordered_dose(dose):
    r=med('heparin PF infusion 100 units/mL',dose=dose,section='Cardiovascular')
    assert automatic_group(r)=='dvt' and effective_section(r)=='Hematology'
    assert not system_body_blocks('Cardiovascular','',[r])


@pytest.mark.parametrize('name,dose,route,rate', [
    ('heparin 1 unit/mL infusion','2 mL/hr','Intravenous','2 mL/hr'),
    ('heparin infusion 10 Units/kg/hr','','Intravenous','10 Units/kg/hr'),
    ('heparin flush 10 units/mL','10 Units/kg/hr','Intracatheter',''),
    ('Heparin (Porcine)-Taurolidine','40 mg','Irrigation',''),
    ('heparin infusion','10 Units/kg/min','Intravenous',''),
    ('heparin infusion','500 units','Subcutaneous',''),
    ('heparin infusion','10 mUnits/kg/hr','Intravenous',''),
    ('heparinized carrier','10 Units/kg/hr','Intravenous',''),
])
def test_heparin_flush_carrier_and_strength_not_used_to_infer_group(name,dose,route,rate):
    r=med(name,dose,route,'Continuous',rate,'Other Medications')
    assert automatic_group(r)=='' and effective_section(r)=='Other Medications'


@pytest.mark.parametrize('name', ['fentanyl','midazolam','ketamine','morphine','hydromorphone','rocuronium','cisatracurium','vecuronium'])
@pytest.mark.parametrize('frequency', ['Once','q6h','Continuous',''])
def test_only_recorded_prn_frequency_enters_prn_group(name,frequency):
    r=med(name,frequency=frequency)
    expected = 'paralytic_infusion' if frequency=='Continuous' and name in ('rocuronium','cisatracurium','vecuronium') else ''
    assert automatic_group(r)==expected
    assert not is_prn(r)


@pytest.mark.parametrize('frequency', ['PRN','q30 min PRN','q2h as needed','AS-NEEDED'])
def test_prn_frequency_variants(frequency):
    r=med('fentanyl infusion syringe',frequency=frequency)
    assert automatic_group(r)=='sedative_prn' and not is_infusion(r)


@pytest.mark.parametrize('name', ['bumetanide infusion','chlorothiazide injection','furosemide solution'])
@pytest.mark.parametrize('section', ['Cardiovascular','FEN / GI','Neurologic','Other Medications'])
def test_diuretics_move_to_fengi_without_duplication(name,section):
    s=new_sheet('P4102');r=med(name+' UNIQUE',section=section);s['medications']=[r]
    original=deepcopy(s)
    fields=fields_with_medications(s)
    assert 'Diuretics' in fields['FEN / GI']
    assert sum(text.count('UNIQUE') for text in fields.values())==1
    assert auto_gi(r)=='diuretic' and s==original


@pytest.mark.parametrize('name', ['furosemidex','acetaminophene','synthetic containing fentanyl','midazolamium','hydromorphone-like-extract'])
def test_no_unrequested_substring_matching(name):
    r=med(name,frequency='Continuous',section='Other Medications')
    assert not automatic_group(r) and not auto_gi(r)


def example_sheet():
    s=new_sheet('P4102')
    s['fields']['Diagnoses']='Synthetic medication-layout example'
    s['fields']['Neurologic']='Synthetic neuro note'
    s['fields']['Cardiovascular']='Synthetic cardiac note'
    s['fields']['Hematology']='Synthetic hematology note'
    s['medications']=[
      med('dexmedetomidine NEURO_DRIP',dose='0.4 mcg/kg/hr (Dosing Weight)',section='Neurologic'),
      med('fentanyl NEURO_PRN',dose='5 mcg',frequency='q1h PRN',section='Other Medications'),
      med('vecuronium PARALYTIC_PRN',dose='1 mg',frequency='q1h PRN',section='Other Medications'),
      med('acetaminophen FEVER_MED',dose='100 mg',route='Oral',frequency='q6h',section='Other Medications'),
      med('milrinone CARDIAC_DRIP',dose='0.25 mcg/kg/min (Dosing Weight)',rate='0.5 mL/hr',section='Cardiovascular'),
      med('heparin WEIGHT_BASED',dose='10 Units/kg/hr (Dosing Weight)',section='Cardiovascular'),
      med('cangrelor CANG_MED',dose='0.1 mcg/kg/min',section='Cardiovascular'),
      med('enoxaparin ENOX_MED',dose='10 mg',route='Subcutaneous',frequency='q12h',rate='',section='Other Medications'),
      med('furosemide DIURETIC_MED',dose='2 mg',frequency='q12h',rate='',section='Cardiovascular'),
      med('heparin flush FLUSH_MED',dose='10 Units',route='Intracatheter',frequency='q12h',rate='',section='Other Medications'),
    ]
    from vitals import parse_vitals
    s['vitals']=parse_vitals('VITALS:\nHeart Rate: 100\nBP: 90/50').rows
    # Use no guessed observation record structure here.
    return s


def test_all_groups_are_deterministic_and_no_source_fields_change():
    s=example_sheet();before=deepcopy(s);f=fields_with_medications(s)
    n=f['Neurologic'];c=f['Cardiovascular'];h=f['Hematology']
    assert n.index('Infusions')<n.index('\nPRN\n')<n.index('Paralytic PRN')<n.index('Fever Control')
    assert c.index('Heart Rate')<c.index('Inotrope Infusions')<c.index('CARDIAC_DRIP')<c.index('Synthetic cardiac note')
    assert h.index('DVT Prophylaxis')<h.index('WEIGHT_BASED')
    for sentinel in ('NEURO_DRIP','NEURO_PRN','PARALYTIC_PRN','FEVER_MED','CARDIAC_DRIP','WEIGHT_BASED','CANG_MED','ENOX_MED','DIURETIC_MED','FLUSH_MED'):
        assert sum(text.count(sentinel) for text in f.values())==1
    assert '(Dosing Weight)' not in ''.join(f.values())
    assert s==before


def test_formats_have_same_groups_and_bold_cv_dose():
    s=example_sheet();before=deepcopy(s)
    h=handoff_html(s);t=handoff_text(s);pdf=handoff_pdf(s)
    for name in ('Infusions','Inotrope Infusions','Fever Control','PRN','Paralytic PRN','DVT Prophylaxis','Diuretics'):
        assert name in h and name in t
        assert name in '\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
    assert '<b>Inotrope Infusions</b>' in h and '<b>milrinone CARDIAC_DRIP</b>' in h
    assert '<b><u>Dose: 0.25 mcg/kg/min</u></b>' in h
    assert 'INFUSIONS' not in h and '(Dosing Weight)' not in h
    doc=fitz.open(stream=pdf,filetype='pdf')
    spans=[sp for page in doc for b in page.get_text('dict')['blocks'] if 'lines' in b for li in b['lines'] for sp in li['spans']]
    assert any('CARDIAC_DRIP' in sp['text'] and 'Bold' in sp['font'] for sp in spans)
    assert s==before


@pytest.mark.parametrize('hidden,include',[(True,True),(False,False)])
def test_grouping_never_restores_hidden_or_excluded(hidden,include):
    s=example_sheet()
    for row in s['medications']:row['hidden']=hidden;row['include']=include
    for text in (handoff_html(s),handoff_text(s)):
        for sentinel in ('NEURO_DRIP','CARDIAC_DRIP','DIURETIC_MED','WEIGHT_BASED','PARALYTIC_PRN','FEVER_MED'):
            assert sentinel not in text


def test_start_label_hidden_with_held_custom_text_and_html_escaping_retained():
    s=new_sheet('P4102')
    r=med('[Held by provider] [START ON 01/02/2027] cangrelor <marker>',dose='0.1 mcg/kg/min (Dosing Weight)')
    s['medications']=[r]
    h=handoff_html(s)
    assert '[Held by provider]' in h and '[START ON' not in h and '&lt;marker&gt;' in h
    assert '[START ON 01/02/2027]' in r['name']
    r['custom_text']='Override <script>display</script> 0.2 mcg/kg/min (Dosing Weight)'
    h=handoff_html(s)
    assert '<script>display</script>' not in h and '&lt;script&gt;display&lt;/script&gt;' in h
    assert '0.2 mcg/kg/min' in h and 'Dose: 0.1' not in h


def test_cv_mapping_required_not_all_continuous_orders_move():
    r=med('synthetic CV drug',section='Other Medications')
    assert is_infusion(r) and not cardiovascular_body('',[r])
    r['section']='Cardiovascular'
    assert 'CV Infusions' in cardiovascular_body('',[r])
    r['infusion_mode']='other'
    assert 'CV Infusions' not in cardiovascular_body('',[r])


@pytest.mark.parametrize('mode',MODES)
def test_group_override_roundtrip_and_original_fields_kept(mode):
    r=med('morphine test',frequency='q1h PRN',section='Other Medications');original=deepcopy(r)
    rules=set_group_rule([],r,mode);rows=apply_group_rules([r],rules)
    v=new_vault();s=new_sheet('P4102');s['medications']=rows;v['rooms'][s['room']]=s;v['settings']['medication_groups']=rules
    key=Fernet.generate_key().decode()
    assert open_vault(seal_vault(v,key),key)==v
    assert all(rows[0][k]==val for k,val in original.items())
    assert r==original and group_mode_for(r,rules)==mode


def test_override_does_not_change_other_form_route_or_frequency():
    r=med('fentanyl injection',frequency='q1h PRN')
    rules=set_group_rule([],r,'other')
    for key,val in [('name','fentanyl syringe'),('route','Oral'),('frequency','q2h PRN')]:
        other=deepcopy(r);other[key]=val
        assert group_mode_for(other,rules)=='auto'
    assert group_for(apply_group_rules([r],rules)[0])==''


@pytest.mark.parametrize('bad',[{},[{'name':'x'}],[{'name':'x','route':'IV','frequency':'PRN','mode':'wrong'}]])
def test_bad_group_rules_rejected(bad):
    with pytest.raises(ValueError):validate_group_rules(bad)


def test_calcium_ca_latest_and_preceding_next_to_mag_phos():
    s=new_sheet('P4102')
    raw='LABS:\nComponent\tValue\tDate\nCA\t8.2 (L)\t01/04/2027\nCA\t8.7\t01/03/2027\nMG\t1.9\t01/04/2027\nMG\t2.0\t01/03/2027\nPHOS\t3.2\t01/04/2027\nPHOS\t3.6\t01/03/2027\n'
    s['labs']=parse_labs(raw).data;original=deepcopy(s)
    cards=[c for c in result_cards(s['labs']) if c['kind']=='bmp']
    assert canonical('CA')=='CALCIUM' and len(cards)==2
    assert cards[0]['rows']['CALCIUM']['value']=='8.2 (L)'
    assert cards[1]['rows']['CALCIUM']['value']=='8.7'
    assert all(set(c['rows'])=={'CALCIUM','MG','PHOS'} for c in cards)
    from lab_layout import card_plan
    for card in cards:
        _,plan=card_plan(card,180)
        text='\n'.join(v[3] for v in plan if v[0]=='text')
        assert text.index('Ca:')<text.index('Mg:')<text.index('Phos:')
    h=handoff_html(s);p=handoff_pdf(s);t=handoff_text(s)
    for text in (h,t,'\n'.join(pg.extract_text() for pg in PdfReader(BytesIO(p)).pages)):
        assert '8.2 (L)' in text and '8.7' in text
    assert s==original


def test_schema16_upgrade_preserves_every_field_and_import_warning():
    v=new_vault();v['schema']=16;v.pop("reset_generation", None);v['settings'].pop('medication_groups')
    s=example_sheet()
    # Produce a real review marker through the existing recovery path.
    res=import_sections(s,'rrrrrrrr\nOrders Placed This Encounter\n• XR chest 1 view\nTiming: Recurring (Daily)\nNumber of Occurrences: BAD\nrrrrrrrr',v['settings'])
    assert res.sheet and res.sheet['import_warnings']
    res.sheet.pop('feeds');res.sheet.pop("devices", None);res.sheet.pop("neuro_devices", None);res.sheet.pop("pacemaker", None);res.sheet.pop("diet", None)
    v['rooms'][s['room']]=res.sheet;before=deepcopy(v)
    key=Fernet.generate_key().decode();encrypted=Fernet(key.encode()).encrypt(json.dumps(v).encode())
    upgraded=open_vault(encrypted,key)
    assert upgraded['schema']==SCHEMA_VERSION==34
    assert upgraded['rooms']=={room: dict(sheet, feeds=None,devices=None,neuro_devices=None,pacemaker=None,diet=None) for room, sheet in before['rooms'].items()}
    assert upgraded['settings']==dict(before['settings'],medication_groups=[])
    assert v==before


def test_inline_group_override_saved_not_draft_and_reimported(app):
    open_room(app);ss=app.st.session_state;r=med('acetaminophen injection',frequency='q6h',section='Other Medications')
    ss['drafts']['P4102']['medications']=[r];ss['group_choice']='other';store=Store()
    app.medication_row_change('P4102',r['id'],'group_mode','group_choice',store)
    assert store.calls and store.calls[0][0]['rooms']=={}
    assert ss['vault']['settings']['medication_groups'][0]['mode']=='other'
    assert effective_section(ss['drafts']['P4102']['medications'][0])=='Other Medications'
    ss['paste']='bbbbbbbb\nMedications:\n• acetaminophen injection\t100 mg\tIntravenous\tq6h\nbbbbbbbb'
    app.create_handoff()
    assert ss['drafts']['P4102']['medications'][0]['group_mode']=='other'


@pytest.mark.parametrize('error',[StorageError('Offline'),ConflictError('Changed elsewhere')])
def test_failed_group_write_keeps_every_draft_and_restores_widget(app,error):
    open_room(app);ss=app.st.session_state;r=med('cangrelor',section='Other Medications');ss['drafts']['P4102']['medications']=[r]
    before=deepcopy(ss['drafts']);ss['choice']='other'
    app.medication_row_change('P4102',r['id'],'group_mode','choice',Store(error))
    assert ss['drafts']==before and ss['choice']=='auto' and ss['notice'][0]=='error'
    assert ss['vault']['settings']['medication_groups']==[]


def test_move_automatic_group_to_another_system_is_remembered(app):
    open_room(app);ss=app.st.session_state;r=med('acetaminophen',frequency='q6h');ss['drafts']['P4102']['medications']=[r]
    ss['new_system']='Other Medications'
    app.medication_row_change('P4102',r['id'],'section','new_system')
    updated=ss['drafts']['P4102']['medications'][0]
    assert updated['group_mode']=='other' and effective_section(updated)=='Other Medications'


def test_heparin_dose_edit_refreshes_effective_section_and_widget(app):
    open_room(app);ss=app.st.session_state;r=med('heparin infusion',dose='10 Units/kg/hr',section='Other Medications');ss['drafts']['P4102']['medications']=[r]
    key='med_draft_'+r['id']+'_dose';ss[key]='2 mL/hr';ss['med_draft_'+r['id']+'_section']='Hematology'
    app.medication_row_change('P4102',r['id'],'dose',key)
    assert effective_section(ss['drafts']['P4102']['medications'][0])=='Other Medications'
    assert 'med_draft_'+r['id']+'_section' not in ss


def test_pending_group_override_saves_before_room_change(app):
    open_room(app);ss=app.st.session_state;r=med('fentanyl',frequency='q1h PRN');ss['drafts']['P4102']['medications']=[r]
    ss['med_draft_'+r['id']+'_group_mode']='other'
    change_room(app,Store())
    assert ss['current_room']=='P4104'
    assert ss['vault']['settings']['medication_groups'][0]['mode']=='other'
    assert ss['vault']['rooms']['P4102']['medications'][0]['group_mode']=='other'


def test_group_admin_can_edit_without_handoff(app,monkeypatch):
    ss=app.st.session_state;r=med('vecuronium',frequency='q1h PRN')
    ss['vault']['settings']['medication_groups']=set_group_rule([],r,'other')
    equip(app,monkeypatch);app.admin_page(None)
    key='group_rule_mode_0';ss[key]='auto'
    app.update_group_admin((r['name'].lower(),r['route'].lower(),r['frequency'].lower()),key,None)
    assert ss['vault']['settings']['medication_groups']==[]
    assert not ss['drafts']


def test_render_all_group_controls_without_duplicate_keys(app,monkeypatch):
    open_room(app);app.st.session_state['drafts']['P4102']=example_sheet()
    downloads=equip(app,monkeypatch)
    app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)


def test_batch_print_preserves_both_rooms_and_long_cv_list():
    s=example_sheet();s2=new_sheet('P4104')
    s2['medications']=[med('SYNTHETIC_CV_'+str(i),section='Cardiovascular') for i in range(32)]
    reader=PdfReader(BytesIO(handoffs_pdf([s,s2])));t='\n'.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages)>=3 and 'CV Infusions' in t
    for i in range(32):assert 'SYNTHETIC_CV_'+str(i) in re.sub(r'\s+','',t)
    assert 'P4102' in t and 'P4104' in t


def test_gi_override_then_automatic_restores_fever_default(app):
    open_room(app);ss=app.st.session_state;r=med('acetaminophen',frequency='q6h',section='Other Medications')
    ss['drafts']['P4102']['medications']=[r]
    ss['gi_choice']='prophylaxis';app.medication_row_change('P4102',r['id'],'gi_mode','gi_choice')
    assert effective_section(ss['drafts']['P4102']['medications'][0])=='FEN / GI'
    ss['gi_choice']='auto';app.medication_row_change('P4102',r['id'],'gi_mode','gi_choice')
    row=ss['drafts']['P4102']['medications'][0]
    assert group_for(row)=='fever' and effective_section(row)=='Neurologic'


def test_special_override_then_automatic_restores_gi_default(app):
    open_room(app);ss=app.st.session_state;r=med('famotidine',frequency='q12h',section='Neurologic')
    ss['drafts']['P4102']['medications']=[r]
    ss['special']='fever';app.medication_row_change('P4102',r['id'],'group_mode','special')
    assert group_for(ss['drafts']['P4102']['medications'][0])=='fever'
    ss['special']='auto';app.medication_row_change('P4102',r['id'],'group_mode','special')
    assert effective_section(ss['drafts']['P4102']['medications'][0])=='FEN / GI'


def test_switching_to_explicit_gi_group_clears_conflicting_special_override(app):
    open_room(app);ss=app.st.session_state;r=med('acetaminophen',frequency='q6h')
    ss['drafts']['P4102']['medications']=[r]
    ss['special']='fever';app.medication_row_change('P4102',r['id'],'group_mode','special')
    ss['gi_choice']='bowel';app.medication_row_change('P4102',r['id'],'gi_mode','gi_choice')
    assert effective_section(ss['drafts']['P4102']['medications'][0])=='FEN / GI'
    assert ss['vault']['settings']['medication_groups']==[]
