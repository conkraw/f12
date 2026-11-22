"""Summarize devices explicitly recorded in the AG airway-clearance table."""
from __future__ import annotations

from dataclasses import dataclass, field
import re


MAX_DEVICES = 64
MAX_DEVICE_LENGTH = 200
SOURCE_LABEL = "cpt delivery source"
HEADINGS = {"airway clearance device", "airway clearance devices"}
EMPTY_VALUES = {
    "", "-", "--", "---", "\u2013", "\u2014", "none", "(none)", "n/a", "na",
    "unknown", "unk", "not documented", "not recorded", "not applicable",
    "no data", "no data recorded", "no results", "no results found",
}
TIMESTAMP = re.compile(
    r"\d{1,2}/\d{1,2}/\d{2,4}"
    r"(?:\s+(?:\d{4}|\d{1,2}:\d{2}(?::\d{2})?)\s*(?:[ap]m)?)?",
    re.I,
)


@dataclass
class AirwayClearanceDevicesResult:
    devices: list[str] = field(default_factory=list)
    error: str = ""


def validate_airway_clearance_devices(value: list[str]) -> None:
    """Validate the optional list without relying on a device-name allowlist."""
    if not isinstance(value, list) or len(value) > MAX_DEVICES:
        raise ValueError("Airway clearance devices must be a list of at most 64 names.")
    for device in value:
        if (not isinstance(device, str) or not device.strip()
                or len(device) > MAX_DEVICE_LENGTH
                or any(ord(char) < 32 or ord(char) == 127 for char in device)):
            raise ValueError("Each airway clearance device must be single-line text of at most 200 characters.")


def _clean(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def _is_empty(value: str) -> bool:
    return value.casefold().rstrip(".") in EMPTY_VALUES


def parse_airway_clearance_devices(block: str) -> AirwayClearanceDevicesResult:
    """Read all supplied CPT source rows, including repeated three-column tables.

    The SmartPhrase already limits the source to its last six sessions. Keep all
    supplied device names without applying a separate date or time window.
    """
    result = AirwayClearanceDevicesResult()
    if not isinstance(block, str):
        result.error = "The AG airway clearance device block must be text."
        return result
    lines = block.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    devices: list[str] = []
    seen: set[str] = set()
    found_source = False
    found_table_header = False
    for raw in lines:
        cells = [_clean(cell) for cell in raw.split("\t")]
        label = cells[0].replace("\uff1a", ":").rstrip(":").casefold()
        if label == SOURCE_LABEL:
            found_source = True
            for cell in cells[1:]:
                for part in cell.split(";"):
                    device = _clean(part)
                    if _is_empty(device) or TIMESTAMP.fullmatch(device):
                        continue
                    key = device.casefold()
                    if key not in seen:
                        devices.append(device)
                        seen.add(key)
            continue
        nonempty = [cell for cell in cells if cell]
        if not nonempty or all(_is_empty(cell) for cell in nonempty):
            continue
        if len(nonempty) == 1 and nonempty[0].replace("\uff1a", ":").rstrip(":").casefold() in HEADINGS:
            continue
        if len(nonempty) == 1 and nonempty[0].casefold() == "other":
            found_table_header = True
            continue
        if all(TIMESTAMP.fullmatch(cell) for cell in nonempty):
            found_table_header = True
            continue
        result.error = "The AG block contains an unrecognized airway clearance table row. Review the CPT Delivery Source table."
        return result
    if found_table_header and not found_source:
        result.error = "The AG table does not contain a CPT Delivery Source row."
        return result
    try:
        validate_airway_clearance_devices(devices)
    except ValueError as exc:
        result.error = str(exc)
        return result
    result.devices = devices
    return result


def airway_clearance_devices_text(sheet: dict) -> str:
    """Show only safely imported device names, once each in source order."""
    if "ag" in sheet.get("import_warnings", {}):
        return ""
    devices = sheet.get("airway_clearance_devices", [])
    return "Airway Clearance Device: " + ", ".join(devices) if devices else ""
