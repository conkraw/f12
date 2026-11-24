"""Head circumference percentile using the age at that measurement.

HC Age is an explicit measurement-age override. Otherwise a dated HC is
matched to the documented general Age and its import date. The raw age date
is stored, never a birth date or a calculated percentile. Reprinting or editing
another field cannot make a historical HC older or change its percentile.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
import math
import re
from zoneinfo import ZoneInfo

from anthropometrics import _age_for_math, age_bounds
from head_circumference_reference import DAYS_PER_MONTH, hc_percentile, hc_zscore, percentile_text


@dataclass
class HeadCircumferenceAssessment:
    percentile: float | None = None
    display_text: str = ''
    reason: str = ''
    inputs: dict = field(default_factory=dict)


def validate_age_as_of(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('The recorded-age reference date is invalid.')
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError('The recorded-age reference date is invalid.') from None


def record_age_as_of(sheet: dict, values: dict) -> None:
    """Stamp only an explicitly supplied current Age, never BMI Age or HC Age."""
    if 'age' not in values:
        return
    if values['age']:
        sheet['age_as_of'] = datetime.now(ZoneInfo('America/New_York')).date().isoformat()
    else:
        sheet.pop('age_as_of', None)


def _age_days(text: str) -> tuple[float | None, bool]:
    """Return a WHO day-age and whether the source omits day precision.

    Whole-year ages are not interpreted as an exact birthday. WHO uses
    30.4375 days per month. A week-plus-day age has day precision.
    """
    text = _age_for_math(text)
    number = r'(\d+(?:\.\d+)?)'
    match = re.fullmatch(number + r'\s*(days?|d|weeks?|wks?|w|months?|mos?|m)', text)
    if match:
        unit = match[2]
        factor = 1 if unit.startswith('d') else 7 if unit.startswith('w') else DAYS_PER_MONTH
        value = float(Decimal(match[1]) * Decimal(str(factor)))
        return (value, not unit.startswith('d')) if math.isfinite(value) else (None, False)
    match = re.fullmatch(r'(\d+)\s*(weeks?|wks?|w|months?|mos?|m)\s*(?:,|and)?\s*(\d+)\s*(?:days?|d)', text)
    if match:
        unit = match[2]
        days = int(match[3])
        if days >= (7 if unit.startswith('w') else 31):
            return None, False
        return int(match[1]) * (7 if unit.startswith('w') else DAYS_PER_MONTH) + days, not unit.startswith('w')
    match = re.fullmatch(r'(\d+)\s*(?:years?|yrs?|y)\s*(?:,|and)?\s*(\d+)\s*(?:months?|mos?|m)', text)
    if match and int(match[2]) < 12:
        return (int(match[1]) * 12 + int(match[2])) * DAYS_PER_MONTH, True
    return None, False


def head_age_eligible(text: str) -> bool:
    """Apply the existing under-two intent without coarse week/day bounds."""
    days, coarse = _age_days(text)
    if days is not None:
        if coarse:
            # Completed 104 weeks can straddle the second birthday. Do not
            # turn that uncertain current age into under-two eligibility.
            return 0 <= days and days + _age_resolution_days(text) <= 24 * DAYS_PER_MONTH
        return 0 <= days < 24 * DAYS_PER_MONTH
    bounds = age_bounds(text)
    return bounds is not None and bounds[0] < 24 and bounds[1] <= 24


def _age_resolution_days(text: str) -> float:
    normalized = _age_for_math(text)
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(weeks?|wks?|w|months?|mos?|m)', normalized)
    if match:
        resolution = 10 ** Decimal(match[1]).as_tuple().exponent
        allowance = resolution * (7 if match[2].startswith('w') else DAYS_PER_MONTH)
    else:
        # Months followed by days supply day precision. Years followed by
        # months give only completed months.
        allowance = 1 if re.search(r'(?:days?|d)$', normalized) else DAYS_PER_MONTH
    return allowance


def _later_than_current_age(days: float, current_text: str) -> bool:
    current, coarse = _age_days(current_text)
    if current is None:
        bounds = age_bounds(current_text)
        return bounds is not None and days >= bounds[1] * DAYS_PER_MONTH
    if not coarse:
        return days > current
    return days >= current + _age_resolution_days(current_text)


def assess_head_circumference(sheet: dict) -> HeadCircumferenceAssessment:
    result = HeadCircumferenceAssessment()
    attrs = sheet.get('anthropometrics') or {}
    item = (sheet.get('circumferences') or {}).get('head')
    if not item:
        return result
    if any(key in sheet.get('import_warnings', {}) for key in ('a', 'i', 'n')):
        result.reason = 'Resolve the age/sex and Nutrition import warnings before calculating the HC percentile.'
        return result
    # Keep the existing handoff display limited to patients under age 2.
    if not head_age_eligible(attrs.get('age', '')):
        result.reason = 'Head circumference is displayed for patients with a documented age under 2 years.'
        return result
    sex = attrs.get('sex', '')
    if sex not in ('Male', 'Female'):
        result.reason = 'Supply Male or Female growth-chart sex for the HC percentile.'
        return result
    explicit = bool(attrs.get('hc_age'))
    source_age = attrs.get('hc_age', '') if explicit else attrs.get('age', '')
    days, approximate = _age_days(source_age)
    if days is None:
        result.reason = 'Supply HC Age at the measurement in days, weeks and days, or months. A whole-year age is not precise enough.'
        return result
    recorded = item.get('date', '')
    anchor = sheet.get('age_as_of', '')
    if not explicit:
        if not recorded or not anchor:
            result.reason = 'Supply HC Age at the measurement, or re-paste a dated HC with the current Age so the measurement age can be established.'
            return result
        try:
            validate_age_as_of(anchor)
            elapsed = (date.fromisoformat(anchor) - date.fromisoformat(recorded)).days
        except (TypeError, ValueError):
            result.reason = 'Verify the HC measurement date and the recorded-age reference date.'
            return result
        if elapsed < 0:
            result.reason = 'The HC measurement date is later than the recorded Age. Re-paste the current source or supply HC Age.'
            return result
        days -= elapsed
    else:
        # A clinician may supply corrected age here. Never infer gestation or
        # correct again. Reject ages clearly later than the general age.
        if _later_than_current_age(days, attrs.get('age', '')):
            result.reason = 'HC Age is later than the documented patient age. Verify both ages.'
            return result
    if not 0 <= days < 24 * DAYS_PER_MONTH:
        result.reason = 'The HC measurement age must be from birth to under 2 years. Verify HC Age and the measurement date.'
        return result
    try:
        value = float(item['value_cm'])
        result.percentile = hc_percentile(value, days, sex)
        z = hc_zscore(value, days, sex)
    except (OSError, TypeError, ValueError, KeyError, OverflowError):
        result.reason = 'The HC percentile is unavailable. Verify HC, age, sex and the bundled WHO reference.'
        return result
    result.display_text = percentile_text(result.percentile)
    # Automatically backdating a rounded current age is an estimate. An
    # explicit HC Age selects the age supplied for this measurement.
    if approximate and not explicit:
        result.display_text = result.display_text.replace('[', '[~', 1)
    result.inputs = {'head_cm': value, 'sex': sex, 'age_days': days,
                     'age_source': 'HC Age' if explicit else 'Age',
                     'recorded_age': source_age, 'measurement_date': recorded,
                     'age_as_of': anchor if not explicit else '',
                     'reference': 'WHO head circumference-for-age'}
    if explicit:
        result.reason = f'WHO HC percentile uses the supplied HC Age ({source_age}). Use a clinician-selected corrected HC age when appropriate for prematurity.'
    else:
        result.reason = f'WHO HC percentile uses Age recorded on {anchor}, adjusted back to the HC date {recorded}.'
        if approximate:
            result.reason += ' The ~ marks an estimate from an age without exact day precision. Supply HC Age for a measurement-specific age.'
    if abs(z) > 5:
        result.reason += ' The HC is beyond 5 standard deviations. Verify the measurement, units and age.'
    return result
