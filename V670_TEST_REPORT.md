# PICU Handoff v6.70 validation

Built from PICU669.zip. No live repository or hosted deployment was changed.

## Executed regression checks

The full regression run completed with 6013 passed and 14 subtests passed in
109.41 seconds. One existing test still expected technical report version 6.48
and failed against the corrected release version 6.70. Its version expectation
was updated. No application behavior was changed to satisfy that old assertion.

The final focused run, after that correction and support for multiline feeding
instruction edits, passed all 554 tests in 2.60 seconds:

```text
python3 -m pytest -q tests/test_nutrition_integration.py tests/test_dietary_orders.py tests/test_nutrition_display.py tests/test_dietary_boundaries.py tests/test_diet_lactate.py tests/test_feeds.py tests/test_fen_gi.py tests/test_measurement_notes_observed_pip.py
```

The full suite was not repeated after these final focused changes. The only
warning was the existing pytest plugin's deprecated internal import.

Two existing test expectations changed. One detailed semicolon tube order now
checks structured feeding fields instead of its former generic label. The
technical-report version test now expects the release's actual version.
All other pre-existing test expectations remain unchanged.

## Supplied dietary examples

All 17 supplied dietary examples were tested separately through the AB import
and FEN/GI renderer. Each imported without errors, skipped sections or warnings.
Repeated detailed and compact views produced one order.

The GT, post-pyloric formula and fortified breast-milk examples retained their
explicit route, formula, hourly rate, daily hours and recorded volume. Their
rate-times-hours calculations matched the supplied daily totals. Mixture,
fortifier, oral-swab, advancement and break instructions remained visible.
NPO medication exceptions and milk-label orders did not create tube feeds.
Regular, Clear Liquid, NPO and None produced the expected oral/empty results.
No numeric mL/kg/day was generated without a documented dosing weight.

The supplied text was tested in memory and is not included in the package.
Packaged fixtures and previews are synthetic.

## Source boundaries and freshness

AB markers support alternating ab text, case variants, odd final a and different
valid marker lengths. AB remains separate from X and ECG Z. Repeated AB blocks
retain the existing multiple-patient rejection. Malformed and unclosed markers
fail the affected dietary section while unrelated valid sections can import.

AB supplies the detailed dietary snapshot when both X and AB are present.
A failed AB import does not silently use X. Successful dietary reimport clears
prior dietary review flags. An unreadable detailed dietary update retains its
records for review while hiding structured dietary and recorded-feed output.

Only feeding rows supplied with the dietary update are linked automatically.
A fresh None or NPO-only AB update does not resurrect older T rows. A later
explicit T update can supply current recorded rows. Generic post-pyloric route
refinement requires a uniquely matching formula and explicit NJ/ND device in
the same import. Earlier retained devices do not establish the new route.

## Calculations and deduplication

Tests cover 20- and 24-hour schedules, decimal rates, kg/g dosing weight,
missing/invalid weight, absent duration, failed I imports, zero rates, held and
future orders, bolus schedules and conflicting listed totals. Measured weight
is not substituted. An hourly rate is never derived from an intake volume.

Oral, enteral and parenteral orders can coexist. Product identity keeps a PN
medication from duplicating its dietary counterpart while preserving distinct
PN formulations and lipid products. Matching hidden and Ignore medication
choices remain effective. Decimal and ratio punctuation in formula names is
preserved. A known recorded formula is not lost when the ordered formula is
missing. Unmatched formula-only device records do not imply an extra feeding
route alongside an explicit dietary tube order.

## Editing, recall and exports

Callbacks, pending edits, inclusion settings, invalid hour edits and multiline
feeding instructions are exercised. Nutrition data survives encrypted save and
reload. Old archives open without migration. Schema stays 34. Structured diet
snapshots and AB diagnostic flags require v6.70 or later after saving.

Text, HTML, single PDF and Print All PDF use the same calculated figures.
Batch checks keep each room's amounts separate. Nutrition-only handoffs are
eligible for Print All. Rendering and export do not mutate source records.
Rich output escapes formulas, fortifiers, instructions and editable text.

The earlier full SmartPhrase supplied during QTc troubleshooting was also
imported with the new code. The dated QTc remained visible, and its detailed
feeding order used the recorded dosing weight correctly.

A synthetic combined oral, tube-feed, PN and dated-QTc PDF was rendered with
Poppler and visually inspected. Feeding instructions, daily calculations and
one PN entry fit within FEN/GI without clipping or overlap. The old ECG remained
visible in Cardiac with its requested flag and problem entry.

## Package and verification limits

All 173 Python files parse with ast and all three TOML files with tomllib.
The release ZIP has CRC verification and regenerated SHA256SUMS.txt. Cache
files and the supplied clinical source examples are excluded.

UI checks use Streamlit widget stubs. No live browser or hosted Streamlit app
was exercised. External repository services are mocked in tests. Encryption,
GitHub storage, Mapping Sync, Secrets, archive paths and dependencies are
unchanged. The new application module is nutrition_display.py.
