# PICU Handoff 6.93

This version adds automatic recovery when the ventilator mode-history import fails.

## Normal operation

The app continues to put the latest confirmed mode first, followed by the other modes and their own settings. Dates stay beside each mode name and three hyphens separate mode blocks.

## If mode history fails

The app retries using the original single-mode approach. It reads the first reported mode and its corresponding settings from the same new SmartPhrase, leaving out All Vent Modes.

A successful fallback shows this note in Alerts and in the handoff:

    Mode history unavailable. Showing first reported settings from this paste. Latest mode unconfirmed.

The note is saved with the handoff and survives reopening, text/HTML/PDF export and encrypted save/reload. A fallback has no inferred timestamp and does not claim that the first mode is the latest.

The fallback cannot recover a missing or unusable original settings block. Conflicting original fields, an unknown or noninvasive original mode, an explicit ventilator Off status, or an incompatible noninvasive delivery label still prevent an invasive fallback. Unavailable settings are not filled from another mode or from another handoff.

Whole-room replacement continues to use only the new paste. The fallback does not restore the previous patient's information or manual notes, and other rooms remain unchanged.

## Runtime availability

The app still checks the loaded history importer with a synthetic example. If that check fails, it checks the independent first-settings importer before allowing work to continue.

If only the fallback is available, the sidebar says:

    Respiratory parser: first reported settings only

If both checks fail, the existing incomplete-update message appears before the archive is opened or a handoff is replaced.

## Install from 6.92

Extract PICU693.zip and open PICU_Handoff_v6_93_Vent_Fallback. Replace all six files beside the app.py that Streamlit runs:

- app.py
- ventilation.py
- noninvasive.py
- importing.py
- workspace_ui.py
- error_store.py

Reboot Streamlit and confirm Version 6.93 in the sidebar. The fallback applies automatically to new imports. It does not rerun earlier imports by itself.

If you are updating from an earlier version, copy the complete package contents into the existing app folder. Keep your existing Streamlit Secrets and encryption key.

## Verification

700 selected regression tests passed. They cover deliberately broken history parsing, the fallback path, mode-specific settings, saved warnings, normal parsing, patient replacement, callbacks and imports.

All five supplied complete source examples imported respiratory support normally without fallback. Each also passed a forced fallback using its original settings.

The synthetic normal and fallback examples in examples/vent_fallback_preview.pdf were rendered and visually inspected. Each fits on one landscape page. Uploaded source text and patient-derived output were not added to the package.

The archive schema and dependencies are unchanged. See TEST_REPORT.md for details. Previous release notes are retained in the V692 files.

Ready to install. This package has not been deployed to your live application.
