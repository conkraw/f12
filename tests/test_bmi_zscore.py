"""CDC published examples and reference-column checks for BMI z scores."""
import csv
import math
from statistics import NormalDist

import pytest

from bmi_reference import (REFERENCE_PATH, bmi_percentile, bmi_zscore,
                           load_reference, zscore_from_parameters)


@pytest.mark.parametrize('bmi,age,sex,expected_z,expected_percentile', [
    (21.2, 114.5, 'Female', 1.4215011771048056, 92.24144441924041),
    (22.6, 50.5, 'Male', 2.8314424507871667, 99.76830714225628),
])
def test_cdc_published_worked_examples(bmi, age, sex, expected_z, expected_percentile):
    # Examples on cdc.gov/growthcharts/extended-bmi-data-files.htm.
    z = bmi_zscore(bmi, age, sex)
    assert z == pytest.approx(expected_z, abs=1e-10)
    assert 100 * NormalDist().cdf(z) == pytest.approx(expected_percentile, abs=1e-10)


@pytest.mark.parametrize('sex,age', [
    (1, 24.5), (2, 24.5), (1, 50.5), (2, 50.5),
    (1, 114.5), (2, 114.5), (1, 239.5), (2, 239.5),
])
def test_published_cdc_zscore_columns_cover_both_formulas(sex, age):
    with REFERENCE_PATH.open(encoding='utf-8-sig', newline='') as handle:
        row = next(row for row in csv.DictReader(handle)
                   if int(row['sex']) == sex and float(row['agemos']) == age)
    columns = [('Z2neg', -2), ('Z1_5neg', -1.5), ('Z1neg', -1),
               ('Z0_5neg', -0.5), ('Z0', 0), ('Z0_5', 0.5),
               ('Z1', 1), ('Z1_5', 1.5), ('Z2', 2), ('Z2_5', 2.5),
               ('Z3', 3), ('Z3_5', 3.5), ('Z4', 4), ('Z4_5', 4.5), ('Z5', 5)]
    for column, expected in columns:
        z = bmi_zscore(float(row[column]), age, 'Male' if sex == 1 else 'Female')
        # CDC rounds these BMI reference columns to four decimals.
        assert z == pytest.approx(expected, abs=0.0002), (column, sex, age)


def test_extreme_lower_tail_does_not_invert_a_zero_percentile():
    assert bmi_percentile(5, 50.5, 'Male') == 0
    z = bmi_zscore(5, 50.5, 'Male')
    assert math.isfinite(z)
    assert z == pytest.approx(-53.764168314760944, abs=1e-10)


def test_extreme_upper_tail_retains_a_score_when_percentile_rounds_to_100():
    assert bmi_percentile(50, 50.5, 'Male') == 100
    z = bmi_zscore(50, 50.5, 'Male')
    assert math.isfinite(z)
    assert z == pytest.approx(13.586729638986021, abs=1e-10)


def test_upper_tail_underflow_is_explicit_instead_of_clamping_score():
    with pytest.raises(ValueError, match='finite z score'):
        bmi_zscore(200, 50.5, 'Male')


def test_monthly_age_bin_includes_start_and_excludes_next_month():
    score = bmi_zscore(14, 24, 'Male')
    assert score == bmi_zscore(14, 24.5, 'Male')
    assert score == bmi_zscore(14, 24.999999, 'Male')
    assert score != bmi_zscore(14, 25, 'Male')
    assert math.isfinite(bmi_zscore(14, 239.999999, 'Female'))


@pytest.mark.parametrize('age', [23.999999, 240, 264, math.nan, math.inf])
def test_age_outside_pediatric_reference_is_rejected(age):
    with pytest.raises(ValueError):
        bmi_zscore(14, age, 'Male')


@pytest.mark.parametrize('sex', ['', 'Unknown', 'male', 'female'])
def test_explicit_supported_growth_chart_sex_is_required(sex):
    with pytest.raises(ValueError):
        bmi_zscore(14, 24, sex)


@pytest.mark.parametrize('bmi', [0, -1, math.nan, math.inf])
def test_invalid_bmi_is_rejected(bmi):
    with pytest.raises(ValueError):
        bmi_zscore(bmi, 24, 'Female')


def test_median_and_l_zero_limit():
    row = load_reference()[2, 114.5]
    assert zscore_from_parameters(row['m'], row) == pytest.approx(0, abs=1e-15)
    values = {'l': 0, 'm': 16, 's': 0.1, 'p95': 20, 'sigma': 2}
    assert zscore_from_parameters(16 * math.exp(-0.2), values) == pytest.approx(-2, abs=1e-12)


def test_p95_transition_agrees_with_published_rounding():
    values = load_reference()[1, 50.5]
    at = zscore_from_parameters(values['p95'], values)
    above = zscore_from_parameters(math.nextafter(values['p95'], math.inf), values)
    assert at == pytest.approx(1.6448536269514722, abs=0.0001)
    assert above == pytest.approx(1.6448536269514722, abs=1e-12)
