"""Synthetic growth-assessment import, review, export and persistence checks."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import re

import pytest
from pypdf import PdfReader

from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from growth_assessment import assess_growth, malnutrition_severity
from import_review import diagnostic
from importing import import_replacement, import_sections
from models import new_sheet, new_vault, save_sheet_in, upgrade_vault, validate_sheet
from pdf_cache import SessionPdfCache, cached_handoffs_pdf
from problem_review import review_text, set_decision, suggestions
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip


NOW = datetime(2026, 11, 22, 23, 30, tzinfo=timezone.utc)


def block(letter, text):
    return letter * 24 + '\n' + text + '\n' + letter * 24


def source(age='10 months', sex='Male', weight='6.3 kg', height='58 cm',
           bmi='17.54', weight_z='-3.38', dcw='5.1 kg', circumferences=''):
    rows = ['NUTRITION:', 'Wt Readings from Last 1 Encounters:']
    if weight:
        rows.append('11/22/26\t' + weight +
                    (f' (<1%, Z= {weight_z})' if weight_z else ''))
    rows.extend(['Dosing Weight: ' + dcw, 'BMI: ' + bmi,
                 'Height:', 'Length: ' + height, 'BSA: 0.31 m²'])
    if circumferences:
        rows.append(circumferences)
    return (block('a', 'Diagnoses:\n1. Synthetic condition\nAge: ' + age +
                  '\nSex: ' + sex) + '\n' + block('i', '\n'.join(rows)))


def imported(**kwargs):
    result = import_replacement('P4102', source(**kwargs), new_vault()['settings'])
    assert not result.errors, result.errors
    assert result.sheet is not None
    validate_sheet(result.sheet)
    return result.sheet


def bmi_sheet(age='24 months', bmi='14', sex='Male'):
    return imported(age=age, sex=sex, weight='8.2 kg', height='83 cm', bmi=bmi)


def malnutrition_item(sheet):
    return next((r for r in suggestions(sheet, NOW) if r['key'] == 'malnutrition'), None)


def text_from_output(value):
    if isinstance(value, bytes):
        return '\n'.join(page.extract_text() or '' for page in PdfReader(BytesIO(value)).pages)
    return re.sub('<[^>]+>', '', value)


@pytest.mark.parametrize('z,expected', [
    (2.0, ''), (0.0, ''), (-1.0, ''), (-1.649999, ''),
    (-1.65, 'Mild malnutrition'), (-1.999999, 'Mild malnutrition'),
    (-2.0, 'Moderate malnutrition'), (-2.999999, 'Moderate malnutrition'),
    (-3.0, 'Severe malnutrition'), (-5.0, 'Severe malnutrition'),
])
def test_clinician_supplied_cutoffs_use_unrounded_score(z, expected):
    assert malnutrition_severity(z) == expected


def test_infant_uses_wfl_and_never_weight_for_age_z_or_dosing_weight():
    sheet = imported()
    original = deepcopy(sheet)
    result = assess_growth(sheet)
    # WHO boys length 58 cm: L=-0.3521, M=5.418, S=0.0843.
    assert result.metric == 'weight_for_length'
    assert result.z_score == pytest.approx(1.7424453496265564, abs=1e-9)
    assert result.severity == ''
    assert 'Weight-for-length z score: +1.74 (WHO)' == result.display_text
    assert sheet['nutrition']['z_score'] == '-3.38'
    assert sheet['dosing_weight'] == '5.1 kg'
    assert malnutrition_item(sheet) is None
    assert sheet == original


@pytest.mark.parametrize('render', [handoff_text, handoff_html, handoff_pdf])
def test_untyped_weight_chart_score_stays_in_record_but_not_handoff(render):
    sheet = imported(weight_z='-3.38')
    original = deepcopy(sheet)
    output = ' '.join(text_from_output(render(sheet, NOW)).split())
    assert 'Weight-for-length z score: +1.74 (WHO)' in output
    assert 'Z-score:' not in output
    assert '-3.38' not in output
    assert sheet['nutrition']['z_score'] == '-3.38'
    assert sheet == original


def test_on_screen_handoff_shows_the_same_growth_and_circumference_text(app, monkeypatch):
    open_room(app)
    sheet = imported(circumferences='Head Circumference: 42.5 cm (11/20/26 0400 : Example RN)')
    app.st.session_state['drafts']['P4102'] = sheet
    equip(app, monkeypatch)
    seen = []
    app.st.markdown = lambda value, **kwargs: seen.append(value)
    app.handoff_notes(sheet)
    text = re.sub('<[^>]+>', '', '\n'.join(seen))
    assert 'Weight-for-length z score: +1.74 (WHO)' in text
    assert 'Head circumference: 42.5 cm [11/20/26]' in text
    assert '-3.38' not in text


@pytest.mark.parametrize('weight,expected', [
    ('4.7 kg', 'Mild malnutrition'),
    ('4.5 kg', 'Moderate malnutrition'),
    ('4.0 kg', 'Severe malnutrition'),
])
def test_infant_severity_reaches_dynamic_problems_line(weight, expected):
    sheet = imported(weight=weight, weight_z='0.0')
    result = assess_growth(sheet)
    assert result.severity == expected
    item = malnutrition_item(sheet)
    assert item is not None and item['label'] == expected
    assert item['status'] == 'review'
    assert expected in review_text(sheet, NOW)


def test_who_extreme_negative_score_uses_tail_continuation():
    result = assess_growth(imported(weight='4 kg'))
    # Official WHO continuation below -3, independently checked against LMS.
    assert result.z_score == pytest.approx(-3.7267262334375726, abs=1e-9)


@pytest.mark.parametrize('weight,height', [
    ('6300 g', '0.58 m'),
    ('6300 g', '.58 m'),
    ('13.889122517647286 lb', '22.83464566929134 in'),
    ('222.22596028235657 oz', '58 cm'),
])
def test_wfl_explicit_units_convert_to_same_reference_value(weight, height):
    result = assess_growth(imported(weight=weight, height=height))
    assert result.z_score == pytest.approx(1.7424453496265564, abs=1e-8)


def test_recorded_bmi_uses_cdc_month_bin_at_exact_second_birthday():
    result = assess_growth(bmi_sheet())
    # CDC boys 24.5-month row: L=-1.982373595, M=16.54777487, S=0.080127429.
    assert result.metric == 'bmi_for_age'
    assert result.z_score == pytest.approx(-2.473990189978945, abs=1e-9)
    assert result.severity == 'Moderate malnutrition'
    assert result.display_text == 'BMI-for-age z score: -2.47 (CDC)'


def test_bmi_calculation_does_not_reconstruct_bmi_from_dcw_or_weight():
    sheet = bmi_sheet()
    first = assess_growth(sheet)
    sheet['dosing_weight'] = '45 kg'
    sheet['nutrition']['weight'] = '30 kg'
    sheet['anthropometrics']['height'] = '130 cm'
    assert assess_growth(sheet).z_score == first.z_score
    sheet['anthropometrics']['bmi'] = '16 kg/m²'
    assert assess_growth(sheet).z_score == pytest.approx(-0.4344521530604632, abs=1e-9)
    assert malnutrition_item(sheet) is None


@pytest.mark.parametrize('age', ['2 y.o.', '3 years', '19 years'])
def test_whole_year_age_does_not_invent_a_bmi_age(age):
    sheet = bmi_sheet(age=age, bmi='11.9')
    result = assess_growth(sheet)
    assert result.z_score is None
    assert result.reason
    assert result.display_text == ''
    assert malnutrition_item(sheet) is None


@pytest.mark.parametrize('age', ['240 months', '20 years', '22 y.o.'])
def test_no_pediatric_bmi_score_or_malnutrition_for_adults(age):
    sheet = bmi_sheet(age=age, bmi='11.9')
    assert assess_growth(sheet).z_score is None
    assert malnutrition_item(sheet) is None
    assert 'BMI-for-age z score:' not in handoff_text(sheet, NOW)


def test_age_and_sex_changes_choose_only_the_applicable_indicator():
    sheet = imported(age='23 months', weight='4.5 kg', height='58 cm', bmi='14')
    infant = assess_growth(sheet)
    assert infant.metric == 'weight_for_length'
    sheet['anthropometrics']['age'] = '24 months'
    older = assess_growth(sheet)
    assert older.metric == 'bmi_for_age'
    assert older.z_score == pytest.approx(-2.473990189978945, abs=1e-9)
    sheet['anthropometrics']['sex'] = 'Female'
    female = assess_growth(sheet)
    assert female.z_score is not None and female.z_score != older.z_score


@pytest.mark.parametrize('missing', ['age', 'sex', 'height', 'weight', 'included'])
def test_wfl_missing_or_excluded_inputs_never_create_a_problem(missing):
    sheet = imported(weight='4.0 kg')
    if missing in ('age', 'sex', 'height'):
        sheet['anthropometrics'][missing] = ''
    elif missing == 'weight':
        sheet['nutrition'] = None
    else:
        sheet['nutrition']['include'] = False
    assert assess_growth(sheet).z_score is None
    assert malnutrition_item(sheet) is None


@pytest.mark.parametrize('height', ['44.9 cm', '110.1 cm'])
def test_wfl_does_not_extrapolate_outside_reference_lengths(height):
    sheet = imported(weight='4.0 kg', height=height)
    assert assess_growth(sheet).z_score is None
    assert malnutrition_item(sheet) is None


@pytest.mark.parametrize('section', ['a', 'i', 'n'])
def test_failed_demographic_source_suppresses_score_and_problem(section):
    sheet = imported(weight='4.0 kg')
    sheet['import_warnings'][section] = [diagnostic(section, 'section_parse_failed')]
    assert assess_growth(sheet).z_score is None
    assert malnutrition_item(sheet) is None


def test_no_bmi_reconstruction_when_recorded_bmi_missing():
    sheet = bmi_sheet(bmi='')
    assert assess_growth(sheet).z_score is None
    assert malnutrition_item(sheet) is None


def test_dismissal_tracks_full_inputs_even_when_score_display_rounds_the_same():
    sheet = imported(weight='4.5 kg')
    before = malnutrition_item(sheet)
    assert before is not None
    dismissed = set_decision(sheet, before['key'], before['fingerprint'],
                             'dismissed', before['label'])
    assert 'malnutrition' not in review_text(dismissed, NOW).lower()
    old_display = assess_growth(dismissed).display_text
    dismissed['nutrition']['weight'] = '4.500001 kg'
    refreshed = malnutrition_item(dismissed)
    assert refreshed is not None
    assert assess_growth(dismissed).display_text == old_display
    assert refreshed['fingerprint'] != before['fingerprint']
    assert refreshed['status'] == 'review'
    assert 'Moderate malnutrition' in review_text(dismissed, NOW)


def test_improved_measurement_removes_automatic_problem_without_manual_cleanup():
    sheet = imported(weight='4.0 kg')
    item = malnutrition_item(sheet)
    assert item is not None
    sheet = set_decision(sheet, item['key'], item['fingerprint'], 'confirmed', item['label'])
    sheet['nutrition']['weight'] = '5.418 kg'
    assert assess_growth(sheet).z_score == pytest.approx(0.0, abs=1e-10)
    assert malnutrition_item(sheet) is None
    assert 'malnutrition' not in review_text(sheet, NOW).lower()


def test_circumference_source_imports_dates_without_staff_names():
    sheet = imported(circumferences=(
        'Head Circumference: Head Circumference: 42.5 cm (16.73") '
        '(11/20/26 0400 : SYNTHETIC_STAFF_NAME, RN)\n'
        'Abdominal Circumference: 45 cm (11/21/26 0500 : ANOTHER_STAFF, RN)'))
    assert sheet['circumferences']['head'] == {'value_cm': '42.5', 'date': '2026-11-20'}
    assert sheet['circumferences']['abdominal'] == {'value_cm': '45', 'date': '2026-11-21'}
    assert 'STAFF' not in json.dumps(sheet)
    body = handoff_text(sheet, NOW).lower()
    assert 'head circumference: 42.5 cm [11/20/26]' in body
    assert 'abdominal girth: 45 cm [11/21/26]' in body


def test_head_circumference_hidden_at_two_but_abdominal_girth_remains():
    sheet = imported(age='24 months', circumferences=(
        'Head Circumference: 42.5 cm (11/20/26 0400 : SYNTHETIC_STAFF, RN)\n'
        'Abdominal Circumference: 45 cm (11/21/26 0500 : SYNTHETIC_STAFF, RN)'))
    body = handoff_text(sheet, NOW).lower()
    assert 'head circumference:' not in body
    assert 'abdominal girth: 45 cm [11/21/26]' in body


def test_new_i_block_clears_absent_circumferences_in_partial_import():
    old = imported(circumferences='Head Circumference: 42.5 cm\nAbdominal Circumference: 45 cm')
    result = import_sections(old, block('i', 'NUTRITION:\nWeight: 6.3 kg\nLength: 58 cm'),
                             new_vault()['settings'])
    assert not result.errors, result.errors
    assert result.sheet['circumferences'] == {'head': None, 'abdominal': None}


def test_whole_room_replacement_cannot_reuse_growth_or_circumferences():
    old = imported(weight='4 kg', circumferences='Head Circumference: 42.5 cm')
    current = import_replacement('P4102', block('a', 'Diagnoses:\n1. New synthetic condition'),
                                 new_vault()['settings'])
    assert not current.errors
    assert current.sheet['id'] != old['id']
    assert assess_growth(current.sheet).z_score is None
    assert malnutrition_item(current.sheet) is None
    assert 'Head circumference:' not in handoff_text(current.sheet, NOW)


@pytest.mark.parametrize('render', [handoff_text, handoff_html, handoff_pdf])
def test_growth_and_problem_visible_in_every_single_patient_export(render):
    sheet = imported(weight='4.5 kg', circumferences='Head Circumference: 42.5 cm (11/20/26 0400)')
    original = deepcopy(sheet)
    output = ' '.join(text_from_output(render(sheet, NOW)).split())
    assert 'Weight-for-length z score: -2.28 (WHO)' in output
    assert 'Moderate malnutrition' in output
    assert '42.5 cm [11/20/26]' in output
    assert sheet == original


def test_print_all_keeps_age_specific_scores_on_correct_patient_pages():
    infant = imported(weight='4.5 kg')
    older = bmi_sheet()
    older['room'] = 'P4104'
    pages = PdfReader(BytesIO(handoffs_pdf([infant, older], NOW))).pages
    assert len(pages) == 2
    assert 'Weight-for-length z score:' in pages[0].extract_text()
    assert 'BMI-for-age z score:' not in pages[0].extract_text()
    assert 'BMI-for-age z score:' in pages[1].extract_text()
    assert 'Weight-for-length z score:' not in pages[1].extract_text()


def test_pdf_cache_refreshes_changed_growth_only():
    first = imported(weight='4.5 kg')
    second = bmi_sheet()
    second['room'] = 'P4104'
    cache = SessionPdfCache()
    try:
        cached_handoffs_pdf([first, second], cache, NOW)
        assert cache.stats['builds'] == 2
        first['nutrition']['weight'] = '4.0 kg'
        output = cached_handoffs_pdf([first, second], cache, NOW)
        assert cache.stats['builds'] == 3
        pages = PdfReader(BytesIO(output)).pages
        assert 'Severe malnutrition' in pages[0].extract_text()
        assert 'Moderate malnutrition' in pages[1].extract_text()
    finally:
        cache.close()


def test_old_vault_and_new_circumferences_round_trip_without_derived_state():
    old = save_sheet_in(new_vault(), new_sheet('P4102'))
    before = deepcopy(old)
    assert upgrade_vault(old) == before
    assert old == before
    sheet = imported(weight='4.5 kg', circumferences='Head Circumference: 42.5 cm (11/20/26 0400)')
    saved = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    loaded = open_vault(seal_vault(saved, key), key)
    assert loaded == saved
    restored = loaded['rooms']['P4102']
    assert assess_growth(restored).severity == 'Moderate malnutrition'
    assert 'Weight-for-length z score:' not in json.dumps(saved)
    assert 'Moderate malnutrition' not in json.dumps(saved)

