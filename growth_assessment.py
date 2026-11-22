"""Current, indicator-specific pediatric growth assessment for the handoff.

Under 24 months use WHO weight for recumbent length. From 24 to under 240
months use CDC BMI for age. The imported score next to a weight is never
treated as either indicator. Scores and problem severity are derived each
time, not saved, so edits and replacement imports cannot retain an old result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import math
import re

from anthropometrics import age_bounds, age_months, empty_anthropometrics
from bmi_reference import bmi_zscore
from who_growth_reference import weight_for_length_zscore


@dataclass
class GrowthAssessment:
    metric: str = ''
    z_score: float | None = None
    severity: str = ''
    display_text: str = ''
    reason: str = ''
    inputs: dict = field(default_factory=dict)


def malnutrition_severity(z_score: float) -> str:
    """Single-indicator cutoffs from the clinician's supplied reference.

    Classify the full precision score. In particular, -1.999 is mild even
    though rounding it to two decimals would display -2.00. No automated
    label is assigned from -1 through values above -1.65, which need other
    supportive clinical indicators in the supplied table.
    """
    if isinstance(z_score, bool) or not isinstance(z_score, (int, float)) or not math.isfinite(z_score):
        return ''
    if z_score <= -3:
        return 'Severe malnutrition'
    if z_score <= -2:
        return 'Moderate malnutrition'
    if z_score <= -1.65:
        return 'Mild malnutrition'
    return ''


def _quantity(value: str, factors: dict[str, str]) -> float | None:
    match = re.fullmatch(r'((?:\d+(?:\.\d+)?|\.\d+))\s*([a-z]+)', value.strip(), re.I)
    if not match or match[2].lower() not in factors:
        return None
    number = float(Decimal(match[1]) * Decimal(factors[match[2].lower()]))
    return number if math.isfinite(number) and number > 0 else None


def measured_weight_kg(value: str) -> float | None:
    return _quantity(value, {'kg': '1', 'g': '0.001', 'lb': '0.45359237',
                             'lbs': '0.45359237', 'oz': '0.028349523125'})


def recorded_length_cm(value: str) -> float | None:
    return _quantity(value, {'cm': '1', 'm': '100', 'in': '2.54', 'inches': '2.54'})


def _score_text(z_score: float) -> str:
    """Keep a displayed rounded score from implying the wrong severity band."""
    for precision in (2, 3, 4, 5, 6, 10, 15):
        rendered = f'{z_score:+.{precision}f}'
        if malnutrition_severity(float(rendered)) == malnutrition_severity(z_score):
            return rendered
    return repr(z_score)


def assess_growth(sheet: dict) -> GrowthAssessment:
    """Assess only complete, usable current inputs. No patient-input caching."""
    result = GrowthAssessment()
    attrs = sheet.get('anthropometrics') or empty_anthropometrics()
    warnings = sheet.get('import_warnings', {})
    if any(section in warnings for section in ('a', 'i', 'n')):
        result.reason = 'Growth assessment is unavailable until the age/sex and Nutrition import warnings are resolved.'
        return result
    bounds = age_bounds(attrs.get('age', ''))
    if bounds is None:
        result.reason = 'Document age to select weight-for-length below 2 years or BMI-for-age from 2 through 19 years.'
        return result
    if bounds[0] >= 240:
        result.reason = 'Pediatric growth z scores are not calculated at age 20 or older.'
        return result
    under_two = bounds[0] < 24 and bounds[1] <= 24
    if not under_two and bounds[0] < 24:
        result.reason = 'A more precise age is needed to select the growth chart at the 2-year boundary.'
        return result
    result.metric = 'weight_for_length' if under_two else 'bmi_for_age'
    sex = attrs.get('sex', '')
    if sex not in ('Male', 'Female'):
        result.reason = 'Supply explicit Male or Female sex for the growth chart.'
        return result
    if under_two:
        nutrition = sheet.get('nutrition') or {}
        if not nutrition.get('include'):
            result.reason = 'Weight-for-length needs an included measured weight and recorded recumbent length.'
            return result
        weight = measured_weight_kg(nutrition.get('weight', ''))
        length = recorded_length_cm(attrs.get('height', ''))
        if weight is None or length is None:
            result.reason = 'Weight-for-length needs measured weight and recumbent length with valid units.'
            return result
        if not 45 <= length <= 110:
            result.reason = 'WHO weight-for-length supports recumbent lengths from 45 to 110 cm. Verify the recorded length.'
            return result
        result.inputs = {'age': attrs['age'], 'sex': sex,
                         'measured_weight': nutrition['weight'], 'length': attrs['height'],
                         'weight_kg': weight, 'length_cm': length,
                         'reference': 'WHO 2006 weight-for-length'}
        try:
            z = weight_for_length_zscore(weight, length, sex)
        except (OSError, ValueError, KeyError, OverflowError):
            result.reason = 'Weight-for-length is unavailable. Verify the measurements and bundled WHO reference.'
            return result
        label, source = 'Weight-for-length z score', 'WHO'
    else:
        months = age_months(attrs.get('age', ''))
        if months is None:
            result.reason = 'BMI-for-age needs age at the BMI measurement in months or years and months. A whole-year age is not precise enough.'
            return result
        bmi_value = attrs.get('bmi', '')
        try:
            bmi = float(bmi_value.split()[0])
        except (ValueError, IndexError):
            result.reason = 'BMI-for-age needs the recorded BMI. Weight-for-age z scores cannot be substituted.'
            return result
        if not math.isfinite(bmi) or bmi <= 0 or bmi > 200:
            result.reason = 'Verify the recorded BMI before calculating BMI-for-age.'
            return result
        result.inputs = {'age': attrs['age'], 'age_months': months, 'sex': sex,
                         'recorded_bmi': bmi_value, 'bmi': bmi,
                         'reference': 'CDC 2000 LMS / 2022 extended BMI-for-age'}
        try:
            z = bmi_zscore(bmi, months, sex)
        except (OSError, ValueError, KeyError, OverflowError):
            result.reason = 'BMI-for-age is unavailable. Verify the recorded BMI and bundled CDC reference.'
            return result
        label, source = 'BMI-for-age z score', 'CDC'
    if not math.isfinite(z):
        result.reason = 'The supplied measurements did not produce a finite growth z score.'
        return result
    result.z_score = z
    result.severity = malnutrition_severity(z)
    result.display_text = f'{label}: {_score_text(z)} ({source})'
    result.reason = ('Uses measured weight and recumbent length, not dosing weight or weight-for-age.'
                     if under_two else
                     'Uses the recorded BMI and documented age month. Editing weight or height does not change the independently recorded BMI.')
    return result


def growth_measurements_text(sheet: dict) -> str:
    """Shared patient-column text for the screen and all handoff exports."""
    parts = [assess_growth(sheet).display_text]
    warnings = sheet.get('import_warnings', {})
    if 'i' not in warnings and sheet.get('circumferences'):
        from circumferences import circumferences_text
        age = (sheet.get('anthropometrics') or {}).get('age', '')
        if any(section in warnings for section in ('a', 'n')):
            age = ''
        parts.append(circumferences_text(sheet['circumferences'], age))
    return '\n'.join(part for part in parts if part)
