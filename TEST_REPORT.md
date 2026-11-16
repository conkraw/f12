# PICU Handoff 6.80 verification

Verified November 16, 2026. Built from PICU679.zip.
This package has not been deployed to the live application.

## Final result

    6729 passed, 213 warnings, 14 subtests passed in 202.94s (0:03:22)

The final complete suite was run with:

    PYTHONPATH=.:tests python3 -m pytest -q --tb=short

No test was skipped or marked as an expected failure for this release.
The first full run found two historical category-capacity fixtures that still
assumed five backfilled built-ins. Their historical input catalogs and expected
capacity were updated to account for the new Airway Clearance built-in. The
existing requirement to retain all original slots and reject an extra slot is
still asserted. No runtime code changed after that first full run.

## New coverage

tests/test_airway_clearance_680.py verifies both supplied nebulizer volumes,
NaCl spellings, concentration and route exclusions, mixtures, contrary saved
categories, generic rule correction, specific exceptions, hidden/ignored rows,
explicit restoration, old catalog capacity and existing custom headings.

tests/test_medication_doses_680.py covers source dose authority, mg/mcg units,
dosing weight precedence, labeled measured-weight fallback, grams, precision,
missing/invalid/failed weights, custom wording, concentrations, ranges, infusion
rates, daily totals and immutable records.

tests/test_medication_integration_680.py checks actual text/HTML/PDF rendering,
encrypted round trips, preserved source fields and safe mapping suggestions.
It also verifies unchanged prepared PDF reuse and regeneration for dose,
dosing-weight and warning changes in the affected room.

The broader suite covers the existing SmartPhrase replacement, room isolation,
autosave, shared-record guards, parsers, nutrition, I/O, encryption and Print all.

## Supplied EPIC examples

Both complete user examples imported successfully in memory with no import
errors. The qualifying 3 mL and 4 mL nebulizer products appeared under
Respiratory / Airway Clearance. Explicit source chlorothiazide mg/kg was
preserved, and the furosemide absolute dose produced the expected per-kg
calculation using the documented dosing weight. Simulated broad old saline
rules did not sweep the enteral sodium order into Respiratory.

The original examples and their patient content are not in this package.
All new packaged test data and preview data are synthetic.

## PDF review

examples/medication_doses_680_preview.pdf contains two synthetic rooms. Both
pages were rendered and visually inspected with PyMuPDF. The additional dose
annotations and their weight basis are readable within the existing columns.
Source dose text, grouping and per-kg output are also asserted through PDF text
extraction. The original layout and pagination code were not changed.

## Compatibility

Exactly nine runtime modules changed or were added. UPDATE_FILES.txt identifies
them. Archive schema remains 34. New dose annotations are transient display
data and do not add saved medication fields.

pdf_cache.py, census_guard.py, importing.py, import_review.py, current_shift.py,
fluid_balance.py, nutrition_display.py, github_store.py, security.py and
requirements.txt are byte-identical to the 6.79 baseline. exports.py changes
only the Labs display context and renderer content-signature version.

190 Python files and 3 TOML files passed syntax parsing.
The ZIP CRC and the packaged SHA256SUMS manifest were verified.

Source ZIP SHA-256: 5a857f84cf391991ca3ceb107ce98eb42889d6e5c9b32413e1aa10142891ef91

## Environment and limits

Python 3.12.14, pytest 9.2.0,
ReportLab 4.4.9, pypdf 6.21.4,
PyMuPDF 1.26.6, cryptography 50.0.0,
requests 2.34.2.

The warnings were library deprecations in the existing PDF compression API and
pytest plugin. Requirements keep pypdf below version 7, where the deprecated
compression arguments are scheduled for removal.

Tests use local synthetic data and storage/widget stubs. There was no live
Streamlit browser, production archive, clinical administration history or
physical-printer validation. No new speed claim is made. Prior 6.79 benchmark
results remain in TEST_REPORT_679.md and PRINT_PERFORMANCE_679.json.
