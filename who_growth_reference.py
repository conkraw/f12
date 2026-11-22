"""WHO 2006 weight-for-recumbent-length z scores from bundled public data.

The caller selects patients younger than 24 months and supplies recumbent
length in centimeters, actual weight in kilograms and explicit growth-chart
sex. Reference lengths are 45.0 through 110.0 cm, without extrapolation.
Only public reference data is cached. Patient values are never cached or sent
to a remote calculation service. Sources are in data/GROWTH_REFERENCE_SOURCES.txt.
"""
from __future__ import annotations

import csv
import io
import math
from functools import lru_cache
from pathlib import Path


REFERENCE_PATH = Path(__file__).resolve().parent / 'data' / 'who_wfl_lms.csv'


def parse_reference(text: str) -> dict:
    """Validate the complete WHO table for both sexes before using any row."""
    rows = {}
    for source in csv.DictReader(io.StringIO(text.lstrip('\ufeff'))):
        try:
            sex = int(source['Sex'])
            length = float(source['Length'])
            values = tuple(float(source[key]) for key in ('L', 'M', 'S'))
        except (KeyError, TypeError, ValueError):
            raise ValueError('The WHO weight-for-length reference has an unexpected format.') from None
        if (sex not in (1, 2) or not math.isfinite(length)
                or any(not math.isfinite(value) for value in values)
                or values[1] <= 0 or values[2] <= 0):
            raise ValueError('The WHO weight-for-length reference contains invalid parameters.')
        tenth = round(length * 10)
        if not 450 <= tenth <= 1100 or abs(length * 10 - tenth) > 1e-7:
            raise ValueError('The WHO weight-for-length reference has invalid length rows.')
        if (sex, tenth) in rows:
            raise ValueError('The WHO weight-for-length reference contains duplicate rows.')
        rows[sex, tenth] = values
    if any((sex, tenth) not in rows for sex in (1, 2) for tenth in range(450, 1101)):
        raise ValueError('The WHO weight-for-length reference is incomplete.')
    # Anchors from the official WHO expanded tables protect against wrong tables.
    for sex, anchor in ((1, (-0.3521, 2.441, 0.09182)),
                        (2, (-0.3833, 2.4607, 0.09029))):
        if any(abs(actual - expected) > 1e-8
               for actual, expected in zip(rows[sex, 450], anchor)):
            raise ValueError('The reference does not match the WHO weight-for-length tables.')
    return rows


@lru_cache(maxsize=1)
def load_reference() -> dict:
    return parse_reference(REFERENCE_PATH.read_text(encoding='utf-8-sig'))


def weight_for_length_zscore(weight_kg: float, length_cm: float, sex: str) -> float:
    """Return the unrounded WHO z score, including WHO's restricted LMS tails.

    LMS parameters are linearly interpolated between adjacent 0.1 cm rows, as
    in WHO's anthro implementation. Beyond +/-3 SD, use the fixed weight
    distance between the corresponding 2 and 3 SD values. Length outside the
    reference range, missing sex, and invalid measurements raise ValueError.
    """
    if sex not in ('Male', 'Female'):
        raise ValueError('WHO weight-for-length requires explicit Male or Female growth-chart sex.')
    try:
        weight, length = float(weight_kg), float(length_cm)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Weight and recumbent length must be positive finite numbers.') from None
    if (isinstance(weight_kg, bool) or isinstance(length_cm, bool)
            or not math.isfinite(weight) or not math.isfinite(length) or weight <= 0):
        raise ValueError('Weight and recumbent length must be positive finite numbers.')
    if not 45 <= length <= 110:
        raise ValueError('WHO weight-for-length requires recumbent length from 45 to 110 cm.')
    rows = load_reference()
    chart_sex = 1 if sex == 'Male' else 2
    scaled = length * 10
    lower = math.floor(scaled)
    upper = min(lower + 1, 1100)
    fraction = scaled - lower
    l, m, s = (a + fraction * (b - a)
               for a, b in zip(rows[chart_sex, lower], rows[chart_sex, upper]))
    z = math.log(weight / m) / s if l == 0 else ((weight / m) ** l - 1) / (l * s)

    def weight_at_z(sd: float) -> float:
        return m * math.exp(s * sd) if l == 0 else m * (1 + l * s * sd) ** (1 / l)

    if z < -3:
        minus3, minus2 = weight_at_z(-3), weight_at_z(-2)
        return -3 + (weight - minus3) / (minus2 - minus3)
    if z > 3:
        plus3, plus2 = weight_at_z(3), weight_at_z(2)
        return 3 + (weight - plus3) / (plus3 - plus2)
    return z
