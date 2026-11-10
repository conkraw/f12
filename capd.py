"""Recorded Y-block CAPD total only. No delirium diagnosis or item-score calculation.

Source range reference: https://pmc.ncbi.nlm.nih.gov/articles/PMC9157792/
Eight recorded items are not summed here. Only an explicit total is imported.
Error messages contain no clinical source text or values.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

LABEL = r"(?:CAPD(?:\s+(?:total\s+)?score)?|Cornell\s+Assessment\s+of\s+Pediatric\s+Delirium(?:\s+(?:total\s+)?score)?)"
LABEL_PREFIX = re.compile(r"^" + LABEL + r"\s*(?:\(\s*0\s*[-–]\s*32\s*\))?\s*:\s*", re.I)
LABEL_ONLY = re.compile(r"^" + LABEL + r"\s*(?:\(\s*0\s*[-–]\s*32\s*\))?\s*:?\s*$", re.I)
MISSING = {"", "none", "--", "-", "n/a", "na", "not assessed", "not documented", "not recorded",
           "no data recorded", "no data", "unable to assess", "unable to score", "uta", "not assessable"}

@dataclass
class CapdResult:
    rows: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    error: str = ""

def score_text(value: str) -> str:
    """A documented integer total from 0 to 32, optionally followed by /32."""
    if not isinstance(value, str):
        raise ValueError("Enter the recorded CAPD total as a whole number from 0 to 32.")
    match = re.fullmatch(r"(\d{1,2})(?:\s*/\s*32)?", value.strip())
    if not match or not 0 <= int(match.group(1)) <= 32:
        raise ValueError("Enter the recorded CAPD total as a whole number from 0 to 32.")
    return str(int(match.group(1)))

def validate_capd_rows(rows: list[dict]) -> None:
    if not isinstance(rows, list) or len(rows) > 1:
        raise ValueError("The CAPD record must contain at most one documented total.")
    if not rows:
        return
    from vitals import validate_vitals
    validate_vitals(rows)
    row = rows[0]
    if row["label"] != "CAPD" or row["section"] != "Neurologic":
        raise ValueError("The CAPD total must remain in Neurologic.")
    score_text(row["value"])

def capd_display_row(rows: list[dict]) -> dict:
    validate_capd_rows(rows)
    value = score_text(rows[0]["value"]) if rows and rows[0]["include"] else "None"
    # Clinician-requested display flag only. The saved score remains numeric,
    # and this helper does not add a diagnosis or alter the imported result.
    if value != "None" and int(value) >= 9:
        value += " (H)"
    return {"label": "CAPD", "value": value, "section": "Neurologic", "include": True}

def parse_capd(block: str) -> CapdResult:
    out = CapdResult()
    totals = []
    for raw in block.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        text = re.sub(r"\s+", " ", raw.replace("\u00a0", " ")).strip()
        if not text or LABEL_ONLY.fullmatch(text):
            continue
        # Epic can wrap its long field label in a user-added CAPD: label.
        for _ in range(4):
            stripped, count = LABEL_PREFIX.subn("", text, count=1)
            if not count:
                break
            text = stripped.strip()
        # Also accept a tab-separated label/value, preserving the field boundary.
        if "\t" in raw and not re.fullmatch(r"\d{1,2}(?:\s*/\s*32)?", text):
            cells = [p.strip() for p in raw.split("\t") if p.strip()]
            if len(cells) == 2 and LABEL_ONLY.fullmatch(cells[0]):
                text = cells[1]
        if LABEL_ONLY.fullmatch(text) or text.casefold().rstrip(".") in MISSING:
            continue
        try:
            total = score_text(text)
        except ValueError:
            out.error = "A CAPD total could not be read. This section was not updated."
            return out
        if totals and totals[0] != total:
            out.error = "Conflicting CAPD totals were supplied without an established order. This section was not updated."
            return out
        totals.append(total)
    if totals:
        out.rows = [{"label": "CAPD", "value": totals[0], "section": "Neurologic", "include": True}]
    return out
