# PICU Handoff 6.79 verification

Verified November 16, 2026. Built from the saved PICU678.zip package.
This release has not been deployed to the live application.

## Automated results

Final full suite: 6551 passed, 14 subtests passed in 143.51s (0:02:23)

    PYTHONPATH=.:tests pytest -q

The suite includes 68 new PDF reuse tests. No test was skipped or marked as an
expected failure for this change. One existing overflow-warning test was updated
to mock the new cached fit-report dependency instead of the retired direct
print_fit_report call. Its original warning assertion is unchanged.

The first full run found a read-only startup refresh cancelling prepared
unchanged downloads. That regression was corrected without changing the startup
tests. Selected-room content checks still run before and after download assembly.
The final full run above is the completed run after that correction and PDF
stream compression/deduplication.

## Behavior tested

The new tests verify initial preparation and reuse across single-patient and
Print all downloads. Repeating an unchanged download does not invoke the clinical
PDF renderer. A changed clinical field rebuilds only that room. Both page targets,
room ordering, metadata-only changes, continued pages and fit reports are covered.

Safety cases cover full-room replacement, removed old content, current saved and
print timestamps, exact rolling laboratory-window boundaries, midnight line-day
changes, HEPLMW day placement, newly eligible MRSA and cardiac laboratory displays,
renderer-version changes, independent sessions, bounded memory, concurrent clicks,
failed rendering, logout/reset, expired downloads, and remote same-ID edits even
when timestamps match. A confirmed import remains saved if PDF preparation fails.
No older PDF is substituted for a failed new render.

The original regression suite still covers clinical parsers, I/O and nutrition
calculations, medication mappings, encryption, room isolation, autosave, storage
conflicts, startup confirmation and the complete-room replacement rules.

## Measured local performance

| Synthetic packet | Rooms | 6.78 rebuild | 6.79 prepared-page assembly | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Simple | 18 | 0.122 s | 0.093 s | 23.9% |
| Mixed | 18 | 2.229 s | 1.536 s | 31.1% |

Each timing is the median of three runs against the exact original exports.py
extracted from PICU678.zip. The mixed case cycles through a simple handoff, the
synthetic compact-PN example, and a longer neurological handoff. Both packets
contain 18 pages. The fixed display clock is November 16, 2026 at 12:00 UTC.

Measured cached assembly includes current display/signature checks, merging,
fresh metadata and compression. It excludes shared-storage network reads,
browser transfers and physical printer time. It is not an end-to-end production
benchmark or a prediction for every patient list.

All three repeated prepared-page runs rebuilt zero clinical PDFs. Editing one
room rebuilt exactly one body. The mixed packet's one-time preparation of all
18 bodies took 3.816 seconds locally,
or 0.212 seconds per room on average.
This initial work moves to the relevant import/save. A fresh session or missing
cache still performs it once. Preparation time is not eliminated.

The mixed final packet was 45,831 bytes compared
with 50,740 bytes from the original exporter.
Full raw timing results and counters are in PRINT_PERFORMANCE_679.json.

## Output comparison

All 18 pages of the mixed packet were pixel-identical to the original v6.78
export at 200 dpi using pdftoppm: zero changed pages and zero changed pixels.
PyMuPDF comparisons also passed for both benchmark packets and representative
one-page, two-page and overflow fixtures in the new tests. A rendered example
was visually inspected for clipping and layout changes.

Cached clinical pages do not contain an old print/save header. The current
header and packet numbering are applied at download time into the same gutter.
The pages remain vector PDF content, not screenshots.

## Source and compatibility

Source ZIP SHA-256: 31e3261de66ed6a7f4ed63b5a5f79ca4822bcbe6d8bbfd27daf1913d71459eff

Five runtime files must be installed together:

    app.py
    exports.py
    census_guard.py
    pdf_cache.py        (new)
    requirements.txt   (adds pypdf>=5.9,<7)

All other existing runtime Python modules are byte-identical to v6.78. Clinical
parsers and calculations, encrypted storage, archive schema 34, room settings,
and mappings are unchanged. No migration, key rotation, or data reset is needed.
All 184 packaged Python files and all 3 TOML files passed syntax parsing.

## Environment and limits

Python 3.13.5, ReportLab 4.4.9,
pypdf 5.9.0, pytest 9.0.2,
and PyMuPDF 1.26.7 were used locally.
The requirements allow pypdf 5.9 through 6.x. Only installed pypdf 5.9.0 was tested.

Application interaction tests use the existing instrumented Streamlit widget
stub, not a live browser. Live Streamlit installation, production shared-storage
latency, deployed multi-user behavior and physical printing were not tested.
No production repository, encrypted clinical archive or real patient data was
accessed or modified. These tests are not clinical validation or a guarantee of
safety. Verify with fictional records in the deployed application before use.

The cache is private to the active server session, held only in memory and
cleared on reset/logout. Previously downloaded PDFs, already printed pages and
another user's previously downloaded files cannot be recalled. The unchanged
institutional-workflow and current-patient verification requirements still apply.
