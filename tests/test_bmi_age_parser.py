"""Separate BMI measurement age without changing the patient age header."""
from copy import deepcopy

import pytest

from anthropometrics import (
    BMI_AGE_ADULT,
    BMI_AGE_AMBIGUOUS,
    BMI_AGE_CONFLICT,
    BMI_AGE_INCOMPLETE,
    BMI_AGE_UNDER_TWO,
    EDITABLE_FIELDS,
    FIELDS,
    age_months,
    bmi_age_text,
    bmi_output_allowed,
    clean_field,
    empty_anthropometrics,
    extract_age_sex,
    extract_anthropometrics,
    measurements_text,
    resolve_bmi_age,
    validate_anthropometrics,
)
from importing import import_replacement, import_sections
from models import new_sheet, new_vault, validate_sheet


def attrs(age='', bmi_age=None, **values):
    data = empty_anthropometrics()
    data['age'] = age
    if bmi_age is not None:
        data['bmi_age'] = bmi_age
    data.update(values)
    return data


def block(letter, text):
    divider = letter * 20
    return divider + '\n' + text + '\n' + divider


def imported(letter, text, previous=None):
    prefix = {'a': 'Diagnoses:\n1. SYNTHETIC_DIAGNOSIS\n',
              'i': 'NUTRITION:\n', 'n': 'Date of Admission: 11/22/2026\n'}[letter]
    result = import_sections(previous or new_sheet('P4102'), block(letter, prefix + text), new_vault()['settings'])
    assert not result.errors, result.errors
    validate_sheet(result.sheet)
    return result.sheet


@pytest.mark.parametrize('source', [
    'BMI Age: 2 y.o. 1 m.o.',
    'BMI Age:\n2 y.o. 1 m.o.',
    'BMI Age:\n\n2 y.o. 1 m.o.',
    ' BMI   Age:   2 y.o. 1 m.o. ',
])
def test_explicit_bmi_age_is_not_a_general_age(source):
    for parse in (extract_age_sex, extract_anthropometrics):
        result = parse(source)
        assert not result.error
        assert result.values == {'bmi_age': '2 y.o. 1 m.o.'}
        assert age_months(result.values['bmi_age']) == 25
        assert not result.remainder.strip()


@pytest.mark.parametrize('source', [
    'Age: 2 y.o. BMI Age: 2 y.o. 1 m.o. Sex: male',
    'BMI Age: 2 y.o. 1 m.o. Age: 2 y.o. Sex: male',
    'Sex: male BMI Age: 2 y.o. 1 m.o. Age: 2 y.o.',
    'Age:\n2 y.o.\nBMI Age:\n2 y.o. 1 m.o.\nSex:\nmale',
])
@pytest.mark.parametrize('letter', ['a', 'i', 'n'])
def test_distinct_general_and_bmi_ages_import_in_each_supported_section(source, letter):
    sheet = imported(letter, source)
    assert sheet['anthropometrics']['age'] == '2 y.o.'
    assert sheet['anthropometrics']['bmi_age'] == '2 y.o. 1 m.o.'
    assert sheet['anthropometrics']['sex'] == 'Male'
    assert resolve_bmi_age(sheet['anthropometrics']) == (25, '')
    assert 'BMI Age:' not in sheet['fields']['Diagnoses']


def test_inline_diagnosis_suffix_can_include_bmi_age_without_losing_diagnosis():
    source = 'Example diagnosis Age: 2 y.o. BMI Age: 2 y.o. 1 m.o. Sex: male'
    result = extract_age_sex(source, allow_inline_suffix=True)
    assert not result.error
    assert result.remainder == 'Example diagnosis'
    assert result.values == {'age': '2 y.o.', 'bmi_age': '2 y.o. 1 m.o.', 'sex': 'Male'}


@pytest.mark.parametrize('source', ['BMI Age in months: 25', 'BMI Age in months:\n25', 'BMI   Age   in   months: 25'])
def test_explicit_months_label_accepts_a_number(source):
    result = extract_anthropometrics(source)
    assert not result.error
    assert result.values == {'bmi_age': '25 months'}


def test_bmi_measurement_age_alias_and_general_age_labels_stay_distinct():
    result = extract_anthropometrics('Age in months: 26\nAge at BMI measurement: 25 months\nSex: male')
    assert not result.error
    assert result.values == {'age': '26 months', 'bmi_age': '25 months', 'sex': 'Male'}
    assert extract_anthropometrics('Age at measurement: 26 months').values == {'age': '26 months'}


