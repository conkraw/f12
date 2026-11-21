# PICU Handoff 6.97

The FEN/GI Intravenous Fluids display is more compact:

- The automatic Intravenous, Continuous line is removed from each fluid entry.
- One blank line separates consecutive IV fluid orders.

Each entry still shows its formulation, rate, timestamp and any maintenance comparison. The route and frequency remain stored for classification and editing. The change applies to the FEN/GI preview, text output and PDF.

## Install from 6.96

Extract PICU697.zip and open PICU_Handoff_v6_97_Compact_IV_Fluids.

Replace these four files beside the app.py that Streamlit runs:

- app.py
- error_store.py
- infusions.py
- iv_fluids.py

Reboot Streamlit once and confirm Version 6.97.

If updating from an earlier version, use the complete package contents. Keep your existing Streamlit Secrets and encryption key.

## Verification

199 existing targeted checks passed. A synthetic handoff with two fluid orders was checked in text, HTML and PDF. The rendered PDF shows the blank line between orders and no automatic route/frequency footer.

See examples/compact_iv_fluids_preview.pdf for the updated print example and TEST_REPORT.md for verification details. Prior release notes are retained in the V696 files.

This package is ready to install and has not been deployed to the live application.
