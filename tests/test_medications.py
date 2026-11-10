from copy import deepcopy
from pathlib import Path
import json
import uuid
import pytest
from cryptography.fernet import Fernet
from medications import (parse_medications, format_medication, remap, upsert_rule, destination_for,
                         suggested_key, validate_rules, validate_medication, DESTINATIONS)
from parser import parse_smartphrase
from models import (new_sheet,new_vault,apply_medications,apply_diagnoses,fields_with_medications,
                    validate_vault,ValidationError,upgrade_vault,LEGACY_SYSTEMS,save_sheet_in)
from security import generate_key,open_vault,seal_vault
from exports import handoff_html,handoff_text,handoff_pdf

SAMPLE=Path(__file__).parents[1]/'examples'/'synthetic_smartphrase.txt'


def sample():
    return parse_medications(parse_smartphrase(SAMPLE.read_text()).blocks['b'])


def single(name='Example medication injection 5 mg',dose='5 mg',route='Intravenous',freq='q6h',rate=''):
    line='\t'.join([name,dose,route,freq,'PROVIDER_PRIVATE_SENTINEL',rate,'ADMIN_PRIVATE_SENTINEL'])
    return parse_medications('Medications:\n• '+line)


def test_sample_detects_nine_orders():
    r=sample()
    assert not r.error and len(r.rows)==9
    assert all(row['section']=='Other Medications' for row in r.rows)


def test_provider_and_last_admin_never_retained():
    r=single(rate='25 mL/hr at 01/01/26 1200')
    assert 'PRIVATE_SENTINEL' not in json.dumps(r.rows)
    assert r.rows[0]['rate_time']=='01/01/26 1200'


def test_repeated_dose_at_end_of_title_not_duplicated():
    out=format_medication(single().rows[0])
    assert out.count('5 mg')==1
    assert out=='Example medication injection 5 mg | Intravenous | q6h'


def test_ordered_weight_based_dose_not_replaced_by_title_amount():
    row=single(name='cefTRIAXone syringe 500 mg',dose='50 mg/kg (Dosing Weight)').rows[0]
    assert '500 mg | Dose: 50 mg/kg (Dosing Weight)' in format_medication(row)


def test_blank_topical_dose_not_shifted_into_route():
    row=single(name='lidocaine 4 % cream',dose=' ',route='Topical',freq='PRN').rows[0]
    assert row['dose']=='' and row['route']=='Topical' and row['frequency']=='PRN'
    assert format_medication(row)=='lidocaine 4 % cream | Topical | PRN'


def test_continuous_fluid_blank_dose_uses_rate():
    row=single(name='sodium acetate 60 mEq in 1,000 mL infusion',dose='',freq='Continuous',rate='30 mL/hr at 01/01/26 1200').rows[0]
    assert 'infusion @ 30 mL/hr | Intravenous | Continuous' in format_medication(row)
    assert '01/01/26' not in format_medication(row)
    assert row['rate_time']=='01/01/26 1200'


def test_continuous_weight_based_dose_and_pump_rate_kept_separate():
    row=single(name='Example sedative infusion',dose='0.1 mg/kg/hr (Dosing Weight)',freq='Continuous',rate='2 mL/hr at 01/01/26 1200').rows[0]
    out=format_medication(row)
    assert 'Dose: 0.1 mg/kg/hr (Dosing Weight)' in out and '@ 2 mL/hr' in out


def test_rate_equal_to_dose_not_duplicated():
    row=single(name='Example fluid infusion',dose='10 mL/hr',freq='Continuous',rate='10 mL/hr at 01/01/26 1200').rows[0]
    assert format_medication(row).count('10 mL/hr')==1


def test_zero_rate_does_not_discontinue_order():
    row=single(freq='Continuous',rate='0 mL/hr at 01/01/26 1200').rows[0]
    assert '@ 0 mL/hr' in format_medication(row)
    assert 'discontinued' not in format_medication(row).lower()
    assert any('zero' in w for w in row['warnings'])


