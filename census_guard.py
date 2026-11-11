"""Recheck the shared patient-list generation before releasing a lazy download.

Only reads shared storage. Worker closures use captured values and never
access Streamlit session state. A normal save may change the archive SHA
without invalidating a prepared download from the same patient list.
"""
from __future__ import annotations

import time


_CHANGED = "The patient list changed. Reload the patient list and prepare a new download."
_UNVERIFIED = "The current patient list could not be verified. Reload the patient list and prepare a new download."


def guard_download(generate, store, generation, *, cancelled=None, expires_at=None):
    """Return a worker-safe generator guarded by the captured reset generation.

    ``expires_at`` uses the same monotonic deadline as existing downloads.
    ``store.load()`` follows GitHubVault's ``(vault, sha)`` return contract.
    """
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
        except Exception:
            raise ValueError(_UNVERIFIED) from None
        # Cancellation or expiry can occur during a slow shared-storage read.
        check_local()
        if current_generation != generation:
            if cancelled is not None:
                cancelled.set()
            raise ValueError(_CHANGED)

    def checked_generate():
        check_current()
        result = generate()
        check_current()
        return result

    return checked_generate
