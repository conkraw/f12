# PICU Handoff 6.87

This update adds Lysis Labs to Hematology. HGBFREE, LDH and uric acid each get a separate line when a result is available. The two latest eligible results are shown older to newer with an arrow. A single result appears without an arrow. This version builds on 6.86.

## Install

Extract PICU687.zip. Copy the contents of PICU_Handoff_v6_87_Lysis_Labs into the root of your existing app repository, where app.py is located. Replace matching application files and include all listed modules. Do not add an extra folder level.

When updating from version 6.86, upload these application files together:

    app.py
    lysis_labs.py
    labs.py
    lab_windows.py
    models.py
    exports.py
    clinical_style.py
    error_store.py

Keep your existing Streamlit Secrets and encryption key. Dependencies and configuration are unchanged. The archive schema remains 34. Restart Streamlit, then confirm the sidebar reads:

    Version 6.87 | Hematology lysis lab trends

Include the new lysis_labs.py module beside app.py. Re-paste the current complete SmartPhrase to load current results. Saved handoffs with supported G-section results can use the new Lysis Labs display without a data migration.

This package is ready to install. It has not been deployed to the live application.

## Lysis Labs in Hematology

The app reads HGBFREE, LDH and URIC ACID or URICACID from section G. Recognized explicit names for these same assays are also supported. It displays the bold Lysis Labs: heading at the top of Hematology, before the existing DVT, notes and medication content.

Each available assay gets its own line. This is a synthetic example:

    Lysis Labs:
    HGBFREE: <8 [11/20/2026]
    LDH: 180 -> 220 [11/20/2026]
    Uric acid: 4.8 -> 6.0 [11/20/2026]

A single result appears without an arrow. When two or more results are available, the two most recent eligible results are selected and displayed older to newer. This differs from the existing lactate trend, which uses the earliest and latest results in its window. Tests without an eligible result are omitted, and no Lysis Labs heading appears when none are available.

The time window follows lactate: rolling 24 hours against the current Eastern display or print time. A date-only result is eligible if its source date overlaps that window. Collection times determine the order when all same-day results have times. Otherwise the supplied Epic row order is retained. No collection time is invented. The date at the end of each line is the date of the newest selected result, matching the lactate display style.

Values, units, flags and less-than or greater-than symbols are preserved. The app does not infer units or convert results. CBC hemoglobin, lactate, urine uric acid and LDH isoenzymes are kept separate. Pending, rejected, excluded, invalid and future results are not selected. Failed G imports suppress derived lysis output.

The selected results appear in Hematology rather than being duplicated in lower Labs. All original G rows remain available in the editor and encrypted archive. A new complete replacement paste without G clears the prior room's lysis results through the existing replacement workflow.

## ECLS in CV

The app reads ECLS settings from the paired alternating adadadad section of the complete SmartPhrase. The CV order remains vital signs, cardiac laboratory results, ECLS settings, then existing CV notes and medications. The ECLS settings heading is bold in the preview and PDF.

This synthetic example uses dosing weight 20 kg and chart-reported BSA 0.8 m²:

    ECLS settings:
    Mode: VA [Oxy Day: 0]
    Blood flow: 1.6 L/min, 80.0 mL/kg/min [CI: 2 L/min/m²]
    RPM: 3100
    Sweep: 0.7 L/min
    FiO₂: 40%

There are six logical lines, including the heading, with no pipe separators between settings. Long lines can wrap within the existing CV column. The handoff font size is unchanged.

| Display | SmartPhrase source |
| --- | --- |
| Mode | ECMO Mode, normalized to VA or VV |
| Oxy Day | Oxygenator Day |
| Blood flow in L/min | Pump Flow (L/min) |
| Blood flow in mL/kg/min | Pump flow × 1000 ÷ dosing weight in kg |
| CI in L/min/m² | Pump flow ÷ chart-reported BSA in m² |
| RPM | Set Speed (rev/min) |
| Sweep | Sweep Gas Flow Rate (L/min) |
| FiO₂ | Blender FiO2 (%) |

Indexed flow is displayed to one decimal place. CI is rounded to two decimal places with trailing zeroes removed. Measured weight does not replace missing dosing weight, and BSA is not reconstructed from height and weight. A separately charted CI is not used in this calculation.

Documented zero values are retained. Missing settings or calculation inputs show UNK. One complete source snapshot supplies the settings. Conflicting duplicate fields or multiple populated reports remain flagged for review.

## AED drug levels

Section G supplies PHENOBARB and PHENYTOIN results. Recognized Phenobarbital and total Phenytoin label variants are supported. Free Phenytoin remains a separate assay and is not combined with total Phenytoin.

The app selects the latest valid measured result for each drug independently. If that result is within the past 24 hours, including the exact 24-hour boundary, it appears under the bold AED Drug Levels: heading in Neuro. Each drug gets its own line. A synthetic recent example is:

    AED Drug Levels:
    Phenobarbital: 30.2 [11/20/2026 07:00]
    Phenytoin: 7.1 (L) [11/20/2026 06:30]

If the latest result is older, it appears on one continuous line in the lower Labs area with its original date and any recorded time. Results are separated by commas and wrap naturally if needed:

    AED Drug Levels: Phenobarbital: 30.2 [Last checked: 11/19/2026], Phenytoin: 7.1 (L) [Last checked: 11/18/2026 12:00]

Each drug appears in one location. A recent Phenobarbital result can appear in Neuro while an older Phenytoin result appears in Labs. Earlier results for the same drug are not repeated in either display. The latest older result has no age limit if it is present in the current source.

The 24-hour window uses the current Eastern time when the handoff is displayed or exported. It does not use the most recent lab date or a saved handoff timestamp. Each render reevaluates placement, and an earlier cached PDF is not reused after a result crosses that cutoff.

A date without a collection time qualifies for Neuro only when the beginning of that source date is within the past 24 hours. At 08:00 on November 20, for example, a result dated only November 19 stays in Labs with Last checked: 11/19/2026. Its collection time is not invented. Pending, cancelled, invalid or future results do not become selected AED levels.

Recorded values, flags such as (L), source dates and supplied units are preserved. No units are added when the source omits them. Display routing does not change the stored G-section rows.

## Replacement and saved handoffs

Every complete SmartPhrase paste replaces the selected room's handoff. A new paste without AD removes old ECLS settings. A new paste without G removes old drug levels. Other rooms keep their own handoffs.

An invalid AD block does not carry forward previous circuit settings. If section G fails import review, the app suppresses automatic AED output from retained rows until the source is corrected. Existing handoffs without ECLS or these drug levels still open normally.

## Existing workflows and verification

The centered password screen from version 6.84 is unchanged, including masked entry, Enter to submit, retry delay, session expiry and logout. The invasive NAVA implementation and existing mapping, I/O and room replacement workflows remain in place.

All 630 executed checks passed: 516 existing regression checks, 97 Lysis Labs selection checks and 17 Lysis Labs integration checks. A two-page synthetic PDF was rendered and visually checked for single-result and two-value trend layouts. TEST_REPORT.md records the verification scope. No supplied patient paste or production credentials are included in this package.

ARCHIVE_COMPATIBILITY.txt describes saved handoff compatibility.
