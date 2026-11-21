# PICU Handoff 6.92 verification

## Regression result

278 selected tests passed, with zero failures, errors or skipped tests.

The final run includes:

- tests/test_vent_mode_history_core.py
- tests/test_vent_mode_history_integration.py
- tests/test_mode_specific_ventilator.py
- tests/test_nava_settings.py
- tests/test_avaps_settings.py
- tests/test_avaps_integration.py
- tests/test_respiratory_update_check.py
- tests/test_measurement_notes_observed_pip.py::test_current_version_is_used_for_new_technical_reports

The 21 mode-history integration tests now check inline mode timestamps, literal three-hyphen separators, removal of the old headings, and preservation of each mode's own settings across text, HTML and PDF. Hidden modes remove their corresponding timestamp and separator. Records without mode history retain their previous format.

Actual source uncertainty notes remain present, including an unrecognized newest mode. No missing timestamps or settings are invented.

## Visual verification

examples/vent_mode_history_preview.pdf contains two synthetic examples. One shows PRVC-IMV, NAVA and PRVC-PS. The other shows PRVC-IMV followed by PS-CPAP.

Both pages were rendered to PNG and visually inspected. Mode timestamps appear on the mode line, three-hyphen separators appear between blocks, and no old history headings or routine timestamp paragraph remain. Both handoffs fit on one landscape page at the normal 8-point body size without clipping.

A separate synthetic Home Vent check confirms that the timestamp is placed on the Mode line and does not attach to Device: Home Vent.

## Scope

The runtime changes from 6.91 are ventilation.py formatting and version labels in app.py and error_store.py. Parsing, source selection, mode ordering, stored values and calculations are unchanged.

The existing PDF cache includes rendered field text in its content signature, so this display change produces a new PDF signature without changing the cache implementation.

The archive schema remains 34. No dependencies or credentials changed. Existing dependency deprecation warnings did not affect test results.

Uploaded patient source text and patient-derived output are not included in this release's tests or preview.

No live Streamlit deployment or production archive write was performed.
