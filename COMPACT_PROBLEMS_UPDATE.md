Current v6.34 behavior is described in AGE_COUNTS_UPDATE.md. Automatic Possible prefixes in the older notes below are no longer printed.

# Compact Problems and BMI output: Version 6.31

## Printed handoff

Problems: Hyponatremia, Hypokalemia, Hypomagnesemia

This is one wrapping paragraph, not a vertical list. The title shares the first
line. Evidence, thresholds, medication names, dates and review-status prefixes
are kept off this band. It remains in the same location below the system columns.
The original selection rules have not changed. Optional confirmations, custom
wording, hiding, and evidence details remain in the Problems editor. No mandatory
review dialog was added. Potential sepsis, respiratory failure, kidney injury,
metabolic acidosis and constipation keep a brief Possible qualifier unless
confirmed by the user, because those automated triggers alone are not diagnostic.

PDF, HTML, text, preview and Print all use the same list. Long lists wrap rather
than being clipped. Existing page fitting remains. Very long sheets can still
need more than one page. No dose, note, result, or device is dropped to force fit.
Import-error warnings are separate and remain visible as before.

## Sex and BMI

In I / NUTRITION or N / admission, include explicit lines such as:

    Age: 5 years 2 months
    Sex: Female
    BMI: 17.14 kg/m²

M and F are also accepted. A value can follow Sex: on the next line.
Conflicting sex values produce an import warning rather than being guessed.
Existing age and sex can still be edited in Labs / Vitals.

No BMI value, percentile, or missing-percentile placeholder prints below
24 months. Unknown age also suppresses BMI until age is supplied. The value is
not deleted from storage. At/above age 2 a documented BMI prints. A calculated
percentile prints only with the required age/sex/reference inputs. Adults keep
the recorded BMI but do not receive pediatric percentiles. The source height,
BSA, measured weight, weight Z-score, and dosing weight are not changed.

Age and sex are not inferred from a chart footnote, diagnosis, weight or BMI.
Years-only age can establish eligibility for printing a BMI, but does not invent
an exact month for percentile calculation. BMI must correspond to age at the
measurement. No DOB capture was added.

The existing CDC formula and reference-data installer are unchanged.
CDC reference: https://www.cdc.gov/growth-chart-training/hcp/using-growth-charts/who-using.html

## Installation

Upload this complete folder's contents, with app.py at the repository root.
Preserve all credentials, the public CDC CSV, and the private data repository.
Do not rerun generators. No new dependencies or schema change. Existing sheets
use the new layout when reopened or exported. Re-paste complete I or N only to
import newly added age/sex lines. Partial-section semantics are unchanged.

Tests use synthetic records, simulated UI callbacks and mocked storage.
No live deployment, private repository, or clinical validation was performed.
