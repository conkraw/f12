# PICU Handoff 6.81 verification

Verified November 16, 2026. Built from PICU680.zip.
This package has not been deployed to the live application.

## Final result

    6879 passed, 231 warnings, 14 subtests passed in 229.44s (0:03:49)

The final complete suite was run with:

    PYTHONPATH=.:tests python3 -m pytest -q --tb=short

No test was skipped or marked as an expected failure for this release.

Existing SBS tests were updated to reflect the requested behavior: every SBS
display needs invasive-mode evidence, dated output includes its source date,
and an older dated value remains visible. Fixtures testing visible SBS now
include an invasive mode. Existing TPN, medication, ventilation, isolation,
failed-import, encryption and callback assertions remain in place.

An initial complete run exposed additional assertions for the previous SBS
behavior. Those fixtures were corrected before the final run. A final parser
review also found that trimming a line with no date suffix could remove an
empty trailing cell in an old SBS matrix. The shared sanitizer now preserves
that whitespace, with a regression case included in the final suite.

## New coverage

tests/test_dated_capd_wat_681.py verifies dated CAPD and WAT-1 totals, latest
timestamp selection, same-day ordering, date-only entries, zero, source
attribution removal, ambiguity, malformed dates, excluded values and legacy
saved WAT behavior. It also verifies that the unrelated ICP/CPP and nutrition
paths retain their existing behavior.

tests/test_dated_sbs_681.py verifies staff-free persistence, date-only output,
old dated scores, source targets, source order, invasive-mode gating, old
PS/noninvasive archives, malformed dates and legacy source formats.

tests/test_dated_score_integration_681.py exercises full imports, actual
text/HTML/PDF output, encryption, replacement, room isolation and PDF-cache
refresh after score, date and airway edits. It also runs full app callbacks
with a Streamlit stub: manual score edits, pending edits captured on room
switch, warning recovery, invalid-edit rollback, date-only SBS addition and
preservation of target labels after an observed reading is added.

The broader suite covers the existing SmartPhrase replacement, medications,
weight calculations, autosave, shared-record guards, nutrition, I/O and Print all.

## Supplied EPIC examples

All three supplied complete examples produced the expected score/date output
in memory. No K, L or Y score warning remained. The ventilated examples
retained their dated SBS target and CAPD values. The HFNC example retained
its dated WAT-1 value without SBS. The nasal-cannula, removed-ETT case supplied
in chat is covered by a synthetic fixture with CAPD present and SBS suppressed.

The first complete example still has its preexisting H/U source notices and
an unrelated ECG review error because its Bazett QTc field is blank. The same
unrelated sections were confirmed in the 6.80 baseline. This release changes
the score sections only and does not fill in an absent QTc value.

The original examples and their patient content are not in this package.
All new packaged tests and preview data are synthetic.

## PDF review

examples/dated_scores_681_preview.pdf contains two synthetic rooms. Both pages
were rendered with PyMuPDF and visually inspected. The ventilated example
shows SBS target, CAPD and WAT-1 with dates. The nasal-cannula example shows
CAPD and WAT-1 without SBS. The score lines are readable within the existing
Neurologic column. Staff attribution and source times are absent from those
score lines. Existing print preparation metadata is retained.

validation/build_dated_scores_681_preview.py rebuilds the preview. The prior
synthetic medication preview remains included.

## Compatibility

Exactly eight runtime modules changed or were added. UPDATE_FILES.txt lists
them. score_dates.py is new. Archive schema remains 34 and no dependency was
added. New CAPD and WAT records use the existing score-row fields with a compact
score/date value. SBS uses its existing source timestamp and target metadata.

The medication matching and dose modules, respiratory parser, PDF-cache
engine, encrypted storage, I/O and nutrition modules listed in
BUILD_MANIFEST_681.json are byte-identical to 6.80. exports.py changes only the
renderer content-signature version so prepared pages refresh for this release.

195 Python files and 3 TOML files passed syntax parsing.
The ZIP CRC and the packaged SHA256SUMS manifest were verified.

Source ZIP SHA-256: e8f18df55e24d5c6494cf272e01cd93d712346e12ca847e70d6d6c0887adcda2

## Environment and limits

Python 3.12.14, pytest 9.2.0,
ReportLab 4.4.9, pypdf 6.21.4,
PyMuPDF 1.26.6, cryptography 50.0.0,
requests 2.34.2.

The warnings were existing library deprecations in the PDF compression API
and pytest plugin. No dependency or deprecation cleanup was part of this change.

Tests use local synthetic data and storage/widget stubs. There was no live
Streamlit browser, production archive or physical-printer validation. No new
speed claim is made. Prior release verification remains in TEST_REPORT_680.md
and TEST_REPORT_679.md.
