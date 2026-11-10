# PICU Handoff 6.59

Built from PICU658.zip. This update adds MRSANPADM to the MRSA screen and
compares both supported MRSA components by their laboratory collection date
and time. The 6.58 medication, sodium, line-day and saving features are included.

## MRSA screening

The newest included result across MRSADNA and MRSANPADM in the G laboratory
block appears in Demographics / Weight as MRSA Screen: followed by the original result and
collection date. Only the label is bold in the preview and PDF.

Negative, Not detected, Positive, Detected, and Pending retain their original
wording. Both lab codes are compared together by collection date and time,
regardless of code or where a result appears in the pasted text. Upload time
and handoff-save time do not determine the chosen result. If same-day collection
times are incomplete, the existing Epic source order is retained. A newer
negative or pending result replaces an older positive result. A missing or
excluded result is not presented as a negative screen.

A MRSADNA or MRSANPADM result must be present in the pasted G laboratory block
with its collection date. Both tab-separated rows and rows whose tabs became spaces are accepted.
Existing saved rows for either component work immediately. Edit or exclude the source result
using the existing laboratory editor. A failed G-block import hides the old
screen until that block is successfully refreshed or reviewed.

## Bupivacaine

Orders containing bupivacaine appear under Neuro > Epidural, including combined
fentanyl-bupivacaine orders. This placement takes priority over older saved
mappings and category snapshots, so an existing saved order does not require
another paste. Each visible order appears once.

The source dose, concentration, route, frequency and recorded rate are retained.
The Epidural display heading does not rewrite a documented route. Existing
hidden or excluded orders keep their display choices. Other medications and
custom categories keep their prior placement.

## Hypernatremia

The Problems rules now add Hypernatremia when the newest eligible blood sodium
result is greater than 145 mmol/L or mEq/L. Routine NA and SODIUM results with
omitted units follow the same cutoff. Urine sodium and sodium-containing
medications do not trigger this rule.

An older elevated result does not override a newer normal result. A newer
unusable result does not cause an older high result to be reused. The rule uses
the existing problem review controls, so its evidence can be reviewed and the
prompt can be confirmed or dismissed. Manually entered diagnoses stay intact.

Cutoff reference: Royal Children's Hospital, Hypernatraemia guideline.
https://www.rch.org.au/clinicalguide/guideline_index/hypernatraemia/

## Vascular line day numbers

PIVs, PICCs, CVCs/CVLs, arterial lines and other recognized vascular access keep
their documented insertion date and show the current day beside it.

Example on November 10, 2026:
PICC Left Basilic (11/08/26, Day 3)

Insertion is Day 1. The next calendar date is Day 2. Calculations use
America/New_York, including daylight saving changes, rather than elapsed
24-hour periods or the server's UTC date.

The date remains the stored value. The day number is calculated when the
handoff is displayed or exported, so reopening a saved handoff does not freeze
its day count. The HTML preview refreshes its line days every minute, on focus,
and before browser printing. PDFs are fixed snapshots and must be regenerated
to show a later day's count.

Missing, invalid or future insertion dates do not produce an invented day
number. Removed lines remain excluded. ETT history and other nonvascular devices
keep their existing formatting. Older CVLs stored under Other are recognized at
display time without modifying their saved category.

## Install

Extract this package and upload the contents of the application folder to your
existing code repository. Keep app.py at the repository root. Use the complete
folder so the new mrsa.py module and all related changes are included. Restart
the Streamlit app and refresh your browser.

Keep your existing Streamlit Secrets, passwords, encryption key, saved archive,
BMI reference data, mappings and custom categories. Do not rerun setup or secret
generators. This update adds no dependency and keeps archive schema 34.

The save-before-Print-All behavior, per-room Last saved timestamps, BMI label
formatting, difficult-airway choices and existing conflict checks remain in
place. These changes apply to saved source data that is already present. Paste
updated SmartPhrase output when adding a laboratory result or order that was
not previously included.

## Verification and example

Tests use synthetic data. The running deployment and shared patient archive
were not accessed. TEST_REPORT.md records verification of this package.

The examples folder includes mrsa_epidural_sodium_line_days_preview.pdf and the
matching synthetic SmartPhrase text. The PDF uses November 10, 2026 as its
example date. The matching HTML refreshes its line days to the date it is opened.
