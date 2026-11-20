# PICU Handoff 6.84

This update adds a centered password screen and a compact ECLS settings block in the Cardiovascular section. It builds on version 6.83 and includes the invasive NAVA update.

## Install

Extract PICU684.zip. Copy the contents of PICU_Handoff_v6_84_ECLS_Login into the root of your existing app repository, where app.py is located. Replace matching application files and add the new modules. Do not add an extra folder level.

When updating from version 6.83, these application files must be uploaded together:

    app.py
    login_ui.py
    ecls.py
    parser.py
    importing.py
    models.py
    import_review.py
    exports.py
    clinical_style.py
    batching.py
    error_store.py

Keep your existing Streamlit Secrets and encryption key. No new package or configuration setting is required. Restart Streamlit, then confirm the sidebar reads:

    Version 6.84 | ECLS settings and centered sign in

This package is ready to install. The live application has not been updated.

## Centered sign in

The password screen uses the EPA tracker's navy and teal palette, a centered card, a masked Password field, and a full-width Sign in button. Enter submits the form. The card adapts to narrow screens. Existing password verification, retry delay, session expiry and logout behavior continue to apply.

## ECLS placement and display

The app reads ECLS settings from the paired alternating adadadad section of the complete SmartPhrase. In the CV column, the order is vital signs, cardiac laboratory results, ECLS settings, then existing CV notes and medications. The ECLS settings heading is bold in the preview and PDF.

For the provided field values, with a dosing weight of 27 kg and a chart-reported BSA of 1 m², the output is:

    ECLS settings:
    Mode: VA [Oxy Day: 0]
    Blood flow: 2.3 L/min, 85.2 mL/kg/min [CI: 2.3 L/min/m²]
    RPM: 3400 | Sweep: 1.2 L/min | FiO₂: 50%

The block has four logical lines. Long lines wrap within the existing CV column, using the current handoff font size.

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

Weight indexed flow is displayed to one decimal place. CI is rounded to two decimal places with trailing zeroes removed. Flow goal and the separately charted CI are not inputs to these calculations. Measured weight does not replace missing dosing weight, and BSA is not reconstructed from height and weight.

## Missing data and replacement

A documented oxygenator day of 0 is retained. Documented zero pump flow or sweep is also retained. Missing settings show UNK. An unavailable dosing weight or BSA withholds the corresponding calculation and shows UNK. Notes in the CV review explain unavailable calculations.

One complete source snapshot supplies the ECLS block. Conflicting duplicate fields or multiple populated reports are flagged for review. The parser does not combine separate circuit snapshots.

Every complete SmartPhrase paste replaces the selected room's handoff. If that new paste lacks AD data, the old ECLS settings are removed. An empty or invalid AD block does not carry forward previous circuit settings. Other rooms keep their own saved handoffs.

Re-paste the current complete SmartPhrase after installing to populate ECLS settings. Existing saved handoffs without ECLS still open normally and show no ECLS heading.

## NAVA and existing workflows

Version 6.83's invasive NAVA parser and display are included unchanged. The app still uses NAVA Ventilator Settings for NAVA level, PEEP, oxygen, Edi peak/min, observed PIP, tidal volume, respiratory rate and apnea time. The current room replacement, mapping, I/O and print cache workflows remain in place.

## Verification

TEST_REPORT.md describes the calculation, import, replacement, encrypted storage, login and export checks. A synthetic PDF was rendered and visually checked at the existing CV column width. No supplied patient paste or production credentials are included in this package.

ARCHIVE_COMPATIBILITY.txt describes saved handoff compatibility.
