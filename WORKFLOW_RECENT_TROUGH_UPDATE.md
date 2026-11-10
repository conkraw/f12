# Version 6.47: short workflow and recent vancomycin troughs

Base: the supplied complete PICU646.zip. The archive schema remains 31.
No new dependencies. No live deployment or shared archive was changed.

## Vancomycin trough

VANCOTROUGH and its existing aliases now use the same rolling 24-hour display
window as theophylline and CK. The latest eligible numeric result appears once
under Infectious Disease > Drug Levels. Old results are kept in the editor and
saved data but do not print. If no eligible result exists, the trough line and
otherwise-empty Drug Levels heading are omitted. Actual timestamps use the
current Eastern clock, including a UTC-based 24-hour cutoff. Future results are
excluded. Date-only rows retain the existing overlap policy: today and the
previous day can qualify without inventing a collection time. No timing caveat
is added to the handoff. A dated result is not proof of an exact collection hour.
Regenerate the PDF to reevaluate the display window.

## Instructions

Short instructions appear directly at the top of Handoff, before room selection.
They use the supplied Epic author Streamlit and SmartPhrase PICUHANDOFFSMARTPHRASE.
The separate Instructions / SmartPhrase workspace has been removed. Existing
sessions that were on that page return to Handoff without discarding drafts.
The publication date remains visible. Published reusable source is still
available in a small SmartPhrase source expander when present.

Admin retains its separate password and the editable instructions/source fields.
The old bundled long guide is displayed as the new short workflow without writing
to shared storage or changing the publication date. Administrator-authored custom
instructions are retained. The Admin editor can publish updated instructions.
Saving instructions here does not install a SmartPhrase in Epic.

## Delete all handoff data

As of 6.51, open the Delete all handoff data expander on Handoff and press
Delete all handoff data. Any signed-in user can do this without an Admin password. The Admin reset
is also labelled Delete all handoff data. This operation clears every saved
patient record in the current shared archive and the initiating session's
patient drafts, including notes, labs, medications, airway records and generated
preview state. Custom rooms are deleted. Preset rooms remain available and blank.

Medication/category mappings, visibility rules, settings, passwords, public BMI
reference data, the reusable SmartPhrase and publication, and technical error
logs are preserved. Technical error logs do not store patient handoffs. Deletion
is committed atomically. Failed or conflicting writes retain the open work and
report failure. Other teammates must reload the saved archive. The reset
identifier and version check stop older sessions from silently saving the
deleted census back. Pending download generators from the cleared session are
revoked. Clearing through Handoff does not grant or extend Admin access.

This clears the current working archive, not earlier storage revisions, external
backups, downloaded files, printed copies or other users' already-displayed
screens. It is not a physical purge of storage history. No live data was deleted
while preparing this update.

## Empty groups

Bowel Regimen, DVT Prophylaxis and GI Prophylaxis labels stay bold even with None.
The same heading treatment is applied consistently to other empty medication
groups. The word None stays normal weight. Existing safeguards are unchanged:
hidden/excluded medications or a failed medication import do not establish None.

## Install

Upload this folder's contents into the existing application code folder,
replacing matching files, with app.py at the root. Keep Secrets, both passwords,
the encryption key, categories, mappings, BMI reference data and shared archive.
Do not rerun setup generators. Restart and refresh. No re-pasting is required.

Sidebar: Version 6.47 | Short workflow, recent troughs and delete all
