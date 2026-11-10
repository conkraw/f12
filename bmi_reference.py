"""CDC BMI-for-age calculation. Reference data only, never remote patient input.

Monthly rows are used as CDC specifies: 48.5 applies to 48 <= age < 49 months.
LMS below/equal P95, extended half-normal method above P95. No extrapolation
outside 24 <= age < 240 months. No guessing sex or age from weight percentiles.
Sources and retrieval options are in BMI_REFERENCE.md.
"""
from __future__ import annotations
import csv
import hashlib
import io
import math
from functools import lru_cache
from pathlib import Path
from statistics import NormalDist

REFERENCE_URL = 'https://www.cdc.gov/growthcharts/data/extended-bmi/bmi-age-2022.csv'
REFERENCE_PATH = Path(__file__).resolve().parent / 'data' / 'cdc_bmi_age_2022.csv'


def parse_reference(text: str) -> dict:
    rows = {}
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    for source in reader:
        row = {str(k).strip().lower(): v.strip() for k, v in source.items() if k is not None and isinstance(v, str)}
        try:
            sex, age = int(row['sex']), float(row['agemos'])
            values = {key: float(row[key]) for key in ('l', 'm', 's', 'sigma', 'p95')}
        except (KeyError, ValueError):
            raise ValueError('The CDC BMI reference has an unexpected format.') from None
        if sex not in (1, 2) or not math.isfinite(age) or any(not math.isfinite(v) for v in values.values()) or min(values[k] for k in ('m', 's', 'sigma', 'p95')) <= 0:
            raise ValueError('The CDC BMI reference contains invalid parameters.')
        if (sex, age) in rows:
            raise ValueError('The CDC BMI reference contains duplicate age/sex rows.')
        rows[sex, age] = values
    if any((sex, month + 0.5) not in rows for sex in (1, 2) for month in range(24, 240)):
        raise ValueError('The CDC BMI reference is incomplete.')
    # Published CDC worked examples prevent accepting an unrelated table.
    girl, boy = rows[2, 114.5], rows[1, 50.5]
    if abs(girl['m'] - 16.57626713) > 0.0001 or abs(boy['p95'] - 17.8219) > 0.001:
        raise ValueError('The BMI reference does not match the CDC worked examples.')
    return rows


@lru_cache(maxsize=1)
def load_reference() -> dict:
    # Only public table data is cached. Patient inputs are never cached.
    return parse_reference(REFERENCE_PATH.read_text(encoding='utf-8-sig'))


def install_reference(content: bytes) -> str:
    if len(content) > 2_000_000:
        raise ValueError('The reference file is too large.')
    parse_reference(content.decode('utf-8-sig'))
    REFERENCE_PATH.parent.mkdir(exist_ok=True)
    temp = REFERENCE_PATH.with_suffix('.tmp')
    temp.write_bytes(content)
    temp.replace(REFERENCE_PATH)
    load_reference.cache_clear()
    return hashlib.sha256(content).hexdigest()


def download_reference() -> str:
    """One fixed public-data URL, no patient fields in request, no telemetry."""
    import requests
    response = requests.get(REFERENCE_URL, timeout=(5, 15))
    response.raise_for_status()
    return install_reference(response.content)


def percentile_from_parameters(bmi: float, values: dict) -> float:
    if not math.isfinite(bmi) or bmi <= 0:
        raise ValueError('BMI must be positive.')
    if bmi > values['p95']:
        return 90 + 10 * NormalDist().cdf((bmi - values['p95']) / values['sigma'])
    l, m, s = values['l'], values['m'], values['s']
    z = math.log(bmi / m) / s if l == 0 else ((bmi / m) ** l - 1) / (l * s)
    return 100 * NormalDist().cdf(z)


def bmi_percentile(bmi: float, age_months: float, sex: str, reference: dict | None = None) -> float:
    if not math.isfinite(age_months) or not 24 <= age_months < 240 or sex not in ('Male', 'Female'):
        raise ValueError('CDC BMI percentile requires age 24 to under 240 months and explicit growth-chart sex.')
    rows = load_reference() if reference is None else reference
    return percentile_from_parameters(bmi, rows[1 if sex == 'Male' else 2, math.floor(age_months) + 0.5])


def bmi_percentile_summary(data: dict) -> tuple[str, str]:
    from anthropometrics import age_months, age_bounds
    if not data['bmi']:
        return '', 'BMI is not supplied.'
    bounds = age_bounds(data['age'])
    if bounds and bounds[0] < 24 and bounds[1] <= 24:
        return 'not calculated (<2 years)', 'CDC BMI-for-age is not used here below age 2.'
    if bounds and bounds[0] >= 240:
        return 'not applicable (adult)', 'CDC pediatric BMI percentiles are not used at age 20 or older.'
    months = age_months(data['age'])
    if months is None or data['sex'] not in ('Male', 'Female'):
        return 'unavailable (age/sex needed)', 'Supply age at BMI measurement in months or years AND months, and explicit sex for the growth chart. No DOB is required.'
    try:
        p = bmi_percentile(float(data['bmi'].split()[0]), months, data['sex'])
    except (OSError, ValueError, KeyError):
        return 'unavailable (reference needed)', 'Load the public CDC reference in Admin. No patient data is sent.'
    label = '<0.1' if p < 0.1 else '>99.9' if p > 99.9 else f'{p:.1f}'
    return label + ' (CDC)', 'Calculated from CDC monthly age/sex parameters using the recorded BMI. Verify source measurements before clinical use.'
