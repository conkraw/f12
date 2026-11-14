# PICU Handoff v6.72 validation

Built from PICU671.zip. No live repository or hosted deployment was changed.

## Executed verification

The final focused regression run passed all 680 tests in 23.27 seconds:

```text
python3 -m pytest -q tests/test_nutrition_display.py tests/test_nutrition_integration.py tests/test_feeds.py tests/test_fen_gi.py tests/test_diet_lactate.py tests/test_batch_exports.py tests/test_save_before_print.py tests/test_workflow_print.py tests/test_print_fit_reset.py tests/test_measurement_notes_observed_pip.py
```

The only warning is the existing third-party anyio pytest deprecation warning.
The full application suite was not repeated for these scoped display changes.
The preceding 6.71 full-run result is retained in V671_TEST_REPORT.md.

## Calories per kg

The display adds kcal/kg/day beside kcal/day when explicit caloric density,
a valid rate and schedule, and positive dosing weight are available. Tests
cover kg and g, different room weights, missing/invalid DCW, failed weight
imports, no measured-weight fallback, zero rate, fractional calories and
independent final rounding from the unrounded calorie calculation.

Existing duration, held/future/bolus, listed-volume, field-conflict and numeric
bounds remain covered. Invalid duration remains uncalculated after warning
acknowledgment and encrypted save/recall. Explicit valid edits still resolve it.

## Missing fields

Formula-only and rate-only rows keep known details without UNK placeholders
or a dangling @. Literal UNK/Unknown formula values are treated as missing,
while real formula names containing those words remain intact. Zero is a
known rate, not a missing value. Rows missing both formula and rate disappear,
including an otherwise empty section heading. Stored source remains editable.

These behaviors are checked in text, HTML, individual PDF and Print All PDF,
as well as encrypted recall. A legacy T-only record with no remaining visible
feed data does not qualify for Print All solely because of that empty row.

## Layout and compatibility

The two-room synthetic preview was regenerated and visually inspected. The
20-hour GT and 24-hour NJ examples show kcal/kg/day correctly. Each room still
fits the existing seven-column landscape layout without clipping or overlap.
Instructions/additives remain hidden, the PN entry remains deduplicated, and
the old dated QTc and Long QTc problem remain visible in the preview.

Only app.py, batching.py, error_store.py and nutrition_display.py changed among
application modules. All other application Python modules and requirements.txt
are byte-identical to v6.71. Schema remains 34. No data migration, encryption,
Secrets, dependency, storage or medication-mapping change is required.

All 173 Python files parse with ast and all three TOML files with tomllib.
ZIP CRC and regenerated SHA256SUMS are verified before delivery. Packaged
examples are synthetic. No supplied clinical source or screenshot is included.
UI checks use the existing Streamlit widget stubs. No live hosted app was
exercised or deployed.
