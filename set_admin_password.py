"""Print ONE Admin password-hash setting. Never creates/replaces other secrets.

Run on your own computer or in a private local notebook. Standard library only.
Paste the returned line inside the existing [app] section of deployment Secrets.
"""
from __future__ import annotations
import getpass
import hashlib
import secrets


def admin_password_line(password: str, confirmation: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError("Choose an Admin password of 12 to 1024 characters, different from the app password.")
    if password != confirmation:
        raise ValueError("Passwords do not match. No settings were changed.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600000)
    encoded = "$".join(("pbkdf2_sha256", "600000", salt.hex(), digest.hex()))
    return 'admin_password_hash = "' + encoded + '"'


def generate_admin_password_line() -> None:
    password = getpass.getpass("New ADMIN password (at least 12 characters, different from app password): ")
    confirmation = getpass.getpass("Repeat the ADMIN password: ")
    line = admin_password_line(password, confirmation)
    password = confirmation = None
    print("Paste this one line inside your EXISTING [app] section in deployment Secrets:")
    print(line)
    print("Keep password_hash, encryption_key, GitHub token and every other setting unchanged.")
    print("No files were written and no encryption key was generated. Do not share this output publicly.")


if __name__ == "__main__":
    generate_admin_password_line()
