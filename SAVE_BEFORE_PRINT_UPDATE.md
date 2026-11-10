# Version 6.57: save before Print all

Built from the supplied PICU656.zip. Clinical parsing, calculations, medication
categories, airway-preservation choices, passwords and archive schema are unchanged.

## Autosave before Print all

Opening Print all captures the current editor values and saves changed open
handoffs before offering the PDF. It uses the same guarded save path as room
changes. Unchanged handoffs are not written again or given a newer timestamp.

A failed save, invalid editor value, unresolved difficult-airway update, or
save conflict blocks Print all and keeps the user's edits available. A direct
Print all page entry also checks saves before creating a download. Other changed
open drafts are saved before the packet is offered. If that later batch fails,
the current room may already be saved, but printing remains blocked.

Continue to click Create / update handoff after pasting a SmartPhrase. Merely
pasted, unapplied source text is not silently imported or saved. The difficult-
airway keep/delete question must be resolved or cancelled before printing.

## Last saved on every handoff

Each sheet now shows Last saved in the upper-left header, below Print prepared.
The time is the last successful save for that room's handoff, in Eastern time
with EST/EDT. It repeats on continuation pages. The separate printing time
continues to reflect PDF creation.

For an open, unsaved draft, the preview retains the prior confirmed save time
and says Unsaved changes. A new patient does not borrow the previous occupant's
save time. Missing timestamps are not replaced with the current time. Session-
only testing is labelled Last session save rather than a shared storage save.

The same information is included in the preview, single-room PDF, Print all,
and existing HTML/text export functions. No additional patient metadata is
persisted for this display. Download callbacks capture private status snapshots
and do not perform network writes from the download worker thread.

## BMI label

BMI: is bold. Its value remains regular weight. Existing BMI age restrictions
and percentile logic are unchanged.

## Install

Replace matching application files with this folder's contents. Keep app.py
at the root. Restart the app and refresh the browser. Preserve existing Secrets,
passwords, encryption key, mappings, categories, BMI reference data and archive.
Do not rerun setup generators. No new dependencies or schema change are needed.

From 6.56, the changed application modules are app.py, exports.py,
save_status.py and clinical_style.py. Existing saved handoffs do not require
re-pasting. Regenerate downloaded PDFs to see the new header and BMI formatting.

Tests use synthetic data and instrumented Streamlit callback simulations.
The live deployment and shared patient archive were not accessed or changed.
