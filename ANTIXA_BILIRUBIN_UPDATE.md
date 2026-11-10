Version 6.52, based on the supplied PICU651.zip

HEPLMW
The latest included numeric HEPLMW whose collection date equals today's Eastern
calendar date prints under HEME > DVT Prophylaxis, after the medications. Its
value, supplied units, flags and collection date/time are preserved. No dose
adjustment or therapeutic interpretation is calculated. Other heparin assay
codes are not substituted for HEPLMW.

This is a same-calendar-date rule, not a rolling 24-hour window. A previous-day
HEPLMW is shown in the lower coagulation area. Regenerating the handoff on a
later date reevaluates placement without changing stored data. Previously
downloaded PDFs do not change. When there is a current-day result, no duplicate
or older HEPLMW is printed below. Without a current-day result, the latest
eligible older result is selected by the existing coagulation display.

When several results share a day, collection times are compared only when all
have times. Otherwise the existing Epic source ordering is retained. Pending,
canceled, excluded and future-dated values are not promoted as current levels.
A failed G import suppresses the derived anti-Xa display. Medication absence
still displays DVT Prophylaxis: None, followed by the independent lab result.
A lab is not treated as evidence that a medication is prescribed.

Hyperbilirubinemia
The latest eligible total bilirubin (BILITOT, including existing TBILI / TOTAL
BILIRUBIN aliases) adds Hyperbilirubinemia to Problems when the source explicitly
marks a numeric result (H), (HH) or (HIGH). A newer normal result does not inherit
an older high flag. Direct bilirubin, an asterisk alone, pending results and
missing values do not trigger this rule. Existing admission-date, exclusion,
failed-import and problem edit/dismissal handling remains in effect. This is the
requested display flag, not an independent diagnosis or treatment recommendation.
The original laboratory rows and imported diagnoses remain unchanged.

Install
Extract this full ZIP and replace the existing application code with the folder
contents, keeping app.py at the root. Restart the app and refresh the browser.
For an existing 6.51 deployment, the changed application modules are:
app.py
categories.py
lab_windows.py
problem_review.py

Keep existing Secrets, both passwords, encryption key, shared archive, custom
categories, medication mappings and public BMI reference file unchanged. Do not
rerun setup generators. No new dependencies or schema migration are required.
No re-pasting is needed for results already saved. Import the complete G section
or full SmartPhrase to add newly available laboratory rows.

Avoid downgrading after saving a review decision for the new bilirubin rule.
Older versions do not recognize that decision key.
