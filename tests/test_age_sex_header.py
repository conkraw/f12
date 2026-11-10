"""Synthetic regression tests for the inline Epic Age/Sex metadata format."""
from copy import deepcopy
from io import BytesIO
import pytest
from pypdf import PdfReader
from anthropometrics import (age_bounds, age_months, clean_field, empty_anthropometrics,
                             extract_age_sex, bmi_output_allowed)
from importing import import_sections
from models import new_sheet, new_vault, fields_with_medications, upgrade_vault
from parser import parse_smartphrase
from exports import (handoff_html, handoff_text, handoff_pdf, handoffs_pdf,
                     patient_column, patient_markup)
from security import generate_key, seal_vault, open_vault


def block(letter, content):
    return letter * 16 + '\n' + content + '\n' + letter * 16


def import_a(tail, sheet=None, destination='Diagnoses'):
    settings = new_vault()['settings']
    settings['diagnoses_destination'] = destination
    result = import_sections(sheet or new_sheet('P4201'), block('a', 'Diagnoses:\n' + tail), settings)
    assert not result.errors, result.errors
    return result.sheet


@pytest.mark.parametrize('tail', [
    '1. Example diagnosis (CMS/HCC)\nAge: 6 y.o. Sex: female',
    '1. Example diagnosis (CMS/HCC) Age: 6 y.o. Sex: female',
    '1. Example diagnosis (CMS/HCC)\nAge: 6 y.o.\nSex: female',
    '1. Example diagnosis (CMS/HCC)\nSex: female Age: 6 y.o.',
    '1. Example diagnosis (CMS/HCC)\nAge:\n6 y.o.\nSex:\nfemale',
    '1. Example diagnosis (CMS/HCC)\n Age: 6 y.o.\tSex: female ',
    '1. Example diagnosis (CMS/HCC)\nAge: 6 y.o.\u00a0Sex: female',
])
def test_exact_user_format_and_common_whitespace(tail):
    sheet = import_a(tail)
    assert sheet['anthropometrics']['age'] == '6 y.o.'
    assert sheet['anthropometrics']['sex'] == 'Female'
    assert sheet['fields']['Diagnoses'] == 'Example diagnosis (CMS/HCC)'
    assert patient_column(sheet, fields_with_medications(sheet)).startswith(
        'Room: P4201\nAge: 6 y.o.\nSex: Female\n\nDiagnoses:')


@pytest.mark.parametrize('section,heading', [('i', 'NUTRITION:'), ('n','Date of Admission: 11/08/2026')])
@pytest.mark.parametrize('source', ['Age: 6 y.o. Sex: female', 'Age: 6 years Sex: F', 'Sex: female Age: 6 y.o.'])
def test_combined_metadata_also_works_in_i_and_n(section,heading,source):
    result=import_sections(new_sheet('P4201'),block(section,heading+'\n'+source),new_vault()['settings'])
    assert not result.errors
    assert result.sheet['anthropometrics']['sex']=='Female'
    assert age_bounds(result.sheet['anthropometrics']['age'])[0]==72


@pytest.mark.parametrize('age,bounds,months', [
    ('6 y.o.',(72,84),None),('6 y.o',(72,84),None),('6 yo',(72,84),None),
    ('1 y.o.',(12,24),None),('18 m.o.',(18,18),18),('5 y.o. 2 months',(62,62),62),
    ('6 Y.O.',(72,84),None),('24 m.o.',(24,24),24),
])
def test_age_abbreviations_do_not_invent_precision(age,bounds,months):
    assert clean_field('age',age)==age
    assert age_bounds(age)==bounds
    assert age_months(age)==months


@pytest.mark.parametrize('age,allowed', [('1 y.o.',False),('18 m.o.',False),('23 months',False),('2 y.o.',True),('24 m.o.',True),('6 y.o.',True)])
def test_bmi_age_gate_still_works_with_epic_abbreviations(age,allowed):
    attrs=empty_anthropometrics();attrs.update(age=age,sex='Female',bmi='17 kg/m²')
    assert bmi_output_allowed(attrs) is allowed


def test_fields_move_out_of_every_diagnosis_destination():
    sheet=import_a('1. Example diagnosis\nAge: 6 y.o. Sex: female',destination='Neurologic')
    assert sheet['fields']['Neurologic']=='Example diagnosis'
    assert sheet['anthropometrics']['sex']=='Female'


def test_keep_actual_diagnoses_and_all_wrapped_words():
    sheet=import_a('1. First diagnosis with\ncontinuation\nAge: 6 y.o. Sex: female\n2. Second diagnosis')
    assert sheet['fields']['Diagnoses']=='First diagnosis with continuation\nSecond diagnosis'


