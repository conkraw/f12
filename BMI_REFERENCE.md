# Pediatric growth reference data

Version 6.106 bundles both complete public reference tables. No download is
needed during handoff creation, and no patient measurement is sent to a growth
calculation service.

## Under 2 years

Use WHO 2006 weight-for-recumbent-length with the included measured weight,
recorded recumbent length, and explicit Male or Female growth-chart sex.
Dosing weight and the score beside an Epic weight row are not used.

The table covers 45 through 110 cm and both sexes. LMS parameters are
interpolated between adjacent 0.1 cm rows. Scores beyond +/-3 use WHO's fixed
weight distance between 2 and 3 SD. There is no length extrapolation and no
assumed standing-height adjustment. The infant length must be recumbent.

File: data/who_wfl_lms.csv
Source: https://www.who.int/tools/child-growth-standards/standards/weight-for-length-height

## Ages 2 through 19

Use the recorded BMI and explicit BMI Age when supplied, with growth-chart
sex. For example, BMI Age: 2 y.o. 1 m.o. means 25 months. General Age remains
separate and stays unchanged in the patient header. BMI Age is shown beside
BMI on the handoff so the calculation age can be reviewed.

BMI Age takes priority for the BMI z score, percentile and weight category.
Without BMI Age, general Age can be used when it supplies total months or years
plus months. A whole-year age such as 2 y.o. is insufficient. An explicit but
incomplete or out-of-range BMI Age does not silently fall back to another age.
No date of birth is required or retained. Pediatric scoring stops at 240 months.

Each new Nutrition import clears a prior BMI Age unless the current paste
supplies it again. Conflicting future measurement ages and incompatible current
age groups do not produce a BMI score. WFL and head-circumference eligibility
continue to use general Age. BMI Age alone does not establish an infant's
current age.

The calculation preserves the app's existing monthly-bin convention. For
example, the 48.5-month row covers age 48 to under 49 months. Below or at P95,
use CDC 2000 LMS directly. Above P95, use the CDC 2022 extended half-normal
method. Low z scores are never recovered from a rounded percentile.

The recorded BMI remains authoritative. Editing measured weight or height does
not recalculate that independently recorded BMI. Update the BMI field when
those source measurements change. Missing BMI does not create a guessed score.

File: data/cdc_bmi_age_2022.csv
Sources:
https://www.cdc.gov/growthcharts/extended-bmi-data-files.htm
https://www.cdc.gov/growthcharts/cdc-data-files.htm

The protected Admin BMI reference panel remains available for optional public
table refreshes. Keeping the bundled CSV in the code repository makes the
reference available after redeployment.

## Malnutrition rule

Use only the age-appropriate calculated indicator and the clinician's supplied
single-data-point cutoffs:

| Calculated z score | Automatic problem |
| --- | --- |
| -2 < z <= -1.65 | Mild malnutrition |
| -3 < z <= -2 | Moderate malnutrition |
| z <= -3 | Severe malnutrition |
| z > -1.65 | No automatic malnutrition problem |

The supplied table requires other supporting indicators for the -1 through
-1.64 range, so this implementation does not assign a problem from that range.
These are the supplied workflow cutoffs, not a claim that every published
malnutrition definition uses the same mild cutoff.

Classify the unrounded score. Display two decimals in ordinary cases and enough
additional precision near a cutoff to avoid displaying a different category.
The existing Problems review and dismissal controls remain available. A change
to the supporting inputs invalidates the old decision fingerprint.

Scores and severity are calculated from the current sheet and are not stored as
fixed diagnoses. Missing inputs, an unsupported age or length, missing reference
data, or unresolved demographic/Nutrition import warnings omit the calculated
score and automatic malnutrition label. A missing score does not imply normal
nutrition. Existing source diagnoses are not removed or rewritten.

The old untyped weight-chart z score remains in the editor and encrypted record.
It is omitted from the printed handoff, which displays the named WFL or
BMI-for-age score instead.

## High growth categories

At ages 2 through 19, the existing recorded BMI is classified using the same
CDC age/sex row as its z score and percentile. Only the highest applicable
category is added to Problems:

| Category | CDC threshold |
| --- | --- |
| Overweight | BMI at or above P85 and below P95 |
| Obesity | BMI at or above P95, below severe criteria |
| Severe obesity | BMI at or above 120% of P95, or at or above 35 kg/m² |

P85 is calculated from the LMS parameters at the exact standard-normal 85th
percentile, approximately z +1.03643. P95 is the official table value. The
standard-normal 95th percentile is approximately z +1.64485. Comparisons use
unrounded values. Severe obesity does not have one fixed z-score threshold.
The classification remains available if an extreme high BMI is beyond the
finite z-score calculation range.

Below age 2, WHO WFL z above +2 adds High weight-for-length. It does not add
pediatric BMI obesity labels. No additional Underweight problem is added,
because the existing requested malnutrition rules cover the low growth score.
No Healthy weight label is added to Problems.

Sources:
https://www.cdc.gov/bmi/child-teen-calculator/bmi-categories.html
https://www.cdc.gov/growth-chart-training/hcp/using-growth-charts/who-using.html

## Measurement and reference checks

Check growth measurements in clinical context, including fluid balance and
measurement accuracy. Head and abdominal circumference are measurements only
and do not contribute to the malnutrition calculation.

Complete source URLs, retrieval date, row counts and hashes are in
data/GROWTH_REFERENCE_SOURCES.txt. Only public reference data belongs in data/.
