# PICU Handoff 6.86 verification

## Scope and results

All 109 existing AED checks passed after the Labs-only formatting change. These include 87 selection checks and 22 import, routing and export checks. Existing assertions for lower Labs formatting were updated. Neuro expectations remain unchanged.

The 718-check regression run reported in version 6.85 belongs to that baseline and was not repeated for this formatting update.

## Display and clinical behavior

Neuro retains the AED Drug Levels: heading and each drug on separate lines. In lower Labs, the heading and selected drug results are on one continuous line, separated by commas. Each result keeps its own Last checked date, recorded value and flags. The line wraps naturally when needed.

The existing checks cover the strict 24-hour boundary, date-only sources, independent drug selection, unchanged stored rows, duplicate suppression, whole-room replacement, plain text, HTML, single and batch PDFs, and cache expiration.

The PDF renderer signature was updated so cached output uses the new Labs layout. ECLS, login, the lab time-window module, models and dependencies were confirmed unchanged from version 6.85.

## Visual review

A two-page synthetic PDF was rendered to PNG and visually inspected. Neuro retains separate lines on the recent-results page. Both older AED results and their dates fit on one physical line in lower Labs on the second page. Bold headings, labels and low-flag coloring are retained. No clipping or overlap was seen at the existing font size.

No supplied patient paste or production credentials are included. This package is ready to install and has not been deployed.
