"""Latest two source measurements for the Hematology Lysis Labs block.

The display follows the existing lactate rolling 24-hour window, including its
date-only overlap convention. It retains source values, flags and units and
does not calculate or interpret a lysis result. Stored laboratory rows remain
unchanged.
"""
from __future__ import annotations

from datetime import datetime
import re

from labs import canonical, date_parts


COMPONENTS = ("HGBFREE", "LDH", "URICACID")
LABELS = {"HGBFREE": "HGBFREE", "LDH": "LDH", "URICACID": "Uric acid"}
_ALIASES = {
    "HGBFREE": "HGBFREE",
    "HGB FREE": "HGBFREE",
    "FREE HEMOGLOBIN": "HGBFREE",
    "HEMOGLOBIN FREE": "HGBFREE",
    "HEMOGLOBIN, FREE": "HGBFREE",
    "PLASMA FREE HEMOGLOBIN": "HGBFREE",
    "PLASMA-FREE HEMOGLOBIN": "HGBFREE",
    "FREE PLASMA HEMOGLOBIN": "HGBFREE",
    "HEMOGLOBIN, PLASMA FREE": "HGBFREE",
    "HEMOGLOBIN, FREE, PLASMA": "HGBFREE",
    "LDH": "LDH",
    "LDH TOTAL": "LDH",
    "LDH, TOTAL": "LDH",
    "LACTATE DEHYDROGENASE": "LDH",
    "LACTIC DEHYDROGENASE": "LDH",
    "LACTIC ACID DEHYDROGENASE": "LDH",
    "URICACID": "URICACID",
    "URIC ACID": "URICACID",
}
# These exact suffixes express a serum/plasma specimen, not urine or an
# isoenzyme. No substring matching is used to guess an analyte.
for _base, _key in tuple(_ALIASES.items()):
    if re.search(r"\b(?:SERUM|PLASMA)\b", _base):
        continue
    for _specimen in ("SERUM", "PLASMA"):
        for _suffix in (" " + _specimen, ", " + _specimen, " (" + _specimen + ")"):
            _ALIASES[_base + _suffix] = _key

_NONRESULT = re.compile(
    r"\b(?:pending|cancelled|canceled|hemolyzed|haemolysed|hemolysed|"
    r"rejected|invalid|not performed|unable|error)\b", re.I)


def lysis_component(component: str) -> str:
    """Return one supported assay key from an explicit source label."""
    if not isinstance(component, str):
        return ""
    return _ALIASES.get(canonical(component), "")


def lysis_selection(sheet: dict, as_of: datetime | None = None) -> dict[str, list[dict]]:
    """Return at most two eligible rows per assay, with the newest first.

    As with lactate, a date-only previous-day result is eligible when that date
    overlaps the rolling 24-hour interval. No collection time is invented.
    Times determine order only when all same-day results have collection
    times. Otherwise Epic's supplied order is retained.

    Returned rows are references to the original snapshot and are read-only.
    """
    from lab_windows import clock, eligible_time, measured, ordered

    now = clock(as_of)
    if "g" in sheet.get("import_warnings", {}):
        return {}
    grouped: dict[str, list[dict]] = {code: [] for code in COMPONENTS}
    for row in sheet.get("labs", {}).get("rows", []):
        if not isinstance(row, dict) or row.get("include") is not True:
            continue
        code = lysis_component(row.get("component", ""))
        if not code or not isinstance(row.get("id"), str):
            continue
        value = row.get("value", "")
        if (not isinstance(value, str) or not measured(value)
                or _NONRESULT.search(value) or not isinstance(row.get("date"), str)):
            continue
        if eligible_time(row, now, hours=24):
            grouped[code].append(row)
    return {code: ordered(grouped[code])[:2] for code in COMPONENTS if grouped[code]}


def lysis_summary(sheet: dict, as_of: datetime | None = None) -> str:
    """Render available lysis assays on separate lines, older then newer."""
    selected = lysis_selection(sheet, as_of)
    if not selected:
        return ""
    lines = ["Lysis Labs:"]
    for code in COMPONENTS:
        rows = selected.get(code)
        if not rows:
            continue
        latest = rows[0]
        day, _ = date_parts(latest["date"])
        stamp = f"{day.month}/{day.day}/{day.year}"
        values = " -> ".join(row["value"] for row in reversed(rows))
        lines.append(LABELS[code] + ": " + values + " [" + stamp + "]")
    return "\n".join(lines)
