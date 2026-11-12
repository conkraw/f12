# PICU Handoff 6.64 verification

Base: the latest PICU663.zip package. This update adds METHB as Methemoglobin
and O2SATV as SvO2 in Cardiovascular, using the latest eligible numeric result
within the past 24 hours. All new test data and preview files are synthetic.

## Verification result

750 tests passed across the new cardiovascular cases and the selected existing
laboratory, blood-gas, source ordering, workflow, formatting and export tests.
This includes 85 new cardiovascular tests. One existing AnyIO pytest-plugin
deprecation warning was emitted. It did not affect test results.

The selected files were test_cv_24h_labs.py, test_windows_problem_review.py,
test_recent_trough_workflow.py, test_latest_gas.py, test_lab_routing_placement.py,
test_diet_lactate.py, test_labs_vitals_visibility.py,
test_labels_colors_groups.py and test_batch_exports.py.

## New behavior checked

- Exact inclusion at 24 hours, exclusion just before the cutoff and exclusion
  of future results.
- Independent latest-result selection for each code, including shuffled rows,
  incomplete times and source-order ties.
- Conservative date-only selection based on the beginning of the Eastern date.
- UTC elapsed-time comparison, 25-hour days, ambiguous fall-back times and
  nonexistent spring clock times.
- Exact code matching without substituting arterial or generic saturations.
- Preservation of source units, decimal values, numeric zero and abnormal flags.
- Omission of pending, canceled, hemolyzed, invalid, hidden and failed-import
  results from the new automatic displays.
- Removal of both G codes from lower laboratory and legacy G gas output,
  including when the values have expired.
- Existing P blood-gas specimen/column behavior remains independent.
- Expiration after a saved handoff is re-rendered, without modifying raw rows
  or clinician-entered notes.
- Encrypted archive save/reload and actual text, HTML, single PDF and Print All
  PDF rendering, with exactly one automatic entry for each new result.

## Findings corrected during verification

The shared numeric recognizer can interpret a single trailing word as a unit.
A numeric-looking result such as 1.2 pending is now excluded for the two new
cardiovascular codes by the existing status-word rejection rule. Other analytes
retain their prior window and selection behavior.

One older navigation test failed identically in the untouched 6.63 package.
Its fixture did not select Continue saved handoffs before testing old-workspace
migration. The test now makes that selection and retains its original assertions
about workspace migration and preservation of the unsaved draft. Production
navigation and daily-start behavior were not changed.

## Printed output

examples/cardiovascular_labs_preview.pdf was rendered and visually inspected.
Both labels, values and dates fit in the Cardiovascular column on one landscape
page. Original clinician notes remain below them. Older test values are omitted
and neither result is repeated in the lower laboratory band. Matching HTML and
plain-text previews are included.

## Compatibility and limits

All 61 application Python modules passed syntax validation. requirements.txt,
models.py, security.py, github_store.py, daily_start.py, census_guard.py,
medications.py and chemotherapy.py match the original package byte for byte.
The archive schema remains 34, with no new dependency or encryption key.

The UI-related existing tests use simulated Streamlit widgets. A live browser
session and the deployed application were not accessed. No new real-patient
SmartPhrase was supplied for this change. The implementation was verified with
synthetic component/value/date rows using the existing parser and export paths.
