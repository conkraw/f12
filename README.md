# PICU Handoff 6.100

## Automatic paralytic PRN counts

The handoff now counts only vecuronium and rocuronium automatically. Paste the complete SmartPhrase as usual. The PRN review form and confirmation step have been removed.

Each positive dated Volume (mL) entry for either medication contributes one count. Exact duplicate entries are included once, and zero-volume entries do not contribute. A dated explicitly administered PRN entry also contributes one. The presence of a paralytic infusion does not suppress the count.

Analgesic and sedative entries are ignored, including malformed entries in those columns beside valid paralytic records. The imported AF records contain only the two supported paralytics. Existing medication orders continue to be displayed through their normal mappings.

The count window starts at the most recent 7 a.m. Eastern and ends at the time the handoff is generated or printed. For a 4 a.m. handoff, the window starts at 7 a.m. on the preceding day. At 7 a.m., it switches to the new day automatically. Future entries are excluded until their administration time arrives.

The number appears after PRN on the first visible Neurologic PRN order for that medication, for example PRN × 3. The count adds no administration dates or times. A valid AF block with no qualifying entries gives zero for the ordered paralytic. A missing or unreadable AF block does not invent a count.

PDF generation, combined PDFs, PDF caching, and HTML printing use the same counting rules. HTML refreshes at printing, on focus, when visible, and every minute. It uses the timestamped entries contained in that export. New source records become available after a new paste.

## CPAP trial display

A reported Pressure Support - Continuous Positive Airway Pressure mode, including PS-CPAP, displays CPAP Trial Data. The CPAP block omits the duplicate respiratory rate. Other modes keep their own settings, and historical PS-CPAP blocks receive their own trial headings.

## Install from 6.99, 6.99.1, or 6.99.2

Extract PICU6100.zip and open PICU_Handoff_v6_100_Automatic_Paralytic_Counts. Replace app.py, categories.py, error_store.py, exports.py, importing.py, prn_counts.py, and prn_html.py beside the app.py that Streamlit runs. Commit the replacements and reboot Streamlit once. Confirm Version 6.100 in the sidebar, then paste the complete SmartPhrase as usual.

For 6.98 or an earlier version, use the complete package's application files. Keep the current Streamlit Secrets and encryption key. Dependencies and archive schema 34 are unchanged. Existing eight-drug PRN records remain readable, but only the two paralytics receive automatic counts. Legacy review signatures do not gate the count.

## Verification

462 targeted tests passed, including the full Streamlit import and save flow, absence of PRN review controls, the prior import-warning regression, mixed medication data, both paralytics, infusion coexistence, exact duplicates, print windows, automatic 7 a.m. rollover, daylight saving transitions, encrypted archive round trips, CPAP output, and PDF caching. The 22 Node tests exercise HTML count refresh. The three native Streamlit tests exercise actual runtime interactions.

The supplied example imported without an AF warning and produced a vecuronium count of 5 at the requested 4 a.m. cutoff. Only aggregate results were reported. No supplied patient source is included in this package.

These are local runtime and automated tests. No live app deployment or production archive write was performed. See TEST_REPORT.md for details and the V6992 files for prior release notes.
