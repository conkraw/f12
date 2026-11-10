# Version 6.28: diet summary and lactate endpoints

This is the complete application update. Upload all folder contents to the code
repository, with app.py at its root. Keep the existing Streamlit Secrets, app
password, Admin password, encryption key, GitHub token and private data archive.
Do not run either secrets/password generator again. No new dependencies.

## What changed

X adds a compact Diet line in FEN/GI, immediately after intake/output and before
feeds. Examples: Adult Regular, Peds Clear Liquid, NPO, NPO except meds (NJ),
Tube Feeding (no tray), Infant Tube Feeding. PN/TPN/PPN, parenteral nutrition,
fat-emulsion entries and print-label-only items are omitted. Actual infant
breast-milk tube-feeding orders are a diet type, not label printing. T continues
to provide the feeding route, formula and rate. Important diet restrictions and
NPO exceptions are retained rather than converted into unrestricted feeding.

Multiple distinct listed diets are not silently combined into one presumed
active order or selected just by their start time. They are shown with a review
warning. Duplicate summaries collapse. Unknown content is omitted and flagged.
Source diet orders and simplified labels are editable under Edit handoff >
FEN / GI > Edit diet / review source. Include/exclude is available for each row.

G recognizes LACWB, LACTATE, LAC, LACTATEVEN and LACTATEART (case-insensitive),
plus previous supported lactate names. All compete by date/time for the earliest
and latest usable results. These print in Cardiovascular after vital signs and
pacemaker, before CV Infusions. Original source code, date, abnormal flag and
supplied units remain visible. Only one available result prints once.

Earliest means earliest AVAILABLE IN THE PASTED G SNAPSHOT, not first in the
hospitalization or the full medical record. No admission-date filtering occurs.
No units are assumed or converted across assay types. Rejected specimens,
'improperly collected', pending, and other nonnumeric entries remain editable in
Labs / Vitals but are not used as measured lactate levels. Blank results do not
produce a guessed value. Same-date entries without complete times use Epic's
source order, with an explicit timing-unverified note on the printed endpoints.

## Import behavior

Paste the complete SmartPhrase or complete G and/or X sections. G replaces the
whole G laboratory snapshot, so retain all other G results that you still need.
Omitting X preserves the previous diet. An included empty, PN-only, or label-only
X clears the diet summary, without touching medications or T feeds. An X failure
skips only X and hides the previous automatic diet from print until it is checked
or successfully reimported. The existing shared error log records only allowlisted
technical diagnostics, not the diet source text.

Saved handoffs migrate from schema 21 to 22 with diet initialized to null. All
other fields, settings, reset generation, timestamps and encryption key stay the
same. Previously saved lactate rows use the new display immediately. Installing
does not clear handoffs. After saving with this version, do not downgrade.

## Limits

The app copies documented results and orders. It cannot determine whether Epic's
order list is current, resolve missing collection times, or infer feeding safety.
Review the source and any warnings. This update has not been tested on your live
Streamlit deployment or authenticated private GitHub connection.
