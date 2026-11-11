# PICU Handoff 6.61 verification

Base: PICU660.zip. This update supports alternative medication orders in Epic
SmartPhrase tables and preserves their meaning in grouped handoff output.

## Supplied-format reproduction

The medication block contained 36 orders and a standalone tab-indented Or
connector. Version 6.60 appended that connector to the preceding row as an
eighth column. The row failed validation, so the complete medication section
was rejected rather than applying 35 readable orders as an incomplete list.

Version 6.61 parses and applies all 36 orders without a medication error or
review warning. Every medication name, dose, route and frequency was compared
against its source column. Names preserve the Or annotation on the alternative.
Each of the 36 orders is emitted exactly once across the handoff categories.
Building the display leaves the complete source sheet unchanged.
The supplied clinical text was inspected locally and is absent from this
package, test fixtures and report.

## Automated verification

- 47 alternative-order tests passed. They cover standalone and trailing-cell
  connectors, blank columns, separate orders, mapping and visibility, incomplete
  sequences, atomic import recovery, encrypted save/reload, and text/HTML/PDF
  output. Named infusion checks cover missing and documented Last Admin rates.
- 119 placement and category tests passed, with 14 subtests. They cover source
  adjacency, alphabetical Neuro output, hidden predecessors, different systems,
  different root/subcategories, bupivacaine placement, legacy Labs output and
  detached-infusion rate selection.
- 266 preservation tests passed, with 14 subtests. They cover both MRSA lab codes
  and latest-result selection, bupivacaine, hypernatremia, line days and labels.
- 621 medication, callback, import-recovery, infusion, FEN/GI, ADS, airway and
  batch-export regression tests passed.

These runs have overlapping bupivacaine coverage. The only test warning was an
existing anyio/pytest plugin deprecation warning. No test failed.

All six changed application modules pass Python syntax validation. Tests use
synthetic records. Callback tests use a simulated Streamlit environment. The
live deployment and shared patient archive were not accessed.

## Persistence and package

Stored data models, archive schema 34, encryption and dependencies are unchanged.
Render-only alternative labels appear on copied rows and do not mutate saved
source data. The existing custom text and hide/include choices remain effective.

ZIP CRC and SHA256 manifest verification passed. Generated caches and compiled
bytecode are excluded. No credentials or supplied clinical attachment are bundled.
