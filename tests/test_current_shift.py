"""Synthetic current-shift parser and elapsed-time regressions."""
from copy import deepcopy
from decimal import Decimal
import pytest
from current_shift import (parse_current_shift, current_shift_text, current_shift_rows,
                           current_shift_heading, shift_window, validate_current_shift)


def source(stamp='01/05/2026 0630', weight='20 kg', out='Urine:300; Drains:15; Chest Tube:30; Other:60'):
    return f'''INTAKE/OUTPUT:
Intake/Output Summary (Last 24 hours) at {stamp}
Last data filed at 01/05/2026 0400
Gross per 24 hour
Intake 1250 ml
Output 1100 ml
Net 150 ml
IO Current Shift:
I/O this shift:
In: 900 (45 mL/kg) [I.V.:900]
Out: 405 (20.25 mL/kg) [{out}]
Weight: {weight}
'''


def parsed(**kwargs):
    result = parse_current_shift(source(**kwargs))
    assert not result.error, result.error
    return result


def shown(result):
    return current_shift_text({'current_shift': result.data})


def test_requested_format_and_four_independent_categories():
    assert shown(parsed()) == ('Current Shift (7pm - 6:30am)\n'
        'UOP: 1.30 mL/kg/hr\nDrains: 0.07 mL/kg/hr\n'
        'Chest Tube: 0.13 mL/kg/hr\nOther: 0.26 mL/kg/hr')
    text = shown(parsed())
    for forbidden in ('In:', 'Out:', 'Net:', '1250', '1100', '150 ml', '900', '405'):
        assert forbidden not in text


@pytest.mark.parametrize('stamp,heading,hours', [
    ('2026-01-05T06:30:00', 'Current Shift (7pm - 6:30am)', '11.5'),
    ('2026-01-05T14:30:00', 'Current Shift (7am - 2:30pm)', '7.5'),
    ('2026-01-05T22:30:00', 'Current Shift (7pm - 10:30pm)', '3.5'),
    ('2026-01-05T23:30:00', 'Current Shift (7pm - 11:30pm)', '4.5'),
    ('2026-01-05T00:00:00', 'Current Shift (7pm - 12am)', '5'),
    ('2026-01-05T07:30:00', 'Current Shift (7am - 7:30am)', '0.5'),
    ('2026-01-05T15:30:00', 'Current Shift (7am - 3:30pm)', '8.5'),
])
def test_shift_windows(stamp, heading, hours):
    data = parsed().data
    data['as_of'] = stamp
    assert shift_window(stamp)[2] == Decimal(hours)
    assert current_shift_heading(data) == heading


@pytest.mark.parametrize('clock', ['0700', '1900'])
def test_exact_boundary_has_no_rate_and_no_divide_by_zero(clock):
    result = parsed(stamp='01/05/2026 ' + clock)
    assert result.data and result.issues and shown(result) == ''


@pytest.mark.parametrize('cutoff,hours', [
    ('2026-03-08T06:30:00', '10.5'),
    ('2026-11-01T06:30:00', '12.5'),
])
def test_dst_uses_actual_elapsed_time(cutoff, hours):
    assert shift_window(cutoff)[2] == Decimal(hours)


@pytest.mark.parametrize('stamp', ['03/08/2026 0230', '11/01/2026 0130'])
def test_dst_nonexistent_or_ambiguous_endpoint_withholds(stamp):
    result = parsed(stamp=stamp)
    assert result.issues and shown(result) == ''


@pytest.mark.parametrize('time', ['0630', '630', '06:30', '6:30 AM', '06:30:00 AM'])
def test_source_clock_variants(time):
    assert '7pm - 6:30am' in shown(parsed(stamp='1/5/26 ' + time))


@pytest.mark.parametrize('time', ['1455', '14:55', '2:55pm', '02:55 PM'])
def test_afternoon_source_clock_variants(time):
    assert '7am - 2:55pm' in shown(parsed(stamp='01/05/2026 ' + time))


@pytest.mark.parametrize('stamp', ['01/05/2026', '01/05/2026 2560', '02/30/2026 0630', '01/05/2026 13:30PM'])
def test_invalid_source_time_never_falls_back_to_filed_or_now(stamp):
    result = parse_current_shift(source(stamp=stamp))
    assert result.error and result.data is None


def test_no_summary_does_not_use_last_data_filed():
    text = '\n'.join(line for line in source().splitlines() if not line.startswith('Intake/Output Summary'))
    result = parse_current_shift(text)
    assert result.data['as_of'] == '' and result.issues and shown(result) == ''


def test_last_filed_and_intake_are_never_used():
    original = parsed()
    text = source().replace('01/05/2026 0400', 'NOT_A_TIME').replace('In: 900 (45 mL/kg) [I.V.:900]', 'In: [Urine:999999; Drains:888888]')
    changed = parse_current_shift(text)
    assert changed.data == original.data


