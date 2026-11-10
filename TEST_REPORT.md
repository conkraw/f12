# Version 6.55 verification

Base: supplied PICU654.zip. ZIP CRC and all original SHA256 manifest entries verified.
Original, unmodified baseline suite: 4512 passed in 94.86 seconds.
Updated working-tree suite: 4591 passed in 94.23 seconds.
Clean staged-ZIP extraction: 4591 passed in 96.69 seconds.
New focused regression suite: 78 passed.

Coverage includes all CAPD integer totals 0 through 32, inclusive threshold 9,
regular-weight values, high-score red color markup, absent/hidden/failed-import
CAPD handling, source-score immutability, no new delirium diagnosis, bold
labels with escaped values, exact lactate trend selection with the new colon,
recognition of racemic inhalation products, exclusion of systemic/non-racemic
products, preserved manual overrides and hiding, one order per destination,
custom category nesting, multiple-room printing, and schema-33 migration.

Current-schema assertions in older tests were updated from 33 to 34.
Lactate output expectations now include the requested colon. Older visible-text
comparisons ignore only b/font/tspan styling tags using the existing helper.
Their content and ordering checks remain. New tests verify actual styling
separately. One existing parameterized category test now covers the new group.

A synthetic encrypted archive was produced by the unmodified 6.54 code, then
opened and re-encrypted by 6.55 with the same synthetic key. All existing room
data, notes, saved timestamps, reset generation, mappings, renamed categories
and rules were preserved. Only schema and one missing built-in category changed.
No real keys or patient archives are included in this package.

The synthetic PDF preview fits on one landscape page at 8-point body text.
It was rendered and visually inspected. Independent PDF text-span inspection
confirms Times-Bold labels, Times-Roman values, red 0xb00020 for CAPD 11 (H),
regular-weight EVD status and lactate values, and no clipping or overlapping text.

Application files changed: app.py, capd.py, clinical_style.py, exports.py,
lab_windows.py, medication_groups.py and models.py.
No requirements, encryption, storage, import parsing, laboratory selection,
SBS logic, vital-sign import, CBC or blood-gas import changes were made.

No live deployment, browser session, or shared patient archive was accessed
or modified. Existing UI tests use local simulations.
