"""A shared, short-lived Admin and Utilities unlock. Not individual identity or MFA.

The username and password hashes come from deployment Secrets, never the guide/vault.
Every protected callback must check its grant again, not just hide a widget.
"""
from __future__ import annotations
import hashlib
import hmac
import time
from security import valid_password_hash, verify_password

IDLE_SECONDS = 15 * 60
MAX_SECONDS = 60 * 60
_GRANT_KEYS = ("admin_unlocked", "admin_grant_hash", "admin_login_at", "admin_last_activity")


def lock_admin(state) -> None:
    from note_utility import clear_note_draft
    clear_note_draft(state, all_values=True)
    for key in _GRANT_KEYS + ("admin_login_username", "admin_login_password"):
        state.pop(key, None)


def _configured_username(config: dict) -> str:
    # Existing deployments retain their password and use admin until configured.
    value = config.get("admin_username", "admin")
    return value.strip() if isinstance(value, str) else ""


def config_error(config: dict) -> str:
    admin = config.get("admin_password_hash", "")
    if not valid_password_hash(admin):
        return "Admin is locked until a separate admin_password_hash is added under [app] in deployment Secrets. Follow ADMIN_SETUP.txt. Routine handoffs remain available."
    if hmac.compare_digest(admin, str(config.get("password_hash", ""))):
        return "Use a different Admin password from the app password. Admin remains locked."
    if not _configured_username(config):
        return "Admin and Utilities are locked until admin_username under [app] in deployment Secrets contains a nonempty username. Follow ADMIN_SETUP.txt. Routine handoffs remain available."
    return ""


def _fingerprint(config: dict) -> str:
    # Invalidate the shared grant if its username or either password hash changes.
    credentials = (config.get("password_hash", ""), config.get("admin_password_hash", ""),
                   _configured_username(config))
    return hashlib.sha256("\0".join(credentials).encode()).hexdigest()


def app_session_valid(state, now: float) -> bool:
    return bool(state.get("authenticated") and
                0 <= now - state.get("last_activity", 0) < state.get("idle_seconds", 900) and
                0 <= now - state.get("login_at", 0) < 8 * 3600)


def admin_valid(state, config: dict, *, touch: bool = False, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    ok = (app_session_valid(state, now) and not config_error(config) and
          state.get("admin_unlocked") is True and
          hmac.compare_digest(str(state.get("admin_grant_hash", "")), _fingerprint(config)) and
          0 <= now - state.get("admin_last_activity", 0) < IDLE_SECONDS and
          0 <= now - state.get("admin_login_at", 0) < MAX_SECONDS)
    if not ok:
        lock_admin(state)
        return False
    if touch:
        state["admin_last_activity"] = now
    return True


def unlock_admin(state, config: dict, password: str, *, username: str = "",
                 now: float | None = None) -> bool:
    """Unlock both protected workspaces with an explicitly submitted credential pair."""
    now = time.monotonic() if now is None else now
    # Clear both widget values and any prior grant even on an early rejection.
    lock_admin(state)
    if not app_session_valid(state, now):
        return False
    problem = config_error(config)
    if problem:
        state["admin_login_error"] = problem
        return False
    if now < state.get("admin_retry_after", 0):
        state["admin_login_error"] = "Wait briefly before trying the Admin username and password again."
        return False
    supplied_username = username.strip() if isinstance(username, str) else ""
    username_matches = hmac.compare_digest(supplied_username.encode(), _configured_username(config).encode())
    password_matches = verify_password(password, config["admin_password_hash"])
    accepted = username_matches and password_matches
    same_as_app = accepted and verify_password(password, config.get("password_hash", ""))
    if accepted and not same_as_app:
        state.pop("admin_login_error", None)
        state.update(admin_unlocked=True, admin_grant_hash=_fingerprint(config),
                     admin_login_at=now, admin_last_activity=now, admin_attempts=0, admin_retry_after=0)
        return True
    attempts = min(state.get("admin_attempts", 0) + 1, 10)
    state.update(admin_attempts=attempts, admin_retry_after=now + min(30, 2 ** attempts),
                 admin_login_error=("Choose an Admin password different from the app password." if same_as_app else
                                    "Admin username or password not accepted. Wait briefly before trying again."))
    return False
