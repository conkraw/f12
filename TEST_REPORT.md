# PICU Handoff v6.69 validation

Built from PICU668.zip, version 6.68. No live repository or deployment was changed.

## Executed tests

Full regression: 5775 passed, 14 subtests passed in 101.62 seconds.

A final observed-volume alias isolation fix was then checked with the affected
AVAPS, integration, mode-specific ventilation, basic ventilation, noninvasive,
and setting-marker suites:

```text
python3 -m pytest -q tests/test_avaps_settings.py tests/test_avaps_integration.py tests/test_mode_specific_ventilator.py tests/test_ventilation.py tests/test_noninvasive.py tests/test_vent_markers_clean_start.py
```

Final result: 407 passed in 1.36 seconds. This run includes the 34 additional
cases for the final alias fix. The full suite was not repeated after that fix.
No pre-existing test expectations were changed in this release.

## AVAPS parser and display

Tests cover the supplied nested label structure, all new AVAPS fields, direct
labels, unit typography, missing and no-data settings, markers, repeated-field
conflicts, AVAPS-only rendering and old conventional AVAPS fields.

AVAPS rate (cm H2O/min) retains its source unit and remains separate from Set RR.
If an explicit value conflicts with that unit, the label and raw value remain
available with an import review issue. No conversion is inferred.

Target and observed volumes stay separate. Dedicated AVAPS observations retain
their source scope for observed, expiratory and inspiratory aliases and ranges.
A stale AVAPS observation cannot replace a conventional PC observation.
The existing PC observed-volume precedence remains unchanged.

Independent review also compared 60 old-record rendering cases against v6.68
across included non-AVAPS modes. They matched. Five targeted checks verified
the final alias fix and generic PC precedence.

## Import, editing and encrypted recall

Integration checks exercise C/D import, E respiratory vitals, absent NIRS and
empty Z ECG handling. Conflicting AVAPS values use the existing C/D review
workflow while unrelated valid sections remain importable. A fresh change from
AVAPS to PC removes the prior AVAPS values while preserving respiratory notes.

All six appended fields support editor callbacks, pending-edit capture and
encrypted save/recall. Existing archives open, schema remains 34 and all 19
existing ventilation editor indexes are unchanged. Saved new fields require
v6.69 or later. Source objects remain unmodified by formatting and export.

## Supplied example

The supplied C, D, E and Z extracts were checked together. They import without
errors or skipped sections and produce the requested AVAPS mode, rate, target
and observed volumes, and pressure-support limits. FiO2 remains in respiratory
vitals. Absent NIRS and the empty ECG block produce no new values.

The rest of this turn's full clinical sample was not separately revalidated.
The supplied clinical source is not included in the deliverable. Packaged tests
and previews use synthetic data.

## Rendering and package checks

Text, HTML, individual PDF and combined PDF outputs use the same settings.
Batch checks verify that one room's target volume does not appear in another
room's output. The editor renders and offers PDF downloads using widget stubs.

A synthetic AVAPS PDF was rendered with Poppler and visually inspected.
All settings fit within the Respiratory column with no clipping or overlap.
Synthetic input, HTML, text and PDF previews are included in examples.

All 168 Python files parse with ast and all three TOML files with tomllib.
The complete ZIP is checked for CRC integrity and includes regenerated SHA256SUMS.txt.
Cache directories and the supplied clinical source are excluded.

Only app.py and ventilation.py change application code from v6.68. Encryption,
GitHub storage, Mapping Sync, archive paths, Secrets, dependencies, the explicit
noninvasive path, and the QTc, NIRS and medication modules remain unchanged.

## Verification limits

UI checks use the existing Streamlit widget stubs. No live browser or hosted
Streamlit deployment was exercised. Repository services are mocked in tests.
One warning comes from the installed pytest plugin's deprecated internal
import. It is not an application failure.
