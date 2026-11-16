# PICU Handoff 6.80

This release adds specific 3% saline nebulizer placement and per-dose weight calculations for Sedative PRNs, chlorothiazide and furosemide. It builds on PICU679.zip and retains faster Print all and complete-room SmartPhrase replacement.

This package has not been deployed to the live application.

## Install

Extract PICU680.zip. Replace matching code files at your existing app repository root, beside the current app.py. Do not add another folder level.

From 6.79, install all nine runtime files listed in UPDATE_FILES.txt together. airway_clearance.py and medication_doses.py are new. Restart Streamlit after uploading them.

For an older installed version, use the complete code set, including pdf_cache.py and requirements.txt. Keep your existing Streamlit Secrets, encryption key, encrypted archives and saved settings. No new dependency or archive migration is required from 6.79.

Confirm the sidebar reads:

    Version 6.80 | Airway clearance and weight-based doses

## What changed

Sodium chloride or NaCl 3% nebulized/inhaled products appear under Respiratory / Airway Clearance. Both 3 mL and 4 mL are covered. Other concentrations, IV and enteral products, flushes and recognized mixtures do not receive that automatic placement.

Old generic sodium chloride or NaCl prefix rules targeting Respiratory are narrowed to the qualifying product. Exact or formulation-specific assignments remain available. Saved settings are not deleted.

Sedative PRNs and intermittent chlorothiazide/furosemide keep their original absolute dose and gain mg/kg/dose or mcg/kg/dose when one unambiguous amount and a usable weight are available.

For a synthetic 10 kg dosing weight:

    fentanyl injection 15 mcg | Calc: 1.5 mcg/kg/dose (DCW 10 kg)

An explicit weight-based dose from EPIC remains authoritative. Calculations use dosing weight first, then an included measured weight if dosing weight is blank. The annotation identifies the weight used. Missing or invalid weights, failed weight imports, dose ranges, concentrations, daily totals and infusion rates do not produce derived doses.

These are ordered amounts per dose. They do not represent a total PRN amount administered.

## Verification and preview

MEDICATION_UPDATE_680.md describes the exact matching and calculation boundaries.
TEST_REPORT.md records completed verification and its limits.
examples/medication_doses_680_preview.pdf contains two synthetic handoffs.
validation/build_medication_preview_680.py rebuilds that preview.

TEST_REPORT_679.md and FASTER_PRINT_ALL.md retain the prior printing release details.
