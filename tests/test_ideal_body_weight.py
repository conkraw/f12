"""Clinical boundary and independent CDC-anchor checks for estimated IBW."""
from copy import deepcopy

import pytest

from anthropometrics import empty_anthropometrics
import ideal_body_weight
from ideal_body_weight import assess_ideal_body_weight
from models import new_sheet


def sheet(age='180 months', sex='Male', bmi='35 kg/m²', height='160 cm', bmi_age=None):
    result = new_sheet('P4102')
    result['anthropometrics'] = empty_anthropometrics()
    result['anthropometrics'].update(age=age, sex=sex, bmi=bmi, height=height)
    if bmi_age is not None:
        result['anthropometrics']['bmi_age'] = bmi_age
    result['nutrition'] = {'include': True, 'weight': '100 kg', 'z_score': ''}
    result['dosing_weight'] = '90 kg'
    return result


@pytest.mark.parametrize('sex,expected', [
    ('Male', 50.8356126976),
    ('Female', 51.022249472),
])
def test_official_cdc_medians_produce_sex_specific_weight(sex, expected):
    # Official CDC 180.5-month row: boys M=19.85766121, girls M=19.9305662.
    result = assess_ideal_body_weight(sheet(sex=sex))
    assert result.weight_kg == pytest.approx(expected, abs=1e-10)
    assert result.display_text == f'Estimated IBW: {expected:.1f} kg (BMI 50th %tile)'
    assert result.inputs['height_m'] == 1.6
    assert result.inputs['age_months'] == 180


def test_independent_cdc_worked_example_median_at_114_months():
    result = assess_ideal_body_weight(sheet(age='114 months', sex='Female', height='140 cm'))
    # The official worked example gives median BMI 16.57626713.
    assert result.weight_kg == pytest.approx(32.4894835748, abs=1e-10)


@pytest.mark.parametrize('height', ['160 cm', '1.6 m', '62.99212598425197 in',
                                    '62.99212598425197 inches'])
def test_equivalent_height_units_do_not_change_estimate(height):
    assert assess_ideal_body_weight(sheet(height=height)).weight_kg == pytest.approx(50.8356126976, abs=1e-10)


@pytest.mark.parametrize('bmi,eligible', [
    ('26.83689999999999 kg/m²', False),
    ('26.8369 kg/m²', True),
    ('26.83690000000001 kg/m²', True),
    ('35 kg/m²', True),
    ('200 kg/m²', True),
])
def test_p95_eligibility_uses_unrounded_bmi_not_z_score(bmi, eligible):
    # CDC boys 180.5-month P95 is 26.8369. Extreme BMI can overflow a z-score
    # calculation but does not invalidate the finite median-BMI weight.
    assert (assess_ideal_body_weight(sheet(bmi=bmi)).weight_kg is not None) is eligible


@pytest.mark.parametrize('bmi', ['16 kg/m²', '25 kg/m²'])
def test_normal_or_overweight_bmi_does_not_show_ibw_even_at_100_kg(bmi):
    result = assess_ideal_body_weight(sheet(bmi=bmi))
    assert result.weight_kg is None
    assert result.display_text == ''
    assert '95th percentile' in result.reason


@pytest.mark.parametrize('age,eligible', [
    ('23.99 months', False), ('24 months', True),
    ('239.99 months', True), ('240 months', False), ('20 years', False),
    ('15 years', False), ('15 y.o.', False), ('', False),
])
def test_pediatric_age_boundaries_and_no_guessed_month(age, eligible):
    assert (assess_ideal_body_weight(sheet(age=age)).weight_kg is not None) is eligible


def test_explicit_bmi_age_matches_existing_bmi_calculations():
    result = assess_ideal_body_weight(sheet(age='15 y.o.', bmi_age='15 y.o. 0 m.o.'))
    assert result.weight_kg == pytest.approx(50.8356126976, abs=1e-10)
    assert result.inputs['age_source'] == 'BMI Age'
    assert result.inputs['age_at_bmi'] == '15 y.o. 0 m.o.'