def test_intermittent_rate_not_shown_as_dose_or_stopped():
    row=single(freq='q6h',rate='0 mL/hr at 01/01/26 1200').rows[0]
    assert '@' not in format_medication(row) and '5 mg' in format_medication(row)


def test_unrecognized_rate_never_invented():
    row=single(dose='',freq='Continuous',rate='Stopped').rows[0]
    assert row['last_rate']==''
    assert row['warnings']
    assert '@' not in format_medication(row)


def test_prn_and_scheduled_stay_separate():
    r=sample()
    albuterol=[row for row in r.rows if row['name'].startswith('albuterol')]
    assert len(albuterol)==2
    assert {row['frequency'] for row in albuterol}=={'q2h PRN','q4h'}


def test_identical_rows_not_silently_deduplicated():
    row='• med\t1 mg\tIntravenous\tq4h\tProvider\t\t'
    r=parse_medications('Medications:\n'+row+'\n'+row)
    assert len(r.rows)==2 and len({x['id'] for x in r.rows})==2


def test_missing_tabs_blocks_entire_import():
    r=parse_medications('Medications:\n• med 1 mg Intravenous q4h Provider')
    assert r.error and not r.rows


def test_partial_bad_row_does_not_become_successful_import():
    good='• med\t1 mg\tIntravenous\tq4h\tProvider\t\t'
    r=parse_medications('Medications:\n'+good+'\n• cannot split this row')
    assert len(r.rows)==1 and r.error


def test_wrapped_name_before_dose_column():
    r=parse_medications('Medications:\n• sodium acetate in dextrose\nand sodium chloride infusion\t\tIntravenous\tContinuous\tProvider\t30 mL/hr at 01/01/26 1200\t')
    assert not r.error and len(r.rows)==1
    assert r.rows[0]['name']=='sodium acetate in dextrose and sodium chloride infusion'


def test_trailing_empty_cells_may_be_missing():
    r=parse_medications('Medications:\n• med\t1 mg\tIntravenous\tq4h')
    assert not r.error and r.rows[0]['last_rate']==''


def test_header_only_is_not_order():
    r=parse_medications('Medications:\nCurrent Facility-Administered Medications\nMedication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin')
    assert r.error and not r.rows


def test_explicit_no_medications_requires_empty_confirmation():
    r=parse_medications('Medications:\nNo current facility-administered medications.')
    assert not r.error and r.empty_confirmed and not r.rows


def test_conflicting_none_and_orders_rejected():
    r=parse_medications('Medications:\nNone\n• med\t1 mg\tIntravenous\tq4h')
    assert r.error


def test_bad_route_detected_without_guessing():
    r=single(route='')
    assert r.error


def test_too_many_columns_rejected():
    r=parse_medications('Medications:\n• med\t1\t2\t3\t4\t5\t6\t7')
    assert r.error


@pytest.mark.parametrize('name,key',[('acetaminophen injection 120 mg','acetaminophen'),
    ('albuterol (Example) 2.5 mg','albuterol'),('sodium acetate 60 mEq in dextrose','sodium acetate'),
    ('heparin flush 10 units/mL','heparin flush'),('midazolam NCS (Neo/Ped) injection','midazolam')])
def test_generic_mapping_suggestions(name,key):
    assert suggested_key(name)==key


def test_mapping_case_insensitive_and_dose_independent():
    rules=upsert_rule([], 'ACETAMINOPHEN', 'Neurologic')
    assert destination_for('acetaminophen injection 120 mg',rules)=='Neurologic'
    assert destination_for('acetaminophen injection 200 mg',rules)=='Neurologic'


def test_no_substring_or_near_name_matching():
    rules=upsert_rule([], 'albuterol', 'Respiratory')
    assert destination_for('levalbuterol nebulizer',rules)=='Other Medications'
    assert destination_for('albuterolx',rules)=='Other Medications'


