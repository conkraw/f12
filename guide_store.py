"""Encrypted reusable guide kept separate from room handoffs and credentials."""
from __future__ import annotations
import base64
import json
from cryptography.fernet import Fernet, InvalidToken
from github_store import GitHubVault, StorageError, ConflictError
from user_guide import default_guide, validate_guide

GUIDE_PATH = "encrypted-data/user-guide.enc"
MAX_TOKEN = 720000


class GuideStore:
    def __init__(self, vault: GitHubVault):
        self.vault = vault

    def load(self) -> tuple[dict, str | None]:
        self.vault._check_repo()
        response = self.vault._request("GET", "/contents/" + GUIDE_PATH,
                                      params={"ref": self.vault.config.branch})
        if response.status_code == 404:
            return default_guide(), None
        if response.status_code != 200:
            raise StorageError("The shared guide could not be loaded. Handoff records were not changed.")
        data = self.vault._json(response)
        try:
            if data.get("type") != "file" or data.get("encoding") != "base64" or not isinstance(data.get("sha"), str) or not data["sha"]:
                raise ValueError
            encoded = data["content"]
            if not isinstance(encoded, str) or len(encoded) > MAX_TOKEN * 2:
                raise ValueError
            token = base64.b64decode("".join(encoded.split()), validate=True)
            if len(token) > MAX_TOKEN:
                raise ValueError
            guide = json.loads(Fernet(self.vault.key.encode("ascii")).decrypt(token))
            validate_guide(guide)
        except (ValueError, TypeError, KeyError, UnicodeError, InvalidToken):
            raise StorageError("The shared guide could not be decrypted or validated. Keep the existing encryption key. Nothing was overwritten.") from None
        return guide, data["sha"]

    def save(self, guide: dict, expected_sha: str | None) -> str:
        validate_guide(guide)
        self.vault._check_repo()
        token = Fernet(self.vault.key.encode("ascii")).encrypt(
            json.dumps(guide, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if len(token) > MAX_TOKEN:
            raise StorageError("The guide is too large. Nothing was saved.")
        body = {"message": "Update encrypted user guide", "branch": self.vault.config.branch,
                "content": base64.b64encode(token).decode("ascii")}
        if expected_sha:
            body["sha"] = expected_sha
        response = self.vault._request("PUT", "/contents/" + GUIDE_PATH, json=body)
        if response.status_code in (409, 422):
            raise ConflictError("The shared guide changed or a repository rule blocked this save. Your draft is retained. Reload the published guide, compare, then save again.")
        if response.status_code not in (200, 201):
            raise StorageError("Shared storage did not confirm the guide save. Your draft is retained. Reload and compare before retrying.")
        result = self.vault._json(response)
        sha = result.get("content", {}).get("sha")
        if not isinstance(sha, str) or not sha:
            raise StorageError("Shared storage did not return a saved guide version. Reload and compare before retrying.")
        return sha
