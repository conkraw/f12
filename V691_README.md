# PICU Handoff 6.91

This update verifies that the running app has loaded the respiratory importer needed for All Vent Modes.

## What was reproduced

Both new uploaded SmartPhrases import respiratory support successfully with the complete 6.90 package. The new package contains that same working parser.

Loading the older 6.89 ventilation selector reproduces the exact reported error:

    The C block has conflicting repeated respiratory fields.

The older selector treats timestamped entries under All Vent Modes as additional current Vent Mode fields. This creates a conflict with the initial mode, even when the mode name is the same.

These checks point to an older or mixed respiratory module in the running deployment. The live deployment was not inspected, so its installed files and restart state are not confirmed.

## Install

Extract PICU691.zip and open PICU_Handoff_v6_91_Respiratory_Import_Check.

If your app is on 6.89 or 6.90, replace all four of these files in the existing app folder:

- app.py
- ventilation.py
- noninvasive.py
- error_store.py

Put the files beside the app.py that Streamlit runs. Uploading only app.py, or placing the replacement files inside another nested folder, will not replace the imported respiratory modules.

For an earlier app version, copy the complete package contents into the existing app folder.

Reboot the Streamlit app after replacing the files. Then confirm both sidebar lines:

    Version 6.91 | Respiratory import check
    Respiratory mode-history parser: ready

Re-paste the complete current SmartPhrase.

Keep the existing Streamlit Secrets and encryption key. This package has not been deployed to your live app.

## Loaded-parser check

After login and before opening the archive, the app runs a small synthetic example through the actual loaded import path. It verifies latest-mode selection, history deduplication and separate PRVC, NAVA and PS-CPAP settings.

The same check runs before a replacement import. If it fails, the app displays a specific incomplete-update message before altering a handoff. The check does not read the patient's paste or write to shared storage.

The ready label reports the result of this functional check. A new app version number alone is not treated as proof that the respiratory modules were updated.

## Current Shift message

The Current Shift warning in the new examples is separate from the respiratory error.

One source says No intake/output data recorded. The other supplies intake but no usable output-category breakdown. Neither supplies the current-shift Urine, Drains, Chest Tube or Other output quantities needed for those rates.

The existing app therefore withholds the unavailable rates. It does not substitute 24-hour output, infer urine output from a total or treat a missing category as zero.

## Verification

All five uploaded examples were checked through the complete replacement-import workflow. Respiratory support imported successfully in each.

The final selected regression run passed 302 tests with no failures, errors or skips. Twelve new tests cover the loaded-parser check, incomplete module updates, startup behavior and preservation of the paste and handoffs when the check fails.

The existing mode-history parser, source-section boundaries and settings format are unchanged from 6.90. The prior synthetic print preview remains in examples/vent_mode_history_preview.pdf.

See TEST_REPORT.md for details. Earlier release notes are retained in the V690 files.

No new modules, dependencies, archive schema or credentials are required.