@pytest.mark.parametrize('age,bmi_age', [
    ('15 years', '16 years 0 months'),
    ('180 months', '181 months'),
    ('10 months', '180 months'),
    ('20 years', '180 months'),
    ('180 months', '15 years'),
])
def test_bmi_age_cannot_override_contradictory_or_incomplete_age(age, bmi_age):
    assert assess_ideal_body_weight(sheet(age=age, bmi_age=bmi_age)).weight_kg is None


def test_older_documented_bmi_age_stays_explicit_in_estimate_provenance():
    result = assess_ideal_body_weight(sheet(age='181 months', bmi_age='180 months'))
    assert result.weight_kg == pytest.approx(50.8356126976, abs=1e-10)
    assert result.inputs['age_at_bmi'] == '180 months'
    assert 'same measurement episode' in result.reason


@pytest.mark.parametrize('sex', ['', 'Unknown', 'male', 'Other'])
def test_no_sex_inference(sex):
    assert assess_ideal_body_weight(sheet(sex=sex)).weight_kg is None


@pytest.mark.parametrize('height', [
    '', '160', '0 cm', '-160 cm', '160 kg', 'nan cm', 'inf cm',
    '1 cm', '160 m', '44.999 cm', '250.001 cm',
    '160 cm (estimated)', '160 cm (wrong)', '160 cm (5\' 0")',
    '160 cm (another 140 cm)', '160 cm extra',
])
def test_missing_malformed_or_unreliable_height_suppresses_estimate(height):
    result = assess_ideal_body_weight(sheet(height=height))
    assert result.weight_kg is None
    assert result.display_text == ''


@pytest.mark.parametrize('height', ['45 cm', '250 cm'])
def test_broad_entry_guard_includes_its_endpoints(height):
    assert assess_ideal_body_weight(sheet(height=height)).weight_kg is not None


@pytest.mark.parametrize('bmi', ['', 'nan', 'inf', '0', '-35', '201', '35 kg',
                                '35 kg/m² unknown', True, None])
def test_invalid_recorded_bmi_is_never_reconstructed(bmi):
    assert assess_ideal_body_weight(sheet(bmi=bmi)).weight_kg is None


@pytest.mark.parametrize('section', ['a', 'i', 'n'])
def test_relevant_import_warning_blocks_estimate(section):
    value = sheet()
    value['import_warnings'][section] = 'Synthetic import warning'
    assert assess_ideal_body_weight(value).weight_kg is None


def test_missing_reference_fails_closed(monkeypatch):
    def unavailable():
        raise FileNotFoundError
    monkeypatch.setattr(ideal_body_weight, 'load_reference', unavailable)
    result = assess_ideal_body_weight(sheet())
    assert result.weight_kg is None
    assert 'reference' in result.reason.lower()


def test_every_calculation_uses_current_inputs_without_mutating_patient():
    value = sheet()
    original = deepcopy(value)
    first = assess_ideal_body_weight(value)
    assert value == original
    value['anthropometrics']['height'] = '170 cm'
    updated = assess_ideal_body_weight(value)
    assert updated.weight_kg == pytest.approx(57.3886408969, abs=1e-10)
    assert updated.weight_kg != first.weight_kg
    value['anthropometrics']['bmi'] = '20 kg/m²'
    assert assess_ideal_body_weight(value).display_text == ''


def test_measured_and_dosing_weight_are_independent_and_unchanged():
    value = sheet()
    first = assess_ideal_body_weight(value)
    value['nutrition']['weight'] = '95 kg'
    value['dosing_weight'] = '75 kg'
    snapshot = deepcopy(value)
    second = assess_ideal_body_weight(value)
    assert second.weight_kg == first.weight_kg
    assert value == snapshot
    assert 'does not select a dosing weight' in second.reason


def test_missing_height_does_not_use_bmi_weight_ratio():
    assert assess_ideal_body_weight(sheet(height='')).weight_kg is None


def test_partial_or_empty_patient_has_no_ibw():
    assert assess_ideal_body_weight({}).display_text == ''
    assert assess_ideal_body_weight(new_sheet('P4104')).display_text == ''
