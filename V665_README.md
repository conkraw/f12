# PICU Handoff 6.65

Built from the latest available PICU664.zip (v6.64) source package.

## Mapping Sync in Admin

Compare medication mappings from your three private GitHub data repositories.
Review conflicts, preview the combined rules, then explicitly approve saving to
all listed apps. The current app's repository is included automatically.
Encrypted mapping-only backups are created before mapping updates begin.

Mappings and patients currently share one encrypted archive. Sync reads that
archive in memory but changes only the mapping allowlist in each destination.
Patient records are never copied between repositories. Each destination keeps
its own patient data, room list, daily-reset markers and diagnosis settings.
Hidden-medication preferences remain local unless you explicitly include them.

Install this update on all three apps. Append the two other data repositories
to existing Streamlit Secrets using MAPPING_SYNC_SECRETS.example.toml. Keep your
existing encryption key and all existing Secrets. Only the app used to run
synchronization needs the extra repository configuration.

Read MAPPING_SYNC_SETUP.md before the first merge. Synchronization is manual,
not continuous. A failed run may have updated only some repositories. Check the
per-repository outcomes and compare again rather than overwriting or reverting
whole archives. Deleted mappings are not automatically removed from other apps.

## Montelukast

New automatic display group:

Respiratory > Leukotriene receptor antagonist

Montelukast and Singulair names are recognized. Existing explicit custom group
and category assignments remain available, and hidden orders stay hidden.
Doses, routes, frequencies and original source text are unchanged.

## Installation

Upload the contents of this folder to each app-code repository, with app.py
at the root. Do not replace or delete the encrypted archive in a data repository.
Restart the apps and confirm Version 6.65 in the sidebar. Keep your current app
password, Admin password, encryption key and ordinary GitHub storage settings.
Do not regenerate Secrets when updating an existing deployment.

Application files changed from v6.64: app.py, categories.py and medication_groups.py.
New application files: mapping_sync.py and mapping_sync_ui.py.
No dependency or archive-schema change. Full application source is included.

Previous features remain included, such as chemotherapy grouping, medication
label cleanup, patient-list startup, MRSA, epidural placement, save-before-print,
and recent METHB/O2SATV results in Cardiovascular. Historical v6.64 documentation
is retained with a V664_ filename prefix.

See TEST_REPORT.md for test results and verification limits. This ZIP has not
been deployed, and no live GitHub repositories were changed during preparation.
