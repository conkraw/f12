"""Read-only save status for the room editor and print preparation screens.

Only the confirmed, loaded archive's ``updated_at`` is a saved timestamp.
Draft timestamps, creation times, import dates and print times are not used.
No storage writes, clinical parsing or clock-based guessed times occur here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Mapping, Any

from print_time import eastern_print_time

_UNSET = object()


def saved_instant(value: Any) -> datetime | None:
    """Read an offset-aware ISO timestamp without assuming a missing timezone."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        instant = datetime.fromisoformat(value.strip())
        if instant.tzinfo is None or instant.utcoffset() is None:
            return None
        return instant.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def saved_time_text(value: Any) -> str:
    instant = saved_instant(value)
    if instant is None:
        return "Save time unavailable"
    try:
        return eastern_print_time(instant)
    except (ValueError, OverflowError):
        return "Save time unavailable"


@dataclass(frozen=True)
class RoomSaveStatus:
    room: str
    last_saved: str
    status: str
    unsaved: bool
    session_only: bool
    different_handoff: bool = False

    @property
    def caption(self) -> str:
        label = "Last saved in this session only" if self.session_only else "Last saved to shared storage"
        return label + ": " + self.last_saved


def room_save_status(
    room: str,
    saved: Mapping | None,
    draft: Mapping | None = None,
    *,
    session_only: bool = False,
    base_sheet: Any = _UNSET,
) -> RoomSaveStatus:
    """Show the current handoff's save, never an old occupant's timestamp.

    The optional base snapshot identifies a conflict already observed after an
    archive reload. This function does not fetch changes from other sessions.
    """
    different = bool(saved is not None and draft is not None and saved.get("id") != draft.get("id"))
    unsaved = draft is not None and draft != saved
    if saved is None or different:
        last_saved = "Not saved yet"
        status = "New handoff - not saved" if draft is not None else "No saved handoff"
        if different:
            status = "New handoff - previous saved sheet is not replaced yet"
    else:
        last_saved = saved_time_text(saved.get("updated_at"))
        status = "Unsaved changes" if unsaved else ("Saved in this session only" if session_only else "Saved")
    if unsaved and base_sheet is not _UNSET and base_sheet != saved:
        status = "Saved record changed - reload and compare before saving"
    return RoomSaveStatus(room, last_saved, status, unsaved, session_only, different)


def latest_saved_time(rooms: Mapping[str, Mapping]) -> str | None:
    """Newest confirmed loaded room-save time, not an Admin/archive write time."""
    instants = [saved_instant(sheet.get("updated_at")) for sheet in rooms.values()]
    valid = [instant for instant in instants if instant is not None]
    return eastern_print_time(max(valid)) if valid else None


def most_recent_save_caption(rooms: Mapping[str, Mapping], *, session_only: bool = False) -> str:
    stamp = latest_saved_time(rooms)
    if stamp is None:
        return "Most recent handoff save: " + ("Time unavailable" if rooms else "No handoffs saved yet")
    if session_only:
        return "Most recent session-only handoff save: " + stamp
    return "Most recent handoff save in loaded archive: " + stamp


def save_status_table(statuses: list[RoomSaveStatus], *, session_only: bool = False) -> str:
    """Small, escaped HTML table. No data-frame/PyArrow dependency is needed."""
    heading = "Last session save (Eastern)" if session_only else "Last saved (Eastern)"
    header_style = "text-align:left;padding:7px 10px;border-bottom:1px solid #999;font-weight:600;"
    cell_style = "text-align:left;padding:7px 10px;border-bottom:1px solid #ddd;vertical-align:top;"
    header = "".join('<th scope="col" style="' + header_style + '">' + escape(label) + '</th>'
                     for label in ("Room", heading, "Status"))
    rows = []
    for item in statuses:
        row = '<th scope="row" style="' + cell_style + 'font-weight:600;">' + escape(item.room) + '</th>'
        row += '<td style="' + cell_style + '">' + escape(item.last_saved) + '</td>'
        status_style = cell_style + ("font-weight:600;" if item.unsaved else "")
        row += '<td style="' + status_style + '">' + escape(item.status) + '</td>'
        rows.append('<tr>' + row + '</tr>')
    return ('<div style="overflow-x:auto;margin:6px 0 12px;">'
            '<table aria-label="Handoff save status" style="border-collapse:collapse;width:100%;font-size:0.92rem;">'
            '<thead><tr>' + header + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')


def handoff_save_caption(sheet: Mapping, status: RoomSaveStatus | None = None) -> str:
    """Export-only save label, never calculated from the printing/import time.

    The UI supplies confirmed archive metadata, including unsaved/new-patient
    and session-only state. Standalone exports use the sheet's stored saved
    timestamp. No new storage fields or patient content are introduced.
    """
    if status is not None:
        if status.room != sheet.get("room"):
            raise ValueError("Save status does not match the handoff room.")
        label = "Last session save: " if status.session_only else "Last saved: "
        text = label + status.last_saved
        if status.unsaved:
            text += " | Unsaved changes"
        return text
    value = sheet.get("updated_at")
    return "Last saved: " + (saved_time_text(value) if value else "Not saved yet")
