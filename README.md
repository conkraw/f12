# PICU Handoff 6.103

## Latest ventilator mode from the Epic flow table

The All Vent Modes flow table is now the primary source for the current mode. The importer compares complete dates and times across every table block, including when Epic splits the six entries into multiple blocks. Blank cells keep their column positions and do not become mode entries.

When the newest mode is PS - CPAP, the handoff uses the dedicated CPAP Trial Settings for pressure support, PEEP, FiO2, and available weaning tidal volumes and tolerance. When a newer conventional mode follows the trial, the handoff switches back to its matching settings. Earlier table modes are available in the existing history editor but are unchecked by default. The older individual SmartLink history format keeps its existing behavior.

NAVA, AVAPS, and non-invasive modes continue through their existing settings rules. An empty or absent table uses the original Vent Mode field. The table can also supply the mode when that original SmartLink has been removed. An unrecognized newest table mode retains its name without borrowing settings from an older mode.

The timestamp belongs to the mode entry. Numerical settings still come from the matching settings section in the same paste, because the table does not timestamp those individual settings. No new settings are calculated.


## Paralytic PRN counts from the AF table

The handoff counts only vecuronium and rocuronium automatically. Paste the complete SmartPhrase as usual, including the dated volume table between the alternating af dividers. No PRN review form or confirmation step is needed.

Each positive dated Volume (mL) cell contributes one count. The parser combines repeated date-header blocks and preserves blank columns so each volume keeps its correct timestamp. Exact duplicate entries are included once. Blank and zero-volume cells do not contribute. Earlier dated FLOWDATETIME output and explicitly administered PRN entries remain supported. The presence of a paralytic infusion does not suppress the count.

Analgesic and sedative entries are ignored, including malformed entries in those columns beside valid paralytic records. The imported AF records contain only the two supported paralytics. Existing medication orders continue to be displayed through their normal mappings.

The count window starts at 07:00 Eastern on the calendar day before printing and ends at the time the handoff is prepared or printed. Both endpoints are included. For a handoff printed on November 22 at 12:30, counting starts on November 21 at 07:00 and includes available entries through November 22 at 12:30. The window continues past 07:00 on the printing day and is not a rolling 24-hour interval. Future entries are excluded until their administration time arrives.

The number appears after PRN on the first visible Neurologic PRN order for that medication. Counts below six display as `PRN × 5`, for example. Six or more display as `PRN ≥6`, reflecting the table's six-entry limit. The count adds no administration dates or times. A valid AF block with no qualifying entries gives zero for the ordered paralytic. A missing or unreadable AF block does not invent a count.

PDF generation, combined PDFs, PDF caching, and HTML printing use the same counting rules. HTML refreshes at printing, on focus, when visible, and every minute. It uses the timestamped entries contained in that export. New source records become available after a new paste.

## CPAP trial display

A reported Pressure Support - Continuous Positive Airway Pressure mode, including PS-CPAP, displays CPAP Trial Data. The CPAP block omits the duplicate respiratory rate. Other modes keep their own settings, and historical PS-CPAP blocks receive their own trial headings.

## Update from 6.102

Update app.py, error_store.py, exports.py, ventilation.py, and ventilator_modes.py together in the application folder. Confirm Version 6.103 in the sidebar, then paste the complete SmartPhrase as usual. If Streamlit has not picked up the updated files, reboot the app once. Version 6.102 AF-table parsing and count-window behavior are preserved.

For an earlier version, use the complete repository's application files. Keep the current Streamlit Secrets and encryption key. Dependencies and archive schema 34 are unchanged. Existing eight-drug PRN records remain readable, but only the two paralytics receive automatic counts. Legacy review signatures do not gate the count.

## Verification

801 focused tests passed on the merged 6.103 code. Coverage includes horizontal flow tables, the older mode-history format, CPAP selection, NAVA, AVAPS, NIV, missing-table fallback, native Streamlit import and save, PDF caching, and batch exports. The new coverage adds 32 table cases and one native end-to-end test. The run took 15.35 seconds and reported 103 existing anyio and pypdf deprecation warnings.

The supplied example selected the conventional mode at 11:40. Making PS - CPAP the newest entry selected its dedicated trial settings. A separate synthetic example combined the mode table with the AF table and retained the expected paralytic displays of `PRN × 5` at 10:30 and `PRN ≥6` at 12:02 while displaying CPAP correctly.

The 6.102 medications.py, prn_counts.py, and prn_html.py files remain identical to the current baseline. No supplied patient examples are committed. These are local runtime and automated checks. Live Streamlit deployment was not verified. See TEST_REPORT.md for details.

## Previous release verification

467 focused tests passed across parsing, HTML print refresh, integration, native Streamlit import and save, medication formatting, and the error journal. Coverage includes repeated header blocks, empty cells, exact duplicates, both paralytics, exclusion of other medications, previous-day 07:00 cutoffs, the six-entry cap, PDF caching, and existing archive compatibility.

The supplied complete SmartPhrase also imported its AF table successfully. It produced three qualifying entries at 06:59, five at 10:30, and the capped six display at 12:02 on the printing day. Its generated PDF used `PRN >=6`, the PDF font-compatible form of `PRN ≥6`.

Test fixtures use synthetic data. No supplied patient source is included in the repository. See V6102_README.md for the previous release's behavior and the earlier versioned notes for previous changes.
