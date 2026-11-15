# PICU Handoff 6.77

This package has not been deployed to your live app.

## Start an updated handoff

Choose START HERE: Create an Updated Handoff when preparing a new patient list
for rounds or evening handoff. This first button opens a warning. It does not
delete anything.

The warning states that ALL previous handoffs will be deleted from the current
list. All saved handoffs and this session's open drafts will be removed, leaving
a blank patient list.

Choose Move Forward and Delete Previous Handoffs to confirm and start the blank
list. You can then add patients for rounds or evening handoff.

If the saved list changes while the warning is open, confirmation reloads the
current list and shows the warning again without deleting anything. Review the
warning and click the confirmation button again to proceed.

## Add or print without clearing

Choose Add a Patient or Print Current List if you only want to add a patient or
print the existing list. This option appears on both the opening screen and the
warning screen. It keeps all current handoffs.

Both workflows are available at any time. There is no morning window or
once-per-day restriction. You can start another updated handoff when you log in
later the same day.

## Existing app behavior

Reusable settings, medication mappings, room choices, and custom room definitions
are preserved. The clinical parsers, nutrition display, 24-hour I/O, 7am/7pm
current shifts, and compact BM label retain their existing behavior.

Local drafts are cleared only after the shared save is confirmed. A retry checks
the saved list so it does not repeat a completed reset over newly added patients.

## Install

Extract the ZIP and replace the matching files in your existing app-code
repository. From version 6.76, replace app.py. If you are updating from version
6.75, replace both app.py and daily_start.py together.

For an earlier version, replace the complete application file set. You can also
use the complete file set for any of these updates.
Keep your existing Streamlit Secrets, encryption key, and separate encrypted
patient-data and mapping repositories. No new dependency is required.

Restart the app and confirm the sidebar reads:

Version 6.77 | Start here + confirmation

See UPDATE_FILES.txt for the file list and TEST_REPORT.md for verification.
