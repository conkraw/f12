"""Allowlisted, patient-free diagnostic messages for Admin Mapping Sync.

Never display response bodies, exception text, headers, tokens or decrypted data.
Only fixed codes/messages, validated HTTP statuses, and numeric schema versions
may enter a report. Repository metadata is supplied separately by the Admin UI.
"""
from __future__ import annotations

from github_store import StorageError
from pathlib import Path


class SyncError(ValueError):
    """Mapping synchronization error with a static, patient-free message."""


MESSAGES = {
    "TOKEN_REJECTED": ("GitHub rejected this repository's token.", "Check that the selected token is valid, not expired or revoked, and belongs to an account with access. Keep your encryption key unchanged."),
    "ACCESS_FORBIDDEN": ("GitHub denied this request.", "Check the token's selected repositories, Contents permission, organization approval and SSO. A rate limit can also cause HTTP 403."),
    "SSO_REQUIRED": ("GitHub requires organization SSO authorization for this token.", "Authorize the token for the organization, then run the read-only check again."),
    "RATE_LIMIT": ("GitHub rate-limited this request.", "Pause requests and retry after the GitHub limit resets. Do not change your encryption key."),
    "TIMEOUT": ("The GitHub request timed out.", "Retry the read-only check. After a save timeout, reload and compare first because the write may have completed."),
    "NETWORK_ERROR": ("The app could not complete the GitHub connection.", "Check service availability and retry the read-only check. Do not regenerate the encryption key."),
    "REDIRECT_BLOCKED": ("GitHub redirected this request. No redirect was followed.", "Check whether the repository was renamed or moved and correct its repository setting."),
    "REPOSITORY_NOT_FOUND": ("GitHub returned 404 for the repository. It may be missing or hidden from this token.", "Check owner/repository in Streamlit Secrets, that it is the data repository, and that this token can access this private repository. A 404 does not prove the repository is absent."),
    "REPOSITORY_NOT_PRIVATE": ("The repository is not reported as private. Archive access is blocked.", "Select the correct private data repository. Do not place patient archives in a public repository."),
    "REPOSITORY_ARCHIVED": ("This repository is archived and cannot be synchronized.", "Use the active private data repository or review its archived status in GitHub."),
    "BRANCH_NOT_FOUND": ("The configured branch could not be found or read.", "Check this data repository's branch name in Streamlit Secrets. Do not assume it is main."),
    "ARCHIVE_NOT_FOUND": ("The configured branch was reachable, but the encrypted archive was not found or readable at the fixed path.", "Check encrypted-data/handoff-v1.enc in this data repository and branch. Confirm the token has Contents read permission. No empty archive will be created by this check."),
    "HTTP_ERROR": ("GitHub returned an unexpected HTTP status.", "Review the status and failed step below, then retry the read-only check. Do not delete or replace the archive."),
    "SERVER_ERROR": ("GitHub reported a server-side error.", "Retry the read-only check after the service recovers. After a save failure, compare before retrying."),
    "RESPONSE_INVALID": ("GitHub returned an unexpected response format.", "Check the API/repository configuration and retry. Response bodies are intentionally not displayed."),
    "ARCHIVE_RESPONSE_INVALID": ("The archive response is not a base64-encoded file with a saved version.", "Check that the fixed path points to the encrypted handoff file, not a folder or a different file. Oversized files are also refused."),
    "ARCHIVE_ENCODING_INVALID": ("The encrypted file's base64 encoding could not be read.", "Verify the original encrypted archive in GitHub. Do not replace it with a blank archive."),
    "ARCHIVE_TOO_LARGE": ("The encrypted archive exceeds this app's 800,000-byte safety limit.", "Review the archive size in its own app. Do not delete patient recall records to troubleshoot this check."),
    "KEY_FORMAT_INVALID": ("This app's encryption key is not a valid Fernet key.", "Restore the existing original key in Streamlit Secrets. Do not generate a replacement key."),
    "DECRYPTION_FAILED": ("The archive could not be authenticated and decrypted with this app's key.", "Compare the existing keys privately across the apps. A different key, damaged ciphertext or the wrong archive can cause this. Never paste the key into a report."),
    "ARCHIVE_JSON_INVALID": ("Decryption succeeded, but the contents are not valid archive JSON.", "Verify that this is the handoff archive rather than a different encrypted file. Do not overwrite it."),
    "ARCHIVE_SCHEMA_MISMATCH": ("The archive uses a different schema.", "Update the app that owns this repository, then open and save its own archive there before comparing again. Updating code alone does not necessarily save an older archive in the current schema. Sync will not migrate patient data."),
    "MAPPING_SETTINGS_INVALID": ("The mapping settings failed validation at the indicated step.", "Review this mapping family in the repository's own app. Check category definitions, rule limits and supported choices. No medication names or patient data are included in this report."),
    "ARCHIVE_VALIDATION_FAILED": ("The saved archive failed validation after its mapping checks.", "Open the archive in its own updated app and review compatibility. Sync will not repair, migrate or discard patient records."),
    "CONFIG_INVALID": ("The Mapping Sync configuration is invalid.", "Correct the indicated entry or field in the web-based Streamlit Secrets editor, keeping existing credentials and encryption key."),
    "ADMIN_EXPIRED": ("Admin authorization expired. This check was stopped.", "Unlock Admin and run the checks again."),
    "MAPPING_CHANGED": ("Mappings changed after the comparison.", "Compare again and review the new merge before saving. No automatic overwrite is attempted."),
    "SAVE_CONFLICT": ("GitHub refused a write because of a concurrent change or repository rule.", "Reload and compare. Also check branch protection and Contents write permission. Do not force an overwrite."),
    "BACKUP_NOT_CONFIRMED": ("The encrypted mapping-only backup was not confirmed.", "Check Contents write permission and branch protection. No mapping writes begin until all required backups are confirmed."),
    "VERIFY_MISMATCH": ("A save was acknowledged, but the current mappings differ from the reviewed merge.", "Reload and compare. Another session may have changed the mappings. Do not automatically overwrite or roll back the archive."),
    "SAVE_NOT_CONFIRMED": ("The archive save was not confirmed.", "Reload and compare before retrying. The write may have completed. No automatic rollback is performed."),
    "UNEXPECTED_ERROR": ("An unexpected application error occurred at this step.", "Use this diagnostic code and failed step to troubleshoot. Raw exception text is withheld because it may contain credentials or clinical data."),
}


