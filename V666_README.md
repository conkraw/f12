# PICU Handoff 6.66

Complete application update built from the supplied PICU665.zip.

## Mapping Sync diagnostics

Admin > Mapping Sync now has a Check connections (read only) button.
Compare mappings runs the same checks before preparing a merge.
The panel identifies the app, repository, branch, failed step, diagnostic code,
HTTP status when available, and suggested action. A failure in one repository
does not hide the results for the others.

Checks distinguish Secrets configuration, repository access, private/active
status, branch access, archive path, encoding, encryption key format,
decryption, JSON format, archive schema, each mapping family and complete
archive validation. No raw errors, remote response bodies, keys, tokens,
medication names or patient content enter the diagnostic report. Repository
names and branches are included. The report can be copied or downloaded.

An approved synchronization also reports its failing phase and operation,
including backup, save and verification failures. Existing conflict review,
encrypted mapping-only backups, SHA guards and partial-save reporting remain.
A read-only check cannot prove that write access or branch rules permit a save.

## New automatic medication display groups

Lactobacillus > FEN / GI > Probiotic
Desmopressin and DDAVP > Neurology (existing Neurologic section) > ADH Analog

These are presentation defaults requested for this app. They do not infer an
indication, recommend treatment or change doses, routes or frequencies.
Existing explicit category/group choices and hide/show preferences are retained.
Both groups are selectable in Admin. An old explicit override may need to be
changed there. Older category catalogs gain the groups without losing custom
entries or rewriting saved patient records.

Montelukast > Respiratory > Leukotriene receptor antagonist remains included.

## Install

Replace the application files in each APP-CODE repository with the contents of
this folder. Keep app.py at the same deployed location. Do not upload this
package into the private DATA repositories containing patient archives.
Restart the apps and confirm Version 6.66 | Mapping Sync diagnostics.

Keep all existing web-based Streamlit Secrets, passwords, GitHub settings and
the original encryption key. No new Secrets fields are required for this update.
The existing mapping_sync configuration remains valid. Do not regenerate keys.
Update all three apps before merging mappings that use the new group values.

Then open Admin > Mapping Sync > Check connections (read only).
Open any Action needed panel and follow its Next step. Download diagnostic
report is available without using the Streamlit deployment logs.

See MAPPING_SYNC_DIAGNOSTICS.md for troubleshooting and MAPPING_SYNC_SETUP.md
for the merge workflow and storage safeguards. TEST_REPORT.md records the
executed tests and limits. No live GitHub repository was read or changed during
preparation, and this package has not been deployed to your apps.

Full source is included. There are no dependency or archive-schema changes.
