from recovery_helpers import assert_retained
"""Recorded values, incremental imports, dates, migrations, routing and exports."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader
from demographics import (parse_admission, separate_dosing_weight, validate_admission_date,
    validate_dosing_weight, demographic_weight_text)
from observations import parse_nutrition
from parser import parse_smartphrase, SECTION_NAMES
from models import (new_sheet,new_vault,validate_sheet,upgrade_vault,save_sheet_in,
    fields_with_medications,SCHEMA_VERSION,ValidationError)
from importing import import_sections
from labs import parse_labs,result_cards,id_labs_text,canonical,panel_for,labs_text
from lab_layout import card_plan,laboratory_html,laboratory_flowables
from exports import handoff_text,handoff_html,handoff_pdf,handoffs_pdf
from security import seal_vault,open_vault,generate_key
from batching import available_handoffs
from test_callbacks import app,open_room
from test_ui_smoke import equip
ROOT=Path(__file__).parents[1]
I='NUTRITION:\nWt Readings from Last 1 Encounters:\n11/03/26\t73.1 kg\n\nDosing Weight:\nDosing Weight\n Dosing\n 66.8 kg\n 8 days ago\n'
G='''GLUCOSE\t113 (H)\t11/06/2026
GLUCOSE\t102\t11/05/2026
NA\t135 (L)\t11/06/2026
NA\t133 (L)\t11/05/2026
K\t3.9\t11/06/2026
K\t3.8\t11/06/2026
CL\t95 (L)\t11/06/2026
CL\t97 (L)\t11/05/2026
CO2\t28\t11/06/2026
CO2\t29\t11/05/2026
BUN\t14\t11/06/2026
BUN\t19\t11/05/2026
CREATININE\t0.70\t11/06/2026
CREATININE\t0.67 (L)\t11/05/2026
PHOS\t3.9\t11/06/2026
PHOS\t4.2\t11/05/2026
MG\t2.0\t11/06/2026
MG\t2.2\t11/05/2026
ALT\t13\t11/06/2026
AST\t22\t11/06/2026
ALKPHOS\t77\t11/06/2026
BILITOT\t0.8\t11/06/2026
ALBUMIN\t3.1 (L)\t11/06/2026
ALBUMIN\t3.2 (L)\t11/05/2026
PT\t13.9\t11/06/2026
INR\t1.1\t11/06/2026
PTT\t33\t11/06/2026
CRP\t2.76 (H)\t10/11/2026
CRP\t2.7 (H)\t10/09/2026
PROCAL\t0.18 (H)\t11/05/2026
PROCAL\t0.50 (H)\t11/03/2026'''

def block(key,body=''):
    return key*12+'\n'+SECTION_NAMES[key]+':\n'+body+'\n'+key*12

def imp(text,sheet=None):
    out=import_sections(sheet or new_sheet('P4102'),text,new_vault()['settings'])
    assert not out.errors,out.errors
    return out.sheet

def example():
    return imp((ROOT/'examples/synthetic_demographics_labs.txt').read_text())


def test_exact_supplied_measured_and_dosing_values_are_separate():
    parsed=parse_nutrition(I)
    assert not parsed.error
    assert parsed.data=={'weight':'73.1 kg','z_score':'','include':True}
    assert parsed.dosing_weight=='66.8 kg'
    s=imp(block('a','1. Synthetic diagnosis')+'\n'+block('i',I))
    f=fields_with_medications(s)
    assert f['Diagnoses']=='Synthetic diagnosis\n----\nWeight: 73.1 kg\nDosing weight: 66.8 kg'
    assert '8 days ago' not in handoff_text(s)


@pytest.mark.parametrize('source',[
    'Dosing Weight: 66.8 kg','Dosing weight\nDosing\n66.8 kg\n8 days ago',
    'DCW: 66.8 kg','Dose calculation weight: 66.8 kg',
    'Dosing Weight:\n11/03/26\t66.8 kg','Dosing Weight:\n66.8 kg (recorded)'])
def test_dosing_formats_never_replace_measured_weight(source):
    r=parse_nutrition('Weight: 73.1 kg\n'+source)
    assert not r.error and r.data['weight']=='73.1 kg' and r.dosing_weight=='66.8 kg'


@pytest.mark.parametrize('source',['Dosing Weight:','Dosing Weight:\nDosing\n--','Dosing Weight: not documented'])
def test_blank_dosing_does_not_fall_back_to_measured(source):
    r=parse_nutrition('Weight: 73.1 kg\n'+source)
    assert not r.error and r.data['weight']=='73.1 kg' and r.dosing_weight==''


def test_no_measured_weight_is_invented_for_dosing_only():
    r=parse_nutrition('NUTRITION:\nDosing Weight:\nDosing\n66.8 kg\n8 days ago')
    assert not r.error and r.data is None and r.dosing_weight=='66.8 kg'
    s=imp(block('i','Dosing Weight: 66.8 kg'))
    assert fields_with_medications(s)['Diagnoses']=='Dosing weight: 66.8 kg'
    assert 'P4102' in available_handoffs(new_vault(),{'P4102':s})


def test_dosing_before_measured_heading_supported():
    r=parse_nutrition('Dosing Weight: 65 kg\nWt Readings from Last 1 Encounters:\n11/03/26 73.1 kg')
    assert not r.error and r.data['weight']=='73.1 kg' and r.dosing_weight=='65 kg'


@pytest.mark.parametrize('v',['-1 kg','0 kg','66.8','66.8 kg/hr','66.8 kg unknown','abc'])
def test_invalid_dosing_fails_closed(v):
    r=import_sections(new_sheet('P4102'),block('a','1. Synthetic')+'\n'+block('i','Dosing Weight: '+v),new_vault()['settings'])
    assert_retained(r, new_sheet("P4102"), "i")


def test_conflicting_undated_dosing_rejected():
    assert separate_dosing_weight('Dosing Weight:\n66 kg\n67 kg').error


def test_latest_dated_dosing_not_largest():
    r=separate_dosing_weight('Dosing Weight:\n11/03/26 68 kg\n11/05/26 66 kg')
    assert not r.error and r.dosing_weight=='66 kg'


def test_z_score_stays_with_measured_weight_and_dosing_is_between():
    r=parse_nutrition('11/03/26 15.3 kg (66%, Z= 0.41)*\nDosing Weight: 14 kg')
    assert demographic_weight_text(r.data,r.dosing_weight)=='Weight: 15.3 kg\nZ-score: 0.41\nDosing weight: 14 kg'
    r.data['include']=False
    assert demographic_weight_text(r.data,r.dosing_weight)=='Dosing weight: 14 kg'


@pytest.mark.parametrize('date',['10/11/2026','10/11/26','2026-10-11'])
def test_admission_inline_and_multiline(date):
    r=parse_admission('Date of Admission: '+date)
    assert not r.error and r.date==date
    assert parse_admission('Date of Admission:\n'+date).date==date


def test_inline_n_heading_is_accepted_by_divider_parser():
    text='nnnnnnnn\nDate of Admission: 10/11/2026\nnnnnnnnn'
    p=parse_smartphrase(text)
    assert 'n' in p.blocks and 'n' not in p.invalid
    s=imp(text)
    assert s['admission_date']=='10/11/2026'
    assert 'Admission: 10/11/2026' in fields_with_medications(s)['Demographics / Weight']
    assert available_handoffs(new_vault(),{'P4102':s})


@pytest.mark.parametrize('date',['2/30/2026','11/31/26','8 days ago','10/11','10/11/2026 99:99','nonsense'])
def test_invalid_admission_date_is_not_inferred(date):
    assert parse_admission('Date of Admission: '+date).error


def test_conflicting_admission_dates_are_not_guessed():
    assert parse_admission('Date of Admission: 10/11/2026\nDate of Admission: 10/12/2026').error


def test_incomplete_n_divider_fails_without_changing_other_sections():
    original=example();before=deepcopy(original)
    r=import_sections(original,block('a','1. Not applied')+'\nnnnnnnnn\nDate of Admission: 10/11/2026',new_vault()['settings'])
    assert_retained(r, before, "n")
    assert original==before


def test_i_and_n_snapshots_clear_independently():
    s=example()
    changed=imp(block('n'),s)
    assert not changed['admission_date'] and changed['nutrition']==s['nutrition'] and changed['dosing_weight']==s['dosing_weight']
    changed=imp(block('i'),s)
    assert changed['nutrition'] is None and not changed['dosing_weight'] and changed['admission_date']==s['admission_date']
    changed=imp(block('i','Weight: 75 kg'),s)
    assert changed['nutrition']['weight']=='75 kg' and not changed['dosing_weight']


def test_other_imports_preserve_demographics_and_notes():
    s=example();s['fields']['Demographics / Weight']='Manual note'
    changed=imp(block('e','Heart Rate: 80'),s)
    for field in ('nutrition','dosing_weight','admission_date','medications','cultures'):
        assert changed[field]==s[field]
    assert changed['fields']['Demographics / Weight']=='Manual note'


def test_glucose_two_values_and_mg_phos_below_each_bmp():
    data=parse_labs(G).data
    cards=[c for c in result_cards(data) if c['kind']=='bmp']
    assert len(cards)==2
    assert [c['rows']['GLUCOSE']['value'] for c in cards]==['113 (H)','102']
    assert [c['rows']['MG']['value'] for c in cards]==['2.0','2.2']
    assert [c['rows']['PHOS']['value'] for c in cards]==['3.9','4.2']
    h,plan=card_plan(cards[0],180)
    nodes={n[3]:n for n in plan if n[0]=='text'}
    assert nodes['Mg: 2.0 [11/06/26]'][2]<nodes['3.9'][2]
    assert nodes['Phos: 3.9 [11/06/26]'][2]<nodes['Mg: 2.0 [11/06/26]'][2]


@pytest.mark.parametrize('source,want',[('glucose','GLUCOSE'),('GLU','GLUCOSE'),('gluc','GLUCOSE'),('MAGNESIUM','MG'),('mg','MG'),('phosphorus','PHOS'),('PHOSPHATE','PHOS'),('albumin','ALBUMIN'),('alb','ALBUMIN'),('heplmw','HEPLMW'),('PROCALCITONIN','PROCAL')])
def test_names_are_case_insensitive_and_grouped(source,want):
    assert canonical(source)==want
    expected='BMP' if want in ('GLUCOSE','MG','PHOS') else 'Hepatic' if want=='ALBUMIN' else 'Coagulation' if want=='HEPLMW' else 'Inflammatory'
    assert panel_for(source)==expected


def test_albumin_latest_in_hepatic_not_generic_other():
    cards=result_cards(parse_labs(G).data)
    hep=next(c for c in cards if c['title'].startswith('Hepatic'))
    assert hep['rows']['ALBUMIN']['value']=='3.1 (L)'
    assert sum('ALBUMIN' in c['rows'] for c in cards)==1


def test_coag_below_hepatic_and_inflammation_in_id_with_original_dates():
    s=imp(block('g',G)+'\n'+block('e','Temp: 36.9 C'))
    s['admission_date']='10/01/2026'  # v6.30: both marker dates are after admission
    s['fields']['Infectious Disease']='Manual ID note'
    f=fields_with_medications(s)
    text=f['Infectious Disease']
    assert text.startswith('Temp: 36.9 C')
    for part in ['CRP: 2.76 (H) [10/11/26]','PROCAL: 0.18 (H) [11/05/26]']:
        assert part in text
    assert text.index('Inflammatory markers')<text.index('Manual ID note')
    assert 'Coagulation' not in text
    lab=f['Lab Results / Trends']
    assert lab.index('Hepatic') < lab.index('Coagulation')
    for part in ['PT: 13.9 [11/06/2026]', 'INR: 1.1 [11/06/2026]', 'PTT: 33 [11/06/2026]']:
        assert part in lab
    assert 'Inflammatory' not in f['Lab Results / Trends']
    assert '2.7 (H)' not in text and '0.50 (H)' not in text
    assert 'Anti-Xa' not in text  # the user supplied no actual HEPLMW result


def test_synthetic_heplmw_keeps_result_label_and_date_no_units_inferred():
    data=parse_labs(G+'\nheplmw\t0.46\t11/06/2026\nHEPLMW\t0.38\t11/05/2026').data
    t=labs_text(data,include_id_panels=False)
    assert 'HEPLMW' not in id_labs_text(data)
    assert 'Anti-Xa (HEPLMW): 0.46' in t and '0.38' not in t
    assert 'IU' not in t and 'therapeutic' not in t
    assert panel_for('ANTI-XA')=='Coagulation'
    assert canonical('ANTI-XA')!='HEPLMW'


def test_excluding_lab_affects_id_or_bmp_without_deletion():
    s=example()
    for r in s['labs']['rows']:
        if canonical(r['component']) in ('CRP','HEPLMW','MG'):r['include']=False
    assert 'CRP:' not in id_labs_text(s['labs']) and 'HEPLMW' not in labs_text(s['labs'],include_id_panels=False)
    assert all('MG' not in c['rows'] for c in result_cards(s['labs']) if c['kind']=='bmp')
    assert any(r['component']=='CRP' for r in s['labs']['rows'])


def test_saved_old_generic_mg_is_reclassified_without_mutation():
    d=parse_labs('MG\t2.0\t11/06/2026').data
    d['rows'][0]['panel']='Other labs';before=deepcopy(d)
    assert result_cards(d)[0]['kind']=='bmp' and d==before


def test_exports_show_new_values_once_and_stay_landscape():
    s=example()
    reader=PdfReader(BytesIO(handoff_pdf(s)))
    assert len(reader.pages)==1
    pdf='\n'.join(p.extract_text() for p in reader.pages)
    for output in (handoff_html(s),handoff_text(s),pdf):
        for term in ['Admission: 01/01/2026','Weight: 70.2 kg','Dosing weight: 65.4 kg','ALBUMIN','HEPLMW','CRP','PROCAL']:
            assert term in output
        assert '2 days ago' not in output and 'SYNTHETIC_PROVIDER' not in output
        assert output.index('Weight:')<output.index('Dosing weight:')
        assert output.count('Coagulation')==1
    assert float(reader.pages[0].mediabox.width)>float(reader.pages[0].mediabox.height)


def test_two_room_print_and_privacy_boundaries():
    one=example();two=imp(block('a','1. Second synthetic example')+'\n'+block('n','01/02/2026'))
    two['room']='P4104'
    pages=PdfReader(BytesIO(handoffs_pdf([one,two]))).pages
    assert len(pages)==2
    assert '65.4 kg' in pages[0].extract_text() and '65.4 kg' not in pages[1].extract_text()
    assert '01/02/2026' in pages[1].extract_text()


def legacy_v8():
    v=save_sheet_in(new_vault(),example());v['schema']=8;v.pop("reset_generation", None);v["settings"].pop("medication_groups", None);v["settings"].pop("medication_gi_groups", None);v['settings'].pop('medication_infusions', None)
    for s in v['rooms'].values():
        s.pop('sbs_vent_mode', None)  # Not present in the historical schema-8 fixture.
        s.pop("feeds", None);s.pop("devices", None);s.pop("neuro_devices", None);s.pop("pacemaker", None);s.pop("diet", None);s.pop("import_warnings", None);s.pop("intake_output", None);s.pop("recurring_orders", None);s.pop("cbc", None);s.pop('blood_gas', None);s.pop('viral_panel', None);s.pop('admission_date');s.pop('dosing_weight')
    return v


def test_schema8_migration_preserves_all_fields_rules_and_cultures():
    old=legacy_v8();before=deepcopy(old);new=upgrade_vault(old)
    assert new['schema']==32 and old==before and new['settings']==dict(before['settings'], medication_infusions=[], medication_gi_groups=[], medication_groups=[])
    for k,val in before['rooms']['P4102'].items():assert new['rooms']['P4102'][k]==val
    assert new['rooms']['P4102']['admission_date']=='' and new['rooms']['P4102']['dosing_weight']==''
    key=generate_key();encrypted=Fernet(key.encode()).encrypt(json.dumps(old).encode())
    assert open_vault(encrypted,key)==new


def test_new_roundtrip_and_no_raw_dosing_metadata():
    v=save_sheet_in(new_vault(),example());key=generate_key();token=seal_vault(v,key)
    assert open_vault(token,key)==v
    assert '2 days ago' not in str(v) and 'SYNTHETIC_PROVIDER' not in str(v)
    assert b'65.4 kg' not in token and b'01/01/2026' not in token


@pytest.mark.parametrize('field,value',[('dosing_weight','0 kg'),('dosing_weight',[]),('admission_date','2/31/2026'),('admission_date',None)])
def test_bad_saved_new_fields_fail(field,value):
    s=example();s[field]=value
    with pytest.raises(ValidationError):validate_sheet(s)


def test_callbacks_and_editor_remain_separate_for_rooms(app,monkeypatch):
    open_room(app);app.load_demographics_sample();app.create_handoff()
    ss=app.st.session_state
    assert ss['drafts']['P4102']['dosing_weight']=='65.4 kg'
    ss['demo_test']='64 kg';app.demographic_change('P4102','dosing_weight','demo_test')
    assert ss['drafts']['P4102']['nutrition']['weight']=='70.2 kg'
    ss['demo_bad']='2/30/2026';app.demographic_change('P4102','admission_date','demo_bad')
    assert ss['drafts']['P4102']['admission_date']=='01/01/2026'
    downloads=equip(app,monkeypatch);app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)
    open_room(app,'P4104')
    ss['demo_test']='99 kg';app.demographic_change('P4102','dosing_weight','demo_test')
    assert ss['drafts']['P4102']['dosing_weight']=='64 kg'
    assert ss['drafts']['P4104']['dosing_weight']==''


def test_session_upgrade_does_not_drop_cultures_or_unsaved_notes(app):
    old=legacy_v8();ss=app.st.session_state
    ss.update(vault=old,drafts={'P4102':deepcopy(old['rooms']['P4102'])},base_sheets={'P4102':deepcopy(old['rooms']['P4102'])})
    ss['drafts']['P4102']['fields']['Other']='Unsaved example'
    app.upgrade_existing_session()
    assert ss['drafts']['P4102']['fields']['Other']=='Unsaved example'
    assert ss['drafts']['P4102']['cultures']==old['rooms']['P4102']['cultures']
    assert ss['drafts']['P4102']['admission_date']==''
