# PICU Handoff v6.68 validation

Built from PICU667.zip, version 6.67. No live repository or deployment was changed.

## Regression results

Full regression: 5719 passed, 14 subtests passed in 99.69 seconds.

Focused final feature and medication-label run:
`python3 -m pytest -q tests/test_medication_label_cleanup.py tests/test_qtc_nirs_override_integration.py tests/test_override_pull.py tests/test_ecg.py tests/test_nirs.py`

Result: 179 passed in 1.08 seconds.

One existing test was updated for the new Ignore destination. It now requires
ignored entries to be absent from output while all visible orders still appear
exactly once. Its checks for source preservation, dose/rate labels, HTML, text,
PDF, combined exports and removal of And/Or/Start On labels remain in place.
No other pre-existing test expectations were changed.

## ECG and problem checks

Coverage includes the exact Bazett label structure, case and whitespace
variants, old ECG dates, date/time ordering, tied results, missing dates,
conflicting newest results, invalid units/dates, and exclusion of the Q-T
interval and other QTc formulas. Tests cover 425, 450, 451 and fractional values
above 450, plus removal of a previous Long QTc problem after a newer normal ECG.

Z-block omission, empty imports, malformed boundaries, partial-section
recovery and duplicate-patient rejection are checked. Failed ECG imports retain
reviewable data while hiding the old QTc and automatic problem from output.
ECG words within ordinary diagnoses remain valid diagnosis text.

Old archives without ECG data still open. New data survives encrypted save and
reload, and ECG-only handoffs remain eligible for Print All. No ECG narrative
is retained in the persisted snapshot.

## NIRS and medication checks

NIRS tests cover the repeated rSO2 Cerebral label, recorded Min/Max and latest,
partial or absent values, reordered statistics, decimal percentages, hidden
rows, section choices, old-row rendering and source nonmutation.

Override tests cover name variants, incomplete source rows, automatic groups,
broad mappings, exact assignments, explicit Ignore, ordinary orders of the same
drug, old saved rows, encrypted recall, and all export paths. UI callback checks
exercise restoration from default Ignore, category Ignore, and the older Admin
exact/prefix Ignore mappings. A failed storage write leaves data and settings
unchanged. The ignored editor section offers Restore to handoff.

## Supplied example

The full supplied SmartPhrase imports with no errors and no skipped sections.
Its ECG becomes QTc: 426 msec [11/13/2026]. Its Neuro line becomes
NIRS: 60% to 68% [last 66]. That QTc does not add Long QTc.

A normalized comparison with v6.67 found changes only in ecg and vitals.
All 25 other imported data groups matched after excluding generated IDs and
creation/update timestamps. The supplied clinical source is not in the package.

## Rendering and package checks

Synthetic individual and combined PDF/HTML/text outputs were checked.
Both the QTc label and its value have red PDF text spans above the cutoff.
A synthetic one-page PDF was rendered with Poppler and visually inspected.
NIRS appears in Neuro, QTc in Cardiac, and Long QTc in Problems. The override
entry is absent while the ordinary same-drug order remains visible. No content
is clipped or overlaps adjacent columns.

All 166 Python files were parsed with ast and all three TOML files with tomllib.
The release ZIP is checked for CRC integrity and contains a regenerated
SHA256SUMS.txt. Cache directories and real clinical samples are excluded.

## Verification limits

Streamlit UI checks use the existing widget stubs. No live browser or hosted
Streamlit deployment was exercised. GitHub and Mapping Sync tests use mocked
services. The only test-run warning comes from an installed pytest plugin's
deprecated internal import. It is not an application failure.

Encryption, archive paths, Secrets, repository access and Mapping Sync modules
are unchanged. Existing archives are accepted. Records using the new optional
fields or Ignore mappings require v6.68 or later.
