# PICU Handoff 6.99.1

## PRN preview fix

Version 6.99 could display the generic unexpected-problem message immediately after importing a handoff with PRN data. The preview used re.search without importing re at module scope. This release adds the missing import.

PRN dates outside Python's representable timezone-conversion range now produce the existing date-validation message in the PRN editor. The draft stays available and no review is saved for an invalid date.

## Update an installed 6.99 app

Extract PICU6991.zip and open PICU_Handoff_v6_99_1_PRN_Preview_Fix. Replace app.py, error_store.py, and prn_counts.py beside the app.py that Streamlit runs. Commit the replacements and reboot Streamlit once. The sidebar should show Version 6.99.1. Reopen the handoff and check its saved status.

For 6.98 or an earlier version, use the complete package's application files. Keep the current Streamlit Secrets and encryption key. Dependencies and archive schema 34 are unchanged.

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

## Verification of this fix

297 targeted tests passed. A full Streamlit AppTest first reproduced the exact reported message while importing synthetic PRN data into the actual app. After the fix, the same flow rendered the preview, offered the PDF download, and saved the handoff without an error. Additional checks covered PRN review, invalid dates, print windows, CPAP output, PDF generation and caching, and save callbacks.

These are local runtime and automated tests. No live app or production archive was accessed. The package contains no supplied patient source. See TEST_REPORT.md for the test details and V699_README.md for the prior release notes.
