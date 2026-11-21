# PICU Handoff 6.94

Home is now the first button at the top of the left sidebar. It is available from Handoff, Print all, Admin and Import errors.

## What Home does

Home saves current handoff edits and any other changed open handoffs, then returns to the original starting screen. You stay signed in.

The starting screen offers the existing choices:

- START HERE: Create an Updated Handoff. This opens the existing confirmation before clearing the patient list.
- Add a Patient or Print Current List. This keeps the list and returns to Handoff.

Home itself keeps the current patients. The patient list is cleared only after choosing the fresh-list option and confirming the existing deletion message.

If saving fails, an editor value is invalid, or a saved room has changed, Home stays in the workspace with the edits available. It does not claim that all changes were saved.

Home does not prepare new PDFs, so returning to the starting screen does not wait for every open handoff to render for printing. Existing save and download safeguards remain in place.

## Returning to the same patient

Continue restores the selected room after Home. It also preserves pending SmartPhrase text already received by the app in session memory, without importing it or putting the raw paste into the saved archive. Text still held only in an unsubmitted browser form is not part of this saved-handoff guarantee.

A confirmed fresh list clears the previous room, drafts and pending resume state. Home cannot bring those cleared handoffs back.

## Install from 6.93

Extract PICU694.zip and open PICU_Handoff_v6_94_Home_Button.

Replace these two files beside the app.py that Streamlit runs:

- app.py
- error_store.py

Reboot Streamlit once to load the update and confirm Version 6.94. After installation, use Home whenever you need the starting screen. Users do not need to restart the website or log out to make another list.

If updating from an earlier version, use the complete package contents. Keep existing Streamlit Secrets and the encryption key.

## Verification

The real Streamlit AppTest flow passed 23 stages without exceptions. It verified Home placement, saving a pending note, remaining signed in, repeated Home-screen reruns, restoring the original room on Continue, and the existing confirmed clear-list workflow.

Automated callback and regression checks cover multi-room saving, conflicts, failed saves, invalid editor values, inline medication mappings and the existing startup/printing behavior. See TEST_REPORT.md for counts and details.

The archive schema and dependencies are unchanged. Ventilator history and its fallback behavior remain as delivered in 6.93.

Previous release notes are retained in the V693 files. This package is ready to install and has not been deployed to your live application.
