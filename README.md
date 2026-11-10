# Version 6.55: demographic labels, CAPD flags and airway category

Built directly from the supplied PICU654.zip.

## Labels and values

Room, Age, Sex, Admission, Diagnoses, Weight, Z-score, Dosing weight,
Height, BSA and EVD labels are bold through the colon. Their values remain
regular weight. The same formatting is used in the HTML preview and PDF,
including Print all.

The compact lactate summary now starts with a bold Lactate: label.
The existing 24-hour selection, earliest-to-latest order, source units,
flags and latest-result date are unchanged. Example:

    Lactate: 1.0 -> 1.1 [11/9/2026]

## CAPD

A displayed CAPD total of 9 or greater gains a red (H) flag, for example:

    CAPD: 11 (H)

CAPD remains bold through the colon. The number and flag remain regular
weight. Scores 0 through 8 do not receive the new flag. Missing, excluded,
or import-failed totals retain the existing CAPD: None display.

This is a requested presentation rule. The numeric total stored in the
archive and editor is unchanged, and no delirium diagnosis is added.
SBS, CAPD and WAT ordering and their selection logic are unchanged.

## Respiratory category

Airway Vasoconstrictor is a new editable medication category in Respiratory.
Racemic epinephrine / racepinephrine inhalation or nebulization orders use
this automatic placement. The Asthmanefrin name is also recognized.
Systemic epinephrine and norepinephrine, injections, and generic non-racemic
epinephrine are not moved to this category.

Saved category overrides remain authoritative. Hidden orders stay hidden.
Separate scheduled and PRN orders are preserved, with each order printed once.
Names, doses, routes and frequencies are not changed. Admin can rename or
nest the category, and the medication selector can assign a different one.

Medication naming reference checked: National Library of Medicine DailyMed,
S2 racepinephrine hydrochloride solution, respiratory (inhalation).
https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=dd1b35c7-b23b-4b95-8162-df3d263fe32e

## Install

Replace the application files with this folder's contents, keeping app.py
at the root. Restart the app and refresh the browser. Keep your existing
Secrets, both passwords, encryption key, mappings, category settings,
BMI reference data and shared patient archive unchanged. Do not rerun
setup generators. No new dependencies or re-pasting are required for
information already stored. Regenerate existing PDFs to see the changes.

Updated application files:

    app.py
    capd.py
    clinical_style.py
    exports.py
    lab_windows.py
    medication_groups.py
    models.py

Archive schema 33 upgrades to 34, adding only the missing built-in category.
Existing names, locations, custom categories, mappings, rooms, notes and
save timestamps are preserved. Do not downgrade after saving new category
choices, because prior versions cannot validate the new category ID.

The compact workspace, quiet Alerts tab, one-click clear-all access,
password protection, autosave, clinical import parsers and PDF fitting
behavior are unchanged. No live deployment or shared archive was modified.

Verification details: TEST_REPORT.md. Historical feature notes remain in the package.
