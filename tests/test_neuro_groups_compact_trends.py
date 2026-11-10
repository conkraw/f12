"""v6.40 presentation regressions. All fixtures are synthetic, not patient records."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import pytest
from pypdf import PdfReader
from cryptography.fernet import Fernet

from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_rooms_infusions import med
from test_last_admin_antiemetics import order
from medication_groups import (automatic_group, group_for, set_group_rule, apply_group_rules,
                               GROUP_NAMES, GROUP_SECTIONS, MODES, validate_group_rules)
from infusions import (system_body_blocks, neuro_body, render_body_blocks, is_infusion)
from fen_gi import effective_section
from labs import parse_labs
from lab_windows import lactate_summary, display_clock
from observations import parse_neuro
from ventilation import parse_ventilation, format_ventilation
from models import new_sheet, new_vault, validate_sheet, fields_with_medications, save_sheet_in
from security import seal_vault, open_vault
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf

NOW = datetime(2026,11,8,22,0,tzinfo=timezone.utc)  # 17:00 EST
NEW = [('dexamethasone','airway_cerebral_steroid'), ('melatonin','insomnia'),
       ('trazodone','insomnia'), ('baclofen','antispasmodic'),
       ('gabapentin','neuromodulation'), ('pregabalin','neuromodulation')]

@pytest.mark.parametrize('name,group', NEW)
@pytest.mark.parametrize('prefix', ['', '[START ON 11/9/2026] ', '[Held by provider] ', 'Followed by: '])
@pytest.mark.parametrize('route', ['Oral','Per NJ Tube'])
def test_requested_defaults_case_labels_source_preserved(name,group,prefix,route):
    row=med(prefix+name.upper()+' synthetic formulation',dose='2 mg',route=route,
            frequency='q12h',rate='',section='Other Medications')
    before=deepcopy(row)
    assert automatic_group(row)==group
    section='Respiratory' if group=='airway_cerebral_steroid' else 'Neurologic'
    assert effective_section(row)==section
    text=render_body_blocks(system_body_blocks(section,'',[row]),True)
    assert '<b>'+GROUP_NAMES[group]+'</b>' in text
    assert row==before

@pytest.mark.parametrize('name', ['dexamethasonex','melatoninase','trazodone-like-extract',
                                'baclofenx','gabapentinx','pregabalinx','mix containing gabapentin'])
def test_unrequested_substring_not_used(name):
    assert automatic_group(med(name,frequency='q12h',section='Other Medications'))==''

@pytest.mark.parametrize('name,route', [('dexamethasone eye drops','Ophthalmic'),
    ('dexamethasone ointment','Topical'),('dexamethasone otic solution','Otic'),
    ('neomycin polymyxin dexamethasone drops','Ophthalmic')])
def test_local_steroids_not_automatically_assigned(name,route):
    row=med(name,route=route,frequency='Daily',section='Other Medications')
    assert not automatic_group(row)

@pytest.mark.parametrize('name,group', NEW)
@pytest.mark.parametrize('mode', ['other','antiepileptic'])
def test_explicit_group_overrides_remain_authoritative(name,group,mode):
    row=med(name,frequency='q12h',section='Respiratory')
    rows=apply_group_rules([row],set_group_rule([],row,mode))
    assert group_for(rows[0])==('' if mode=='other' else 'antiepileptic')
    assert effective_section(rows[0])==('Respiratory' if mode=='other' else 'Neurologic')
    assert row.get('group_mode','auto')=='auto'

@pytest.mark.parametrize('name,group', NEW)
@pytest.mark.parametrize('flag,value', [('hidden',True),('include',False)])
def test_new_category_never_restores_hidden_order(name,group,flag,value):
    row=med(name,frequency='q12h');row[flag]=value
    assert not system_body_blocks('Neurologic','',[row])

@pytest.mark.parametrize('name', ['rocuronium','cisatracurium','vecuronium'])
@pytest.mark.parametrize('frequency,expected', [('Continuous','paralytic_infusion'),
    ('Titrate','paralytic_infusion'),('q1h PRN','paralytic_prn'),('Once','')])
def test_paralytic_routes_to_separate_block_not_sedative_drips(name,frequency,expected):
    row=med(name+' infusion syringe',frequency=frequency,section='Other Medications')
    assert automatic_group(row)==expected
    if expected:
        blocks=system_body_blocks('Neurologic','',[row])
        assert blocks[0]==('heading',GROUP_NAMES[expected])
        assert sum(isinstance(v,dict) and v['id']==row['id'] for _,v in blocks)==1
        assert blocks[1][0]==('infusion' if expected=='paralytic_infusion' else 'medication')


def example_sheet():
    s=new_sheet('P4102')
    s['fields']['Diagnoses']='Synthetic handoff demonstration'
    from anthropometrics import empty_anthropometrics
    s['anthropometrics']=empty_anthropometrics()
    s['anthropometrics']['age']='6 years'
    s['anthropometrics']['sex']='Female'
    s['neuro_vitals']['k']=parse_neuro('Target Arousal Level (SBS): SBS -1','k').rows
    s['neuro_vitals']['l']=parse_neuro('WAT-1 total score (0-12): 0','l').rows
    rows=[
      med('pregabalin NM_Z',dose='1 mg',route='Oral',frequency='q12h',rate=''),
      med('melatonin INS_A',dose='1 mg',route='Oral',frequency='Nightly',rate=''),
      med('levetiracetam AED_A',dose='10 mg',frequency='q12h',rate=''),
      med('dexamethasone STER_A',dose='1 mg',frequency='q6h',rate=''),
      med('baclofen SPASM_A',dose='1 mg',route='Oral',frequency='TID',rate=''),
      med('trazodone INS_B',dose='1 mg',route='Oral',frequency='Nightly',rate=''),
      med('gabapentin NM_A',dose='1 mg',route='Oral',frequency='q8h',rate=''),
      med('acetaminophen FEVER_A',dose='10 mg',route='Oral',frequency='q6h',rate=''),
      med('vecuronium PARA_PRN_A',dose='1 mg',frequency='q1h PRN',rate=''),
      med('cisatracurium PARA_INF_A',dose='1 mcg/kg/min',frequency='Continuous',rate=''),
      med('midazolam SED_PRN_B',dose='1 mg',frequency='q1h PRN',rate=''),
      med('fentanyl SED_PRN_A',dose='1 mcg',frequency='q1h PRN',rate=''),
      order(name='dexmedetomidine SED_INF_A',dose='0-1 mcg/kg/hr',
            admin='0.4 mcg/kg/hr at 11/08/26 1200',section='Neurologic'),
    ]
    s['medications']=rows
    s['fields']['Neurologic']='Synthetic neurologic note'
    s['labs']=parse_labs('LABS:\nComponent\tValue\tDate\nLACTATE\t1.1\t11/08/2026 1400\nLACWB\t1.0\t11/07/2026 1800').data
    s['ventilation']=parse_ventilation('Vent Mode: Pressure Control - Intermittent Mandatory Ventilation\nResp Rate (Set): 12\nPIP Set (cm H2O): 20 cm H2O\nVt Insp ml: Avg: 75 Min: 70 Max: 80\nPEEP (cm H2O): 5 cm H2O').data
    validate_sheet(s)
    return s


def test_neuro_category_order_and_alphabetical_medicines():
    s=example_sheet()
    from sbs_test_helpers import observed
    observed(s, '-1', NOW)
    before=deepcopy(s)
    with display_clock(NOW):
        text=fields_with_medications(s)['Neurologic']
    ordered=['SBS: -1','WAT-1 total score (0-12): 0','\nInfusions\n','\nPRN\n',
        'Paralytic Infusions','Paralytic PRN','Antiepileptic',
        'Antispasmodic','Fever Control','Insomnia','Neuromodulation','Synthetic neurologic note']
    assert [text.index(x) for x in ordered]==sorted(text.index(x) for x in ordered)
    assert text.index('SED_PRN_A')<text.index('SED_PRN_B')
    assert text.index('NM_A')<text.index('NM_Z')
    assert text.index('INS_A')<text.index('INS_B')
    for row in s['medications']:
        assert fields_with_medications(s)[effective_section(row)].count(row['name'])==1
    assert s==before


def test_all_outputs_and_pdf_preserve_order_rates_and_observations():
    s=example_sheet();before=deepcopy(s)
    html=handoff_html(s,NOW);text=handoff_text(s,NOW);pdf=handoff_pdf(s,NOW)
    pdftext='\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
    for output in [html,text,pdftext]:
        for heading in ['Airway/Cerebral Steroids','Antiepileptic','Antispasmodic','Fever Control','Insomnia','Neuromodulation']:
            assert heading in output
        assert 'Observed TV:' in output and 'Observed TVi' not in output and 'Observed TVe' not in output
        assert 'Lactate 1.0' in output and '[11/8/2026]' in output
        assert 'Lactate earliest' not in output and 'Lactate latest' not in output
        assert output.index('Paralytic PRN')<output.index('Airway/Cerebral Steroids')
    assert '<b><u>Last Admin rate: 0.4 mcg/kg/hr</u></b>' in html
    assert s==before
    assert len(PdfReader(BytesIO(pdf)).pages)==1


def test_neuro_taper_same_name_order_not_reversed_by_alphabetical_sort():
    rows=[med('[START ON 11/9/2026] dexamethasone syrup',dose='2 mg',frequency='q12h'),
          med('[START ON 11/10/2026] dexamethasone syrup',dose='1 mg',frequency='q24h')]
    blocks=system_body_blocks('Respiratory','',list(reversed(rows)))
    assert [v['id'] for k,v in blocks if isinstance(v,dict)]==[r['id'] for r in reversed(rows)]


def with_lactates(rows):
    s=new_sheet('P4102')
    r=parse_labs('LABS:\nComponent\tValue\tDate\n'+rows)
    assert not r.error
    s['labs']=r.data
    return s

@pytest.mark.parametrize('rows,expected', [
 ('LACWB\t1.1\t11/08/2026\nLAC\t1.0\t11/08/2026','Lactate 1.0 -> 1.1 [11/8/2026]'),
 ('LAC\t1.0\t11/07/2026\nLACTATEART\t1.1\t11/08/2026','Lactate 1.0 -> 1.1 [11/8/2026]'),
 ('LAC\t1.2\t11/08/2026 0800\nLACWB\t1.0\t11/08/2026 0500\nLACTATEVEN\t1.1\t11/08/2026 1500','Lactate 1.0 -> 1.1 [11/8/2026]'),
 ('LAC\t1.1\t11/08/2026','Lactate 1.1 [11/8/2026]'),
 ('LAC\t0\t11/08/2026','Lactate 0 [11/8/2026]'),
 ('LAC\t1.0\t11/08/2026\nLAC\t1.0\t11/07/2026','Lactate 1.0 -> 1.0 [11/8/2026]'),
 ('LAC\t1.0\t11/06/2026\nLAC\t1.1\t11/08/2026','Lactate 1.1 [11/8/2026]'),
 ('LACTATE\t1.1 mmol/L\t11/08/2026\nLAC\t2.2 mmol/L (H)\t11/07/2026','Lactate 2.2 mmol/L (H) -> 1.1 mmol/L [11/8/2026]'),
 ('LAC\t<0.5\t11/08/2026','Lactate <0.5 [11/8/2026]'),
 ('LAC\tPending\t11/08/2026',''),
 ('LAC\t1.2\t11/09/2026',''),
 ('LAC\t1.2\t11/06/2026',''),
])
def test_compact_lactate_trends(rows,expected):
    s=with_lactates(rows);before=deepcopy(s)
    assert lactate_summary(s,NOW)==expected
    assert s==before


def test_lactate_excluded_latest_and_boundary():
    s=with_lactates('LACTATE\t5\t11/08/2026 1600\nLACWB\t1.1\t11/08/2026 1500\nLAC\t1.0\t11/07/2026 1700\nLAC\t9\t11/07/2026 1659')
    s['labs']['rows'][0]['include']=False
    assert lactate_summary(s,NOW)=='Lactate 1.0 -> 1.1 [11/8/2026]'

@pytest.mark.parametrize('field',['Vt Insp ml','Vt Exp ml','Vt (observed, mL)'])
def test_tv_label_change_does_not_rename_source_fields(field):
    r=parse_ventilation('Vent Mode: Pressure Control - Intermittent Mandatory Ventilation\n'+field+': 72 mL')
    before=deepcopy(r.data)
    assert format_ventilation(r.data)=='Mode: PC-IMV\nObserved TV: 72 mL'
    assert field in r.data['values'] and r.data==before

@pytest.mark.parametrize('mode',['airway_cerebral_steroid','insomnia','antispasmodic','neuromodulation','paralytic_infusion'])
def test_group_rule_roundtrip_and_callbacks(mode,app):
    row=med('Synthetic custom medication',section='Neurologic')
    rules=set_group_rule([],row,mode)
    validate_group_rules(rules)
    changed=apply_group_rules([row],rules)[0]
    v=new_vault();v['settings']['medication_groups']=rules
    s=new_sheet('P4301');s['medications']=[changed]
    v=save_sheet_in(v,s);key=Fernet.generate_key().decode()
    assert open_vault(seal_vault(v,key),key)==v
    open_room(app)
    ss=app.st.session_state;ss['drafts']['P4102']['medications']=[row]
    widget='med_draft_'+row['id']+'_group_mode';ss[widget]=mode
    app.medication_row_change('P4102',row['id'],'group_mode',widget,None)
    assert ss['drafts']['P4102']['medications'][0]['group_mode']==mode
    assert ss['vault']['settings']['medication_groups'][0]['mode']==mode


def test_new_categories_full_ui_smoke(app,monkeypatch):
    open_room(app);app.st.session_state['drafts']['P4102']=example_sheet()
    downloads=equip(app,monkeypatch)
    with display_clock(NOW):app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)


def test_batch_print_each_room_preserves_groups():
    a=example_sheet();b=deepcopy(a)
    b['room']='P4104';b['id']=new_sheet('P4104')['id']
    pdf=handoffs_pdf([a,b],NOW)
    pages=PdfReader(BytesIO(pdf)).pages
    assert len(pages)==2
    for page in pages:
        text=page.extract_text()
        assert 'Neuromodulation' in text and 'Lactate 1.0 -> 1.1 [11/8/2026]' in text


def test_neuro_taper_embedded_product_doses_do_not_reorder_steps():
    rows=[med('dexamethasone (Decadron) 1 mg/mL syringe 2 mg',dose='2 mg',frequency='q6h'),
          med('[START ON 11/9/2026] dexamethasone (Decadron) 1 mg/mL syringe 1 mg',dose='1 mg',frequency='q12h'),
          med('[START ON 11/10/2026] dexamethasone (Decadron) 1 mg/mL syringe 0.5 mg',dose='0.5 mg',frequency='q24h')]
    before=deepcopy(rows)
    blocks=system_body_blocks('Respiratory','',rows)
    assert [v['id'] for k,v in blocks if isinstance(v,dict)]==[r['id'] for r in rows]
    assert rows==before
