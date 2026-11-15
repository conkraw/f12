# PICU Handoff 6.78

Every new SmartPhrase replaces the entire handoff for the selected room.
The app no longer imports new source text into an existing patient record.
This package has not been deployed to the live app.

## Room replacement

Select the correct room, paste the complete new SmartPhrase, and click
Replace room handoff. A successful import builds a blank record, adds only
information from that new phrase, and saves the whole replacement in one write.
It then clears the previous local draft and editor values.

The replacement clears all previous patient-specific information, including
omitted sections, medications, diagnoses, labs, vitals, nutrition, I/O, devices,
manual notes, difficult-airway details, and prior problem-review decisions.
This happens on every new import, including an update to the same patient.
Manual notes must be re-entered after importing when they are still needed.
Opening a room, printing a list, or editing a field without importing another
SmartPhrase does not trigger this replacement.

Other rooms, custom room definitions, reusable settings, and medication mappings
are preserved. Shared storage is updated immediately on successful import.
With shared storage disabled, replacement is saved only within that session.
Additional manual edits retain the existing Save, room-change autosave, and
Print all autosave workflow.

## Failed or incomplete imports

The app builds and validates the new record before replacing anything.
Empty, unsupported, repeated-patient, or entirely failed imports do not replace
the previous handoff. The app reports Handoff NOT replaced and keeps the pasted
text for correction. It must not be mistaken for an updated handoff.

When at least one section imports successfully but another fails, the replacement
contains only successfully parsed NEW information. Failed sections remain absent
and are flagged in Alerts and the printed import-review summary. No previous
patient values are used as a fallback. Review the complete source and output.

A save conflict or unconfirmed write does not claim success. The old local record
and pasted text are kept with an explicit warning. Reload the saved archive before
retrying because an unacknowledged write may have reached shared storage.

Previously prepared downloads in the current session are revoked on successful
replacement. Shared downloads also check selected room identities before and
after generation, rejecting a download when one of those rooms was replaced.
Already downloaded files, printed pages, and other open browser previews cannot
be recalled. Other users must reload to see the new handoff.

## Your two startup choices remain

START HERE: Create an Updated Handoff still opens the clear-all warning for a
new rounds or evening list. Only Move Forward and Delete Previous Handoffs
confirms the deletion. All rooms are cleared only through this deliberate reset.

Add a Patient or Print Current List preserves the list. Importing a new phrase
inside that workflow now replaces only the selected room, never merges it.
There is no time window or once-per-day restriction.

## Install

Extract PICU678.zip and replace the matching application-code files in the
existing app-code repository. The complete application file set is included.
From 6.77, the changed runtime modules are:

    app.py
    importing.py
    import_review.py
    census_guard.py
    user_guide.py
    workspace_ui.py

Replace all six together. For an earlier version, use the complete file set.
Keep Streamlit Secrets, the encryption key, and separate encrypted patient-data
and mapping repositories. No new dependency or archive schema is required.

Restart the app and verify:

    Version 6.78 | Replace, never merge

Use two fictional patient examples in the same room to verify the deployment
before clinical use. Give the first example a manual note and fields omitted
from the second. After importing the second, confirm the first example is gone
from the preview, saved handoff, reload, and Print all, while another room remains
unchanged. Check shared storage and the saved timestamp.

Existing saved handoffs are not retroactively corrected. Use START HERE once to
rebuild any list that might already contain mixed records. Replacement removes
old information from the active handoff, not from encrypted Git history or files
already downloaded or printed.

## Scope

The low-level section parsers and clinical calculations are unchanged. The app
now calls a new whole-room replacement entry point that never accepts the old
patient record. Existing 24-hour I/O, 7am/7pm current-shift, BM, nutrition, and
medication-classification rules are preserved.

See TEST_REPORT.md for test results and limitations. No live repository,
clinical patient record, or production storage was accessed for this update.
