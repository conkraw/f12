"""Read the explicitly supplied AE code status without inferring an order.

Code status is a presentation snapshot, never a default resuscitation order.
Missing source text stays empty, and Epic's ``No Order`` value is preserved.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


MAX_CODE_STATUS = 300
HEADING = re.compile(r"^code\s+status\s*(?::\s*(.*))?$", re.I)


def validate_code_status(value: str) -> None:
    if (not isinstance(value, str) or len(value) > MAX_CODE_STATUS
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("The code status must be single-line text of at most 300 characters.")


@dataclass
class CodeStatusResult:
    value: str = ""
    error: str = ""


def parse_code_status(block: str) -> CodeStatusResult:
    """Accept the Code Status heading with one unambiguous supplied value."""
    result = CodeStatusResult()
    lines = [line.replace("\u00a0", " ").strip()
             for line in block.replace("\r\n", "\n").replace("\r", "\n").splitlines()
             if line.strip()]
    if not lines:
        return result
    first = HEADING.fullmatch(lines[0].replace("\uff1a", ":"))
    if first is None:
        result.error = "The AE block must start with Code Status:."
        return result
    values = ([first.group(1)] if first.group(1) else []) + lines[1:]
    for value in values:
        if HEADING.fullmatch(value.replace("\uff1a", ":")):
            result.error = "More than one Code Status heading was supplied. Review the AE block."
            return result
        try:
            validate_code_status(value)
        except ValueError as exc:
            result.error = str(exc)
            return result
        if result.value and result.value.casefold() != value.casefold():
            result.error = "Conflicting code status values were supplied. Review the AE block."
            return result
        if not result.value:
            result.value = value
    return result


def code_status_text(sheet: dict) -> str:
    """Return the recorded status only when its source was imported safely."""
    if "ae" in sheet.get("import_warnings", {}):
        return ""
    value = sheet.get("code_status", "").strip()
    return "Code Status: " + value if value else ""
