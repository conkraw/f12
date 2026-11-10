"""Display the latest supplied MRSADNA screening result in demographics.

Keep source wording and collection date intact. Negative and pending results
are displayed as recorded, rather than interpreted as positive infection.
The laboratory rows remain the sole stored source, so existing archives need
no migration and successful G-block replacements clear an absent screen.
"""
from __future__ import annotations

from datetime import datetime

from labs import canonical, ordered_components
from lab_windows import clock, eligible_time


def mrsa_screen_text(sheet: dict, as_of: datetime | None = None) -> str:
    """Latest included MRSADNA row, with the usual lab date/order convention."""
    if "g" in sheet.get("import_warnings", {}):
        return ""
    now = clock(as_of)
    rows = [row for row in sheet.get("labs", {}).get("rows", [])
            if row.get("include") and canonical(row.get("component", "")) == "MRSADNA"
            and eligible_time(row, now)]
    ordered = ordered_components({"rows": rows, "notes": []}).get("MRSADNA", [])
    if not ordered:
        return ""
    latest = ordered[0]
    return "MRSA Screen: " + latest["value"] + " [" + latest["date"] + "]"