def test_specific_prefix_takes_priority():
    rules=upsert_rule([], 'heparin', 'Hematology')
    rules=upsert_rule(rules, 'heparin flush', 'Other Medications')
    assert destination_for('heparin flush 10 units/mL',rules)=='Other Medications'
    assert destination_for('heparin infusion 50 units/mL',rules)=='Hematology'


def test_exact_rule_takes_priority():
    rules=upsert_rule([], 'drug', 'Neurologic')
    rules=upsert_rule(rules, 'drug infusion', 'Respiratory','exact')
    assert destination_for('drug infusion',rules)=='Respiratory'
    assert destination_for('drug infusion 10 mg',rules)=='Neurologic'


def test_unknown_goes_other_medications():
    assert destination_for('unknown preparation',[])=='Other Medications'


def test_rule_update_not_duplicate():
    rules=upsert_rule([], 'acetaminophen','Neurologic')
    rules=upsert_rule(rules,'Acetaminophen','Other Medications')
    assert len(rules)==1 and rules[0]['destination']=='Other Medications'


def test_no_patient_doses_in_rule_structure():
    rules=upsert_rule([], 'acetaminophen','Neurologic')
    assert set(rules[0])=={'name','match','destination'}


@pytest.mark.parametrize('bad',[{'name':'drug','match':'fuzzy','destination':'Neurologic'},
    {'name':'drug','match':'prefix','destination':'Unknown'}, {'name':'','match':'prefix','destination':'Neurologic'},
    {'name':'drug','match':'prefix','destination':'Neurologic','raw_paste':'bad'}])
def test_bad_rule_rejected(bad):
    with pytest.raises(ValueError): validate_rules([bad])


def test_medication_list_replace_preserves_notes_and_no_accumulation():
    s=new_sheet('P4102')
    s['fields']['Respiratory']='Keep this note'
    s=apply_medications(s,sample().rows)
    s2=apply_medications(s,sample().rows)
    assert len(s2['medications'])==9
    assert s2['fields']['Respiratory']=='Keep this note'


def test_remapping_preserves_dose_and_custom_text():
    rows=sample().rows
    rows[0]['custom_text']='Edited practice wording'
    moved=remap(rows,upsert_rule([],'acetaminophen','Neurologic'))
    assert moved[0]['dose']==rows[0]['dose'] and moved[0]['custom_text']==rows[0]['custom_text']
    assert rows[0]['section']=='Other Medications'


def test_excluded_order_does_not_export():
    rows=single(name='EXCLUDED_SENTINEL').rows
    rows[0]['include']=False
    s=apply_medications(new_sheet('P4102'),rows)
    assert 'EXCLUDED_SENTINEL' not in handoff_text(s)
    assert 'EXCLUDED_SENTINEL' not in handoff_html(s)


def test_medication_raw_paste_or_provider_field_not_allowed():
    row=single().rows[0]
    row['provider']='PRIVATE'
    with pytest.raises(ValueError): validate_medication(row)


def legacy_vault():
    v={'schema':1,'settings':{'diagnoses_destination':'Diagnoses','rooms':['P4102']},'rooms':{}}
    v['rooms']['P4102']={'id':uuid.uuid4().hex,'room':'P4102','created_at':'2026-01-01','updated_at':None,
        'fields':{k:('LEGACY_NOTE' if k=='Diagnoses' else '') for k in LEGACY_SYSTEMS}}
    return v


def test_legacy_upgrade_keeps_every_note_and_id():
    old=legacy_vault()
    new=upgrade_vault(old)
    assert new['schema']==34 and old['schema']==1
    assert new['rooms']['P4102']['id']==old['rooms']['P4102']['id']
    for key,value in old['rooms']['P4102']['fields'].items():
        assert new['rooms']['P4102']['fields'][key]==value
    assert new['settings']['medication_mappings']==[]


