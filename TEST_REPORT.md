# PICU Handoff 6.82 verification

Verified November 16, 2026. Built from the exact PICU681.zip release, with
direct-upgrade checks against PICU680.zip because the user reverted to 6.80.
This package has not been deployed to the live application.

## Final regression result

    6962 passed, 231 warnings, 14 subtests passed in 232.10s (0:03:52)

The complete suite was run after the production files were frozen:

    PYTHONPATH=.:tests python3 -m pytest -q --tb=short

No test was skipped or marked as an expected failure for this release.

## Confirmed regressions and fixes

The 6.81 dated-score helpers repeatedly used the laboratory parser to try
multiple date formats during validation, source ordering, display and cached
PDF content checks. Compact two-digit-year dates caused format-cache churn.
The 6.82 score parser directly validates ordinary source dates and times with
calendar checks. Unusual formats from older archives retain the unchanged
legacy parser. No global cache of patient text was introduced.

The 6.81 editor snapshot also rewrote some unchanged legacy WAT records to
their displayed form. Room navigation then treated that rewrite as an edit,
saved shared storage and warmed a PDF. The 6.82 snapshot compares against the
sanitized editor baseline and normalizes only actual edits. Read-only viewing
keeps the archive and existing import warning unchanged.

## New regression coverage

tests/test_score_date_performance_682.py adds 57 cases covering calendar and
leap-year validity, the 68/69 two-digit-year boundary, midnight/noon, AM/PM,
compact time, seconds, missing time and legacy formats. Deterministic call
checks confirm that ordinary score import, full sheet validation, HTML
preview and unchanged PDF cache hits do not enter the date-format trial loop.

tests/test_dated_score_edit_performance_682.py adds 26 cases. Unchanged legacy
navigation produces zero shared-store saves and zero PDF warming calls.
Actual score, date and inclusion edits save and warm once. The tests also
cover warning recovery, invalid-edit rollback, sanitized output and room
isolation through the actual app callbacks with widget/storage stubs.

The complete existing suite retains medication mapping and dose calculations,
dated-score selection, SBS gating, complete-room replacement, storage guards,
encryption, nutrition, I/O and prepared PDF reuse.

## Performance evidence

PERFORMANCE_682.md explains the fixtures and results. PERFORMANCE_682.json
retains raw repetitions, profiles, cache counts and environment details.
Timing runs were completed before the final full suite started.

For 30 warmed HTML renders of a simple dated-score fixture, date-format
compilations fell from 4,680 in 6.81 to zero in 6.82. Profiled score-date
parsing time fell from about 0.178 seconds to 0.012 seconds.

Median warm Print all time for 18 synthetic rooms with 40 laboratory rows
each was 324.86 ms in 6.80, 392.45 ms in 6.81 and 314.33 ms in 6.82.
This local run places the corrected path near the 6.80 baseline. It is not a
claim that all deployed actions are faster. The larger single-sheet HTML/PDF
measurements were more variable and showed smaller improvements.

Each version initially generated 18 clinical PDF bodies and then reused them
for one warmup plus five measured packets, with zero additional body builds.
The PDF-cache engine and its freshness checks were not changed.

## Output and compatibility

validation/check_score_output_682.py compared 6.81 and 6.82 in separate
processes using identical synthetic observed-SBS, explicit-target and
nasal-cannula records. Generated identifiers and save metadata were fixed.
Stored-sheet, text and HTML hashes matched exactly. Score dates and values
were not removed from the comparison. Source attribution stayed absent and
the nasal-cannula record suppressed SBS.

The existing dated-score PDF preview remains included. The rendering and
layout code is byte-identical to 6.81, and the full PDF regression tests pass.
No new visual layout or print metadata format was introduced.

Only app.py, sbs.py and score_dates.py changed relative to 6.81. All eight
runtime files needed to upgrade directly from 6.80 are listed in UPDATE_FILES.txt.
The package contains the complete application. The general laboratory parser,
medication changes, respiratory parser, storage layer and PDF renderer remain
unchanged. Archive schema remains 34, with no new dependency or migration.

The renderer content-signature version remains at 6.81 because clinical
output is unchanged. Existing valid prepared bodies do not need a separate
6.82-only invalidation.

199 Python files and 3 TOML files passed syntax parsing.
Packaged file checksums and ZIP CRC were verified.

Source PICU681.zip SHA-256: 4c1a32be06df11336c7a68e569479369e8db9bfa3f75c2f0af70fd1ad297ab9f
Rollback PICU680.zip SHA-256: e8f18df55e24d5c6494cf272e01cd93d712346e12ca847e70d6d6c0887adcda2

## Environment and limits

Python 3.12.14, pytest 9.2.0,
ReportLab 4.4.9, pypdf 6.21.4,
PyMuPDF 1.26.6, cryptography 50.0.0,
requests 2.34.2.

The warnings are existing pytest-plugin and PDF compression deprecations.
Measurements use local synthetic data, with no live Streamlit deployment,
production archive, network-latency measurement or concurrent-user load.
Callback tests establish the number of avoided saves without assigning a
duration to a network request. No patient paste is included in this package.
