# PICU Handoff v6.65: executed test report

Prepared November 13, 2026 from the user's available PICU664.zip source.

## Results

The complete application regression suite passed:

    PYTHONPATH=.:tests python -m pytest -q --disable-warnings --maxfail=12
    5319 passed, 14 subtests passed in 151.15s

After a final Admin widget-state cleanup, all 50 tests dedicated to the new
mapping synchronization and montelukast features were rerun and passed:

    PYTHONPATH=.:tests python -m pytest -q tests/test_mapping_sync.py tests/test_mapping_sync_ui.py tests/test_montelukast.py --disable-warnings
    50 passed in 1.33s

The final cleanup invalidates stale Admin mapping widgets after synchronization.
It does not change stored patient data or patient draft widgets. The callback
test explicitly checks this behavior and checks that unsaved drafts are retained.

## New checks

The new tests cover unique-rule merging, identical-rule deduplication, explicit
conflict choices, normalization, custom-category ID reconciliation, category
references, input validation and optional hide/show preference synchronization.

Synthetic repositories test that each destination retains its own patient data,
even when the same room identifier is used in all three. Current patient-only
changes are preserved. Competing mapping changes abort the merge. Public
repositories, unsupported schemas, incorrect keys, unsafe paths, invalid
configuration, unreviewed plans and expired Admin approval are rejected.

Backup tests decrypt the generated mapping-only backup and verify its scope and
original mappings. Patient records and credentials are not included. A backup
failure prevents subsequent mapping writes. Partial saves and unconfirmed
outcomes are reported without a destructive cross-repository rollback.

UI tests use a Streamlit widget stub to exercise rendering, comparison, approval,
conflict changes, overlap acknowledgement, preview expiry and authorization.
No real browser session is represented by these tests.

Montelukast tests cover generic and Singulair names, boundary-safe matching,
Respiratory placement, the new Leukotriene receptor antagonist subcategory,
older saved category catalogs, hidden orders, explicit custom overrides and
unchanged source medication details.

## Existing test maintenance

Existing category-capacity tests were adjusted for one additional built-in group.
The original 250 category slots are preserved, with three backfilled built-ins
instead of two. No existing custom category is removed to make room.

Four stale tests failed in both the updated package and the untouched v6.64
baseline. They expected an older reset notice or old medication display prefixes
that v6.64 already removed. Only those assertions were corrected. The app's
existing reset logic, source-order preservation and cleaned display behavior
were not changed to satisfy those tests.

## Packaging checks

Every Python file in the final package was parsed successfully. The included TOML
examples and Streamlit configuration were parsed successfully. Archive CRC and
SHA-256 file-manifest checks passed. Python caches and temporary test outputs are
excluded. No actual deployment Secrets or encrypted patient archive is included.
The supplied examples and tests are synthetic development fixtures.

Only app.py, categories.py and medication_groups.py changed among the existing
application modules. mapping_sync.py and mapping_sync_ui.py are new. Existing
models.py, security.py, github_store.py, reset handling and dependency versions
remain unchanged. The archive schema remains version 34.

## Verification limits

No live GitHub repository was read or changed. The package has not been deployed
to the user's three applications. Tests use synthetic encrypted archives and
mocked GitHub responses, not real patient records or production credentials.
Streamlit was not available in this execution environment, so live browser
interaction and deployment compatibility still need to be checked in the user's
deployment. Existing PDF export tests ran, but this release does not claim a new
manual visual review of every PDF layout.

Install v6.65 in all three apps before synchronization. Configure approved private
data repositories and tokens in deployment Secrets, retain the existing shared
key, compare the mappings, review conflicts, then explicitly approve the merge.
The setup instructions are in MAPPING_SYNC_SETUP.md.
