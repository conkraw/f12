"""Source-faithful AED laboratory selection for Neuro and the lower lab area.

Only explicit phenobarbital and total phenytoin aliases are recognized. Free
phenytoin and other assays are not merged with these results. The stored G
rows, values, flags, dates and units are never changed by display routing.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

from labs import canonical, date_parts


COMPONENTS = ("PHENOBARB", "PHENYTOIN")
LABELS = {"PHENOBARB": "Phenobarbital", "PHENYTOIN": "Phenytoin"}
LAB_PANEL = "AED Drug Levels (last checked)"
_ALIASES = {
    "PHENOBARB": "PHENOBARB",
    "PHENOBARBITAL": "PHENOBARB",
    "PHENOBARBITAL LEVEL": "PHENOBARB",
    "PHENOBARBITAL, SERUM": "PHENOBARB",
    "PHENOBARBITAL (SERUM)": "PHENOBARB",
    "PHENYTOIN": "PHENYTOIN",
    "PHENYTOIN LEVEL": "PHENYTOIN",
    "PHENYTOIN TOTAL": "PHENYTOIN",
    "PHENYTOIN, TOTAL": "PHENYTOIN",
    "TOTAL PHENYTOIN": "PHENYTOIN",
    "PHENYTOIN TOTAL LEVEL": "PHENYTOIN",
    "PHENYTOIN, SERUM": "PHENYTOIN",
    "PHENYTOIN TOTAL, SERUM": "PHENYTOIN",
}
_NONRESULT = re.compile(
    r"\b(?:pending|cancelled|canceled|hemolyzed|haemolysed|hemolysed|"
    r"rejected|invalid|not performed|unable|error)\b", re.I)


def aed_component(component: str) -> str:
    """Return a supported assay key without broad substring matching."""
    if not isinstance(component, str):
        return ""
    return _ALIASES.get(canonical(component), "")


def _not_future(row: dict, now: datetime) -> bool:
    """Require a valid recorded date and no possible future collection time.

    A fall-back wall time has two possible instants. Both must be in the past.
    A nonexistent spring clock time has no valid instant and is excluded.
    A date-only row is kept as a date, without assigning a collection time.
    """
    from lab_windows import EASTERN

    try:
        local, timed = date_parts(row["date"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return False
    if not timed:
        return local.date() <= now.date()
    possible = set()
    for fold in (0, 1):
        instant = local.replace(tzinfo=EASTERN, fold=fold).astimezone(timezone.utc)
        if instant.astimezone(EASTERN).replace(tzinfo=None) == local:
            possible.add(instant)
    return bool(possible) and all(instant <= now.astimezone(timezone.utc)
                                  for instant in possible)


def aed_selection(sheet: dict, as_of: datetime | None = None) -> dict[str, dict[str, dict]]:
    """Choose one current or historical measured result per supported assay.

    Select the latest valid measured row first, then apply the time window.
    Recent means every possible collection instant fits the last 24 hours.
    Previous-day dates without a time therefore remain in Labs unless their
    earliest possible instant also qualifies. Current and historical results
    are mutually exclusive for each drug. No maximum age applies to the latest
    historical result supplied in the current source.

    The returned rows are original row references. Callers must treat them as
    read-only, or use aed_lab_rows for display copies.
    """
    from lab_windows import clock, measured, ordered, cardiac_recent_time

    now = clock(as_of)
    selected: dict[str, dict[str, dict]] = {"recent": {}, "older": {}}
    if "g" in sheet.get("import_warnings", {}):
        return selected
    candidates: dict[str, list[dict]] = {code: [] for code in COMPONENTS}
    for row in sheet.get("labs", {}).get("rows", []):
        if not isinstance(row, dict) or row.get("include") is not True:
            continue
        code = aed_component(row.get("component", ""))
        if not code or not isinstance(row.get("id"), str):
            continue
        value = row.get("value", "")
        if (not isinstance(value, str) or not measured(value)
                or _NONRESULT.search(value) or not _not_future(row, now)):
            continue
        candidates[code].append(row)
    for code in COMPONENTS:
        rows = ordered(candidates[code])
        if not rows:
            continue
        latest = rows[0]
        if cardiac_recent_time(latest, now):
            selected["recent"][code] = latest
        else:
            selected["older"][code] = latest
    return selected


def aed_summary(sheet: dict, as_of: datetime | None = None) -> str:
    """Neuro heading and latest qualifying levels, retaining source dates."""
    rows = aed_selection(sheet, as_of)["recent"]
    if not rows:
        return ""
    lines = ["AED Drug Levels:"]
    for code in COMPONENTS:
        if code in rows:
            row = rows[code]
            lines.append(LABELS[code] + ": " + row["value"] + " [" + row["date"] + "]")
    return "\n".join(lines)


def aed_lab_rows(sheet: dict, as_of: datetime | None = None) -> list[dict]:
    """Copy historical display rows into one named lab panel.

    Normalizing display component and panel does not change the saved source
    row. Values, flags, units and collection dates remain verbatim.
    """
    selected = aed_selection(sheet, as_of)["older"]
    return [dict(selected[code], component=code, panel=LAB_PANEL)
            for code in COMPONENTS if code in selected]


def aed_lab_summary(sheet: dict, as_of: datetime | None = None) -> str:
    """Optional plain-text fallback with an explicit last-checked label."""
    rows = aed_selection(sheet, as_of)["older"]
    if not rows:
        return ""
    lines = ["AED Drug Levels:"]
    for code in COMPONENTS:
        if code in rows:
            row = rows[code]
            lines.append(LABELS[code] + ": " + row["value"]
                         + " [Last checked: " + row["date"] + "]")
    return "\n".join(lines)


def aed_card_rows(data: dict) -> dict[str, dict]:
    """Group already routed lab data across recognized aliases for one card.

    Time and validity filtering belongs in aed_selection before aed_lab_rows
    reaches the lab renderer. This function only preserves existing ordering
    within the provided rows and does not mutate their component labels.
    """
    from lab_windows import ordered

    grouped: dict[str, list[dict]] = {code: [] for code in COMPONENTS}
    for row in data.get("rows", []):
        code = aed_component(row.get("component", ""))
        if code and row.get("include") is True:
            grouped[code].append(row)
    return {code: ordered(grouped[code])[0] for code in COMPONENTS if grouped[code]}
