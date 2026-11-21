# PICU Handoff 6.96

This update adds an Intravenous Fluids group in FEN/GI and visible feedback while a handoff is being processed.

## Intravenous Fluids

Recognized continuous IV fluids appear together under Intravenous Fluids. The display keeps the original formulation and the source of the displayed rate, including its timestamp.

A numeric Last Admin rate is used when available. If Last Admin contains an event such as New Bag without a rate, the explicit Last Rate is used. An ordered rate is labeled Ordered rate when it is the only usable rate. Bag volume is never converted into an hourly rate.

For a synthetic dosing weight of 20 kg, an IV rate of 45 mL/hr appears with a 3/4 maintenance comparison. A 1 or 2 mL/hr fluid remains visible with its rate and no maintenance comparison.

### Maintenance comparison

The reference uses the hourly 4-2-1 formula with documented dosing weight:

- First 10 kg: 4 mL/kg/hr.
- Next 10 kg: 2 mL/kg/hr.
- Each kilogram above 20 kg: 1 mL/kg/hr.

The calculation uses the raw formula result at all weights. For example, 66 kg gives a reference of 106 mL/hr, so 75 mL/hr displays as approximately 71% maintenance. The comparison describes the displayed rate relative to this reference.

Exact quarter fractions display as 1/4, 1/2, 3/4, or maintenance. Rates within two percentage points of a quarter fraction use a preceding ~. Other ratios use a rounded percentage. The comparison applies to each fluid separately.

Missing, unreadable or failed dosing-weight information leaves the comparison blank. Measured weight is not substituted for dosing weight. Stopped, held, paused or discontinued events also suppress the comparison. Ambiguous rates require review.

The automatic group recognizes the supplied sodium-acetate formulations, common saline and dextrose fluids, lactated Ringer's, Plasma-Lyte and explicitly documented standard dilute KCl bags. Medication drips in a carrier, boluses, flushes, small electrolyte replacement bags, concentrated products, PN, lipids and nebulized products retain their existing categories. D50 retains Hypoglycemia.

Saved category choices, custom wording, Ignore and visibility controls remain available. Older category settings receive the new built-in category without an archive schema change.

Formula references:

[University of Pennsylvania: hourly 4-2-1 calculation](https://www.med.upenn.edu/pedsinpractice/dehydration/)

[UCSF: maintenance IV fluid calculation and dosing-weight basis](https://medconnection.ucsfbenioffchildrens.org/maintenance-iv-fluid/)

## Processing feedback

A native spinner shows live elapsed time. A progress bar identifies the current step: reading the SmartPhrase, saving the handoff or preparing the PDF.

The first import shows progress without a time estimate. After a successful import, later imports can display typical remaining time using up to five recent successful imports in that session. Estimates update at step boundaries. Shared-storage and session-only timings are kept separately.

A parse or save failure clears the indicator and preserves the existing failure handling. Partial imports retain their Alerts message. A PDF preparation failure keeps the confirmed save and reports that preparation will retry on download.

Only phase durations are kept for estimates. They remain in the current session and are not added to the saved patient archive.

## Install from 6.95

Extract PICU696.zip and open PICU_Handoff_v6_96_IV_Fluids_Progress.

Copy these seven files into the existing app folder:

- app.py
- categories.py
- error_store.py
- fen_gi.py
- infusions.py
- iv_fluids.py
- processing_feedback.py

iv_fluids.py and processing_feedback.py are new files and must be included beside app.py.

Reboot Streamlit once and confirm Version 6.96. If updating from an earlier version, use the complete package contents. Keep existing Streamlit Secrets and the encryption key.

No dependency or archive schema change is required. The Home button, ventilator fallback and lumbar drain update are included.

See TEST_REPORT.md for the verification results and examples/iv_fluids_preview.pdf for the synthetic print preview. Previous release notes are retained in the V695 files.

This package is ready to install and has not been deployed to the live application.
