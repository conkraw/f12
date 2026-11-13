# PICU Handoff v6.66: executed test report

Prepared November 13, 2026 from the supplied PICU665.zip source package.

## Final full regression result

Command: python -m pytest -q

5407 passed, 14 subtests passed in 154.93 seconds.

A targeted run covering mapping sync, the new diagnostics, new medication
groups, montelukast, chemotherapy and bupivacaine also passed:

306 passed, 14 subtests passed in 1.92 seconds.

## Additional transport-level validation

The real MappingRepository/GitHubVault request path was exercised against
three independent synthetic in-memory GitHub services with a shared test key.
All three scenarios passed:

| Scenario | Archive writes to apps 1, 2, 3 | Expected result |
| --- | --- | --- |
| Successful reviewed merge | 1, 1, 1 | All destinations updated and verified. |
| Backup access denied in app 2 | 0, 0, 0 | No mapping writes start. Failed backup operation identified. |
| Concurrent-write refusal in app 2 | 1, 0, 0 | Earlier update retained, later writes stopped, no forced overwrite. |

Each scenario confirmed that every destination retained its own patient-record
collection. Decrypted mapping backups contained no patient-record content.
Remote error-body sentinel text was excluded from results.
Reproduce with python validation/check_mapping_sync_transport.py.

## Diagnostic coverage

Failure injection covers HTTP 401, 403, 404, 429, redirects and server errors,
rate-limit and SSO headers, timeouts and connection failures, public/archived
repositories, missing branches and archives, unexpected response formats,
base64 errors, oversized archives, malformed keys, incorrect keys/ciphertext,
invalid JSON, incompatible numeric and malformed schema values, invalid
mapping families, and complete-archive validation failures.

Tests verify the failed step, diagnostic code and available HTTP status.
Repository checks use GET requests only and do not make backups or saves.
A failure in one repository does not hide results from others. Admin expiry
stops subsequent repository checks. A stale merge preview cannot be reused
after a failed comparison. Read-only checks do not create a merge preview.
Configuration errors identify the numbered entry and field without echoing its
value. Unexpected errors do not echo their message or clinical content.

UI callback/render tests use a Streamlit widget stub. They cover successful
comparison, detailed failures, read-only checks, conflict review, approval,
preview expiry, report output and authorization. Report content is checked
for synthetic token/patient sentinels. Real browser interaction was not tested.

## Medication coverage

Lactobacillus is placed under FEN / GI > Probiotic.
Desmopressin and DDAVP are placed under Neurologic > ADH Analog.
Tests cover generic/formulation names, case variation, supported source-label
cleanup, multiple desmopressin routes, boundary-safe nonmatches, single output
placement, hidden orders, explicit category overrides, Admin mapping choices,
older catalogs, encrypted round trips and unchanged medication source fields.
Existing montelukast, chemotherapy and bupivacaine behavior remains covered.

## Category-capacity fixture updates

The first regression run found three historical capacity assertions based on
three backfilled built-ins. The new release adds two more reserved built-ins.
The historical fixtures were corrected to omit those new categories when
constructing a pre-update catalog and to expect 255 total slots after backfill.
Their rejection tests for an additional custom category remain in place.
The original 250 slots are preserved. No production capacity safeguard was
removed to make the tests pass.

## Packaging and unchanged components

All Python sources and included TOML files are parsed during packaging.
Archive CRC and the SHA-256 file manifest are checked before delivery.
models.py, security.py and requirements.txt are byte-identical to PICU665.zip.
The archive schema stays at 34, with the same encrypted archive path and key.
No real deployment Secrets or patient archive is packaged. Runtime caches,
pytest caches and local temporary logs are excluded.

## Verification limits

No live GitHub repository was read or changed. This package has not been
deployed to the user's apps, and the original production sync failure has not
been reproduced with the user's credentials or archives. The new diagnostics
are intended to identify that failure when run in the deployed app.

Streamlit was unavailable in this execution environment. Installing it was
blocked by network name-resolution failure, so no real Streamlit browser or
Community Cloud session was tested. UI tests use a widget stub. GitHub tests
use mocked responses and synthetic encrypted archives. These checks are not a
security audit or a determination of regulatory compliance.

Install v6.66 in all three apps, retain the existing web-based Secrets and key,
then run Admin > Mapping Sync > Check connections (read only). Review the
repository-specific result before attempting another approved merge.
