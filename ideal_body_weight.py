"""Pediatric reference-weight estimate using the CDC median BMI method.

For ages 24 to under 240 months with recorded BMI at or above the CDC 95th
percentile, estimated IBW is the age/sex-specific median BMI times recorded
height in meters squared. This display estimate does not select a medication,
fluid, nutrition or ventilator dosing weight. All patient inputs are read
fresh. Only the existing public CDC reference table is cached.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import math

from anthropometrics import bmi_age_text, clean_field, resolve_bmi_age
from bmi_reference import load_reference


# Broad entry guard for likely unit errors. This is not a CDC growth-chart
# height range and does not validate body proportions for clinical use.
MIN_HEIGHT_M = 0.45
MAX_HEIGHT_M = 2.5


@dataclass
class IdealBodyWeightAssessment:
    weight_kg: float | None = None
    display_text: str = ''
    reason: str = ''
    inputs: dict = field(default_factory=dict)


def _height_m(value: str) -> float:
    """Validate documented units and charting annotations before conversion."""
    normalized = clean_field('height', value)
    number, unit = normalized.split()
    factor = {'cm': '0.01', 'm': '1', 'in': '0.0254', 'inches': '0.0254'}[unit]
    height = float(Decimal(number) * Decimal(factor))
    if not math.isfinite(height) or not MIN_HEIGHT_M <= height <= MAX_HEIGHT_M:
        raise ValueError('Verify the height. Automatic IBW uses a 45 to 250 cm entry guard.')
    return height


def assess_ideal_body_weight(sheet: dict) -> IdealBodyWeightAssessment:
    """Return a display-only estimate for complete, eligible current inputs.

    Use the same documented BMI Age and monthly CDC bin as BMI-for-age.
    Measured weight and dosing weight never select eligibility or replace
    missing BMI or height. A whole-year patient age does not supply a guessed
    month. No patient field, review decision or previously saved value is
    changed by calculating this estimate.
    """
    result = IdealBodyWeightAssessment()
    warnings = sheet.get('import_warnings') or {}
    if any(section in warnings for section in ('a', 'i', 'n')):
        result.reason = 'Estimated IBW is unavailable until the age/sex and Nutrition import warnings are resolved.'
        return result
    attrs = sheet.get('anthropometrics') or {}
    months, age_reason = resolve_bmi_age(attrs)
    if months is None:
        result.reason = age_reason
        return result
    sex = attrs.get('sex', '')
    if sex not in ('Male', 'Female'):
        result.reason = 'Estimated IBW needs explicit Male or Female sex for the growth chart.'
        return result
    try:
        bmi = float(clean_field('bmi', attrs.get('bmi', '')).split()[0])
    except (ValueError, TypeError, AttributeError, IndexError, OverflowError):
        result.reason = 'Estimated IBW needs a valid recorded BMI to assess the 95th percentile threshold.'
        return result
    try:
        values = load_reference()[1 if sex == 'Male' else 2, math.floor(months) + 0.5]
        median_bmi, p95 = values['m'], values['p95']
    except (OSError, ValueError, KeyError, OverflowError):
        result.reason = 'Estimated IBW is unavailable. Verify the bundled CDC BMI reference.'
        return result
    # Compare the recorded BMI directly with the published P95. Rounded
    # percentile display or an unrepresentable extreme z score cannot change
    # eligibility at this boundary.
    if bmi < p95:
        result.reason = 'Estimated IBW is shown when recorded BMI is at or above the 95th percentile for age and sex.'
        return result
    try:
        height = _height_m(attrs.get('height', ''))
        weight = median_bmi * height ** 2
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
        result.reason = ('Estimated IBW needs a valid recorded height with units. '
                         'Verify the height and any annotations. Automatic estimates '
                         'use a broad 45 to 250 cm entry guard for likely unit errors.')
        return result
    if not math.isfinite(weight) or weight <= 0:
        result.reason = 'The recorded height did not produce a positive finite IBW estimate.'
        return result
    result.weight_kg = weight
    result.display_text = f'Estimated IBW: {weight:.1f} kg (BMI 50th %tile)'
    result.reason = (
        f'Uses CDC median BMI for {months:g} months and recorded height squared. '
        'Verify that height and BMI refer to the same measurement episode. '
        'This reference estimate does not select a dosing weight.'
    )
    result.inputs = {
        'age': attrs.get('age', ''),
        'bmi_age': attrs.get('bmi_age', ''),
        'age_source': 'BMI Age' if attrs.get('bmi_age') else 'Age',
        'age_at_bmi': bmi_age_text(attrs),
        'age_months': months,
        'sex': sex,
        'recorded_bmi': attrs.get('bmi', ''),
        'bmi': bmi,
        'recorded_height': attrs.get('height', ''),
        'height_m': height,
        'median_bmi': median_bmi,
        'bmi_p95': p95,
        'reference': 'CDC age/sex-specific 50th percentile BMI times height in meters squared',
    }
    return result