@pytest.mark.parametrize('source', ['BMI Age: 25', 'BMI Age:\n25', 'BMI Age: PRIVATE_SENTINEL'])
def test_unqualified_number_or_unparseable_bmi_age_fails_without_source_in_error(source):
    result = extract_anthropometrics(source)
    assert result.error
    assert 'PRIVATE_SENTINEL' not in result.error
    assert 'age' not in result.values


def test_conflicting_explicit_bmi_ages_fail_instead_of_overwriting():
    result = extract_anthropometrics('BMI Age: 25 months\nBMI Age: 26 months')
    assert result.error


def test_generic_age_is_not_extracted_from_nonpatient_prose():
    for source in ('Delayed bone age: 2 years', 'Maternal BMI Age: 25 months', 'History of BMI Age: 25 months'):
        result = extract_age_sex(source, allow_inline_suffix=True)
        assert not result.error
        assert not result.values
        assert result.remainder == source


def test_optional_field_preserves_original_five_field_records():
    assert FIELDS == ('age', 'sex', 'bmi', 'height', 'bsa')
    assert EDITABLE_FIELDS == FIELDS + ('bmi_age', 'hc_age')
    data = empty_anthropometrics()
    before = deepcopy(data)
    assert set(data) == set(FIELDS)
    validate_anthropometrics(data)
    assert data == before
    data['bmi_age'] = clean_field('bmi_age', '2 y.o. 1 m.o.')
    validate_anthropometrics(data)
    with pytest.raises(ValueError):
        validate_anthropometrics({'bmi_age': '25 months'})
    with pytest.raises(ValueError):
        validate_anthropometrics(dict(data, unknown=''))
    with pytest.raises(ValueError):
        clean_field('bmi_age', '25')


@pytest.mark.parametrize('data,expected', [
    (attrs('25 months'), 25),
    (attrs('2 y.o.', '2 y.o. 1 m.o.'), 25),
    (attrs('', '25 months'), 25),
    (attrs('26 months', '25 months'), 25),
    (attrs('25 months', '25 months'), 25),
    (attrs('3 years', '25 months'), 25),
    (attrs('2 years', '35.999 months'), 35.999),
    (attrs('19 years', '239.9 months'), 239.9),
    (attrs('26 months', ''), 26),
])
def test_resolver_prefers_documented_bmi_age_and_allows_older_measurement_age(data, expected):
    assert resolve_bmi_age(data) == (expected, '')


@pytest.mark.parametrize('data,reason', [
    (attrs('', ''), BMI_AGE_INCOMPLETE),
    (attrs('2 years'), BMI_AGE_INCOMPLETE),
    (attrs('25 months', '2 years'), BMI_AGE_INCOMPLETE),
    (attrs('25 months', '100 weeks'), BMI_AGE_INCOMPLETE),
    (attrs('1 year', '25 months'), BMI_AGE_UNDER_TWO),
    (attrs('0.5 years', '25 months'), BMI_AGE_UNDER_TWO),
    (attrs('23 months', '25 months'), BMI_AGE_UNDER_TWO),
    (attrs('2 years', '23 months'), BMI_AGE_UNDER_TWO),
    (attrs('', '23 months'), BMI_AGE_UNDER_TWO),
    (attrs('20 years', '239 months'), BMI_AGE_ADULT),
    (attrs('20.0 years', '239 months'), BMI_AGE_ADULT),
    (attrs('19 years', '240 months'), BMI_AGE_ADULT),
    (attrs('', '240 months'), BMI_AGE_ADULT),
    (attrs('104 weeks', '25 months'), BMI_AGE_AMBIGUOUS),
    (attrs('24 months', '25 months'), BMI_AGE_CONFLICT),
    (attrs('2 years', '36 months'), BMI_AGE_CONFLICT),
    (attrs('25 months 2 days', '26 months'), BMI_AGE_CONFLICT),
])
def test_resolver_rejects_incomplete_out_of_range_ambiguous_or_conflicting_inputs(data, reason):
    assert resolve_bmi_age(data) == (None, reason)


def test_bmi_age_text_keeps_the_explicit_string_and_never_mutates_general_age():
    data = attrs('2 y.o.', '2 y.o. 1 m.o.')
    before = deepcopy(data)
    assert bmi_age_text(data) == '2 y.o. 1 m.o.'
    resolve_bmi_age(data)
    assert data == before
    assert bmi_age_text(attrs('25 months', '')) == '25 months'


