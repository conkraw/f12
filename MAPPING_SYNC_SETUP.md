# PICU Handoff 6.66: Mapping Sync

## Install the application update

Upload the contents of this application folder to each of your three app-code
repositories. Keep app.py at the repository root. Do not upload the application
files into the private repositories that hold your encrypted patient archives.
Restart each Streamlit app and confirm the sidebar says Version 6.66.

Keep your existing app password, Admin password, encryption key, GitHub storage
settings, saved archive, custom categories and patient recall data. Do not run
the original key-generation notebook again when installing an update.

Install v6.66 on all three apps before merging. In particular, older app versions
may not recognize the new Probiotic or ADH Analog medication-group values.
No archive-schema or dependency change is required for this release.

## New diagnostic checks

No new Secrets entries are needed when Mapping Sync is already configured.
Keep using the web-based Streamlit Secrets editor. There is no local secrets
file to create for your Community Cloud deployment.

Open Admin > Mapping Sync > Check connections (read only). Each app gets a
summary and detailed step results. Compare mappings runs the same checks.
A failed check never creates backups or writes to any repository. It reports
which repository and operation failed without displaying patient data or keys.
See MAPPING_SYNC_DIAGNOSTICS.md for codes and suggested corrections.

## Connect the other two data repositories

Start with the app you will use to run synchronization. In its existing Streamlit
Secrets, append the example from MAPPING_SYNC_SECRETS.example.toml. Replace the
two owner/repository placeholders with the private DATA repositories for the
other two apps. Your current app's data repository is included automatically.

Use the branch that actually holds encrypted-data/handoff-v1.enc. Do not point
sync at a repository that contains only the application's Python files.
Nothing is found by scanning a folder. Only that exact archive path is read.
A missing archive stops comparison rather than creating an empty archive.

The existing GitHub token is used unless you supply an optional mapping_sync.token
or a token inside a specific repository entry. A sync token needs access to the
selected private data repositories and Contents read/write permission. Tokens,
repository configuration and the encryption key remain in deployment Secrets.
Do not commit real tokens or keys in the example file or any code repository.

All sources use the current app's existing encryption key and API host. Incorrect
keys, inaccessible or public repositories, malformed archives and unsupported
archive schemas are rejected. An older schema must be updated through its own
app before comparison. Mapping Sync does not migrate patient records.

Only the app running synchronization needs the extra repository configuration.
Adding the other two repositories to each app also allows you to run sync from
any of them. Alternatively, the same configuration can list all three repositories
in every app. The current app's own entry is recognized and is not duplicated.

## Use Mapping Sync

Open Admin with your separate Admin password, then expand Mapping Sync.
Select Compare mappings. The app reads the saved mappings from the configured
repositories and displays counts, conflicting entries and the proposed union.

Choose a source value for each conflict. Nothing silently chooses the most
recent repository or the repository with the most mappings. Identical rules
are deduplicated. Missing rules are added. Independently created custom
categories with the same name and location are reconciled, including references
from their medication rules. A contradictory category name, parent or display
order requires review. Invalid combinations are blocked before writing.

The full proposed mapping list is available for inspection. Different matching
rules, such as a general prefix and an exact medication formulation, remain
separate. Potentially overlapping rules and mixed old/new mapping layers are
flagged separately and require acknowledgement. This is a conservative review,
not a proof that every possible medication-name overlap has been detected.
The app's existing category and matching-priority logic is unchanged.

Hidden-medication preferences stay local by default. Select the optional
checkbox before comparing only when you also intend to merge hide/show rules.

Confirm that the apps are updated and approve the merge. Select Save merged
mappings to all listed apps. Encrypted mapping-only backups are created in each
changed repository before any mapping updates start. After completion, use
Reload saved archive in the other apps before continuing their work.

This is manual synchronization, not a continuously shared master repository.
New changes remain local until you compare and merge again. Deletions do not
propagate: a rule deleted in one app can return if another app still has it.
Remove an unwanted rule from every source before running another merge.

## Exactly what is shared

The default allowlist consists of medication_categories,
medication_category_rules, medication_mappings, medication_infusions,
medication_gi_groups and medication_groups. medication_visibility is included
only when explicitly selected. No other settings are copied between apps.

Patient records, saved medication source rows and doses, notes, timestamps,
room lists, diagnosis preferences, reset-generation markers and daily-list
start markers remain those of each destination. Sync does not reapply mappings
to existing saved handoffs or save open patient drafts. New imports and normal
mapping actions continue to use the app's existing behavior.

## Combined archives and concurrency

In this app version, mappings and patients share one encrypted JSON archive.
The sync app necessarily decrypts each configured archive in server memory to
read its settings. It cannot access only the mappings at the GitHub-permission
level. Previews and backup files retain only allowlisted mapping settings.
Do not treat this feature as isolation from the other archives' patient data.
Use only deployments, credentials and repositories approved for your workflow.

Before saving, the destination archive is read again. Its own current patient
records are retained, and only the selected mapping settings are changed. The
write uses that archive's current GitHub SHA. A competing save is refused
rather than overwritten. Patient-only edits made before this final read are
retained. Changed mappings invalidate the comparison. No blind retry is made.

GitHub writes across repositories are not one transaction. If a later save
fails, earlier saves may already have succeeded. The status table distinguishes
verified updates, unsaved destinations and unconfirmed writes. A timeout can
leave the outcome uncertain. Reload and compare again before retrying.
Automatic rollback is intentionally not used because it could undo newer work.

## Backups and recovery

Backups are encrypted using the existing key and stored at:

encrypted-data/mapping-sync-backups/<random-identifier>.enc

They contain the original selected mapping lists, scope, archive SHA and backup
time. They do not contain the patient-record collection, passwords or tokens.
Their filenames and commit messages contain no medication or patient names.
The result table shows the backup path for each changed repository.

A mapping backup is NOT a replacement handoff archive. Do not overwrite
handoff-v1.enc with it. This release does not add a one-click restore control.
Recovery should restore only the backed-up mapping fields into the latest
current archive, under the same review and SHA guards. Do not revert a whole
patient archive just to undo a mapping change. Retain the original encryption
key because the backup cannot be decrypted without it.

## Montelukast

Montelukast and Singulair names receive the automatic display group:

Respiratory > Leukotriene receptor antagonist

The group is available in Admin and medication category choices. Older category
catalogs gain the built-in without losing custom definitions. Explicit custom
group/category choices and hidden-order preferences still take priority, as in
other ordinary automatic medication groups. A conflicting older explicit
montelukast assignment can be changed in Admin to the new category.
No dose, route, frequency, source order or clinical treatment is changed.

## Lactobacillus and desmopressin

Lactobacillus receives FEN / GI > Probiotic as an automatic display group.
Desmopressin and DDAVP receive Neurology (the existing Neurologic section) >
ADH Analog. The groups are available in Admin. Explicit existing category/group
choices are retained, as are hidden orders and source medication details.
No dose, indication or treatment change is inferred.

## Verification and limits

See TEST_REPORT.md for the exact executed tests and remaining limits.
This package has not been deployed to your apps and no live repository was read
or changed during its preparation. Repository names and access must be supplied
in your deployment Secrets before the first synchronization.
