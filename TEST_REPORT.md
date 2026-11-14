# PICU Handoff 6.73 validation

Built from PICU672.zip, Library version 5. No live repository or hosted app was
changed. The complete 6.72 code set is retained apart from the listed changes.

## Completed test runs

957 selected tests passed in two completed regression runs.

Main focused run: 764 passed in 23.28 seconds.

```text
python -m pytest -q tests/test_current_shift.py tests/test_current_shift_integration.py tests/test_fen_gi.py tests/test_nutrition_display.py tests/test_nutrition_integration.py tests/test_feeds.py tests/test_diet_lactate.py tests/test_batch_exports.py tests/test_save_before_print.py tests/test_workflow_print.py tests/test_print_fit_reset.py tests/test_measurement_notes_observed_pip.py
```

Additional compatibility run: 193 passed in 2.33 seconds.

```text
python -m pytest -q tests/test_arterial_pressure.py tests/test_callbacks.py tests/test_error_journal.py tests/test_import_recovery.py tests/test_parser.py tests/test_security_models.py tests/test_ui_smoke.py
```

The new current-shift tests account for 84 of the 764 tests. The only existing
test assertion changed is the expected technical-report version, 6.72 to 6.73.
No existing behavioral regression was removed or weakened.

A broader full-suite attempt reached approximately 41 percent without a reported
failure before the 200-second execution limit. That attempt did not finish and
is not represented as a full-suite pass. The completed focused and compatibility
runs above are the release verification evidence.

## Covered behavior

Tests cover all three shifts, midnight, source-clock formats, daylight-saving
changes, exact shift-start boundaries, explicit zero, missing values, grams,
very small positive rates, comma-separated volumes, wrapped output lines,
unknown categories, invalid units, duplicate values and malformed sections.

Integration checks verify that the 24-hour snapshot object, its source times,
its text and its heading are unchanged. H does not replace S totals. The
snapshot survives encrypted save/reload and appears in text, HTML, individual
PDF and Print All. Reprinting later does not change the rates. Failed new H
imports clear old shift rates, and acknowledgment does not restore them.

The two uploaded text examples were also exercised locally against both the
current-shift parser and the full importer. Both imported their intended shift
outputs without skipped sections. No uploaded patient source is packaged.

## Layout and integrity

A synthetic one-room PDF and three-room Print All PDF were generated. The
one-room preview was visually inspected after rasterization. Current Shift
appears below existing I/O, with no clipping or overlap. Print All produces one
page per synthetic room. All generated previews contain synthetic data only.

All Python and TOML files are parsed during packaging. ZIP CRC and the file
SHA256 manifest are checked. No Secrets, encryption key, medication-mapping,
data-repository or dependency change is required.

UI coverage uses existing widget stubs. A live Streamlit browser session and
hosted deployment were not exercised.
