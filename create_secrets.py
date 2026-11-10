"""Create deployment secrets using the Python standard library only.

Run locally, never in a public notebook. Does not need Streamlit or a new Python.
Does not print the password, token, or encryption key. Does not overwrite keys.
"""
from __future__ import annotations
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets


def create_secrets_file() -> Path:
    target = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if target.exists():
        raise RuntimeError("A secrets file already exists. Keep its encryption key. Do not replace it to reset a password.")
    password = getpass.getpass("Create your APP password (at least 12 characters): ")
    if len(password) < 12 or len(password) > 1024:
        raise ValueError("Use 12 to 1024 characters.")
    if password != getpass.getpass("Type it again: "):
        raise ValueError("Passwords do not match. Nothing was written.")
    repository = input("Private DATA repository, owner/name (blank for session-only test): ").strip()
    token = getpass.getpass("Fine-grained GitHub token (blank for session-only test): ") if repository else ""
    if repository and not token:
        raise ValueError("A repository was entered without its token. Nothing was written.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
    password_hash = "$".join(["pbkdf2_sha256", "600000", salt.hex(), digest.hex()])
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    # JSON string quoting is also valid for these TOML basic strings.
    text = '\n'.join([
        "# PRIVATE: do not upload this file to GitHub or send it in chat.", "[app]",
        "password_hash = " + json.dumps(password_hash), "encryption_key = " + json.dumps(key),
        "github_enabled = " + ("true" if repository else "false"),
        "clinical_use_approved = false", "idle_minutes = 15", "", "[github]",
        "repository = " + json.dumps(repository), "token = " + json.dumps(token),
        'branch = "main"', 'api_base = "https://api.github.com"', 'api_version = "2022-11-28"', "",
    ])
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(text)
    print("Created .streamlit/secrets.toml next to the app. Open it locally and copy its contents into deployment Secrets.")
    print("Never upload that file to GitHub. Keep a secure backup of the encryption key and token.")
    return target


if __name__ == "__main__":
    create_secrets_file()
