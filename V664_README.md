# PICU Handoff 6.64

Built from the latest PICU663.zip package.

## Cardiovascular laboratory results

| Epic component | Handoff label | Selection |
| --- | --- | --- |
| METHB | Methemoglobin | Latest included numeric result within 24 hours |
| O2SATV | SvO2 | Latest included numeric result within 24 hours |

Both results appear in Cardiovascular with their original value, units, flags
and collection date/time. Units are not added or converted. A missing, excluded,
pending, invalid or expired result does not produce an automatic entry.

The cutoff uses the current Eastern time, including elapsed-time handling
across daylight saving changes. Exactly 24 hours is included. Future results
are excluded. Saved handoffs recalculate these displays when opened, refreshed
or exported. A downloaded PDF or HTML file remains a snapshot of its laboratory
results and must be generated again to refresh them.

Collection times give the exact rolling cutoff. For a date-only row, the start
of its recorded Eastern date must fall within the past 24 hours. This normally
includes today's date and excludes yesterday's uncertain result. No collection
time is invented. When same-day times are incomplete, Epic's source order is
retained, as in the other laboratory displays.

Include METHB and O2SATV in the G laboratory block of the pasted SmartPhrase.
Add their collection times when available, especially for results from yesterday.
Existing saved rows for these codes work immediately. Paste a new SmartPhrase
if those rows were not previously imported. All original rows stay in the lab
editor. Neither code is repeated in the lower laboratory or legacy G gas display.
Independent P blood-gas tables retain their existing specimen/column display.

## Install this update

Replace app.py, lab_windows.py and clinical_style.py together. Uploading the
complete application folder includes all required modules. Keep app.py at the
repository root, restart Streamlit and refresh the browser. The sidebar should
show Version 6.64.

Existing Secrets, encryption keys, saved handoffs, mappings and custom notes
continue to work. This update adds no dependency or archive-schema change.
See TEST_REPORT.md for verification and examples/cardiovascular_labs_preview.pdf
for a synthetic printed example.

## Included from version 6.63

Common chemotherapy medications have an automatic
Hematology > Chemotherapy placement. Medication display names omit the leading
And:, Or: and START ON annotations while retaining complete source orders.

The complete package also includes the chemotherapy, medication-label and
daily patient-list updates from previous releases.

## Chemotherapy

Known conventional chemotherapy names and common verified brand names route to
Hematology > Chemotherapy. This includes asparaginase products, doxorubicin,
vincristine, cytarabine, methotrexate, mercaptopurine, cyclophosphamide, etoposide
and other named agents listed in CHEMOTHERAPY_REFERENCE.md.

Dexamethasone is excluded from this new rule and keeps its prior placement.
Other corticosteroids, supportive medicines, antiemetics, hydration and growth
factors are not swept into Chemotherapy. Name matching is explicit and does not
guess a cancer diagnosis, indication or dose. Existing explicit group and category
choices remain available for drugs used in another context.

The new built-in category is available in older saved category catalogs without
renaming custom categories or discarding existing slots. Saved orders can gain
the new automatic placement without repasting, unless an explicit saved choice
already controls their placement.

## Cleaner medication names

The medication name shown in summaries, handoff previews, text and PDF output
omits leading And:, Or:, the generated Alternative order: label and recognized
[START ON ...] annotations. This also applies to infusion names.

Original names and dates remain in the editable source record. The app continues
to use those original values for routing, hidden-order rules, schedule checks
and recorded-rate selection. Held and discontinued labels remain visible.
Followed by wording and custom handoff text remain intact.

Every order stays separate with its recorded dose, route, frequency and rate.
Linked alternatives retain their source order within a category. No orders are
combined or omitted by the label cleanup.

The latest supplied SmartPhrase contains 35 medication orders. All 35 import
without a medication parsing error. The source text and screenshots are not
included in this package. The new preview files in examples use synthetic data.

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
patient_list_started_at setting. Use the full 6.62 or later package after that setting is
saved, since older application versions do not recognize it.

## Alternative medication orders from 6.61

An unrecognized Or line previously became part of the preceding medication
row. The extra column caused the complete medication section to be rejected.
The parser now recognizes Or alongside And and Followed by. It still rejects
malformed or incomplete medication tables without applying a partial list.

Linked alternatives in the same category remain together in source order,
including in the alphabetically arranged Neuro section. Source connector
annotations still support parsing and grouping, while the 6.63 name cleanup
hides And:, Or: and Alternative order: in displayed medication names.
Custom handoff wording remains authoritative.

Alternative infusions follow the same documented Last Admin rate selection
as other infusions. The update does not infer an administered rate from an
ordered dose when the existing rule requires an actual administration rate.

The earlier 36-order SmartPhrase format remains supported. Regression fixtures
are synthetic and preserve independent source name, dose, route and frequency
boundaries.

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
folder so chemotherapy.py, daily_start.py, census_guard.py and all earlier modules are included. Restart
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
