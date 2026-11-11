# PICU Handoff 6.62

Built from PICU661.zip. After signing in, choose whether to start a new patient
list or continue the saved handoffs. Nothing is deleted just by signing in.

From 6.61, replace app.py, models.py and handoff_reset.py, and add daily_start.py
and census_guard.py. Uploading this complete application folder includes all
five files. Restart Streamlit and refresh your browser.

## After sign-in

Start new patient list opens a review showing the rooms to remove and the rooms
that will stay. Confirm that review to start today's list, then enter your
patients. Continue saved handoffs opens the existing workspace so you can print
processed handoffs, update patients or add patients. Continue makes no write or
deletion to the saved archive.

The new-list review uses each handoff's last saved timestamp in America/New_York.
The archive does not have a separate timestamp for when clinical text was entered.
The removal rule is:

- Remove handoffs last saved on a date before today.
- Remove handoffs last saved today from 5:00:00 AM through 8:30:00 AM, inclusive.
- Keep today's handoffs saved before 5:00 AM or after 8:30 AM.
- Keep handoffs with missing, invalid or future save times for manual review.

The screen shows the last saved time and reason for each room. The reviewed
selection is fixed until confirmation. If the shared archive or Eastern date
changes, reload and review again before starting the list.

A successful start is recorded in the encrypted archive. A second user or later
login on the same Eastern date cannot repeat the daily cleanup and remove the
patients entered since the first start. Continue remains available at every login.
The separate full-delete control remains available for an intentional complete
reset. Configured rooms, medication categories, mappings and other settings stay
in place during the daily cleanup.

Selected handoffs are removed in full, including difficult-airway details. The
keep-airway reset option and Keep/Delete/Cancel airway update pop-up are removed.
The ordinary airway editor and printed alert remain available. Updating a retained
patient preserves manually entered fields through the normal update workflow.

Other sessions keep pending edits only for the same handoffs that survive a reset.
Removed patients, replacement identities and unsaved old drafts are not restored
when the shared list reloads. PDF downloads verify the shared list before and
after generation, so an open tab cannot create a new PDF from a cleared list.
Previously downloaded files and an already displayed browser preview remain
snapshots and are not erased by a reset.

No new dependency, password or encryption key is required. Existing archives
load without conversion. The first daily start adds a validated nonclinical
patient_list_started_at setting. Use the full 6.62 package after that setting is
saved, since older application versions do not recognize it.

## Alternative medication orders from 6.61

An unrecognized Or line previously became part of the preceding medication
row. The extra column caused the complete medication section to be rejected.
The parser now recognizes Or alongside And and Followed by. It still rejects
malformed or incomplete medication tables without applying a partial list.

Linked alternatives in the same category remain together in source order,
including in the alphabetically arranged Neuro section. If the preceding
order is hidden or belongs to another category, the separate entry displays
Alternative order: instead of an Or label that could refer to an unrelated
medication. These display labels do not change stored source names, grouping
rules, doses or visibility settings. Custom handoff wording remains authoritative.

Alternative infusions follow the same documented Last Admin rate selection
as other infusions. The update does not infer an administered rate from an
ordered dose when the existing rule requires an actual administration rate.

The supplied SmartPhrase was checked locally: all 36 medication orders now
import, with every source name, dose, route and frequency preserved. Its
clinical content is not included in this package. Regression fixtures are
synthetic.

TMax remains regular text in the handoff preview and PDF output. MRSA Screen
and BMI labels remain bold. All features below are included.

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
folder so daily_start.py, census_guard.py and all earlier modules are included. Restart
the Streamlit app and refresh your browser.

Keep your existing Streamlit Secrets, passwords, encryption key, saved archive,
BMI reference data, mappings and custom categories. Do not rerun setup or secret
generators. This update adds no dependency and keeps archive schema 34.

The save-before-Print-All behavior, per-room Last saved timestamps, BMI label
formatting, ordinary difficult-airway editor and existing conflict checks remain in
place. These changes apply to saved source data that is already present. Paste
updated SmartPhrase output when adding a laboratory result or order that was
not previously included.

## Verification and example

Tests use synthetic data. The running deployment and shared patient archive
were not accessed. TEST_REPORT.md records verification of this package.

The examples folder includes mrsa_epidural_sodium_line_days_preview.pdf and the
matching synthetic SmartPhrase text. The PDF uses November 10, 2026 as its
example date. The matching HTML refreshes its line days to the date it is opened.
