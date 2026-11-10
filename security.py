"""Password hashing and authenticated JSON encryption. No plaintext persistence."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import secrets
from cryptography.fernet import Fernet, InvalidToken
from models import ValidationError, validate_vault, upgrade_vault

ITERATIONS = 600_000


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError("Use a password of 12 to 1024 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "$".join(["pbkdf2_sha256", str(ITERATIONS), salt.hex(), digest.hex()])


def valid_password_hash(encoded: str) -> bool:
    try:
        kind, rounds, salt, digest = encoded.split("$")
        return (kind == "pbkdf2_sha256" and 600_000 <= int(rounds) <= 2_000_000
                and len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(digest)) == 32)
    except (ValueError, TypeError, AttributeError):
        return False


def verify_password(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or len(password) > 1024 or not valid_password_hash(encoded):
        return False
    _, rounds, salt, expected = encoded.split("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds))
    return hmac.compare_digest(digest, bytes.fromhex(expected))


def generate_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def seal_vault(vault: dict, key: str) -> bytes:
    validate_vault(vault)
    payload = json.dumps(vault, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    token = Fernet(key.encode("ascii")).encrypt(payload)
    if len(token) > 800_000:
        raise ValidationError("The encrypted archive is too large. Nothing was saved.")
    return token


def open_vault(token: bytes, key: str) -> dict:
    try:
        vault = json.loads(Fernet(key.encode("ascii")).decrypt(token).decode("utf-8"))
        return upgrade_vault(vault)
    except (InvalidToken, ValueError, TypeError, UnicodeError, KeyError):
        raise ValidationError("The archive could not be decrypted or validated. Check the original encryption key. Nothing was overwritten.") from None
