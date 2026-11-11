"""Pure daily-list planning using confirmed save times and the Eastern date.

No storage writes or session changes occur here. The caller must bind a preview
to its archive version and commit the candidate before clearing local drafts.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
import uuid

from models import validate_vault
from save_status import saved_instant, saved_time_text


EASTERN = ZoneInfo("America/New_York")
START_MARKER = "patient_list_started_at"
MORNING_START = time(5, 0)
MORNING_END = time(8, 30)


def _clock(now: datetime | None) -> tuple[datetime, datetime]:
    value = datetime.now(timezone.utc) if now is None else now
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("The patient-list clock must include a timezone.")
    try:
        return value.astimezone(timezone.utc), value.astimezone(EASTERN)
    except (ValueError, OverflowError):
        raise ValueError("The patient-list clock is outside the supported date range.") from None


def _eastern(instant: datetime | None) -> datetime | None:
    if instant is None:
        return None
    try:
        return instant.astimezone(EASTERN)
    except (ValueError, OverflowError):
        return None


def _started_on(vault: dict, eastern_now: datetime) -> bool:
    marker = _eastern(saved_instant(vault["settings"].get(START_MARKER)))
    return marker is not None and marker.date() == eastern_now.date()


def started_today(vault: dict, now: datetime | None = None) -> bool:
    """Whether the shared marker belongs to today's Eastern calendar date."""
    validate_vault(vault)
    _, eastern_now = _clock(now)
    return _started_on(vault, eastern_now)


def daily_reset_plan(vault: dict, now: datetime | None = None) -> dict:
    """Return reviewable removals and retained rooms without changing the vault.

    Selection uses updated_at only. Remove earlier Eastern dates and today's
    inclusive 05:00:00 through 08:30:00 window. Retain unknown/future save times,
    today's pre-05:00 saves, and today's later saves. After the first daily
    start, every subsequent plan for that Eastern date is a no-op.

    The as_of value is an aware UTC ISO timestamp. Pass its parsed datetime to
    start_daily_list to keep a confirmed preview's clock fixed.
    """
    validate_vault(vault)
    utc_now, eastern_now = _clock(now)
    already_started = _started_on(vault, eastern_now)
    plan = {"date": eastern_now.date().isoformat(), "as_of": utc_now.isoformat(),
            "already_started": already_started,
            "started_at": vault["settings"].get(START_MARKER, ""),
            "remove": [], "keep": []}
    for room in sorted(vault["rooms"]):
        raw_stamp = vault["rooms"][room].get("updated_at")
        instant = saved_instant(raw_stamp)
        local_stamp = _eastern(instant)
        remove = False
        if already_started:
            reason = "Today's list already started"
        elif instant is None or local_stamp is None:
            reason = "Save time unavailable"
        elif instant > utc_now:
            reason = "Future save time"
        elif local_stamp.date() < eastern_now.date():
            remove, reason = True, "Saved before today"
        elif MORNING_START <= local_stamp.time() <= MORNING_END:
            remove, reason = True, "Saved today from 5:00 AM through 8:30 AM"
        elif local_stamp.time() < MORNING_START:
            reason = "Saved today before 5:00 AM"
        else:
            reason = "Saved today after 8:30 AM"
        metadata = {"room": room, "last_saved": saved_time_text(raw_stamp),
                    "saved_at": instant.isoformat() if instant is not None else "",
                    "reason": reason}
        plan["remove" if remove else "keep"].append(metadata)
    return plan


def start_daily_list(vault: dict, now: datetime | None = None) -> dict:
    """Build an atomic candidate, preserving every unselected record and setting.

    The marker and generation are part of the same candidate as deletions.
    Callers must not store either separately. A first start is recorded even
    when no rooms qualify, protecting later morning entries from a repeat start.
    """
    plan = daily_reset_plan(vault, now)
    candidate = deepcopy(vault)
    if plan["already_started"]:
        return candidate
    for row in plan["remove"]:
        del candidate["rooms"][row["room"]]
    candidate["settings"][START_MARKER] = plan["as_of"]
    candidate["reset_generation"] = uuid.uuid4().hex
    validate_vault(candidate)
    return candidate
