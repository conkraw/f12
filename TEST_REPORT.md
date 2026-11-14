# PICU Handoff 6.75 validation

Source: the supplied PICU674.zip. No live deployment or repository was changed.

## Completed test runs

238 focused tests passed in 1.81 seconds:

```text
python -m pytest -q --disable-warnings tests/test_current_shift.py tests/test_current_shift_integration.py tests/test_bowel_movements.py tests/test_io_sources.py tests/test_12h_shift_bm_layout.py
```

359 compatibility tests passed in 3.37 seconds:

```text
python -m pytest -q --disable-warnings tests/test_fen_gi.py tests/test_empty_groups_icp_cpp.py tests/test_dynamic_categories.py tests/test_arterial_pressure.py tests/test_security_models.py tests/test_parser.py
```

Total: 597 selected tests passed in completed runs. A broader selected run
was stopped by the 200-second execution limit before completion. It is not
counted and no full-suite pass is claimed. Existing test expectations for the
old shift schedule, regular BM label and version string were updated to the
new requirements. Detection, source-selection and error-handling assertions
were retained.

## New regression coverage

The 28 new tests include an independent minute-by-minute oracle across a whole
ordinary day. They cover 7am and 7pm starts, no reset at 3pm or 11pm, actual elapsed
time rather than a fixed denominator, midnight, year/month/leap-day boundaries,
rate examples for all requested output categories, legacy encrypted snapshot
recalculation without re-paste, and later print time not changing the endpoint.
Existing tests retain the spring/fall daylight-saving and ambiguous-time checks.

Label/spacing tests inspect plain text, escaped HTML, individual PDFs and Print
All PDFs. They verify the exact capitalized label, bold label-only PDF spans,
regular-weight Yes/No spans, position beneath medications or an empty Bowel
Regimen, and one normal line of vertical spacing without a blank line.

## Visual and compatibility checks

Synthetic before/after one-room and two-room PDFs were generated. The updated
one-room PDF and BM close-up were visually reviewed. The BM label is bold and
Yes is regular on the next line after the medication. Current Shift shows
7pm-6:30am and the recalculated rates. These checks use local software, not a
live browser or hosted application.

No schema or dependency changed. The core 24-hour balance parser/formatter,
H/S source selector, importing/model logic, nutrition, encryption, storage and
PDF export engine are byte-for-byte unchanged from 6.74. A shared medication
block renderer has a narrow generated-BM observation formatting branch.

Clinical source examples are not packaged. Included previews are synthetic.
