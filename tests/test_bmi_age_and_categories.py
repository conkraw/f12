"""Synthetic v6.106 BMI measurement-age and high-weight integration checks."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import re

import pytest
from pypdf import PdfReader

from anthropometrics import FIELDS, empty_anthropometrics, validate_anthropometrics
from bmi_reference import bmi_percentile, bmi_percentile_summary, bmi_zscore
from exports import handoff_html, handoff_pdf, handoff_text, patient_header
from growth_assessment import assess_growth
from importing import import_replacement, import_sections
from models import new_sheet, new_vault, save_sheet_in, upgrade_vault, validate_sheet
from pdf_cache import SessionPdfCache
from problem_review import review_text, set_decision, suggestions
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip


NOW = datetime(2026, 11, 23, 0, 30, tzinfo=timezone.utc)


def block(letter, text):
    return letter * 24 + '\n' + text + '\n' + letter * 24


def source(age='2 y.o.', bmi_age='2 y.o. 1 m.o.', bmi='11.9',
           weight='8.2 kg', height='83 cm', weight_z='-4.37',
           circumferences=''):
    identity = ['Diagnoses:', '1. Synthetic condition']
    if age is not None:
        identity.append('Age: ' + age)
    identity.append('Sex: male')
    nutrition = ['NUTRITION:', 'Wt Readings from Last 1 Encounters:',
                 f'11/22/26\t{weight} (<1%, Z= {weight_z})',
                 'Dosing Weight: 7 kg', 'BMI:',
                 'Body mass index is ' + bmi + ' kg/m².']
    if bmi_age is not None:
        nutrition.append('BMI Age: ' + bmi_age)
    nutrition.extend(['Height:', 'Length: ' + height])
    if circumferences:
        nutrition.append(circumferences)
    return block('a', '\n'.join(identity)) + '\n' + block('i', '\n'.join(nutrition))


def imported(**kwargs):
    result = import_replacement('P4102', source(**kwargs), new_vault()['settings'])
    assert not result.errors, result.errors
    assert result.sheet is not None
    validate_sheet(result.sheet)
    return result.sheet


def item(sheet, key):
    return next((row for row in suggestions(sheet, NOW) if row['key'] == key), None)


def export_text(render, sheet):
    output = render(sheet, NOW)
    if isinstance(output, bytes):
        output = '\n'.join(page.extract_text() or '' for page in PdfReader(BytesIO(output)).pages)
    else:
        output = re.sub('<[^>]+>', '', output)
    return ' '.join(output.split())


def test_explicit_epic_bmi_age_does_not_replace_general_age():
    sheet = imported()
    attrs = sheet['anthropometrics']
    assert attrs['age'] == '2 y.o.'
    assert attrs['bmi_age'] == '2 y.o. 1 m.o.'
    assert patient_header(sheet) == 'Room: P4102\nAge: 2 y.o.\nSex: Male'
    growth = assess_growth(sheet)
    assert growth.metric == 'bmi_for_age'
    assert growth.z_score == pytest.approx(-5.73426217561093, abs=1e-10)
    assert growth.severity == 'Severe malnutrition'
    assert growth.weight_category == ''
    assert item(sheet, 'malnutrition')['label'] == 'Severe malnutrition'
    assert item(sheet, 'growth_weight') is None


@pytest.mark.parametrize('bmi_age', ['25 months', '2 years 1 month', '2 y.o. 1 m.o.'])
def test_equivalent_bmi_age_forms_select_same_month(bmi_age):
    growth = assess_growth(imported(bmi_age=bmi_age))
    assert growth.z_score == pytest.approx(-5.73426217561093, abs=1e-10)


def test_bmi_percentile_z_and_category_all_use_twenty_five_months():
    # At 24 months this BMI is below P95. At 25 months it exceeds P95.
    sheet = imported(bmi='19.2')
    growth = assess_growth(sheet)
    assert growth.z_score == pytest.approx(bmi_zscore(19.2, 25, 'Male'), abs=1e-12)
    assert growth.z_score != bmi_zscore(19.2, 24, 'Male')
    assert growth.weight_category == 'Obesity'
    expected_percentile = f'{bmi_percentile(19.2, 25, "Male"):.1f} (CDC)'
    assert bmi_percentile_summary(sheet['anthropometrics'])[0] == expected_percentile
    assert item(sheet, 'growth_weight')['label'] == 'Obesity'


def test_bmi_age_also_changes_overweight_threshold():
    # 18.1 is below P85 in the boys 24-month bin, above P85 at 25 months.
    sheet = imported(bmi='18.1')
    assert assess_growth(sheet).weight_category == 'Overweight'
    sheet['anthropometrics']['bmi_age'] = '24 months'
    assert assess_growth(sheet).weight_category == ''
    assert item(sheet, 'growth_weight') is None


@pytest.mark.parametrize('bmi,category', [
    ('16', ''), ('18.1', 'Overweight'), ('19.2', 'Obesity'),
    ('23', 'Severe obesity'), ('35', 'Severe obesity'),
])
def test_high_bmi_has_one_highest_category_and_no_low_category(bmi, category):
    sheet = imported(bmi=bmi)
    growth = assess_growth(sheet)
    assert growth.weight_category == category
    assert growth.severity == ''
    rows = [row for row in suggestions(sheet, NOW) if row['key'] == 'growth_weight']
    assert len(rows) == bool(category)
    if category:
        assert rows[0]['label'] == category
        assert review_text(sheet, NOW).split(', ') == [category]
    assert item(sheet, 'malnutrition') is None


def test_extreme_bmi_category_does_not_depend_on_finite_upper_tail_z():
    sheet = imported(bmi='200')
    growth = assess_growth(sheet)
    assert growth.z_score is None
    assert growth.weight_category == 'Severe obesity'
    assert item(sheet, 'growth_weight')['label'] == 'Severe obesity'
    assert growth.severity == ''


def test_low_bmi_keeps_malnutrition_without_an_additional_underweight_label():
    sheet = imported(bmi='11.9', weight_z='+7.0')
    assert assess_growth(sheet).severity == 'Severe malnutrition'
    assert assess_growth(sheet).weight_category == ''
    assert review_text(sheet, NOW) == 'Severe malnutrition'
    assert 'Underweight' not in handoff_text(sheet, NOW)


def test_negative_weight_for_age_does_not_override_high_bmi_category():
    sheet = imported(bmi='23', weight_z='-8.1')
    assert assess_growth(sheet).weight_category == 'Severe obesity'
    assert assess_growth(sheet).severity == ''
    assert item(sheet, 'malnutrition') is None
    assert sheet['nutrition']['z_score'] == '-8.1'


def test_missing_general_age_can_use_explicit_bmi_age_without_head_or_wfl():
    sheet = imported(age=None, circumferences=(
        'Head Circumference: 42.5 cm (11/20/26 0400)\n'
        'Abdominal Circumference: 45 cm (11/21/26 0500)'))
    assert sheet['anthropometrics']['age'] == ''
    assert assess_growth(sheet).metric == 'bmi_for_age'
    assert assess_growth(sheet).z_score == pytest.approx(-5.73426217561093, abs=1e-10)
    assert 'Age: --' in patient_header(sheet)
    output = handoff_text(sheet, NOW)
    assert 'BMI Age: 2 y.o. 1 m.o.' in output
    assert 'Head circumference:' not in output
    assert 'Weight-for-length z score:' not in output
    assert 'Abdominal girth: 45 cm [11/21/26]' in output


def test_bmi_age_under_two_does_not_infer_wfl_or_head_eligibility():
    sheet = imported(age=None, bmi_age='10 months', weight='7 kg', height='58 cm',
                     circumferences='Head Circumference: 42.5 cm (11/20/26 0400)')
    assert assess_growth(sheet).z_score is None
    assert assess_growth(sheet).weight_category == ''
    assert item(sheet, 'growth_weight') is None
    assert 'Head circumference:' not in handoff_text(sheet, NOW)


def test_under_two_uses_general_age_and_wfl_not_bmi_for_high_weight():
    sheet = imported(age='10 months', bmi_age='9 months', bmi='35', weight='7 kg', height='58 cm',
                     circumferences='Head Circumference: 42.5 cm (11/20/26 0400)')
    growth = assess_growth(sheet)
    assert growth.metric == 'weight_for_length'
    assert growth.z_score > 2
    assert growth.weight_category == 'High weight-for-length'
    assert growth.severity == ''
    assert item(sheet, 'growth_weight')['label'] == 'High weight-for-length'
    assert item(sheet, 'malnutrition') is None
    assert 'Obesity' not in review_text(sheet, NOW)
    assert 'Head circumference: 42.5 cm [11/20/26]' in handoff_text(sheet, NOW)


def test_high_wfl_display_does_not_round_back_to_normal_threshold():
    # WHO boys at 58 cm, inverse LMS for z=2.004.
    sheet = imported(age='10 months', bmi_age=None,
                     weight='6.448818591652038 kg', height='58 cm')
    growth = assess_growth(sheet)
    assert growth.z_score == pytest.approx(2.004, abs=1e-10)
    assert growth.weight_category == 'High weight-for-length'
    displayed_z = float(growth.display_text.split(': ', 1)[1].split()[0])
    assert displayed_z > 2


@pytest.mark.parametrize('age,bmi_age', [
    ('22 y.o.', '22 years 1 month'),
    ('20 years', '19 years 1 month'),
    ('240 months', '240 months'),
])
def test_adults_receive_no_pediatric_bmi_category(age, bmi_age):
    sheet = imported(age=age, bmi_age=bmi_age, bmi='40')
    assert assess_growth(sheet).z_score is None
    assert assess_growth(sheet).weight_category == ''
    assert item(sheet, 'growth_weight') is None


def test_explicit_incomplete_bmi_age_does_not_fall_back_to_precise_general_age():
    sheet = imported(age='25 months', bmi_age='2 y.o.', bmi='23')
    growth = assess_growth(sheet)
    assert growth.z_score is None
    assert growth.weight_category == ''
    assert growth.reason
    assert not bmi_percentile_summary(sheet['anthropometrics'])[0].endswith(' (CDC)')
    assert item(sheet, 'growth_weight') is None


@pytest.mark.parametrize('age,bmi_age', [
    ('24 months', '25 months'),
    ('2 y.o.', '3 years 1 month'),
])
def test_bmi_age_definitely_later_than_general_age_blocks_calculation(age, bmi_age):
    sheet = imported(age=age, bmi_age=bmi_age, bmi='23')
    growth = assess_growth(sheet)
    assert growth.z_score is None
    assert growth.weight_category == ''
    assert growth.reason
    assert not bmi_percentile_summary(sheet['anthropometrics'])[0].endswith(' (CDC)')
    assert item(sheet, 'growth_weight') is None


def test_i_replacement_without_bmi_age_clears_previous_specific_age():
    sheet = imported(bmi='23')
    result = import_sections(sheet, block('i', 'NUTRITION:\nWeight: 10 kg\nBMI: 19.2\nHeight: 83 cm'),
                             new_vault()['settings'])
    assert not result.errors, result.errors
    attrs = result.sheet['anthropometrics']
    assert not attrs.get('bmi_age')
    assert attrs['age'] == '2 y.o.'
    assert assess_growth(result.sheet).z_score is None
    assert item(result.sheet, 'growth_weight') is None
    assert sheet['anthropometrics']['bmi_age'] == '2 y.o. 1 m.o.'


@pytest.mark.parametrize('bmi,key', [('11.9', 'malnutrition'), ('23', 'growth_weight')])
def test_changed_bmi_age_invalidates_current_growth_dismissal(bmi, key):
    sheet = imported(bmi=bmi)
    first = item(sheet, key)
    assert first is not None
    sheet = set_decision(sheet, key, first['fingerprint'], 'dismissed', first['label'])
    assert review_text(sheet, NOW) == ''
    sheet['anthropometrics']['bmi_age'] = '2 y.o. 2 m.o.'
    refreshed = item(sheet, key)
    assert refreshed is not None
    assert refreshed['fingerprint'] != first['fingerprint']
    assert refreshed['status'] == 'review'
    assert refreshed['label'] in review_text(sheet, NOW)


@pytest.mark.parametrize('bmi,key', [('11.9', 'malnutrition'), ('23', 'growth_weight')])
def test_same_effective_age_but_changed_age_source_invalidates_dismissal(bmi, key):
    sheet = imported(age='25 months', bmi_age='25 months', bmi=bmi)
    first = item(sheet, key)
    assert first is not None
    original_score = assess_growth(sheet).z_score
    sheet = set_decision(sheet, key, first['fingerprint'], 'dismissed', first['label'])
    del sheet['anthropometrics']['bmi_age']
    refreshed = item(sheet, key)
    assert assess_growth(sheet).z_score == original_score
    assert refreshed['fingerprint'] != first['fingerprint']
    assert refreshed['status'] == 'review'


@pytest.mark.parametrize('render', [handoff_text, handoff_html, handoff_pdf])
def test_bmi_age_is_visible_with_recorded_bmi_and_new_score(render):
    sheet = imported()
    before = deepcopy(sheet)
    output = export_text(render, sheet)
    assert 'Age: 2 y.o.' in output
    assert 'BMI Age: 2 y.o. 1 m.o.' in output
    assert 'BMI: 11.9 kg/m²' in output
    assert 'BMI-for-age z score: -5.73 (CDC)' in output
    assert 'Severe malnutrition' in output
    assert 'Z-score: -4.37' not in output
    assert sheet == before


@pytest.mark.parametrize('render', [handoff_text, handoff_html, handoff_pdf])
def test_high_category_prints_once_in_problems(render):
    sheet = imported(bmi='23')
    output = export_text(render, sheet)
    assert output.count('Severe obesity') == 1
    assert 'Problems: Severe obesity' in output
    assert 'Overweight' not in output
    assert 'malnutrition' not in output.lower()


def test_bmi_age_change_refreshes_cached_pdf_body():
    sheet = imported(bmi='19.2')
    cache = SessionPdfCache()
    try:
        first = cache.prepare(sheet, NOW)
        sheet['anthropometrics']['bmi_age'] = '24 months'
        second = cache.prepare(sheet, NOW)
        assert first.signature != second.signature
        assert cache.stats['builds'] == 2
        first_text = '\n'.join(p.extract_text() or '' for p in PdfReader(BytesIO(first.data)).pages)
        second_text = '\n'.join(p.extract_text() or '' for p in PdfReader(BytesIO(second.data)).pages)
        assert 'Problems: Obesity' in first_text
        assert 'Problems: Overweight' in second_text
    finally:
        cache.close()


def test_old_five_field_record_and_optional_bmi_age_encrypted_round_trip():
    old_sheet = imported(age='25 months', bmi_age=None)
    assert set(old_sheet['anthropometrics']) == set(FIELDS)
    assert 'bmi_age' not in empty_anthropometrics()
    validate_anthropometrics(old_sheet['anthropometrics'])
    old = save_sheet_in(new_vault(), old_sheet)
    before = deepcopy(old)
    assert upgrade_vault(old) == before
    assert old == before
    new = save_sheet_in(new_vault(), imported())
    key = generate_key()
    restored = open_vault(seal_vault(new, key), key)
    assert restored == new
    restored_sheet = restored['rooms']['P4102']
    assert restored_sheet['anthropometrics']['bmi_age'] == '2 y.o. 1 m.o.'
    assert assess_growth(restored_sheet).severity == 'Severe malnutrition'
    assert 'BMI-for-age z score' not in json.dumps(restored)


def test_opening_editor_does_not_add_optional_blank_bmi_age(app, monkeypatch):
    open_room(app)
    sheet = imported(age='25 months', bmi_age=None)
    app.st.session_state['drafts']['P4102'] = sheet
    before = deepcopy(sheet['anthropometrics'])
    equip(app, monkeypatch)
    app.neuro_weight_editor(sheet)
    key = 'anthro_' + sheet['id'] + '_bmi_age'
    assert app.st.session_state[key] == ''
    snapshot = app.editor_snapshot('P4102')
    assert snapshot['anthropometrics'] == before
    assert sheet['anthropometrics'] == before


def test_bmi_age_callback_and_pending_snapshot_keep_general_age(app):
    open_room(app)
    sheet = imported(bmi_age=None)
    ss = app.st.session_state
    ss['drafts']['P4102'] = sheet
    key = 'anthro_' + sheet['id'] + '_bmi_age'
    ss[key] = '2 y.o. 1 m.o.'
    app.anthropometric_change('P4102', 'bmi_age', key)
    assert ss['drafts']['P4102']['anthropometrics']['bmi_age'] == '2 y.o. 1 m.o.'
    assert ss['drafts']['P4102']['anthropometrics']['age'] == '2 y.o.'
    ss[key] = '2 y.o. 2 m.o.'
    snapshot = app.editor_snapshot('P4102')
    assert snapshot['anthropometrics']['bmi_age'] == '2 y.o. 2 m.o.'
    assert snapshot['anthropometrics']['age'] == '2 y.o.'
    assert ss['drafts']['P4102']['anthropometrics']['bmi_age'] == '2 y.o. 1 m.o.'


def test_invalid_bmi_age_callback_on_old_record_does_not_raise_or_mutate(app):
    open_room(app)
    sheet = imported(age='25 months', bmi_age=None)
    ss = app.st.session_state
    ss['drafts']['P4102'] = sheet
    before = deepcopy(sheet['anthropometrics'])
    key = 'anthro_' + sheet['id'] + '_bmi_age'
    ss[key] = 'invalid age'
    app.anthropometric_change('P4102', 'bmi_age', key)
    assert ss[key] == ''
    assert ss['drafts']['P4102']['anthropometrics'] == before