class DiagnosticError(SyncError, StorageError):
    """Structured exception. Compatible with the existing SyncError/StorageError handlers."""
    def __init__(self, code: str, step: str, status_code=None, *, detail=None, action=None):
        # Callers supply only hardcoded steps and messages, not user/archive text.
        self.code = code if code in MESSAGES else "UNEXPECTED_ERROR"
        self.step = step
        self.status_code = status_code if type(status_code) is int and 100 <= status_code <= 599 else None
        self.detail, self.action = MESSAGES[self.code]
        if detail is not None:
            self.detail = detail
        if action is not None:
            self.action = action
        ValueError.__init__(self, self.detail + " " + self.action)

    def row(self) -> dict:
        return {"Step": self.step, "Result": "Failed", "Code": self.code,
                "HTTP": str(self.status_code) if self.status_code is not None else "",
                "Detail": self.detail, "Next step": self.action}


def passed(checks, step: str, detail: str, status_code=None) -> None:
    if checks is not None:
        checks.append({"Step": step, "Result": "Passed", "Code": "OK",
                       "HTTP": str(status_code) if status_code else "",
                       "Detail": detail, "Next step": ""})


def failed(checks, error: DiagnosticError):
    if checks is not None:
        checks.append(error.row())
    raise error from None


def safe_error(exc: Exception, step: str) -> DiagnosticError:
    """Never return str(exc), repr(exc), HTTP bodies or headers."""
    if isinstance(exc, DiagnosticError):
        return exc
    if isinstance(exc, StorageError):
        code = getattr(exc, "diagnostic_code", "")
        if code in MESSAGES:
            return DiagnosticError(code, step, getattr(exc, "status_code", None))
        return DiagnosticError("UNEXPECTED_ERROR", step, getattr(exc, "status_code", None))
    allowed_types = {"KeyError", "TypeError", "ValueError", "IndexError", "AttributeError",
                     "RuntimeError", "NameError", "ImportError", "ModuleNotFoundError", "RecursionError"}
    kind = type(exc).__name__ if type(exc).__name__ in allowed_types else "Exception"
    location = ""
    trace = exc.__traceback__
    allowed_files = {"mapping_sync.py", "mapping_sync_ui.py", "sync_diagnostics.py", "github_store.py",
                     "categories.py", "models.py", "medications.py", "medication_groups.py", "fen_gi.py"}
    while trace is not None:
        name = Path(trace.tb_frame.f_code.co_filename).name
        if name in allowed_files:
            location = name + ":" + str(trace.tb_lineno)
        trace = trace.tb_next
    detail = MESSAGES["UNEXPECTED_ERROR"][0] + " Exception type: " + kind + "."
    if location:
        detail += " App location: " + location + "."
    return DiagnosticError("UNEXPECTED_ERROR", step, detail=detail)


def http_error(status: int, step: str, not_found: str = "HTTP_ERROR") -> DiagnosticError:
    code = {401: "TOKEN_REJECTED", 403: "ACCESS_FORBIDDEN", 404: not_found,
            409: "SAVE_CONFLICT", 422: "SAVE_CONFLICT", 429: "RATE_LIMIT"}.get(status, "HTTP_ERROR")
    if 500 <= status <= 599:
        code = "SERVER_ERROR"
    elif 300 <= status < 400:
        code = "REDIRECT_BLOCKED"
    return DiagnosticError(code, step, status)
