"""Documented stool signals from the dedicated AC SmartPhrase block only.

The source block is assumed to cover the user's configured past-24-hour window.
Undated stool fields cannot independently establish when a BM happened. False
means no recognized positive signal was documented, not confirmed absence of BM.
Only the boolean is persisted. Raw stool descriptions, amounts and dates are not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
import re

LABEL = "Last BM (24 Hours):"
HELP = (
    "Reads only the AC stool block. Yes means a documented stool amount or a "
    "positive stool-containing diaper weight. No means no positive signal was "
    "documented, not proof that no BM occurred. The AC source must be limited "
    "to the past 24 hours. These undated values cannot verify that time window."
)
_MISSING = re.compile(
    r"^(?:|[-–—.]+|none(?: recorded| documented)?|no|no (?:data|results?)"
    r"(?: (?:recorded|documented|available|found))?\.?|not (?:documented|recorded|"
    r"available|assessed)|n\s*/?\s*a|unknown|not applicable)$", re.I
)
_AMOUNT = re.compile(r"^stool\s+amount$", re.I)
_DIAPER = re.compile(
    r"^diaper\s+weight\s+(?:mixed\s+urine\s*/\s*stool|with\s+stool)"
    r"(?:\s*\(\s*g\s*\))?$", re.I
)
_POSITIVE_AMOUNT = re.compile(
    r"^(?:small|medium|moderate|large|smear|smears|scant|trace|yes)"
    r"(?:\s*\([^\n]*\))?$", re.I
)
_NUMBER = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+"
_WEIGHT_VALUE = re.compile(r"^\+?(" + _NUMBER + r")\s*(?:g|grams?)?$", re.I)
_AMOUNT_VALUE = re.compile(r"^\+?(" + _NUMBER + r")\s*(?:g|grams?|mL|cc|x)?$", re.I)


@dataclass
class BowelMovementResult:
    data: dict | None = None
    error: str = ""
    issues: list[str] = field(default_factory=list)


def validate_bowel_movement(data: dict | None) -> None:
    """Allow absent legacy snapshots, but never coerce text/numbers to booleans."""
    if data is None:
        return
    if (not isinstance(data, dict) or set(data) != {"documented"}
            or type(data["documented"]) is not bool):
        raise ValueError("The bowel-movement snapshot is invalid.")


def parse_bowel_movement(block: str) -> BowelMovementResult:
    """Read an already bounded AC block. No searches of other source sections."""
    result = BowelMovementResult()
    if not isinstance(block, str) or len(block) > 20_000:
        result.error = "The AC stool block is invalid or too large."
        return result
    positive = False
    unrecognized = False
    for raw in block.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = " ".join(raw.replace("\u00a0", " ").replace("：", ":").split())
        if _MISSING.fullmatch(line):
            continue
        # Optional non-data heading. It does not establish a time or a BM.
        if line.casefold().rstrip(":") in {"stool", "bowel movement", "bowel movements", "stool / bowel movement"}:
            continue
        name, sep, value = line.partition(":")
        if not sep or not (_AMOUNT.fullmatch(name.strip()) or _DIAPER.fullmatch(name.strip())):
            unrecognized = True
            continue
        value = value.strip()
        if _MISSING.fullmatch(value):
            continue
        is_amount = bool(_AMOUNT.fullmatch(name.strip()))
        if is_amount and _POSITIVE_AMOUNT.fullmatch(value):
            positive = True
            continue
        numeric = (_AMOUNT_VALUE if is_amount else _WEIGHT_VALUE).fullmatch(value)
        if numeric:
            # Parse only the value, never the '(g)' label or an unrelated time.
            positive = positive or float(numeric.group(1).replace(",", "")) > 0
        else:
            unrecognized = True
    if unrecognized and not positive:
        result.error = "The AC stool data could not be read reliably. Re-paste a supported stool amount or diaper weight."
        return result
    if unrecognized:
        result.issues.append("Some AC entries were not recognized. A separate documented stool signal established Yes.")
    result.data = {"documented": positive}
    validate_bowel_movement(result.data)
    return result


def bowel_movement_text(sheet: dict) -> str:
    """Return plain text. Rich output emphasizes only the label, never Yes/No."""
    if "ac" in sheet.get("import_warnings", {}):
        return ""
    data = sheet.get("bowel_movement")
    validate_bowel_movement(data)
    if data is None:
        return ""
    return LABEL + (" Yes" if data["documented"] else " No")


def bowel_movement_markup(text: str, esc=escape) -> str:
    """Bold only the generated label, without adding spacing or styling notes."""
    if text in (LABEL + " Yes", LABEL + " No"):
        return "<b>" + esc(LABEL) + "</b>" + esc(text[len(LABEL):])
    return esc(text)
