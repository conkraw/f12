"""WHO head-circumference-for-age percentiles from bundled public data.

The caller supplies head circumference in centimeters, age at measurement in
days and explicit growth-chart sex. Only reference data is cached. No patient
measurements are stored or sent to a remote service. Prematurity correction
and the app's narrower display-age eligibility are the caller's responsibility.
Sources and data provenance are in data/GROWTH_REFERENCE_SOURCES.txt.
"""
from __future__ import annotations

import csv
import io
import math
from functools import lru_cache
from pathlib import Path
from statistics import NormalDist


REFERENCE_PATH = Path(__file__).resolve().parent / 'data' / 'who_hcfa_lms.csv'
MAX_AGE_DAYS = 1826
DAYS_PER_MONTH = 30.4375


def parse_reference(text: str) -> dict:
    """Validate both complete daily sex-specific WHO reference series."""
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if reader.fieldnames != ['Sex', 'AgeDays', 'L', 'M', 'S']:
        raise ValueError('The WHO head circumference reference has an unexpected format.')
    rows = {}
    for source in reader:
        try:
            sex = int(source['Sex'])
            day = int(source['AgeDays'])
            values = tuple(float(source[key]) for key in ('L', 'M', 'S'))
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError('The WHO head circumference reference has an unexpected format.') from None
        if (None in source or sex not in (1, 2) or not 0 <= day <= MAX_AGE_DAYS
                or any(not math.isfinite(value) for value in values)
                or values[0] != 1 or values[1] <= 0 or values[2] <= 0):
            raise ValueError('The WHO head circumference reference contains invalid parameters.')
        if (sex, day) in rows:
            raise ValueError('The WHO head circumference reference contains duplicate rows.')
        rows[sex, day] = values
    if len(rows) != 2 * (MAX_AGE_DAYS + 1):
        raise ValueError('The WHO head circumference reference is incomplete.')
    # Exact anchors from WHO anthro's hcanthro.txt distinguish this table from
    # the other daily growth standards and detect switched sex labels.
    anchors = {
        (1, 0): (1, 34.4618, 0.03686),
        (2, 0): (1, 33.8787, 0.03496),
        (1, MAX_AGE_DAYS): (1, 50.7372, 0.02945),
        (2, MAX_AGE_DAYS): (1, 49.9225, 0.0285),
    }
    for key, anchor in anchors.items():
        if any(abs(actual - expected) > 1e-9
               for actual, expected in zip(rows[key], anchor)):
            raise ValueError('The reference does not match the WHO head circumference tables.')
    return rows


@lru_cache(maxsize=1)
def load_reference() -> dict:
    """Cache public reference rows only, never a patient's calculation."""
    return parse_reference(REFERENCE_PATH.read_text(encoding='utf-8-sig'))


def hc_zscore(head_cm: float, age_days: float, sex: str) -> float:
    """Return the full-precision WHO head-circumference-for-age z score.

    The WHO anthro implementation rounds age to the nearest integer day,
    resolving half-day ties upward. Ages outside the bundled reference are
    rejected before rounding. There is no age or measurement extrapolation.
    """
    if sex not in ('Male', 'Female'):
        raise ValueError('WHO head circumference requires explicit Male or Female growth-chart sex.')
    try:
        head, age = float(head_cm), float(age_days)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Head circumference and age must be finite numbers.') from None
    if (isinstance(head_cm, bool) or isinstance(age_days, bool)
            or not math.isfinite(head) or not math.isfinite(age)
            or not 0 < head <= 100):
        raise ValueError('Head circumference must be positive centimeters and age must be finite.')
    if not 0 <= age <= MAX_AGE_DAYS:
        raise ValueError('WHO head circumference supports age from 0 through 1826 days.')
    day = math.floor(age + 0.5)
    chart_sex = 1 if sex == 'Male' else 2
    l, m, s = load_reference()[chart_sex, day]
    z = math.log(head / m) / s if l == 0 else math.expm1(l * math.log(head / m)) / (l * s)
    if not math.isfinite(z):
        raise ValueError('Head circumference is outside the calculable reference range.')
    return z


def hc_percentile(head_cm: float, age_days: float, sex: str) -> float:
    """Return an unrounded percentile, retaining full z-score precision."""
    return 100 * NormalDist().cdf(hc_zscore(head_cm, age_days, sex))


def percentile_text(percentile: float) -> str:
    """Format a compact percentile bracket without claiming 0th or 100th."""
    try:
        value = float(percentile)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('A percentile must be a finite number from 0 to 100.') from None
    if isinstance(percentile, bool) or not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError('A percentile must be a finite number from 0 to 100.')
    if value < 1:
        return '[<1st %tile]'
    if value > 99:
        return '[>99th %tile]'
    whole = math.floor(value + 0.5)
    suffix = 'th' if 10 <= whole % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(whole % 10, 'th')
    return f'[{whole}{suffix} %tile]'
