"""Recheck the shared patient-list generation before releasing a lazy download.

Only reads shared storage. Worker closures use captured values and never
access Streamlit session state. Unrelated saves may change the archive SHA
without invalidating a prepared download. Selected rooms are checked by both
identity and full saved-record fingerprint, so a same-patient edit also blocks
an old snapshot. List resets and new SmartPhrases still invalidate old packets.
"""
from __future__ import annotations

import time
import hashlib
import json


_CHANGED = "The patient list changed. Reload the patient list and prepare a new download."
_UNVERIFIED = "The current patient list could not be verified. Reload the patient list and prepare a new download."


def saved_room_version(sheet) -> str:
    """Detect same-ID edits too, including two saves within the same second."""
    value = json.dumps(sheet, sort_keys=True, ensure_ascii=False,
                       separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def guard_download(generate, store, generation, *, cancelled=None, expires_at=None,
                   expected_rooms=None, expected_versions=None):
    """Return a worker-safe generator guarded by the captured reset generation.

    ``expires_at`` uses the same monotonic deadline as existing downloads.
    ``store.load()`` follows GitHubVault's ``(vault, sha)`` return contract.
    """
    expected_rooms = dict(expected_rooms) if expected_rooms is not None else None
    expected_versions = dict(expected_versions) if expected_versions is not None else None

    def check_local():
        if cancelled is not None and cancelled.is_set():
            raise ValueError("This download was cleared. Reload the patient list and prepare a new download.")
        if expires_at is not None and time.monotonic() >= expires_at:
            raise ValueError("The session expired. Sign in and prepare a new download.")

    def check_current():
        check_local()
        if store is None:
            return
        try:
            fresh, _ = store.load()
            current_generation = fresh["reset_generation"]
            if not isinstance(current_generation, str):
                raise ValueError
            checking_rooms = expected_rooms is not None or expected_versions is not None
            current_rooms = fresh.get("rooms") if checking_rooms else None
            if checking_rooms and not isinstance(current_rooms, dict):
                raise ValueError
            room_changed = False
            for room, expected_id in (expected_rooms or {}).items():
                current = current_rooms.get(room)
                if current is not None and (not isinstance(current, dict) or not isinstance(current.get("id"), str)):
                    raise ValueError
                current_id = current["id"] if current is not None else None
                room_changed = room_changed or current_id != expected_id
            for room, expected_version in (expected_versions or {}).items():
                room_changed = room_changed or saved_room_version(current_rooms.get(room)) != expected_version
        except Exception:
            raise ValueError(_UNVERIFIED) from None
        # Cancellation or expiry can occur during a slow shared-storage read.
        check_local()
        if current_generation != generation or room_changed:
            if cancelled is not None:
                cancelled.set()
            raise ValueError(_CHANGED)

    def checked_generate():
        check_current()
        result = generate()
        check_current()
        return result

    return checked_generate