@pytest.mark.parametrize('text', ['Delayed bone age: 6 years', 'Maternal age: 40 years', 'Sex: female pattern of inheritance'])
def test_nonpatient_or_invalid_metadata_not_silently_discarded(text):
    parsed=extract_age_sex(text,allow_inline_suffix=True)
    if text.startswith('Sex:'):
        assert parsed.error
    else:
        assert parsed.remainder==text and not parsed.values


def test_only_explicit_labels_not_inference():
    sheet=import_a('1. Six-year-old female with example diagnosis')
    assert not sheet.get('anthropometrics')
    assert 'Age: --\nSex: --' in handoff_text(sheet)


def test_metadata_only_a_does_not_erase_diagnoses():
    sheet=new_sheet('P4201');sheet['fields']['Diagnoses']='Existing diagnosis'
    sheet=import_a('Age: 6 y.o. Sex: female',sheet)
    assert sheet['fields']['Diagnoses']=='Existing diagnosis'


def test_missing_metadata_does_not_erase_prior_valid_values():
    sheet=import_a('1. Old diagnosis\nAge: 6 y.o. Sex: female')
    sheet=import_a('1. New diagnosis',sheet)
    assert sheet['anthropometrics']['age']=='6 y.o.'
    assert sheet['fields']['Diagnoses']=='New diagnosis'


@pytest.mark.parametrize('source', ['Age: 6 y.o. Sex: female\nAge: 9 years', 'Age: six years Sex: female', 'Age: 6 y.o. Sex: PRIVATE_SENTINEL'])
def test_conflicts_or_invalid_fields_keep_old_a_and_allow_other_sections(source):
    original=import_a('1. Existing diagnosis\nAge: 5 years Sex: male')
    previous=deepcopy(original)
    result=import_sections(original,block('a','Diagnoses:\n1. New diagnosis\n'+source)+'\n'+block('e','VITALS:\nHeart Rate: 99'),new_vault()['settings'])
    assert result.errors and result.sheet['fields']['Diagnoses']=='Existing diagnosis'
    assert result.sheet['anthropometrics']==previous['anthropometrics']
    assert result.sheet['vitals'][0]['value']=='99'
    assert 'PRIVATE_SENTINEL' not in str(result.errors)
    assert original==previous


def test_reimport_repairs_previously_joined_diagnosis_and_keeps_other_fields():
    sheet=new_sheet('P4201')
    sheet['fields']['Diagnoses']='Example diagnosis Age: 6 y.o. Sex: female'
    sheet['fields']['Goals / Follow-up']='Retain this note'
    sheet['updated_at']='2026-11-08T12:00:00+00:00'
    sheet['anthropometrics']=dict(age='',sex='',height='100 cm',bsa='',bmi='17 kg/m²')
    before=deepcopy(sheet)
    result=import_a('1. Example diagnosis Age: 6 y.o. Sex: female',sheet)
    assert result['fields']['Diagnoses']=='Example diagnosis'
    assert result['fields']['Goals / Follow-up']==before['fields']['Goals / Follow-up']
    assert result['updated_at']==before['updated_at']
    assert result['anthropometrics']['height']=='100 cm'
    assert result['anthropometrics']['bmi']=='17 kg/m²'
    assert sheet==before


def test_text_html_and_pdf_header_order():
    sheet=import_a('1. Example diagnosis (CMS/HCC)\nAge: 6 y.o. Sex: female')
    sheet['admission_date']='11/08/2026'
    fields=fields_with_medications(sheet)
    for text in [handoff_text(sheet),handoff_html(sheet),patient_markup(sheet,fields),patient_column(sheet,fields)]:
        assert text.index('Room: P4201') < text.index('Age: 6 y.o.') < text.index('Sex: Female') < text.index('Admission: 11/08/2026')
        assert text.count('Age: 6 y.o.')==1 and text.count('Sex: Female')==1
    for pdf in [handoff_pdf(sheet),handoffs_pdf([sheet])]:
        reader=PdfReader(BytesIO(pdf));assert len(reader.pages)==1
        text=reader.pages[0].extract_text()
        assert text.index('Room: P4201') < text.index('Age: 6 y.o.') < text.index('Sex: Female') < text.index('Admission: 11/08/2026')
        assert text.count('Age: 6 y.o.')==1 and text.count('Sex: Female')==1


def test_existing_archive_not_rewritten_and_new_fields_roundtrip():
    vault=new_vault();vault['rooms']['P4201']=import_a('1. Example diagnosis\nAge: 6 y.o. Sex: female')
    original=deepcopy(vault)
    assert upgrade_vault(vault)==original and vault==original
    key=generate_key()
    assert open_vault(seal_vault(vault,key),key)==original
