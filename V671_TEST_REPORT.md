# PICU Handoff v6.71 validation

Built from PICU670.zip. No live repository or hosted deployment was changed.

## Regression result

The final full regression run passed: 6101 tests and 14 subtests in 108.96 seconds. The only warning is the existing third-party anyio pytest deprecation warning.

Focused checks also passed before the final full run: 96 nutrition-renderer
cases, 87 detailed dietary-parser cases, 43 nutrition-integration cases and
348 existing feeds, FEN/GI, diet/lactate and measurement/version cases.

## Compact display and source reconciliation

Diet labels replace Oral labels. Tube feeds share one heading. Dietary and
recorded counterparts appear once, including the supplied screenshot pattern
of a post-pyloric order and an NJ record with a different formula label.
Synthetic tests retain the dietary formula and rate, preserve separate GT/NJ
routes and ambiguous same-route devices, respect excluded entries, and prevent
old recorded feeds from returning after a new empty or failed dietary update.

Instructions, additives, the daily-volume equation and the dosing-weight basis
line are absent from text, HTML, individual PDF and Print All PDF. Those source
fields remain stored and editable. Existing PN medication deduplication and
hidden/Ignore choices continue to pass.

## Calculations

Tests cover explicit 20-hour and 24-hour schedules, the missing continuous
schedule default, decimal rates, kcal/oz, kcal/mL and kcal/L, positive kg/g
DCW, absent/invalid DCW, failed weight imports and no measured-weight fallback.

An explicit non-24-hour duration prints. A 24-hour duration does not print.
Invalid, conflicting and explicitly unknown durations do not default. Their
constraint is rechecked against retained source even after a review warning
is acknowledged or an encrypted record is reopened. A valid manual duration
resolves it. Bolus, held and future orders do not get continuous daily totals.
Listed-volume conflicts withhold calculated totals for source review.

Calorie calculations use explicit final density. Brand numbers, ratios,
recipes, dilution, signed or ranged density text and multiple densities do
not create calorie totals. T-only records accept an unambiguous ending density
in their own formula. Bounded Decimal arithmetic handles extreme stored
numeric values without crashing the handoff.

## Editing, recall and prior features

Tests exercise editing callbacks, invalid values, pending edits, source
retention, inclusion settings, save/recall, room separation and PDF downloads.
Schema remains 34. Old archives need no migration. UI tests use existing
Streamlit widget stubs, not a live browser.

models.py, exports.py, security.py, github_store.py, mapping_sync.py,
mapping_sync_ui.py, sync_diagnostics.py, requirements.txt, ecg.py, nirs.py,
ventilation.py, medications.py, parser.py, feeds.py and batching.py are byte
identical to v6.70. QTc, NIRS, Override Pull Ignore and AVAPS support remains.

## Visual and package verification

A two-page synthetic PDF was rendered and visually inspected. Its first room
shows a 20-hour GT feed, oral diet and one PN medication. Its second room shows
a 24-hour NJ feed with the duration omitted and the recorded formula duplicate
suppressed. Both fit the existing one-page-per-room seven-column layout
without clipping or overlap. A dated red QTc and Long QTc problem remain
visible in the synthetic preview.

All 173 Python files parse with ast and all three TOML files with tomllib.
ZIP CRC and all regenerated SHA256SUMS entries are verified before delivery.
No supplied clinical source or screenshot is included. Packaged examples are
synthetic. Existing dependencies, Secrets and encrypted data repositories
remain compatible. No hosted Streamlit session was exercised or deployed.
