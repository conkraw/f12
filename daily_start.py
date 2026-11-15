"""Build a blank handoff list at any time, without changing reusable settings.

The caller must save the candidate before discarding local drafts. Each
intentional start gets a new generation, including repeat starts on the same day.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid

from models import validate_vault


START_MARKER = "patient_list_started_at"


def start_daily_list(vault: dict, now: datetime | None = None) -> dict:
    """Clear every saved handoff, regardless of its age or the last list start.

    Keep the existing module and start marker for archive compatibility. The
    marker records the action time only and never limits when a list can start.
    """
    validate_vault(vault)
    when = datetime.now(timezone.utc) if now is None else now
    if not isinstance(when, datetime) or when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("The patient-list clock must include a timezone.")
    try:
        stamp = when.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        raise ValueError("The patient-list clock is outside the supported date range.") from None
    candidate = deepcopy(vault)
    candidate["rooms"] = {}
    candidate["settings"][START_MARKER] = stamp
    candidate["reset_generation"] = uuid.uuid4().hex
    validate_vault(candidate)
    return candidate
