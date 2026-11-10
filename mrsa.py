"""Display the newest MRSADNA or MRSANPADM screening result in demographics.

Keep source wording and collection date intact. Negative and pending results
are displayed as recorded, rather than interpreted as positive infection.
The laboratory rows remain the sole stored source, so existing archives need
no migration and successful G-block replacements clear an absent screen.
"""
from __future__ import annotations

from datetime import datetime

from labs import canonical, MRSA_COMPONENTS
from lab_windows import clock, eligible_time, ordered


def mrsa_screen_text(sheet: dict, as_of: datetime | None = None) -> str:
    """Compare both codes by lab date/time, independent of code or paste order."""
    if "g" in sheet.get("import_warnings", {}):
        return ""
    now = clock(as_of)
    rows = [row for row in sheet.get("labs", {}).get("rows", [])
            if row.get("include") and canonical(row.get("component", "")) in MRSA_COMPONENTS
            and eligible_time(row, now)]
    results = ordered(rows)
    if not results:
        return ""
    latest = results[0]
    return "MRSA Screen: " + latest["value"] + " [" + latest["date"] + "]"
