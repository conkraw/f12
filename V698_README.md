# PICU Handoff 6.98

## Print all with visible preparation

On Print all, choose your rooms and click Prepare selected handoffs. A live elapsed timer remains visible while the app prepares the packet. The progress display counts completed handoffs, then shows the combining and final verification steps. A success message shows the total preparation time and enables Download all selected handoffs (PDF).

The timer measures PDF preparation. It does not estimate browser transfer time or the printer queue. Download still checks the current saved handoffs and refreshes print metadata. A changed selection, page target, saved handoff or current displayed content requires fresh preparation.

## More room on one page

Select Auto-fit to 1 page. Handoffs that already fit at the normal 8-point size keep their existing layout. For longer handoffs, the PDF uses tighter spacing, removes empty footer space and balances the clinical column widths.

Other Medications and Devices use compact 6-point text when needed. Their details remain present, separated by visible dividers. Main clinical text stays between 8 and 6.5 points, and difficult-airway alerts remain at least 8 points.

Goals / Follow-up is omitted from the PDF when needed to fit the handoff. The saved notes, editor, HTML preview and text output retain that content. The app reports when this print-only omission occurs. The explicit two-page option continues to retain Goals / Follow-up.

Exceptionally long handoffs can still need continuation pages. The app reports overflow and preserves the remaining clinical content rather than cutting it off.

## Install from 6.97

Extract PICU698.zip and open PICU_Handoff_v6_98_Print_Timer_One_Page. Replace the existing files below and add the new print_feedback.py beside the app.py that Streamlit runs:

- app.py
- error_store.py
- exports.py
- pdf_cache.py
- print_feedback.py

Reboot Streamlit once and confirm Version 6.98. Existing saved handoffs do not need to be pasted again for these print changes.

If updating from an earlier version, use the complete package contents. Keep your existing Streamlit Secrets and encryption key. Dependencies and the saved-data schema are unchanged.

## Verification

367 targeted tests passed. Native Streamlit interface checks completed without exceptions. A dense synthetic PDF was rendered and visually inspected. It fits on one page with 8-point main text, 6-point secondary text and Goals / Follow-up omitted from the PDF only.

The supplied source was also checked privately. Its one-page output uses 7.5-point main text, compared with 7 points in the prior version. The supplied source is not included in this package.

See examples/adaptive_one_page_preview.pdf, examples/adaptive_one_page_check.json and TEST_REPORT.md. Prior release notes are retained in the V697 files.

Ready to install. This package has not been deployed to the live application.
