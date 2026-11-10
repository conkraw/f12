"""Synthetic regression cases only. No patient data, credentials or live writes."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import math
import pytest
from pypdf import PdfReader
from anthropometrics import empty_anthropometrics, clean_field, age_months, extract_anthropometrics, validate_anthropometrics
from bmi_reference import percentile_from_parameters, bmi_percentile, bmi_percentile_summary
from fluid_balance import empty_balance, balance_text
from importing import import_sections
from models import new_sheet, new_vault, fields_with_medications, upgrade_vault, SCHEMA_VERSION, validate_sheet
from exports import handoff_html, handoff_pdf, handoff_text
from medications import parse_medications
from medication_groups import group_for, apply_group_rules, validate_group_rules, group_mode_for
from infusions import system_body_blocks
from vitals import parse_vitals, text_by_system
from security import generate_key, seal_vault, open_vault
from batching import available_handoffs
from test_callbacks import app, open_room
from test_ui_smoke import equip


def block(letter, text):
    heading = {'e':'VITALS:', 'i':'NUTRITION:'}.get(letter, '')
    if heading and not text.startswith(heading):
        text = heading + '\n' + text
    return letter*16+'\n'+text+'\n'+letter*16


def imported(letter, text, sheet=None):
    out=import_sections(sheet or new_sheet('P4102'), block(letter,text),new_vault()['settings'])
    assert not out.errors, out.errors
    return out.sheet


def row(name, dose='1 mg', route='Intravenous', freq='q12h'):
    result=parse_medications('Medications:\nMedication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin\n•\t'+ '\t'.join([name,dose,route,freq,'Synthetic Provider','','']),[])
    assert not result.error, result.error
    return result.rows[0]


@pytest.mark.parametrize('field,value,expected',[
 ('age','5 years 2 months','5 years 2 months'),('age','14 months','14 months'),
 ('age','10 days','10 days'),('sex','female','Female'),('sex','M','Male'),
 ('bmi','17.14','17.14 kg/m²'),('bmi','17.14 kg/m².','17.14 kg/m²'),
 ('height','100 cm','100 cm'),('height','1.1 m','1.1 m'),
 ('bsa','0.65 m^2','0.65 m²'),('bsa','1.3 m2','1.3 m²'),
 ('bsa','',''),('bmi','None',''),('age','None',''),
])
def test_explicit_values_only(field,value,expected):
    assert clean_field(field,value)==expected


@pytest.mark.parametrize('field,value',[
 ('age','5'),('age','five years'),('sex','unknown sex'),('height','100'),
 ('bmi','0'),('bmi','nan'),('bmi','inf'),('bsa','29 m/k2'),('bsa','0 m2'),
 ('bsa','29 m2'),('bmi','18 BMI percentile 55'),('height','0 cm'),
])
def test_no_unvalidated_metrics(field,value):
    with pytest.raises(ValueError): clean_field(field,value)


@pytest.mark.parametrize('text,months', [('5 years 2 months',62),('9y 6m',114),('24 months',24),('239.9 months',239.9),('5 years',None),('8 weeks',None),('3 years 14 months',None)])
def test_age_never_invented_months(text,months):
    assert age_months(text)==months


def test_i_extract_keeps_measured_and_dosing_separate():
    s=imported('i','NUTRITION:\n01/02/2026\t10 kg (50%, Z= 0.1)*\n* Growth percentiles are based on CDC (Girls, 2-20 Years) data.\nDosing Weight:\nDosing Weight\nDosing\n8 kg\n3 days ago\nBMI:\nBody mass index is 17.14 kg/m².\nAge: 5 years 2 months\nSex: Female\nHeight: 100 cm\nBSA: 0.65 m²')
    assert s['nutrition']['weight']=='10 kg' and s['dosing_weight']=='8 kg'
    assert s['anthropometrics']==dict(age='5 years 2 months',sex='Female',bmi='17.14 kg/m²',height='100 cm',bsa='0.65 m²')
    text=handoff_text(s)
    assert text.index('Room: P4102') < text.index('Age: 5 years 2 months') < text.index('BMI: 17.14')
    assert 'Weight: 10 kg\nZ-score: 0.1\nDosing weight: 8 kg' in text


def test_no_sex_or_age_inferred_from_weight_footnote():
    s=imported('i','NUTRITION:\n01/02/2026 10 kg (50%, Z= 0.1)*\n* Growth percentiles are based on WHO (Boys, 0-2 years) data.\nBMI:\nBody mass index is 17.14 kg/m².')
    assert not s['anthropometrics']['age'] and not s['anthropometrics']['sex']
    assert 'BMI' not in fields_with_medications(s)['Diagnoses']
    assert 'age/sex needed' in bmi_percentile_summary(s['anthropometrics'])[0]


def test_n_demographics_do_not_confuse_admission_date():
    s=imported('n','Date of Admission: 01/02/2026\nAge: 4 years 2 months\nSex: Male')
    assert s['admission_date']=='01/02/2026'
    assert s['anthropometrics']['age']=='4 years 2 months'


def test_i_reimport_clears_bmi_but_not_manually_entered_age():
    s=imported('i','Age: 4 years 2 months\nBMI: 18\nSex: Male')
    s=imported('i','NUTRITION:\nWeight: 12 kg',s)
    assert not s['anthropometrics']['bmi'] and s['anthropometrics']['age']=='4 years 2 months'


def test_invalid_new_metric_does_not_block_other_sections():
    s=import_sections(new_sheet('P4102'),block('i','BSA: 29 m/k2')+'\n'+block('e','Heart Rate: 100'),new_vault()['settings'])
    assert s.errors and s.sheet['vitals'][0]['value']=='100'
    assert 'i' in s.sheet['import_warnings']


@pytest.mark.parametrize('bmi,age,sex,word',[
 ('17 kg/m²','10 months','Male','<2 years'),
 ('25 kg/m²','20 years','Female','adult'),
 ('17 kg/m²','5 years','Male','age/sex'),
 ('17 kg/m²','62 months','','age/sex'),
])
def test_percentile_gated(bmi,age,sex,word):
    d=empty_anthropometrics();d.update(bmi=bmi,age=age,sex=sex)
    assert word in bmi_percentile_summary(d)[0]


def test_cdc_published_worked_examples_and_median():
    girl=dict(l=-2.257782149,m=16.57626713,s=.132796819,p95=22.3979,sigma=1)
    boy=dict(l=1,m=1,s=1,p95=17.8219,sigma=2.398288)
    assert percentile_from_parameters(21.2,girl)==pytest.approx(92.2414444192)
    assert percentile_from_parameters(22.6,boy)==pytest.approx(99.7683,abs=.0001)
    assert percentile_from_parameters(girl['m'],girl)==pytest.approx(50)
    assert percentile_from_parameters(20,dict(l=0,m=20,s=.1,p95=25,sigma=3))==pytest.approx(50)
    assert bmi_percentile(21.2,114,'Female',{(2,114.5):girl})==pytest.approx(92.2414444192)


@pytest.mark.parametrize('age,sex',[(23.99,'Male'),(240,'Male'),(60,''),(float('nan'),'Female')])
def test_percentile_no_extrapolation(age,sex):
    with pytest.raises(ValueError):bmi_percentile(17,age,sex,{})


def test_missing_reference_does_not_block_sheet_export():
    s=new_sheet('P4102');s['anthropometrics']=dict(age='5 years 2 months',sex='Female',bmi='17.14 kg/m²',height='',bsa='')
    with patch('bmi_reference.load_reference',side_effect=OSError):
        assert 'BMI: 17.14' in handoff_text(s)
        assert 'reference needed' not in handoff_text(s)
        assert 'reference needed' in bmi_percentile_summary(s['anthropometrics'])[0]
        assert handoff_pdf(s).startswith(b'%PDF')


@pytest.mark.parametrize('weight,intake,expected',[
 ('10 kg','100 mL','In: 100 mL (10 mL/kg)'),
 ('8.2 kg','340.25 ml','In: 340.25 ml (41.5 mL/kg)'),
 ('10 kg','0 mL','In: 0 mL (0 mL/kg)'),
 ('10000 g','100 mL','In: 100 mL (10 mL/kg)'),
 ('10 kg','1 L','In: 1 L (100 mL/kg)'),
 ('10 kg','100 cc','In: 100 cc (10 mL/kg)'),
 ('','100 mL','Intake: 100 mL'),('0 kg','100 mL','Intake: 100 mL'),
 ('10 kg','--','Intake: --'),('10 kg','100','Intake: 100'),
])
def test_fluid_calculation_is_display_only(weight,intake,expected):
    data=empty_balance();data.update(intake=intake,output='50 mL',net='50 mL')
    before=deepcopy(data)
    assert expected in balance_text(data,weight)
    assert 'Net: 50 mL' in balance_text(data,weight)
    assert data==before


def test_output_uses_dosing_weight_not_measured_and_no_fallback():
    s=imported('s','Intake 100 mL\nOutput 200 mL\nNet -100 mL')
    s['nutrition']=dict(weight='20 kg',z_score='',include=True)
    assert 'mL/kg' not in fields_with_medications(s)['FEN / GI']
    s['dosing_weight']='10 kg'
    out=fields_with_medications(s)['FEN / GI']
    assert 'In: 100 mL (10 mL/kg)' in out and 'Out: 200 mL (20 mL/kg)' in out
    assert 'Net: -100 mL' in out
    assert handoff_html(s).count('Out: 200 mL (20 mL/kg)')==1


def test_failed_weight_refresh_suppresses_calculation():
    from import_review import diagnostic
    s=imported('s','Intake 100 mL\nOutput 200 mL\nNet -100 mL');s['dosing_weight']='10 kg'
    s['import_warnings']['i']=[diagnostic('i','section_parse_failed',action='not_updated')]
    assert 'mL/kg' not in fields_with_medications(s)['FEN / GI']


@pytest.mark.parametrize('source,section,expected',[
 ('ETCO2 (mmHg) Avg: 45 mmHg Min: 40 mmHg Max: 60 mmHg\nLast ETCO2: ETCO2 (mmHg): 55 mmHg','Respiratory','ETCO2: 40 to 60 mmHg [55]'),
 ('SpO2 Avg: 97.2 % Min: 89 % Max: 100 %\nLast SPO2: SpO2: 100 %','Respiratory','SpO2: 89% to 100% [100]'),
 ('SpO2 Avg: 76.8 % Min: 68 % Max: 86 %\nLast SPO2: SpO2: (!) 80 %','Respiratory','SpO2: 68% to 86% [(!) 80]'),
 ('CVP (mean) Avg: 16.2 mmHg Min: 9 mmHg Max: 22 mmHg\nLast CVP: CVP (mean): 19 mmHg','Cardiovascular','CVP (mean): 9 to 22 mmHg [19]'),
 ('Last CVP: CVP (mean): 0 mmHg','Cardiovascular','CVP: 0 mmHg'),
 ('Last ETCO2: ETCO2 (mmHg): 36 mmHg\nETCO2 (mmHg) Avg: 36 mmHg Min: 36 mmHg Max: 36 mmHg','Respiratory','ETCO2: 36 to 36 mmHg [36]'),
 ('Pulse Ox Avg: 98% Min: 94% Max: 100%\nLast Pulse Ox: 99%','Respiratory','SpO2: 94% to 100% [99]'),
])
def test_range_and_latest(source,section,expected):
    r=parse_vitals(source);assert not r.error
    assert text_by_system(r.rows)[section]==expected
    s=imported('e',source)
    assert expected in fields_with_medications(s)[section]
    assert expected in handoff_text(s)


@pytest.mark.parametrize('text',['Last CVP:','Last ETCO2:','Last SPO2:','Last CVP: No data recorded'])
def test_empty_latest_is_omitted(text):
    r=parse_vitals('Heart Rate: 100\n'+text)
    assert not r.error and len(r.rows)==1


def test_latest_without_range_and_range_without_latest():
    assert text_by_system(parse_vitals('Last ETCO2: 55 mmHg').rows)=={'Respiratory':'ETCO2: 55 mmHg'}
    assert text_by_system(parse_vitals('ETCO2 Avg: 45 mmHg Min: 40 mmHg Max: 60 mmHg').rows)=={'Respiratory':'ETCO2: 40 to 60 mmHg'}


def test_inconsistent_units_not_merged():
    r=parse_vitals('CVP Avg: 10 mmHg Min: 5 mmHg Max: 15 mmHg\nLast CVP: 2 kPa')
    text=text_by_system(r.rows)['Cardiovascular']
    assert '[2]' not in text and 'Last CVP: 2 kPa' in text


def test_conflicting_last_readings_not_guessed():
    r=parse_vitals('Last CVP: 8 mmHg\nLast CVP: 9 mmHg\nCVP Min: 5 mmHg Max: 15 mmHg')
    text=text_by_system(r.rows)['Cardiovascular'];assert '[8]' not in text and '[9]' not in text
    assert 'Last CVP: 8 mmHg' in text and 'Last CVP: 9 mmHg' in text


@pytest.mark.parametrize('name',['phenytoin','fosphenytoin','phenobarbital','cloBAZam (Onfi)','clobozam','levETIRAcetam (Keppra)','valproic acid','pentobarbital'])
def test_antiepileptic_defaults(name):
    r=row(name);assert group_for(r)=='antiepileptic'
    s=new_sheet('P4102');s['medications']=[r]
    neuro=fields_with_medications(s)['Neurologic'];assert 'Antiepileptic' in neuro and name in neuro
    assert fields_with_medications(s)['Other Medications']==''


def test_continuous_pentobarbital_emphasized_in_antiepileptic_once():
    r=row('pentobarbital infusion','1 mg/kg/hr (Dosing Weight)',freq='Continuous')
    blocks=system_body_blocks('Neurologic','',[r])
    assert blocks==[('heading','Antiepileptic'),('infusion',r)]
    s=new_sheet('P4102');s['medications']=[r]
    assert '<b>pentobarbital infusion</b>' in handoff_html(s)
    assert handoff_text(s).count('pentobarbital infusion')==1
    assert '(Dosing Weight)' not in handoff_text(s)


def test_additional_names_and_exact_override():
    rules=[dict(name='lacosamide',route='',frequency='',mode='antiepileptic',match='prefix')]
    validate_group_rules(rules)
    a,b=row('lacosamide injection'),row('lacosamide solution',route='Oral')
    assert all(group_for(r)=='antiepileptic' for r in apply_group_rules([a,b],rules))
    assert group_mode_for(row('lacosamide-like compound'),rules)=='antiepileptic'
    assert group_mode_for(row('lacosamideother'),rules)=='auto'
    rules.append(dict(name='lacosamide injection',route='intravenous',frequency='q12h',mode='other'))
    assert group_mode_for(a,rules)=='other'


def test_schema22_upgrade_and_new_fields_encrypted_roundtrip():
    v=new_vault();v['schema']=22;s=new_sheet('P4102');v['rooms'][s['room']]=s
    before=deepcopy(v);up=upgrade_vault(v)
    assert v==before and up['schema']==32
    assert up['rooms']==before['rooms'] and up['settings']==before['settings']
    up['rooms']['P4102']['anthropometrics']=dict(age='62 months',sex='Female',bmi='17 kg/m²',height='100 cm',bsa='0.65 m²')
    key=generate_key();assert open_vault(seal_vault(up,key),key)==up


def test_optional_metrics_make_room_printable_without_inventing_data():
    s=new_sheet('P4102');s['anthropometrics']=empty_anthropometrics()
    assert available_handoffs(new_vault(),{'P4102':s})=={}
    s['anthropometrics']['age']='3 years 0 months'
    assert 'P4102' in available_handoffs(new_vault(),{'P4102':s})


def test_ui_demographics_snapshot_and_autosave(app,monkeypatch):
    open_room(app);ss=app.st.session_state;s=ss['drafts']['P4102']
    for field,value in dict(age='5 years 2 months',sex='Female',bmi='17.14',height='100 cm',bsa='0.65 m2').items():
        ss['anthro_'+s['id']+'_'+field]=value
    snap=app.editor_snapshot('P4102');assert snap['anthropometrics']['bsa']=='0.65 m²'
    app.save_room(None);assert ss['vault']['rooms']['P4102']['anthropometrics']==snap['anthropometrics']
    equip(app,monkeypatch);app.handoff_page(None)


def test_admin_extra_names_saved_and_applied_without_upload(app,monkeypatch):
    ss=app.st.session_state;ss['antiepileptic_extra_names']='lacosamide\nbrivaracetam'
    app.save_antiepileptic_names(None)
    assert {r['name'] for r in ss['vault']['settings']['medication_groups']}=={'lacosamide','brivaracetam'}
    equip(app,monkeypatch);app.group_admin(None)


def test_new_output_all_formats_do_not_mutate_source():
    s=imported('i','Weight: 12 kg\nDosing Weight: 10 kg\nAge: 5 years 2 months\nBMI: 17.14\nHeight: 100 cm\nBSA: 0.65 m²')
    s=imported('s','Intake 100 mL\nOutput 200 mL\nNet -100 mL',s)
    s=imported('e','ETCO2 Min: 40 mmHg Max: 60 mmHg\nLast ETCO2: 55 mmHg',s)
    s['medications']=[row('levETIRAcetam 10 mg/mL IV syringe','10 mg/kg')]
    before=deepcopy(s);h=handoff_html(s);t=handoff_text(s);pdf=handoff_pdf(s)
    text='\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    for needle in ['Age: 5 years 2 months','BMI: 17.14','Height: 100 cm','Antiepileptic','ETCO2: 40 to 60 mmHg [55]','In: 100 mL (10 mL/kg)']:
        assert needle in h and needle in t and needle in text
    assert s==before


def _test_reference_csv():
    """Artificial structure fixture only. Never saved as a runtime reference."""
    lines=['sex,agemos,L,M,S,sigma,P95']
    for sex in (1,2):
        for month in range(24,240):
            l,m,s,sigma,p95=1,20,.1,3,25
            if (sex,month)==(2,114):l,m,s,p95=-2.257782149,16.57626713,.132796819,22.3979
            if (sex,month)==(1,50):p95,sigma=17.8219,2.398288
            lines.append(','.join(map(str,(sex,month+.5,l,m,s,sigma,p95))))
    return '\n'.join(lines).encode()


def test_reference_validator_requires_complete_table():
    from bmi_reference import parse_reference
    text=_test_reference_csv().decode()
    assert len(parse_reference(text))==432
    with pytest.raises(ValueError):parse_reference(text.rsplit('\n',1)[0])
    with pytest.raises(ValueError):parse_reference(text+'\n'+text.splitlines()[1])
    with pytest.raises(ValueError):parse_reference(text.replace('16.57626713','16.5'))
    with pytest.raises(ValueError):parse_reference(text.replace(',20,',',nan,'))


def test_reference_install_is_atomic_and_keeps_last_good_file(tmp_path,monkeypatch):
    import bmi_reference as ref
    target=tmp_path/'data'/'reference.csv'
    monkeypatch.setattr(ref,'REFERENCE_PATH',target)
    ref.load_reference.cache_clear()
    try:
        content=_test_reference_csv()
        digest=ref.install_reference(content)
        assert len(digest)==64 and target.read_bytes()==content
        assert ref.bmi_percentile(21.2,114,'Female')==pytest.approx(92.2414444192)
        with pytest.raises(ValueError):ref.install_reference(b'sex,agemos\n1,48.5')
        assert target.read_bytes()==content
    finally:ref.load_reference.cache_clear()


def test_reference_request_contains_no_patient_input(tmp_path,monkeypatch):
    import bmi_reference as ref
    import requests
    seen=[]
    class Response:
        content=_test_reference_csv()
        def raise_for_status(self):pass
    def get(url,**kwargs):
        seen.append((url,kwargs));return Response()
    monkeypatch.setattr(requests,'get',get)
    monkeypatch.setattr(ref,'REFERENCE_PATH',tmp_path/'data'/'reference.csv')
    ref.load_reference.cache_clear()
    try:
        ref.download_reference()
        assert seen==[(ref.REFERENCE_URL,{'timeout':(5,15)})]
    finally:ref.load_reference.cache_clear()


def test_new_e_removes_old_last_without_guessing():
    s=imported('e','SpO2 Avg: 97% Min: 90% Max: 100%\nLast SpO2: 99%')
    s=imported('e','SpO2 Avg: 97% Min: 90% Max: 100%\nLast SpO2:',s)
    assert '[99]' not in fields_with_medications(s)['Respiratory']


def test_new_occupant_does_not_keep_age_bmi(app):
    open_room(app);ss=app.st.session_state
    ss['drafts']['P4102']['anthropometrics']=dict(age='62 months',sex='Female',bmi='17 kg/m²',height='',bsa='')
    app.start_new_patient()
    assert not any(ss['drafts']['P4102'].get('anthropometrics',{}).values())


def test_zero_cvp_is_preserved_in_brackets():
    s=imported('e','CVP (mean) Avg: 5 mmHg Min: -1 mmHg Max: 10 mmHg\nLast CVP: CVP (mean): 0 mmHg')
    assert 'CVP (mean): -1 to 10 mmHg [0]' in fields_with_medications(s)['Cardiovascular']
