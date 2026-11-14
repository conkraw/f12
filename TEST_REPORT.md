# PICU Handoff 6.74 validation

Source: supplied PICU673.zip. No live app or repository was modified.

## Completed release runs

1,261 selected tests passed in two completed runs.

Focused feature and print regression run: 891 passed in 22.14 seconds.

```text
python -m pytest -q --disable-warnings tests/test_bowel_movements.py tests/test_io_sources.py tests/test_current_shift.py tests/test_current_shift_integration.py tests/test_fen_gi.py tests/test_nutrition_display.py tests/test_nutrition_integration.py tests/test_feeds.py tests/test_diet_lactate.py tests/test_batch_exports.py tests/test_save_before_print.py tests/test_workflow_print.py tests/test_print_fit_reset.py tests/test_measurement_notes_observed_pip.py
```

Additional compatibility run: 370 passed in 2.62 seconds.

```text
python -m pytest -q --disable-warnings tests/test_arterial_pressure.py tests/test_callbacks.py tests/test_error_journal.py tests/test_import_recovery.py tests/test_parser.py tests/test_security_models.py tests/test_ui_smoke.py tests/test_dietary_boundaries.py tests/test_dosing_weight_display.py tests/test_empty_groups_icp_cpp.py
```

The new BM/source-selection tests add 127 cases. Earlier assertions about never
using H totals were revised to test the new requested H-when-S-is-empty behavior
while retaining populated-S priority. An obsolete unsupported-AC-divider test
now uses AD, with separate positive and malformed AC tests added. The technical
report's expected version was changed from 6.73 to 6.74.

A full-suite attempt during development was stopped by the execution limit
before completion. It is not claimed as a full-suite pass. The two completed
runs above are the release evidence, after the identified expectation changes.

## Source and persistence checks

The latest inline H/AC snippet imports its exact provided Intake, Output, Net,
summary timestamp and last-filed timestamp. Its Current Shift and BM result
are separate. All six mounted full SmartPhrase text examples import their
H-based totals, without skipped sections, while retaining their current shift.
All four supplied full examples containing AC stool signals produce Yes.
No uploaded clinical source text is included in the ZIP.

Synthetic tests cover positive stool amounts, positive mixed/stool diaper weights,
blank AC, zero values, missing values, unreadable fields, malformed dividers,
multiple-patient rejection, replacement of stale BM status, no inference from
I/O Other or feeding text, custom Bowel Regimen categories, boolean validation,
legacy archives, encrypted save/reload, reprint behavior, and UI import/save.

I/O tests cover absent/empty S, blank S field placeholders, explicitly zero S,
partial S, populated S priority, malformed boundaries, missing totals, no net
recalculation, no completed-shift reinterpretation, and independent recovery of
24-hour totals versus current-shift data. Existing dosing-weight and shift-rate
calculations remain unchanged.

## Output checks

Text, HTML, single PDF, and Print All include the two I/O sections and BM once
in the correct order. A synthetic one-room PDF was rasterized and visually
inspected. A synthetic three-room PDF has three pages. PDF font flags confirm
the BM line is not bold. Preview files under examples contain synthetic data.

UI checks use the existing widget stubs, not a live browser or hosted deployment.
These are software checks, not independent clinical validation of the undated
AC SmartLink's 24-hour reporting window.
