"""WHO daily HC anchors, age rounding, percentile display and table failures."""
import math

import pytest

from head_circumference_reference import (
    DAYS_PER_MONTH, MAX_AGE_DAYS, REFERENCE_PATH, hc_percentile, hc_zscore,
    load_reference, parse_reference, percentile_text,
)


@pytest.mark.parametrize('sex,day,median', [
    ('Male', 0, 34.4618), ('Female', 0, 33.8787),
    ('Male', 30, 37.2435), ('Female', 30, 36.5163),
    ('Male', 365, 46.0637), ('Female', 365, 44.894),
    ('Male', 1826, 50.7372), ('Female', 1826, 49.9225),
])
def test_official_daily_medians_are_50th_percentile(sex, day, median):
    assert hc_zscore(median, day, sex) == pytest.approx(0, abs=1e-12)
    assert hc_percentile(median, day, sex) == pytest.approx(50, abs=1e-12)


def test_complete_reference_has_every_daily_row_for_both_sexes():
    rows = load_reference()
    assert len(rows) == 3654
    assert set(rows) == {(sex, day) for sex in (1, 2) for day in range(1827)}
    assert DAYS_PER_MONTH == 365.25 / 12
    assert MAX_AGE_DAYS == 1826


@pytest.mark.parametrize('sex,median,coefficient', [
    ('Male', 34.4618, 0.03686), ('Female', 33.8787, 0.03496),
])
def test_official_birth_standard_deviation_matches_normal_percentiles(sex, median, coefficient):
    # WHO L=1 for HC. M*S is the standard deviation in centimeters.
    assert hc_zscore(median + median * coefficient, 0, sex) == pytest.approx(1)
    assert hc_percentile(median + median * coefficient, 0, sex) == pytest.approx(84.1344746068543)
    assert hc_percentile(median - median * coefficient, 0, sex) == pytest.approx(15.8655253931457)


def test_age_rounding_matches_who_half_day_upward_rule():
    # Boys medians on days 0, 1 and 2 are 34.4618, 34.5620 and 34.6622.
    assert hc_percentile(34.4618, 0.499999, 'Male') == pytest.approx(50)
    assert hc_percentile(34.562, 0.5, 'Male') == pytest.approx(50)
    assert hc_percentile(34.6622, 1.5, 'Male') == pytest.approx(50)
    # WHO converts one month to 30.4375 days then rounds to day 30.
    assert hc_percentile(37.2435, DAYS_PER_MONTH, 'Male') == pytest.approx(50)


def test_percentile_does_not_round_z_score_before_conversion():
    median, coefficient = 34.4618, 0.03686
    head = median * (1 + coefficient * 0.123456)
    assert hc_zscore(head, 0, 'Male') == pytest.approx(0.123456, abs=1e-12)
    assert hc_percentile(head, 0, 'Male') == pytest.approx(54.91269927023118, abs=1e-10)


@pytest.mark.parametrize('head,age,sex', [
    (34, -0.01, 'Male'), (34, 1826.01, 'Male'),
    (34, math.nan, 'Male'), (34, math.inf, 'Male'),
    (34, None, 'Male'), (34, True, 'Male'),
    (0, 0, 'Male'), (-34, 0, 'Male'), (100.01, 0, 'Male'),
    (math.nan, 0, 'Male'), (math.inf, 0, 'Male'),
    (None, 0, 'Male'), (True, 0, 'Male'),
    (34, 0, ''), (34, 0, 'Unknown'), (34, 0, 'male'),
])
def test_invalid_values_and_unsupported_ages_are_not_extrapolated(head, age, sex):
    with pytest.raises(ValueError):
        hc_percentile(head, age, sex)


@pytest.mark.parametrize('value,expected', [
    (0, '[<1st %tile]'), (0.9999, '[<1st %tile]'),
    (1, '[1st %tile]'), (2, '[2nd %tile]'), (3, '[3rd %tile]'),
    (11, '[11th %tile]'), (12, '[12th %tile]'), (13, '[13th %tile]'),
    (21, '[21st %tile]'), (22, '[22nd %tile]'), (23, '[23rd %tile]'),
    (55.5, '[56th %tile]'), (56.49, '[56th %tile]'),
    (98.9, '[99th %tile]'), (99, '[99th %tile]'),
    (99.0001, '[>99th %tile]'), (100, '[>99th %tile]'),
])
def test_compact_display_uses_correct_ordinals_and_open_tails(value, expected):
    assert percentile_text(value) == expected


@pytest.mark.parametrize('value', [-1, 101, math.nan, math.inf, None, True])
def test_invalid_percentile_does_not_render(value):
    with pytest.raises(ValueError):
        percentile_text(value)


def test_extreme_hc_values_never_print_zero_or_one_hundred_percentile():
    assert percentile_text(hc_percentile(1, 0, 'Male')) == '[<1st %tile]'
    assert percentile_text(hc_percentile(100, 0, 'Female')) == '[>99th %tile]'


@pytest.mark.parametrize('mutation', [
    lambda text: '\n'.join(text.splitlines()[:-1]),
    lambda text: text + text.splitlines()[1] + '\n',
    lambda text: text.replace('Sex,AgeDays,L,M,S', 'Sex,Age,L,M,S', 1),
    lambda text: text.replace('1,0,1,34.4618,0.03686', '1,0,1,33.8787,0.03496', 1),
    lambda text: text.replace('1,0,1,34.4618,0.03686', '1,0,1,34.4618,nan', 1),
    lambda text: text.replace('1,0,1,34.4618,0.03686', '1,0.1,1,34.4618,0.03686', 1),
    lambda text: text.replace('1,0,1,34.4618,0.03686', '1,0,0,34.4618,0.03686', 1),
])
def test_incomplete_wrong_or_corrupt_reference_is_rejected(mutation):
    with pytest.raises(ValueError):
        parse_reference(mutation(REFERENCE_PATH.read_text(encoding='utf-8')))
