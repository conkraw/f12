# PICU Handoff 6.99

## CPAP trial display

A reported Pressure Support - Continuous Positive Airway Pressure mode, including PS-CPAP, now displays the heading CPAP Trial Data. The CPAP block omits the duplicate respiratory rate. Other modes keep their own settings, and a historical PS-CPAP block receives its own trial heading. An unused CPAP template does not establish that a trial occurred.

## PRN counts in Neurologic

The AF section, enclosed by alternating af dividers, supports hydromorphone, morphine, fentanyl, midazolam, ketamine, pentobarbital, vecuronium, and rocuronium. Familiar brand aliases are recognized.

A confirmed medication total appears after its PRN wording, for example q1h PRN × 4. The number appears once per medication, on its first visible Neurologic PRN order. It does not annotate a continuous infusion or a scheduled order. Administration dates and times are not added to the printed PRN entry.

The count window begins at the most recent 7 a.m. Eastern and ends when the handoff is generated. At 4 a.m. on November 22, that means November 21 at 7 a.m. through November 22 at 4 a.m. At or after 7 a.m., the new reporting day starts. Individual and combined PDFs use the same clock, and cached PDFs refresh when the displayed count changes. HTML exports recalculate their existing confirmed count data before printing and remove an expired count after the next 7 a.m.

## Review the volume source

Generic Volume (mL) records do not establish the number of PRN administrations. They can include continuous infusions, combine multiple doses, or omit actual administrations. The supplied example contains hourly hydromorphone volumes and administration times that are absent from the matching volume-table rows. This version does not convert those volumes into guessed dose counts.

Open Medications > PRN counts after importing the complete SmartPhrase. Choose a medication and check its entries against the MAR. Enter the actual administration date and time. Enter 0 for an infusion or another non-PRN entry, or the verified number of PRN doses. Add missing administrations as new rows. Leave uncertain entries blank until resolved.

Click Confirm [medication] PRN count to validate and save that medication's review through the existing handoff save workflow. A blank count remains unknown. A verified zero is allowed. Doses at the same administration time should be combined in one row, with duplicate volume rows set to 0. Reviews for other medications are preserved.

A complete replacement paste clears previous PRN entries and review decisions along with the rest of the room's old handoff. A changed medication record invalidates that medication's confirmation. The next 7 a.m. requires a new review. Counts use the administrations present in the pasted and reviewed data. New Epic administrations require a fresh paste or a new verified entry.

## Install from 6.98

Extract PICU699.zip and open PICU_Handoff_v6_99_CPAP_PRN. Upload the following files beside the app.py that Streamlit runs, replacing matching files and adding the three new PRN modules:

- app.py
- categories.py
- clinical_style.py
- error_store.py
- exports.py
- import_review.py
- importing.py
- medications.py
- models.py
- parser.py
- ventilation.py
- prn_counts.py
- prn_html.py
- prn_ui.py

Reboot Streamlit once and confirm Version 6.99. Paste the complete SmartPhrase again to import the new AF section, then review PRN counts in Medications.

For an earlier version, use the complete package. Keep the current Streamlit Secrets and encryption key. Dependencies and archive schema 34 are preserved. Use the updated application files together. Earlier app code may not recognize the new optional PRN field.

The print-all timer, cached PDF preparation, compact one-page fitting, medication mappings, and full-room replacement workflow from 6.98 remain available. Prior release notes are retained in the V698 files.

## Verification

908 targeted checks passed across parser, source review, midnight and 7 a.m. windows, daylight saving transitions, current and historical CPAP output, all eight medications, individual and combined exports, PDF cache freshness, encrypted archive round trips, mapping synchronization, room replacement, and Streamlit callbacks. Real Streamlit form tests checked blank, zero, fractional, added, deleted, and stale entries. Node tests executed the HTML print-refresh script. A synthetic one-page PDF was rendered and visually checked.

The supplied clinical example was used only for local verification and is not included in this package. The package is ready to install. No live application deployment or production archive write was performed.
