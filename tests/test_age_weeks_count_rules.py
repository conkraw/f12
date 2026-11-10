"""v6.34 regressions. Synthetic metadata and laboratory data only."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfReader
from anthropometrics import (clean_field, age_bounds, age_months, bmi_output_allowed,
                             empty_anthropometrics, extract_age_sex)
from cbc import parse_cbc, cbc_cards
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf
from importing import import_sections
from lab_windows import display_clock
from labs import parse_labs
from models import new_sheet, new_vault, upgrade_vault, validate_sheet
from problem_review import (suggestions, review_text, empty_review, set_decision,
                            limitation_notes, _is_low)
from security import generate_key, seal_vault, open_vault

NOW = datetime(2026, 11, 8, 23, 0, tzinfo=timezone.utc)


def block(letter, body):
    return letter * 25 + '\n' + body + '\n' + letter * 25


def metadata(age='5 wk.o.', sex='male', kind='split'):
    if kind == 'inline':
        return f'Age: {age} Sex: {sex}'
    if kind == 'split':
        return f'Age:\n{age}\n\nSex:\n{sex}'
    return f'Age:\n\n\t{age}\n\nSex:\n\n\t{sex}'


def age_sheet(age='5 wk.o.', sex='male', kind='split', section='a'):
    heading = {'a': 'Diagnoses:\n1. Synthetic condition', 'i': 'NUTRITION:',
               'n': 'Date of Admission: 11/01/2026'}[section]
    r = import_sections(new_sheet('P4201'), block(section, heading+'\n'+metadata(age, sex, kind)),
                        new_vault()['settings'])
    assert not r.errors, r.errors
    return r.sheet


def cbc_sheet(hgb='10.9*', platelets='174*', hgb_unit='g/dL', plt_unit='K/uL'):
    s = new_sheet('P4201')
    s['admission_date'] = '11/01/2026'
    result = parse_cbc('Results from last 7 days\nLab\tUnits\t11/08/26\n1200\n'
        f'WBC AUTO\tK/uL\t5.2\nHEMOGLOBIN\t{hgb_unit}\t{hgb}\n'
        f'HEMATOCRIT\t%\t31.9\nPLATELETS AUTO\t{plt_unit}\t{platelets}')
    assert not result.error, result.error
    s['cbc'] = result.data
    return s


def keys(s):
    return {x['key'] for x in suggestions(s, NOW)}


@pytest.mark.parametrize('age', ['5 wk.o.', '5 wk.o', '5 wks.o.', '5 WK.O.',
                                '5 wk. o.', '5 w.o.', '5 weeks', '5 wk.o. 2 d.o.'])
@pytest.mark.parametrize('kind', ['inline', 'split', 'blank_lines'])
def test_week_old_spellings_and_multiline_labels(age, kind):
    s = age_sheet(age, kind=kind)
    assert s['anthropometrics']['age'] == age
    assert s['anthropometrics']['sex'] == 'Male'
    assert s['fields']['Diagnoses'] == 'Synthetic condition'
    assert age_bounds(age)[1] < 24
    assert age_months(age) is None
    assert not bmi_output_allowed(s['anthropometrics'])
    validate_sheet(s)


@pytest.mark.parametrize('section', ['a', 'i', 'n'])
@pytest.mark.parametrize('sex,normalized', [('male','Male'), ('female','Female'), ('M','Male'), ('F','Female')])
def test_week_old_age_with_separate_sex_in_each_supported_section(section, sex, normalized):
    s = age_sheet(sex=sex, section=section)
    assert s['anthropometrics']['age'] == '5 wk.o.'
    assert s['anthropometrics']['sex'] == normalized


@pytest.mark.parametrize('age,allowed', [('23 mo.o.',False), ('24 mo.o.',True),
    ('1 yr.o.',False), ('2 yr.o.',True), ('6 yrs.o.',True), ('12 mos.o.',False)])
def test_other_unambiguous_epic_age_abbreviations(age, allowed):
    assert clean_field('age',age) == age
    attrs = empty_anthropometrics()
    attrs.update(age=age, sex='Male', bmi='17 kg/m²')
    assert bmi_output_allowed(attrs) is allowed


@pytest.mark.parametrize('text', ['Age: five wk.o. Sex: male', 'Age: 5 wk.op. Sex: male',
    'Age: 5 wk.o.\nAge: 7 wk.o.\nSex: male', 'Age: 5 wk.o. Sex: unexpected'])
def test_invalid_or_conflicting_metadata_still_rejected(text):
    assert extract_age_sex(text).error


def test_demographics_print_once_and_infant_bmi_stays_hidden():
    s = age_sheet()
    s['admission_date'] = '11/01/2026'
    s['anthropometrics'].update(bmi='17 kg/m²', height='55 cm', bsa='0.25 m²')
    with display_clock(NOW):
        for text in (handoff_text(s), handoff_html(s),
                     PdfReader(BytesIO(handoff_pdf(s))).pages[0].extract_text()):
            assert text.index('Room: P4201') < text.index('Age: 5 wk.o.') < text.index('Sex: Male')
            assert text.index('Sex: Male') < text.index('Admission:')
            assert text.count('Age: 5 wk.o.') == 1 and text.count('Sex: Male') == 1
            assert 'BMI:' not in text and 'Synthetic condition' in text


@pytest.mark.parametrize('value,expected', [('11.49*',True),('11.5*',False),('11.51*',False),
    ('8.0*',True),('0*',True),('8.0',False),('13.0*',False),('11.5',False),
    ('<11.5*',True),('>10*',False)])
def test_hgb_strict_threshold_and_required_asterisk(value, expected):
    s = cbc_sheet(hgb=value, platelets='200')
    assert ('HGB' in keys(s)) is expected


@pytest.mark.parametrize('value,expected', [('174*',True),('174.9*',True),('175*',False),
    ('176*',False),('0*',True),('90*',True),('90',False),('460*',False),
    ('<175*',True),('>90*',False)])
def test_platelets_strict_threshold_and_required_asterisk(value, expected):
    s = cbc_sheet(hgb='13', platelets=value)
    assert ('PLT' in keys(s)) is expected


@pytest.mark.parametrize('unit', ['K/uL', 'K/µL', 'K/μL', '10^3/uL', 'x10^3/uL', '10^9/L', '×10⁹/L'])
def test_equivalent_platelet_units(unit):
    assert 'PLT' in keys(cbc_sheet(plt_unit=unit))


@pytest.mark.parametrize('unit', ['', 'g/L', 'mmol/L', 'mg/dL'])
def test_unknown_or_different_hgb_units_not_assumed(unit):
    s = cbc_sheet(hgb_unit=unit)
    assert 'HGB' not in keys(s)
    assert any('Hemoglobin:' in x for x in limitation_notes(s,NOW))


@pytest.mark.parametrize('unit', ['', '/uL', '%', 'g/dL'])
def test_unknown_or_different_platelet_units_not_assumed(unit):
    assert 'PLT' not in keys(cbc_sheet(plt_unit=unit))


@pytest.mark.parametrize('key,unit,value', [('HGB','g/dL','10.9*'),('PLT','K/uL','174*')])
def test_g_format_starred_values_with_explicit_units(key,unit,value):
    s = new_sheet('P4201')
    s['admission_date'] = '11/01/2026'
    parsed = parse_labs(f'LABS:\nComponent\tValue\tDate\n{key}\t{value} {unit}\t11/08/2026')
    assert not parsed.error
    s['labs'] = parsed.data
    assert key in keys(s)


def test_low_flags_unchanged_and_other_asterisks_not_treated_as_low():
    s = new_sheet('P4201')
    s['labs'] = parse_labs('LABS:\nComponent\tValue\tDate\nNA\t131*\t11/08/2026\n'
                         'K\t2.6 (L)\t11/08/2026\nHGB\t8.9 (L)\t11/08/2026').data
    assert {'K','HGB'} <= keys(s) and 'NA' not in keys(s)
    assert not any('Hemoglobin:' in n for n in limitation_notes(cbc_sheet(), NOW))


def test_patient_specific_limits_keep_precedence():
    s = cbc_sheet()
    assert {'HGB','PLT'} <= keys(s)
    s['problem_review'] = empty_review()
    s['problem_review']['low_limits'] = {'HGB': {'value':'9','unit':'g/dL'},
                                         'PLT': {'value':'150','unit':'K/uL'}}
    assert not {'HGB','PLT'} & keys(s)


def test_standard_hgb_overrides_newer_low_istat_and_missing_q_does_not_fill():
    s = new_sheet('P4201')
    source = ('Results from last 7 days\nLab\tUnits\t11/08/26\n1400\t11/08/26\n1200\n'
              'WBC AUTO\tK/uL\t -- \t5.2\nHEMOGLOBIN\tg/dL\t -- \t12.4\n'
              'HEMOGLOBIN ISTAT\tg/dL\t8.2*\t -- \nHEMATOCRIT\t%\t25*\t37\n'
              'PLATELETS AUTO\tK/uL\t -- \t230')
    result = parse_cbc(source)
    assert not result.error
    s['cbc'] = result.data
    assert not keys(s)
    assert cbc_cards(s['labs'],s['cbc'])[0]['rows']['HGB']['value'] == '12.4'
    s['cbc']['rows'] = [r for r in s['cbc']['rows'] if r['component'] != 'HEMOGLOBIN']
    assert 'HGB' in keys(s)


def test_newer_normal_counts_supersede_older_flagged_counts():
    s = cbc_sheet()
    for row in list(s['cbc']['rows']):
        old = deepcopy(row)
        old.update(date='11/07/26 1200',column=1,id=uuid4().hex)
        s['cbc']['rows'].append(old)
        if row['component'] == 'HEMOGLOBIN': row['value'] = '12.4'
        if row['component'] == 'PLATELETS AUTO': row['value'] = '230'
    assert not keys(s)


def test_excluded_cells_and_failed_q_cannot_trigger():
    s = cbc_sheet()
    for row in s['cbc']['rows']: row['include'] = False
    assert not keys(s)
    from import_review import diagnostic
    s = cbc_sheet()
    s['import_warnings']['q'] = [diagnostic('q','section_parse_failed')]
    assert not keys(s)


def test_ambiguous_or_malformed_numeric_values_not_guessed():
    for text in ['8.5 | 9.5*','pending*','nan*','--','-1*']:
        for key,unit in [('HGB','g/dL'),('PLT','K/uL')]:
            assert not _is_low({'value':text,'unit':unit}, None, key)[0]


def test_no_auto_possible_prefix_and_no_confirmation_or_diagnosis_mutation():
    from test_windows_problem_review import med
    s = cbc_sheet()
    med(s)
    s['fields']['Diagnoses'] = 'Documented synthetic diagnosis'
    before = deepcopy(s)
    text = review_text(s,NOW)
    assert text == 'Sepsis, Anemia, Thrombocytopenia'
    items = suggestions(s,NOW)
    assert all(r['status']=='review' for r in items)
    assert 'organ dysfunction' in items[0]['caution']
    assert before == s
    for item in items:
        if item['key'] == 'HGB':
            s = set_decision(s,'HGB',item['fingerprint'],'dismissed','Anemia')
    assert review_text(s,NOW) == 'Sepsis, Thrombocytopenia'


def test_new_rules_print_compactly_in_all_outputs():
    s = age_sheet()
    s['cbc'] = cbc_sheet()['cbc']
    before = deepcopy(s)
    with display_clock(NOW):
        for text in (handoff_text(s), handoff_html(s)):
            assert 'Anemia, Thrombocytopenia' in text
            assert 'Possible' not in text and 'configured cutoff' not in text
        for pdf in (handoff_pdf(s), handoffs_pdf([s])):
            pages = PdfReader(BytesIO(pdf)).pages
            assert len(pages) == 1
            text = pages[0].extract_text()
            assert 'Anemia, Thrombocytopenia' in text
            assert 'Possible' not in text and 'configured cutoff' not in text
    assert s == before


def test_encrypted_roundtrip_and_upgrade_preserve_fields():
    vault = new_vault()
    s = age_sheet()
    s['cbc'] = cbc_sheet()['cbc']
    s['updated_at'] = '2026-11-08T22:59:00+00:00'
    vault['rooms']['P4201'] = s
    before = deepcopy(vault)
    assert upgrade_vault(vault) == before and vault == before
    key = generate_key()
    assert open_vault(seal_vault(vault,key),key) == before
