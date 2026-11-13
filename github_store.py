"""Private-repository encrypted vault with optimistic concurrency control.

Only fixed filenames and generic commit messages leave the app unencrypted.
The encryption key, room list, and clinical content are not used in URLs/commits.
"""
from __future__ import annotations
from dataclasses import dataclass
import base64
import re
from urllib.parse import quote, urlparse
import requests
from security import open_vault, seal_vault
from models import new_vault


class StorageError(RuntimeError):
    """Static message plus optional safe transport metadata, never response bodies."""
    def __init__(self, message: str, *, status_code=None, diagnostic_code=""):
        super().__init__(message)
        self.status_code = status_code if type(status_code) is int else None
        self.diagnostic_code = diagnostic_code


class ConflictError(StorageError):
    pass


@dataclass(frozen=True)
class GitHubConfig:
    token: str
    repository: str
    branch: str = "main"
    api_base: str = "https://api.github.com"
    path: str = "encrypted-data/handoff-v1.enc"
    api_version: str = "2022-11-28"

    def validate(self) -> None:
        if not self.token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise StorageError("Set the storage token and repository in deployment secrets.")
        url = urlparse(self.api_base)
        if url.scheme != "https" or not url.netloc or url.query or url.fragment or url.username:
            raise StorageError("Use an HTTPS storage API address without credentials or query parameters.")
        if not self.branch or not re.fullmatch(r"[A-Za-z0-9_./-]+", self.branch) or ".." in self.branch:
            raise StorageError("The storage branch setting is invalid.")
        if self.path != "encrypted-data/handoff-v1.enc":
            raise StorageError("Use the fixed, nonclinical archive path.")


class GitHubVault:
    def __init__(self, config: GitHubConfig, key: str, session=None):
        config.validate()
        self.config, self.key = config, key
        self.http = session or requests.Session()
        self.url = config.api_base.rstrip("/") + "/repos/" + config.repository
        self.headers = {"Accept": "application/vnd.github+json", "Authorization": "Bearer " + config.token,
                        "X-GitHub-Api-Version": config.api_version}

    def _request(self, method: str, endpoint: str, **kwargs):
        try:
            response = self.http.request(method, self.url + endpoint, headers=self.headers,
                                         timeout=(10, 30), allow_redirects=False, **kwargs)
        except requests.Timeout:
            raise StorageError("Shared storage timed out. Reload and compare before retrying.", diagnostic_code="TIMEOUT") from None
        except requests.RequestException:
            raise StorageError("Shared storage could not be reached. A save may have completed before the connection ended. Reload and compare before retrying.", diagnostic_code="NETWORK_ERROR") from None
        if response.status_code in (401, 403):
            headers = getattr(response, "headers", {}) or {}
            code = "TOKEN_REJECTED" if response.status_code == 401 else "ACCESS_FORBIDDEN"
            if response.status_code == 403 and (headers.get("X-RateLimit-Remaining", headers.get("x-ratelimit-remaining")) == "0"
                                               or headers.get("Retry-After", headers.get("retry-after"))):
                code = "RATE_LIMIT"
            elif response.status_code == 403 and headers.get("X-GitHub-SSO", headers.get("x-github-sso", "")).startswith("required"):
                code = "SSO_REQUIRED"
            raise StorageError("Shared storage rejected access. Check the token permissions, organization approval, and rate limits.",
                               status_code=response.status_code, diagnostic_code=code)
        if 300 <= response.status_code < 400:
            raise StorageError("Shared storage redirected the request. Check the repository/API address. No redirect was followed.", status_code=response.status_code, diagnostic_code="REDIRECT_BLOCKED")
        return response

    @staticmethod
    def _json(response):
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except ValueError:
            raise StorageError("Shared storage returned an unexpected response. Nothing was overwritten.") from None

    def _check_repo(self) -> None:
        response = self._request("GET", "")
        if response.status_code != 200:
            raise StorageError("The repository was not found or is not accessible.")
        data = self._json(response)
        if data.get("private") is not True:
            raise StorageError("Storage is blocked because the repository is not private.")
        if data.get("archived") is True:
            raise StorageError("The repository is archived. Use an active private repository.")
        branch = self._request("GET", "/branches/" + quote(self.config.branch, safe=""))
        if branch.status_code != 200:
            raise StorageError("The storage branch is missing or inaccessible. Initialize the private repository with a README first.")

    def _contents_path(self) -> str:
        return "/contents/" + self.config.path

    def load(self) -> tuple[dict, str | None]:
        self._check_repo()
        response = self._request("GET", self._contents_path(), params={"ref": self.config.branch})
        if response.status_code == 404:
            return new_vault(), None
        if response.status_code != 200:
            raise StorageError("The encrypted archive could not be loaded.")
        data = self._json(response)
        if data.get("type") != "file" or data.get("encoding") != "base64" or not data.get("sha"):
            raise StorageError("The archive response is invalid or too large. Nothing was overwritten.")
        try:
            content = base64.b64decode("".join(data["content"].split()), validate=True)
        except (ValueError, KeyError, TypeError):
            raise StorageError("The archive encoding is invalid. Nothing was overwritten.") from None
        return open_vault(content, self.key), data["sha"]

    def save(self, vault: dict, expected_sha: str | None) -> str:
        self._check_repo()
        encrypted = seal_vault(vault, self.key)
        payload = {"message": "Update encrypted handoff archive", "branch": self.config.branch,
                   "content": base64.b64encode(encrypted).decode("ascii")}
        if expected_sha:
            payload["sha"] = expected_sha
        response = self._request("PUT", self._contents_path(), json=payload)
        if response.status_code in (409, 422):
            raise ConflictError("The save was refused. Another session may have changed the archive, or a repository rule blocked the write. Keep your draft and reload the saved archive before retrying.")
        if response.status_code not in (200, 201):
            raise StorageError("Shared storage did not confirm the save. Reload and compare before retrying.")
        data = self._json(response)
        new_sha = data.get("content", {}).get("sha")
        if not new_sha:
            raise StorageError("Shared storage did not return a saved version. Reload before retrying.")
        return new_sha
