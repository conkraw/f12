# PICU Handoff 6.95

Lumbar drain status now appears in Neuro directly below the last visible WAT-1 row, with six hyphens on a separate line.

Example layout when a WAT-1 score is supplied:

```text
WAT-1 total score (0-12): 2
------
Lumbar Drain: Clamped
```

The score above is illustrative. If the source has no WAT-1 value, the drain appears after CAPD in the same score area. The app does not add a WAT score.

## What appears

An explicitly named Lumbar Drain in either device block is routed to Neuro. Its actual reported status is shown, including Clamped, Open, or another supplied status. Missing or conflicting status displays UNK.

The lumbar drain is removed from the bottom device inventory to avoid a duplicate. Other drains, including scalp drains, keep their existing placement. A lumbar puncture or a surgical drain described only by a lumbar location does not establish a lumbar drain.

Identical records of the same lumbar drain in both device blocks appear once. Separate device identities retain their own status. A status or date is never copied from another device.

Include controls, removed-device markers and failed-section hiding also apply to lumbar drains. Older saved records categorized as Other are supported when their own label explicitly identifies a Lumbar Drain.

This display is included in the handoff preview, text export, PDF and Print all. Lumbar status can be edited in Devices / airway and neuro drains.

## Install from 6.94

Extract PICU695.zip and open PICU_Handoff_v6_95_Lumbar_Drain.

Replace these six files beside the app.py that Streamlit runs:

- app.py
- batching.py
- devices.py
- error_store.py
- import_review.py
- models.py

Reboot Streamlit once to load the update and confirm Version 6.95.

If updating from an earlier version, use the complete package contents. Keep existing Streamlit Secrets and the encryption key.

The package includes the Home button and the ventilator history fallback from the previous releases. No archive schema or dependency update is needed.

## Verification

718 selected automated checks passed, including 54 new lumbar drain cases. The supplied source was checked for its lumbar status, Neuro placement, absence of an inferred date and separation from the scalp drain. The new lumbar entry imports without a V-section warning.

The synthetic preview in examples/lumbar_drain_preview.pdf contains one example with WAT-1 and one without a WAT value. Each fits on one page. Both pages were rendered and visually checked.

See TEST_REPORT.md for the verification scope. Previous release notes are retained in the V694 files.

This package is ready to install and has not been deployed to the live application.
