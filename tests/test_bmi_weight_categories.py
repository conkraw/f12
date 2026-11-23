"""CDC high-BMI categories, inclusive cutoffs and precise BMI-age use."""
import csv
import math
from unittest.mock import patch

import pytest

from bmi_reference import (REFERENCE_PATH, bmi_percentile_summary,
                           bmi_weight_category, bmi_zscore, load_reference)


@pytest.mark.parametrize('bmi,expected', [
    (11.9, ''),
    (16, ''),
    (18.1, 'Overweight'),
    (19.2, 'Obesity'),
    (23, 'Severe obesity'),
])
def test_male_25_month_reference_categories(bmi, expected):
    # Official row 25.5: P85 ~= 18.0367, P95 = 19.1647.
    assert bmi_weight_category(bmi, 25, 'Male') == expected


def test_exact_unrounded_p85_boundary_is_inclusive_without_a_z_round_trip():
    # Male 25.5-month LMS inverse at normal quantile(0.85).
    p85 = 18.03668013084155
    assert bmi_weight_category(math.nextafter(p85, -math.inf), 25, 'Male') == ''
    assert bmi_weight_category(p85, 25, 'Male') == 'Overweight'
    assert bmi_weight_category(math.nextafter(p85, math.inf), 25, 'Male') == 'Overweight'


@pytest.mark.parametrize('sex,age', [
    ('Male', 24), ('Female', 24), ('Male', 50), ('Female', 50),
    ('Male', 114), ('Female', 114), ('Male', 239), ('Female', 239),
])
def test_official_rounded_percentile_columns_bracket_category_cutoffs(sex, age):
    chart_sex = 1 if sex == 'Male' else 2
    with REFERENCE_PATH.open(encoding='utf-8-sig', newline='') as handle:
        row = next(row for row in csv.DictReader(handle)
                   if int(row['sex']) == chart_sex and float(row['agemos']) == age + 0.5)
    p85, p95 = float(row['P85']), float(row['P95'])
    # CDC P85 is rounded to four decimals, so bracket it by 0.001 BMI.
    assert bmi_weight_category(p85 - 0.001, age, sex) == ''
    assert bmi_weight_category(p85 + 0.001, age, sex) == 'Overweight'
    assert bmi_weight_category(math.nextafter(p95, -math.inf), age, sex) == 'Overweight'
    assert bmi_weight_category(p95, age, sex) == 'Obesity'
    assert bmi_weight_category(math.nextafter(p95, math.inf), age, sex) == 'Obesity'


def test_severe_cutoff_at_120_percent_of_p95_is_inclusive():
    cutoff = 1.2 * 19.1647
    assert cutoff == 22.99764
    assert bmi_weight_category(math.nextafter(cutoff, -math.inf), 25, 'Male') == 'Obesity'
    assert bmi_weight_category(cutoff, 25, 'Male') == 'Severe obesity'
    assert bmi_weight_category(math.nextafter(cutoff, math.inf), 25, 'Male') == 'Severe obesity'


def test_absolute_bmi_35_severe_cutoff_can_apply_below_120_percent_p95():
    row = load_reference()[2, 239.5]
    assert 1.2 * row['p95'] > 35
    assert bmi_weight_category(math.nextafter(35.0, -math.inf), 239, 'Female') == 'Obesity'
    assert bmi_weight_category(35, 239, 'Female') == 'Severe obesity'
    assert bmi_weight_category(40, 239, 'Female') == 'Severe obesity'


def test_category_calculation_is_independent_of_extreme_zscore_underflow():
    with pytest.raises(ValueError, match='finite z score'):
        bmi_zscore(200, 50, 'Male')
    with patch('bmi_reference.zscore_from_parameters', side_effect=AssertionError('no z score needed')):
        assert bmi_weight_category(200, 50, 'Male') == 'Severe obesity'
        assert bmi_weight_category(1e-320, 50, 'Male') == ''


def test_same_month_bin_and_reference_injection_as_bmi_zscore():
    rows = load_reference()
    with patch('bmi_reference.load_reference', side_effect=AssertionError('use supplied reference')):
        for age in (25, 25.5, 25.999999):
            assert bmi_weight_category(19.12, age, 'Male', rows) == 'Overweight'
        assert bmi_weight_category(19.12, 26, 'Male', rows) == 'Obesity'


@pytest.mark.parametrize('age', [0, 23.999999, 240, 264, math.nan, math.inf, None, True])
def test_no_infant_adult_or_invalid_age_categories(age):
    with pytest.raises(ValueError):
        bmi_weight_category(40, age, 'Male')


@pytest.mark.parametrize('sex', ['', 'Unknown', 'male', 'female', None])
def test_explicit_growth_chart_sex_is_required(sex):
    with pytest.raises(ValueError):
        bmi_weight_category(25, 50, sex)


@pytest.mark.parametrize('bmi', [0, -1, math.nan, math.inf, None, True])
def test_invalid_bmi_is_rejected(bmi):
    with pytest.raises(ValueError):
        bmi_weight_category(bmi, 50, 'Male')


def test_percentile_summary_uses_separate_precise_bmi_age():
    data = {'age': '2 y.o.', 'bmi_age': '2 y.o. 1 m.o.',
            'sex': 'Male', 'bmi': '11.9 kg/m²'}
    with patch('bmi_reference.bmi_percentile', return_value=0.0000004896887) as calculate:
        summary, reason = bmi_percentile_summary(data)
    calculate.assert_called_once_with(11.9, 25.0, 'Male')
    assert summary == '<0.1 (CDC)'


@pytest.mark.parametrize('general_age,bmi_age,expected', [
    ('23 months', '', 'not calculated'),
    ('', '23 months', 'not calculated'),
    ('20 years', '', 'not applicable'),
    ('', '240 months', 'not applicable'),
    ('2 y.o.', '', 'unavailable'),
    ('2 y.o.', '2 y.o.', 'unavailable'),
])
def test_percentile_summary_preserves_age_exclusion_labels(general_age, bmi_age, expected):
    data = {'age': general_age, 'bmi_age': bmi_age, 'sex': 'Male', 'bmi': '17 kg/m²'}
    with patch('bmi_reference.bmi_percentile', side_effect=AssertionError('must not calculate')):
        summary, reason = bmi_percentile_summary(data)
    assert summary.startswith(expected)
    assert reason