def test_legacy_ciphertext_loads_with_existing_key():
    key=generate_key()
    token=Fernet(key.encode()).encrypt(json.dumps(legacy_vault()).encode())
    loaded=open_vault(token,key)
    assert loaded['schema']==34
    assert 'LEGACY_NOTE' in handoff_text(loaded['rooms']['P4102'])


def test_unknown_legacy_field_rejected_not_dropped():
    old=legacy_vault()
    old['rooms']['P4102']['fields']['unexpected']='preserve me'
    with pytest.raises(ValidationError): upgrade_vault(old)


def test_mapping_and_meds_encrypted_roundtrip():
    v=new_vault()
    v['settings']['medication_mappings']=upsert_rule([],'acetaminophen','Neurologic')
    s=apply_medications(new_sheet('P4102'),remap(sample().rows,v['settings']['medication_mappings']))
    v=save_sheet_in(v,s)
    key=generate_key()
    cipher=seal_vault(v,key)
    assert b'acetaminophen' not in cipher and b'P4102' not in cipher
    assert open_vault(cipher,key)==v


def test_html_is_landscape_with_all_column_headers_and_bands():
    html=handoff_html(apply_medications(new_sheet('P4102'),sample().rows))
    assert 'letter landscape' in html
    for header in ['PATIENT','NEURO','RESP','CARDIAC','FEN / GI','HEME','ID']:
        assert '<th>'+header+'</th>' in html
    for label in ['Other Medications','Goals / Follow-up','Airway','Last Intubation','Access','Drains / Tubes']:
        assert label in html


def test_medication_html_is_escaped():
    row=single().rows[0]
    row['custom_text']='<script>PRIVATE</script>'
    html=handoff_html(apply_medications(new_sheet('P4102'),[row]))
    assert '<script>PRIVATE' not in html and '&lt;script&gt;' in html


def test_pdf_landscape_and_all_nine_orders():
    fitz=pytest.importorskip('fitz')
    pdf=handoff_pdf(apply_medications(new_sheet('P4102'),sample().rows))
    doc=fitz.open(stream=pdf,filetype='pdf')
    text=' '.join(p.get_text() for p in doc)
    assert all(page.rect.width==792 and page.rect.height==612 for page in doc)
    assert text.count('albuterol')==2 and 'q2h PRN' in text and 'q4h' in text
    assert '30 mL/hr' in text and 'Provider' not in text


def test_long_column_continues_without_losing_text():
    fitz=pytest.importorskip('fitz')
    s=new_sheet('P4102')
    tokens=[f'NEUROTOKEN{i:04d}' for i in range(220)]
    s['fields']['Neurologic']='\n'.join(tokens)
    doc=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    text=' '.join(p.get_text() for p in doc)
    assert len(doc)>1
    for token in tokens: assert text.count(token)==1
    for page in doc:
        for block in page.get_text('blocks'):
            assert block[0]>=0 and block[1]>=0 and block[2]<=page.rect.width+1 and block[3]<=page.rect.height+1


def test_long_bottom_bands_and_access_continue():
    fitz=pytest.importorskip('fitz')
    s=new_sheet('P4102')
    for section,prefix in [('Other Medications','MEDTOKEN'),('Lab Results / Trends','LABTOKEN'),('Airway','AIRWAYTOKEN'),('Tasks','TASKTOKEN')]:
        s['fields'][section]='\n'.join(f'{prefix}{i:04d}' for i in range(60))
    doc=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    text=' '.join(p.get_text() for p in doc)
    assert len(doc)>1
    for prefix in ['MEDTOKEN','LABTOKEN','AIRWAYTOKEN','TASKTOKEN']:
        for i in range(60): assert text.count(f'{prefix}{i:04d}')==1


@pytest.mark.parametrize('title,dose', [('drug injection 190 mg','90 mg'), ('drug injection 0.5 mg','5 mg'), ('drug injection 15 mg','5 mg')])
def test_different_numeric_suffix_is_not_duplicate_dose(title,dose):
    row=single(name=title,dose=dose).rows[0]
    assert 'Dose: '+dose in format_medication(row)
