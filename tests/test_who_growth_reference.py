"""Independent WHO table anchors, tail behavior and invalid input checks."""
import math

import pytest

from who_growth_reference import load_reference, weight_for_length_zscore


def test_complete_official_reference_and_sex_specific_medians():
    assert len(load_reference()) == 1302
    assert weight_for_length_zscore(5.418, 58, 'Male') == pytest.approx(0)
    assert weight_for_length_zscore(5.3507, 58, 'Female') == pytest.approx(0)
    assert weight_for_length_zscore(18.2689, 110, 'Male') == pytest.approx(0)
    assert weight_for_length_zscore(2.4607, 45, 'Female') == pytest.approx(0)


@pytest.mark.parametrize('sex,length,weight,expected', [
    ('Male', 65, 5.736, -3),
    ('Male', 65, 6.193, -2),
    ('Male', 65, 5.279, -4),
    ('Male', 80, 7.565, -4),
    ('Female', 65, 5.459, -3),
    ('Female', 65, 5.937, -2),
    ('Female', 65, 4.982, -4),
    ('Female', 80, 7.145, -4),
])
def test_who_published_expanded_table_weights(sex, length, weight, expected):
    # WHO's published SD columns round weights to 0.001 kg. The unrounded
    # calculation therefore differs slightly from the integer table labels.
    assert weight_for_length_zscore(weight, length, sex) == pytest.approx(expected, abs=0.002)


def test_length_interpolation_uses_reference_parameters():
    # At 45.0 and 45.1 cm, WHO boys' medians are 2.4410 and 2.4577 kg.
    # The interpolated median at 45.05 cm must correspond to z = 0.
    assert weight_for_length_zscore((2.441 + 2.4577) / 2, 45.05, 'Male') == pytest.approx(0, abs=1e-12)


def test_infant_weight_for_length_is_independent_of_weight_for_age():
    assert weight_for_length_zscore(6.3, 58, 'Male') == pytest.approx(1.7424453496265564)


def test_extreme_positive_tail_matches_published_weight():
    # WHO expanded boys' table at 45 cm reports 3.571 kg at +4 SD.
    assert weight_for_length_zscore(3.571, 45, 'Male') == pytest.approx(4, abs=0.002)


@pytest.mark.parametrize('weight,length,sex', [
    (5, 44.99, 'Male'), (5, 110.01, 'Male'), (0, 58, 'Male'),
    (-1, 58, 'Male'), (math.nan, 58, 'Male'), (math.inf, 58, 'Male'),
    (5, math.nan, 'Male'), (5, math.inf, 'Male'), (None, 58, 'Male'),
    (5, 58, ''), (5, 58, 'Unknown'), (True, 58, 'Male'),
])
def test_missing_or_out_of_range_inputs_are_not_extrapolated(weight, length, sex):
    with pytest.raises(ValueError):
        weight_for_length_zscore(weight, length, sex)
