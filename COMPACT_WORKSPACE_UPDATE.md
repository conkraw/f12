# Version 6.53: compact Handoff workspace

## Main screen

The main workflow is room selection, paste, Create / update handoff, then
Preview / print. The paste box is two lines tall (68 pixels), scrolls for long
input and retains the previous maximum input length. It stays visible above
every tab. Creating a handoff returns to Preview / print.

Room selection and Save handoff share one row. Age, sex, confirmed save time
and unsaved status share a compact caption. The default Epic instructions are
shorter. Administrator-authored instructions remain unchanged. The removed
SmartPhrase source panel and publication controls are not reintroduced.

The empty Respiratory support to RESP heading is gone from the opening view.
Respiratory support editing remains under Edit handoff > Respiratory support.
Room actions contains Clear pasted text, Load saved handoff, Start blank for
new patient, custom-room removal, the all-room save list and Delete all handoff
data. No new password or confirmation requirement is added.

## Alerts

Alerts follows Difficult airway. Routine import notices, skipped-section
details, technical-log status and the last action appear as escaped text
lines at 0.75 rem, normally 12 pixels. There are no large informational cards.
Import-review acknowledgement controls remain available in this tab.

A warning/error count appears in the compact status line when applicable.
Failed saves, complete import failures and known save conflicts keep one short
visible status. Their details are in Alerts. No error is treated as success,
no retained value is accepted automatically, and no save timestamp is invented.

Import summaries are remembered per handoff in session memory while switching
rooms. They do not enter the shared clinical archive. Existing durable import
flags and the technical error journal are unchanged. Logout/expiration clears
session state. A successful clear-all removes the new session-only UI records.

## Performance

Streamlit's native stateful tabs render only the selected panel. Hidden labs,
medication editors, problem editors and preview exports no longer all run on
each interaction. Pending edits are validated and captured before switching
panels. Drafts remain the source of truth when inactive widgets are removed.

PDF fitting no longer runs automatically during ordinary page loads, edits or
room selection. It still runs on every actual PDF download, using the existing
fitting algorithm and fresh download-time stamp. Print options > Check page
count performs an optional preflight. Page-target choices survive tab cleanup.

The nonclinical instruction publication refresh interval is five minutes,
instead of 30 seconds. This does not change clinical data retrieval, archive
save/reload, conflict checks, or laboratory/SBS time windows.

There is no process-wide patient-data cache, no cached clinical PDF reused
between patients or users, and no change to the clinical parsers or archive.

## Installation

From 6.52, changed runtime files are app.py, the new workspace_ui.py, and
requirements.txt. Upload all three, or the complete folder contents. This
release requires Streamlit >=1.55,<2 for stateful tabs. Rebuild/restart the
hosting environment so the requirement is installed, then refresh the browser.
No new library apart from the Streamlit minimum-version change is introduced.

Keep existing Secrets, both passwords, encryption key, categories, medication
mappings, BMI reference data and saved archive. Do not run setup generators.
No re-pasting is needed. Printing content and font fitting remain as in 6.52.

## Technical references

Native stateful tabs and conditional rendering:
https://docs.streamlit.io/1.55.0/develop/api-reference/layout/st.tabs

Collapsed-label text-area minimum height:
https://docs.streamlit.io/1.55.0/develop/api-reference/widgets/st.text_area

Widget state lifecycle:
https://docs.streamlit.io/develop/concepts/architecture/widget-behavior