@pytest.mark.parametrize('age,bmi_age,allowed', [
    ('2 years', '25 months', True), ('22 years', '25 months', True),
    ('1 year', '25 months', False), ('23 months', '25 months', False),
    ('0.5 years', '25 months', False),
    ('104 weeks', '25 months', False), ('', '25 months', True),
    ('', '2 years', True), ('', '23 months', False), ('', '', False),
])
def test_bmi_display_keeps_current_age_gate_with_explicit_bmi_age_fallback(age, bmi_age, allowed):
    assert bmi_output_allowed(attrs(age, bmi_age)) is allowed


def test_explicit_bmi_age_is_reviewable_next_to_the_bmi():
    data = attrs('2 y.o.', '2 y.o. 1 m.o.', sex='Male', bmi='11.9 kg/m²')
    text = measurements_text(data)
    assert text.startswith('BMI: 11.9 kg/m²\nBMI Age: 2 y.o. 1 m.o.\n')
    assert text.count('BMI Age:') == 1
    assert data['age'] == '2 y.o.'


def test_successful_nutrition_import_without_bmi_age_clears_stale_optional_value():
    previous = imported('i', 'Age: 2 y.o.\nBMI Age: 25 months\nBMI: 11.9\nSex: male')
    before = deepcopy(previous)
    result = imported('i', 'BMI: 14', previous)
    assert 'bmi_age' not in result['anthropometrics']
    assert result['anthropometrics']['age'] == '2 y.o.'
    assert resolve_bmi_age(result['anthropometrics'])[0] is None
    assert previous == before


def test_explicit_blank_bmi_age_clears_and_keeps_the_optional_field_visible():
    previous = imported('i', 'Age: 2 y.o.\nBMI Age: 25 months\nBMI: 11.9\nSex: male')
    result = imported('i', 'BMI: 14\nBMI Age:', previous)
    assert result['anthropometrics']['bmi_age'] == ''
    assert resolve_bmi_age(result['anthropometrics'])[0] is None


def test_missing_bmi_age_does_not_add_an_empty_optional_field_to_old_records():
    result = imported('i', 'Age: 25 months\nBMI: 14\nSex: male')
    assert set(result['anthropometrics']) == set(FIELDS)


def test_current_a_bmi_age_survives_i_omission_and_i_blank_explicitly_clears_it():
    a = block('a', 'Diagnoses:\n1. SYNTHETIC_DIAGNOSIS\nAge: 2 y.o. BMI Age: 25 months Sex: male')
    for suffix, expected in [('', '25 months'), ('\nBMI Age:', ''), ('\nBMI Age: 26 months', '26 months')]:
        result = import_replacement('P4102', a + '\n' + block('i', 'NUTRITION:\nBMI: 11.9' + suffix), new_vault()['settings'])
        assert not result.errors
        assert result.sheet['anthropometrics']['bmi_age'] == expected
        assert result.sheet['anthropometrics']['age'] == '2 y.o.'


def test_current_n_bmi_age_is_applied_after_i_clears_a_stale_value():
    previous = imported('i', 'Age: 2 y.o.\nBMI Age: 25 months\nBMI: 11.9\nSex: male')
    source = block('i', 'NUTRITION:\nBMI: 12') + '\n' + block('n', 'Date of Admission: 11/22/2026\nBMI Age: 26 months')
    result = import_sections(previous, source, new_vault()['settings'])
    assert not result.errors
    assert result.sheet['anthropometrics']['bmi_age'] == '26 months'


def test_invalid_nutrition_bmi_age_does_not_partially_replace_previous_fields():
    previous = imported('i', 'Age: 2 y.o.\nBMI Age: 25 months\nBMI: 11.9\nSex: male')
    before = deepcopy(previous)
    result = import_sections(previous, block('i', 'NUTRITION:\nBMI: 14\nBMI Age: 25'), new_vault()['settings'])
    assert result.errors
    assert result.sheet['anthropometrics'] == before['anthropometrics']
    assert 'i' in result.sheet['import_warnings']
    assert previous == before


def test_bmi_age_without_general_age_does_not_populate_patient_header_age():
    result = imported('i', 'BMI Age: 25 months\nBMI: 11.9\nSex: male')
    assert result['anthropometrics']['age'] == ''
    assert result['anthropometrics']['bmi_age'] == '25 months'
    assert resolve_bmi_age(result['anthropometrics']) == (25, '')
