# PICU Handoff 6.58 verification

Base package: PICU657.zip. All verification used synthetic data.

## Automated checks

The full suite passed 4,805 tests and 12 subtests in 114.70 seconds.
After the final custom-category compatibility corrections, 607 affected tests
and 14 subtests passed in 16.50 seconds. This follow-up covered new features,
medication routing and categories, batch exports, line days, saved-print
callbacks and the existing Streamlit UI simulations.

The full suite and focused reruns reported one unrelated anyio pytest plugin
deprecation warning, with no failing tests.

Feature coverage includes MRSA result polarity, latest-result selection,
source escaping, text and PDF label emphasis, bupivacaine combinations and stale
mappings, retained source dose/route/rate, old custom category catalogs at their
size limit, renamed category collisions, sodium thresholds and date ordering,
normal sodium after an older high value, excluded and invalid results, urine
sodium exclusion, and preservation of clinician-entered diagnoses.

Line checks cover PIV, PICC, CVC/CVL, arterial access, old CVLs stored as Other,
insertion Day 1, calendar and year rollover, leap day, daylight saving changes,
UTC versus Eastern midnight, missing or future dates, date edits, saved-record
reload, unchanged source data, and single-room plus Print All output.

## Actual original-package archive compatibility

The actual original 6.57 code from PICU657.zip generated and encrypted two
synthetic schema34 records. The updated app opened that archive with every
stored field and setting unchanged, including old custom categories, stale
bupivacaine placement, raw labs, old CVL kind Other, notes, IDs and save times.

The expected MRSA, Epidural, Hypernatremia and CVL Day3 displays appeared in text,
HTML, single-sheet PDF and Print All PDF. A newer normal sodium suppressed an
older high sodium. Rendering did not modify the archive. Re-encryption and
reopening with the same test key returned the exact original archive object.

## Export and layout verification

The combined synthetic PDF was rendered to PNG and visually inspected. The MRSA
label, Epidural group, Problems line and dated vascular inventory fit within the
existing landscape layout without clipping or overlap.

The actual JavaScript extracted from the generated HTML was executed in Node
with a minimal DOM fixture and a controlled clock. It passed Eastern midnight,
one-minute refresh, focus, visibility and repeated beforeprint events without
duplicate day labels. The print timestamp advanced independently of saved time.
A native browser could not be launched in this environment, so this JavaScript
check is not a full browser UI test. The Streamlit callback tests use widget
simulations. The hosted app and shared patient archive were not accessed.

## Delivery

The ZIP includes all original application content, the changed modules, new
mrsa.py, focused regression tests, release notes and a synthetic PDF/HTML example.
Generated caches and compiled bytecode are excluded. SHA256SUMS.txt records
package file hashes, excluding itself. ZIP member hashes and CRCs were verified.
