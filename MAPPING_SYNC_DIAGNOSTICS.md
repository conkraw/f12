# Mapping Sync diagnostics in v6.66

## Start here

Keep your current web-based Streamlit Secrets. Install the complete v6.66 app
files in the code repositories and restart the apps. In the app running sync,
open Admin, expand Mapping Sync and choose Check connections (read only).
Compare mappings also runs these checks before it creates a merge preview.

The summary identifies each configured app. Expand an Action needed panel to
see the failed step, code, HTTP status when available, and Next step.
The detailed table shows which earlier checks passed. Other repositories are
still checked after a failure, unless Admin authorization expires.

Copy diagnostic report and Download diagnostic report contain repository names,
branches, the fixed archive path, the token's configuration field name, and
safe diagnostic messages. They do not contain token values, encryption keys,
HTTP response bodies, medication names, patient records or raw exception text.
Review repository names before sharing the report outside your organization.
Unexpected application errors may include a safe exception type and a known
application filename/line number, not the exception value, source line or locals.

A short code and failed step are also written to deployment logs. The direct
Admin panel and downloadable report are the primary troubleshooting tools.

## What the checks do

The app uses GET requests only. It does not create an empty archive, make a
backup, save mappings, repair an archive or modify patient data during these
checks. The combined encrypted archive must be decrypted in server memory to
validate its structure and extract mapping settings. Neither the diagnostic
report nor the merge preview contains the patient-record collection.

A successful read proves only the read operations and archive validation that
were performed. It does not prove write permission, bypass branch protection,
check another app's deployed code version, or confirm institutional approval
for the storage arrangement. The schema result reports archive compatibility,
not the remote code version. No secret value or key fingerprint is displayed.

## Common results

| Code or step | Meaning and next action |
| --- | --- |
| CONFIG_INVALID | The exact Secrets field or numbered repository entry is shown. Use owner/repository, not a GitHub URL. Use [[mapping_sync.repositories]] for entries. |
| TOKEN_REJECTED / HTTP 401 | Check whether the selected token is expired, revoked or incorrect. The panel identifies which Secrets field supplies it without showing its value. |
| ACCESS_FORBIDDEN / HTTP 403 | Check token repository access, Contents permissions, organization approval and SSO. A rate limit can also cause 403. |
| RATE_LIMIT | GitHub rate-limited the request. Pause requests and retry after the limit resets. |
| SSO_REQUIRED | Authorize the token for the organization. |
| REPOSITORY_NOT_FOUND / HTTP 404 | The repository may be absent or hidden from the token. Check its exact name and private-repository access. A 404 does not distinguish these possibilities. |
| REPOSITORY_NOT_PRIVATE | The app blocks access before reading the patient archive when GitHub does not report a private repository. |
| REPOSITORY_ARCHIVED | Use the active private data repository or review its archived status. |
| BRANCH_NOT_FOUND | Check the actual data-repository branch. Do not assume its name is main. |
| ARCHIVE_NOT_FOUND | The branch was reachable, but encrypted-data/handoff-v1.enc was not found or readable. Check that this is the DATA repository and that the token has Contents read permission. |
| KEY_FORMAT_INVALID | The current app's key is not valid Fernet formatting. Restore the original key. Do not generate a new one. |
| DECRYPTION_FAILED | The current app's key cannot authenticate/decrypt this file. Possible causes include a different key, a wrong file or damaged ciphertext. The check does not claim to distinguish those causes. |
| ARCHIVE_JSON_INVALID | Decryption worked, but the content is not valid JSON for this archive. Do not replace it with a blank file. |
| ARCHIVE_SCHEMA_MISMATCH | The panel shows the saved and expected numeric schema. Updating code does not necessarily resave an older archive. Open and save it through its own updated app. Sync does not migrate patient records. |
| MAPPING_SETTINGS_INVALID | The failing mapping family is shown, such as FEN / GI groups or category assignments. Review that family in its own updated app. No rule contents are printed in diagnostics. |
| ARCHIVE_VALIDATION_FAILED | Mapping checks passed, but the full saved structure did not. Review compatibility in the app that owns this archive. No patient record is discarded or repaired by sync. |
| TIMEOUT / NETWORK_ERROR / SERVER_ERROR | Retry the read-only check. After a save failure, reload and compare first because a write may already have completed. |
| REDIRECT_BLOCKED | Check whether the repository was moved or renamed. Credentials are not forwarded through redirects. |
| UNEXPECTED_ERROR | A safe error type and application location may be included. Use the report to troubleshoot without exporting raw exceptions or clinical data. |

## During an approved merge

The result table includes Phase, Step, Code, HTTP and Next step in addition to
App, Status, Backup and Detail. This distinguishes preflight, backup, write and
post-save verification failures. Existing review is still required before any
merge, and all required encrypted mapping-only backups precede mapping writes.

There is no atomic transaction across repositories. Earlier repositories may
have updated before a later one fails. A timeout can leave a write unconfirmed.
The app stops rather than blindly retrying or rolling back whole archives.
Compare again before retrying, and use each result row to see what completed.

Patient records remain those of each destination. The merge changes only the
approved mapping fields in the latest destination archive and uses its current
SHA. It does not copy patient recall data between repositories.

## References checked for the diagnostic wording

GitHub REST troubleshooting, including private-resource 404 responses and rate limits:
https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api

GitHub repository contents API, including read/write permission requirements:
https://docs.github.com/en/rest/repos/contents

Streamlit Community Cloud app settings and the web Secrets editor:
https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/app-settings

These references inform troubleshooting guidance. They do not verify the
permissions or contents of your own repositories. No live repositories were
accessed while preparing this release.
