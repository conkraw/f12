# PICU Handoff 6.102

## Paralytic PRN counts from the AF table

The handoff counts only vecuronium and rocuronium automatically. Paste the complete SmartPhrase as usual, including the dated volume table between the alternating af dividers. No PRN review form or confirmation step is needed.

Each positive dated Volume (mL) cell contributes one count. The parser combines repeated date-header blocks and preserves blank columns so each volume keeps its correct timestamp. Exact duplicate entries are included once. Blank and zero-volume cells do not contribute. Earlier dated FLOWDATETIME output and explicitly administered PRN entries remain supported. The presence of a paralytic infusion does not suppress the count.

Analgesic and sedative entries are ignored, including malformed entries in those columns beside valid paralytic records. The imported AF records contain only the two supported paralytics. Existing medication orders continue to be displayed through their normal mappings.

The count window starts at 07:00 Eastern on the calendar day before printing and ends at the time the handoff is prepared or printed. Both endpoints are included. For a handoff printed on November 22 at 12:30, counting starts on November 21 at 07:00 and includes available entries through November 22 at 12:30. The window continues past 07:00 on the printing day and is not a rolling 24-hour interval. Future entries are excluded until their administration time arrives.

The number appears after PRN on the first visible Neurologic PRN order for that medication. Counts below six display as `PRN × 5`, for example. Six or more display as `PRN ≥6`, reflecting the table's six-entry limit. The count adds no administration dates or times. A valid AF block with no qualifying entries gives zero for the ordered paralytic. A missing or unreadable AF block does not invent a count.

PDF generation, combined PDFs, PDF caching, and HTML printing use the same counting rules. HTML refreshes at printing, on focus, when visible, and every minute. It uses the timestamped entries contained in that export. New source records become available after a new paste.

## CPAP trial display

A reported Pressure Support - Continuous Positive Airway Pressure mode, including PS-CPAP, displays CPAP Trial Data. The CPAP block omits the duplicate respiratory rate. Other modes keep their own settings, and historical PS-CPAP blocks receive their own trial headings.

## Update from 6.100 or 6.101

Update app.py, error_store.py, exports.py, medications.py, prn_counts.py, and prn_html.py together in the application folder. Confirm Version 6.102 in the sidebar, then paste the complete SmartPhrase as usual. If Streamlit has not picked up the updated files, reboot the app once.

For an earlier version, use the complete repository's application files. Keep the current Streamlit Secrets and encryption key. Dependencies and archive schema 34 are unchanged. Existing eight-drug PRN records remain readable, but only the two paralytics receive automatic counts. Legacy review signatures do not gate the count.

## Verification

467 focused tests passed across parsing, HTML print refresh, integration, native Streamlit import and save, medication formatting, and the error journal. Coverage includes repeated header blocks, empty cells, exact duplicates, both paralytics, exclusion of other medications, previous-day 07:00 cutoffs, the six-entry cap, PDF caching, and existing archive compatibility.

The supplied complete SmartPhrase also imported its AF table successfully. It produced three qualifying entries at 06:59, five at 10:30, and the capped six display at 12:02 on the printing day. Its generated PDF used `PRN >=6`, the PDF font-compatible form of `PRN ≥6`.

Test fixtures use synthetic data. No supplied patient source is included in the repository. See V6102_README.md for this release's behavior and the earlier versioned notes for previous changes.
