# PICU Handoff 6.101

## Automatic paralytic PRN counts

The handoff now counts only vecuronium and rocuronium automatically. Paste the complete SmartPhrase as usual. The PRN review form and confirmation step have been removed.

Each positive dated Volume (mL) entry for either medication contributes one count. Exact duplicate entries are included once, and zero-volume entries do not contribute. A dated explicitly administered PRN entry also contributes one. The presence of a paralytic infusion does not suppress the count.

Analgesic and sedative entries are ignored, including malformed entries in those columns beside valid paralytic records. The imported AF records contain only the two supported paralytics. Existing medication orders continue to be displayed through their normal mappings.

The count always starts at 7 a.m. on the previous Eastern calendar day. Before 7 a.m. today, it ends at the current print time. At 7 a.m. or later, it remains capped at the end of today's 6:59 a.m. minute. Today's entries at 7 a.m. or later are excluded. The count does not restart at 7 a.m.

| Printed today | Counted interval |
| --- | --- |
| 4 a.m. | Yesterday at 7 a.m. through today at 4 a.m. |
| 8 a.m. | Yesterday at 7 a.m. through today at 6:59 a.m. |
| Afternoon or evening | Yesterday at 7 a.m. through today at 6:59 a.m. |

The entire 6:59 minute is included. At the next Eastern midnight, yesterday and today advance to the new calendar dates. Future entries remain excluded. This window applies to both vecuronium and rocuronium.

The number appears after PRN on the first visible Neurologic PRN order for that medication, for example PRN × 3. The count adds no administration dates or times. A valid AF block with no qualifying entries gives zero for the ordered paralytic. A missing or unreadable AF block does not invent a count.

PDF generation, combined PDFs, PDF caching, and HTML printing use the same counting rules. HTML refreshes at printing, on focus, when visible, and every minute. It uses the timestamped entries contained in that export. New source records become available after a new paste.

## CPAP trial display

A reported Pressure Support - Continuous Positive Airway Pressure mode, including PS-CPAP, displays CPAP Trial Data. The CPAP block omits the duplicate respiratory rate. Other modes keep their own settings, and historical PS-CPAP blocks receive their own trial headings.

## Install from 6.100

Extract PICU6101.zip and open PICU_Handoff_v6_101_Previous_Day_PRN_Window. Replace app.py, error_store.py, exports.py, prn_counts.py, and prn_html.py beside the app.py that Streamlit runs. Commit the replacements and reboot Streamlit once. Confirm Version 6.101 in the sidebar.

From 6.99, 6.99.1, or 6.99.2, also replace categories.py and importing.py. From 6.98 or earlier, use the complete package's application files. Keep the current Streamlit Secrets and encryption key. Dependencies and archive schema 34 are unchanged.

## Verification

480 targeted tests passed. Core and HTML tests reproduced the old 7 a.m. reset behavior before the fix and then passed with the capped window. Coverage includes before 7 a.m., exact 7 a.m., 8 a.m., late evening, the full 6:59 minute, midnight, daylight saving transitions, year and leap-day boundaries, text and HTML exports, individual and combined PDFs, PDF caching, and native Streamlit import and save.

The full app test at 8 a.m. confirms that the overnight count is retained and doses at 7 a.m. or later are excluded. The previous import-warning regression also passes. No review controls were reintroduced. Tests also cover exclusion of sedatives and analgesics, infusion coexistence, archive compatibility, and CPAP output.

These are local runtime and automated tests. No live deployment or production archive write was performed. No supplied patient source is included. See TEST_REPORT.md for details and the V6100 files for the preceding release notes.
