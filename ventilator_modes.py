"""Local display abbreviations for the Epic labels supplied by the app owner.

PRVC is the requested handoff shorthand for Epic's volume-targeted pressure
control family. It is not a vendor-independent assertion of equivalence.
Source mode text is retained in the ventilation record and remains editable.
"""
from __future__ import annotations
import re


def strip_setting_marker(value: str) -> str:
    """Ignore only a leading Epic (S) marker, not parenthetical clinical text.

    This is a matching/display normalization. Original C-block field values
    remain stored. Unknown annotations are not silently discarded.
    """
    return re.sub(r"^(?:\(\s*S\s*\)\s*)+", "", value.strip(), flags=re.I).strip()


def key(value: str) -> str:
    return re.sub(r"\s+", " ", strip_setting_marker(value)).casefold().replace("–", "-").replace("—", "-")


# Source label: (printed abbreviation, control family, non-invasive label)
MODE_SPECS = {
    "Volume Targeted Pressure Control - Intermittent Mandatory Ventilation": ("PRVC-IMV", "PRVC", False),
    "Volume Targeted Pressure Control - Continuous Mandatory Ventilation": ("PRVC", "PRVC", False),
    "Volume Targeted Pressure Control - PS": ("PRVC-PS", "PRVC", False),
    "Pressure Control - Intermittent Mandatory Ventilation": ("PC-IMV", "PC", False),
    "Pressure Control - Continuous Mandatory Ventilation": ("PC-CMV", "PC", False),
    "Volume Control - Intermittent Mandatory Ventilation": ("VC-IMV", "VC", False),
    "Volume Control - Continuous Mandatory Ventilation": ("VC-CMV", "VC", False),
    "Pressure Support - Continuous Positive Airway Pressure": ("PS-CPAP", "PS", False),
    "Continuous Positive Airway Pressure - Non Invasive Ventilation": ("CPAP NIV", "CPAP", True),
    "Bilevel Non Invasive Ventilation": ("BiLevel NIV", "BiLevel", True),
    "Average Volume-Assured Pressure Support - Non Invasive Ventilation": ("AVAPS NIV", "AVAPS", True),
    "Average Volume-Assured Pressure Support": ("AVAPS", "AVAPS", False),
    "Neurally Adjusted Ventilatory Assist - Non Invasive Ventilation": ("NAVA NIV", "NAVA", True),
    "Neurally Adjusted Ventilatory Assist": ("NAVA", "NAVA", False),
    "Volume Support Ventilation": ("VSV", "VSV", False),
    "Airway Pressure Release Ventilation": ("APRV", "APRV", False),
    "High Frequency Oscillatory Ventilation": ("HFOV", "HFOV", False),
    "High Frequency Jet Ventilation": ("HFJV", "HFJV", False),
    "CPAP Therapeutic Intermittent": ("CPAP Therapeutic Intermittent", "CPAP", True),
    "Proportional Pressure Support": ("PPS", "PPS", False),
    "Adaptive Support Ventilation": ("ASV", "ASV", False),
    "Bubble CPAP": ("Bubble CPAP", "CPAP", True),
}
_LOOKUP = {key(name): value for name, value in MODE_SPECS.items()}
for _spec in MODE_SPECS.values():
    _LOOKUP[key(_spec[0])] = _spec
# The abbreviated right-hand column of the supplied Epic screenshots.
_LOOKUP.update({
    "pc": ("PC", "PC", False),
    "vc": ("VC", "VC", False),
    key("Volume Targeted PC - IMV"): ("PRVC-IMV", "PRVC", False),
    key("Volume Targeted PC - CMV"): ("PRVC", "PRVC", False),
    key("Volume Targeted PC - PS"): ("PRVC-PS", "PRVC", False),
    key("PC - IMV"): ("PC-IMV", "PC", False),
    key("PC - CMV"): ("PC-CMV", "PC", False),
    key("VC - IMV"): ("VC-IMV", "VC", False),
    key("VC - CMV"): ("VC-CMV", "VC", False),
    key("PS - CPAP"): ("PS-CPAP", "PS", False),
})


def spec(mode: str) -> tuple[str, str, bool] | None:
    return _LOOKUP.get(key(mode))


def control_family(mode: str) -> str:
    known = spec(mode)
    if known:
        return known[1]
    text = key(mode)
    if "volume targeted pressure control" in text or "pressure regulated volume control" in text or re.search(r"\bprvc\b", text):
        return "PRVC"
    if "pressure control" in text or re.search(r"\b(?:pc|pcv)\b", text):
        return "PC"
    if "volume control" in text or re.search(r"\b(?:vc|vcv)\b", text):
        return "VC"
    return ""


def display_mode(mode: str, home: bool = False) -> str:
    known = spec(mode)
    family = control_family(mode)
    if home and family in {"PC", "PRVC", "VC"}:
        return family
    if known:
        return known[0]
    # Only shorten an explicitly recognizable family. Preserve unfamiliar suffixes.
    if key(mode) in {"pressure control", "pcv"}:
        return "PC"
    if key(mode) in {"volume control", "vcv"}:
        return "VC"
    if key(mode) in {"volume targeted pressure control", "pressure regulated volume control"}:
        return "PRVC"
    return strip_setting_marker(mode)
