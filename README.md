# PICU Handoff 6.92

Ventilator modes now show their date and time on the same line as the mode name. Each mode keeps its own settings, with a line containing three hyphens between mode blocks.

## Display

Synthetic example:

    Mode: PRVC-IMV (11/20/26 20:00)
    Set RR: 21
    Set TV: 180 mL
    Set PEEP: 6 cm H2O
    ---
    Mode: PS-CPAP (11/20/26 17:00)
    Set PEEP: 9 cm H2O
    Pressure Support: 8 cm H2O

The newest confirmed mode stays first. The extra Latest reported mode, Last reported mode and Other reported modes labels are removed, along with the routine sentence about settings without timestamps.

The date and time belong to the mode entry. An unavailable date is left out. Existing review notes for ambiguous source data and missing settings remain available.

This layout is used by the handoff text, HTML and PDF. A Home Vent device line remains separate from its dated Mode line.

## Install from 6.91

Extract PICU692.zip and open PICU_Handoff_v6_92_Compact_Vent_Modes.

Replace these files beside the app.py that Streamlit runs:

- app.py
- ventilation.py
- error_store.py

Reboot Streamlit and confirm Version 6.92 in the sidebar. Open the handoff again and generate a fresh print or download.

Existing handoffs that already contain mode-history dates use the new layout when rendered again. Re-importing those handoffs is not needed for this display change.

If you are updating from an earlier version, copy the complete package contents into the existing app folder. Keep your existing Streamlit Secrets and encryption key.

## Verification

278 selected regression tests passed. The checks cover mode histories, separate mode settings, all export formats, existing ventilator formatting and the respiratory import check.

The two synthetic handoffs in examples/vent_mode_history_preview.pdf were regenerated and visually inspected. Each fits on one landscape page.

The parser, shared archive schema and dependencies are unchanged. Only ventilation.py formatting and the version labels in app.py and error_store.py changed at runtime.

See TEST_REPORT.md for details. The previous release notes are retained in the V691 files.

Ready to install. This package has not been deployed to the live application.
