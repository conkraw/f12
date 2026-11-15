# PICU Handoff 6.76

Built from version 6.75. This package has not been deployed to your live app.

## Two choices after login

### Create New Handoff for Rounds/Signout

Clears all saved handoffs and this session's open drafts, then opens a blank
patient list. Add the patients you want for rounds or signout.

The screen states that all current handoffs will be cleared before you click.
The button applies immediately, without a separate review or confirmation screen.

### Print, Update, or Add to Current List

Keeps all current patients. Print the list, update existing handoffs, or add new
patients without starting over.

Both choices are available at any time. There is no morning window or
once-per-day restriction. Each new login presents these choices, so you can
start another blank list later the same day.

## Existing app behavior

Reusable settings, medication mappings, room choices, and custom room definitions
are preserved. The clinical parsers, nutrition display, 24-hour I/O, 7am/7pm
current shifts, and compact BM label remain as they were in version 6.75.

The new-list action clears local drafts only after the shared save succeeds.
If a save response is lost, retrying checks the saved list before proceeding so
patients added after a completed reset are kept.

## Install

If you are running version 6.75, extract the ZIP and replace both app.py and
daily_start.py in your existing app-code repository. Replace both files together.
You can also replace the complete application file set. Use the full set when
updating from an earlier version.

Keep your existing Streamlit Secrets, encryption key, and separate encrypted
patient-data and mapping repositories. No new dependency is required.

Restart the app and confirm the sidebar reads:

Version 6.76 | Clear start options

See UPDATE_FILES.txt for the file list and TEST_REPORT.md for verification.