@pytest.mark.parametrize('weight', ['', '0 kg', '-2 kg', 'UNK', '20 pounds', 'NaN kg'])
def test_missing_invalid_weight_no_fallback(weight):
    result = parsed(weight=weight)
    assert result.data['weight_kg'] == '' and result.issues and shown(result) == ''


def test_grams_convert_and_block_weight_controls():
    assert parsed(weight='20000 g').data['weight_kg'] == '20'
    sheet = {'current_shift': parsed().data, 'dosing_weight': '5 kg',
             'nutrition': {'weight': '15 kg'}}
    assert 'UOP: 1.30 mL/kg/hr' in current_shift_text(sheet)


def test_other_is_not_urine_and_missing_categories_omitted():
    text = shown(parsed(out='Other:60'))
    assert text.endswith('Other: 0.26 mL/kg/hr')
    assert not any(word in text for word in ('UOP', 'Drains', 'Chest Tube'))


def test_explicit_zero_is_retained_and_missing_is_not_zero():
    result = parsed(out='Urine:0; Drains:--')
    assert 'UOP: 0.00 mL/kg/hr' in shown(result)
    assert 'Drains' not in shown(result) and result.issues


def test_small_positive_rate_does_not_round_to_zero():
    assert 'UOP: <0.01 mL/kg/hr' in shown(parsed(out='Urine:0.5'))
    assert '&lt;0.01' in current_shift_text({'current_shift': parsed(out='Urine:0.5').data}, True)


@pytest.mark.parametrize('out', ['Urine:300 mL', 'Urine:300 cc', 'Urine:300 (15 mL/kg)', 'Urine:300 (2 mL/kg/hr)'])
def test_volume_units_parentheticals(out):
    assert 'UOP: 1.30 mL/kg/hr' in shown(parsed(out=out))


def test_comma_number_decimal_and_multiline_breakdown():
    text = shown(parsed(out='Urine:1,200.75;\n Chest Tube:30; Other:60'))
    assert 'UOP: 5.22 mL/kg/hr' in text and 'Chest Tube: 0.13' in text


@pytest.mark.parametrize('out', ['Urine:-5', 'Urine:5 mL/kg/hr', 'Urine:5 L', 'Urine:NaN', 'Urine:<5', 'Urine:1; Urine:2'])
def test_ambiguous_or_invalid_volume_rejected(out):
    result = parse_current_shift(source(out=out))
    assert result.error and result.data is None


def test_unknown_categories_not_reassigned():
    text = shown(parsed(out='Urine:300; Emesis/NG output:45; Stool:70'))
    assert 'UOP: 1.30' in text and 'Other:' not in text and '45' not in text


@pytest.mark.parametrize('replacement', ['Out: 0', 'Out: 405 (20.25 mL/kg)', 'Out: 0 []'])
def test_no_breakdown_does_not_infer_urine(replacement):
    text = source()
    text = '\n'.join(replacement if line.startswith('Out:') else line for line in text.splitlines())
    result = parse_current_shift(text)
    assert not result.error and result.data is None


def test_broken_brackets_rejected():
    result = parse_current_shift(source().replace('Other:60]', 'Other:60'))
    assert result.error


@pytest.mark.parametrize('extra', ['\nI/O this shift:\nOut: 10 [Urine:10]\nWeight:20 kg', '\nWeight: 10 kg', '\nOut: 5 [Urine:5]'])
def test_duplicate_snapshots_values_not_added(extra):
    result = parse_current_shift(source() + extra)
    assert result.error and result.data is None


def test_repeated_summary_rejected():
    text = source().replace('IO Current Shift:', 'Intake/Output Summary (Last 24 hours) at 01/05/2026 0600\nIO Current Shift:')
    assert parse_current_shift(text).error


@pytest.mark.parametrize('body', ['', 'INTAKE/OUTPUT:\nNo data', 'INTAKE/OUTPUT:\nI/O last 3 completed shifts:\nOut: 500 [Urine:500]\nWeight:20 kg'])
def test_no_current_shift_marker_returns_empty(body):
    assert parse_current_shift(body).data is None


def test_parser_retains_only_allowlisted_data_and_no_source_intake():
    data = parsed().data
    assert set(data) == {'as_of', 'weight_kg', 'outputs'}
    assert set(data['outputs']) == {'urine', 'drains', 'chest_tube', 'other'}
    before = deepcopy(data)
    for _ in range(2):
        current_shift_text({'current_shift': data})
    assert data == before


@pytest.mark.parametrize('field,value', [('as_of', '01/05/26 0630'), ('weight_kg', '0'), ('outputs', {'urine': '-5'}), ('outputs', {'intake': '100'}), ('outputs', {'urine': 100})])
def test_invalid_archive_data_rejected(field, value):
    data = parsed().data
    data[field] = value
    with pytest.raises(ValueError):
        validate_current_shift(data)
