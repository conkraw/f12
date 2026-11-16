from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def observed(sheet, value="-1", at=None):
    instant = at or datetime.now(timezone.utc)
    sheet["sbs_observations"] = {"readings": [{"value": value,
        "recorded_at": instant.astimezone(ZoneInfo("America/New_York")).strftime("%m/%d/%Y %H:%M"), "include": True}], "notes": []}
    return sheet
