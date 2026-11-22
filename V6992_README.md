# PICU Handoff 6.99.2

## Import-warning fix

Version 6.99.1 could raise ValueError while recording an import warning because the technical journal accepted only two numeric version components. Its own version had three. The validator now accepts both two-component versions such as 6.99 and three-component versions such as 6.99.2, with each component bounded to three digits. Older encrypted technical records remain readable. Malformed versions remain invalid.

The sidebar reads the same version constant used by the journal. The previous PRN preview and timestamp-validation corrections are included.

## Update an installed 6.99.1 app

Extract PICU6992.zip and open PICU_Handoff_v6_99_2_Import_Warning_Fix. Replace app.py and error_store.py beside the app.py that Streamlit runs. Commit the replacements and reboot Streamlit once. The sidebar should show Version 6.99.2. Reopen the handoff and check its saved status and Alerts.

If updating directly from 6.99, also replace prn_counts.py from this package. For 6.98 or an earlier version, use the complete package's application files. Keep the current Streamlit Secrets and encryption key. Dependencies and archive schema 34 are unchanged.

The reported exception was reached after the handoff commit step. It did not itself undo a completed save. Reopen the room and check the saved handoff instead of assuming it was lost.

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

469 targeted tests passed. A full Streamlit AppTest first reproduced the exact callback traceback with a synthetic import that produced an AF warning. After the fix, that same flow records the technical event, reaches the preview, and saves the handoff. Tests also check encrypted legacy and patch-version journal round trips, failed log writes, room replacement, PRN output, and PDF caching.

These are local runtime and automated tests. No live app or production archive was accessed. The package contains no supplied patient source. See TEST_REPORT.md for details and the V6991 files for the prior release notes.
