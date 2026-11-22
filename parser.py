"""Deterministic SmartPhrase parsing. No OCR, external calls, or clinical inference."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from anthropometrics import extract_age_sex

SECTION_NAMES = {
    "a": "Diagnoses", "b": "Medications", "c": "Invasive Ventilation",
    "d": "Non-invasive Ventilation", "e": "VITALS", "f": "CULTURES",
    "g": "LABS", "h": "INTAKE/OUTPUT", "i": "NUTRITION", "j": "Wound Review",
    "k": "Target Arousal Level", "l": "WAT Score", "m": "ICP Trends", "n": "Date of Admission", "o": "Respiratory Viral Panel", "p": "Blood Gas", "q": "Complete Blood Count", "r": "Orders Placed This Encounter", "s": "Intake / Output totals", "t": "Feeds", "u": "Devices", "v": "Intracranial Pressure Monitor", "w": "Pacemaker", "x": "Diet", "y": "CAPD", "z": "ECG", "ab": "Dietary Orders", "ac": "Stool / bowel movement", "ad": "ECLS settings", "ae": "Code Status", "af": "PRN administrations", "ag": "Airway Clearance Device",
}
MAX_PASTE = 150_000
DIVIDER = re.compile(r"^([a-z])\1{7,}$", re.I)
DIETARY_DIVIDER = re.compile(r"^(?:ab){4,}a?$", re.I)
STOOL_DIVIDER = re.compile(r"^(?:ac){4,}a?$", re.I)
ECLS_DIVIDER = re.compile(r"^(?:ad){4,}a?$", re.I)
CODE_STATUS_DIVIDER = re.compile(r"^(?:ae){4,}a?$", re.I)
PRN_DIVIDER = re.compile(r"^(?:af){4,}a?$", re.I)
AIRWAY_CLEARANCE_DIVIDER = re.compile(r"^(?:ag){4,}a?$", re.I)
NUMBER_OR_BULLET = re.compile(r"^\s*(?:\d+[.)]\s+|[•\-]\s+)")


def _heading(line: str) -> str | None:
    text = line.replace("：", ":").strip().rstrip(":").strip().casefold()
    if re.fullmatch(r"dietary\s+orders(?:\s*\(\s*from\s+admission\s*,?\s*onward\s*\))?", text):
        return "ab"
    if re.fullmatch(r"diet\s+orders", text):
        return "x"
    if re.match(r"^date of admission\s*:", text):
        return "n"
    if re.match(r"^code\s+status(?:\s*:|$)", text):
        return "ae"
    if text in ("prn", "prns", "prn administrations", "prn medications"):
        return "af"
    if text in ("airway clearance device", "airway clearance devices"):
        return "ag"
    if re.match(r"^(?:capd|cornell assessment of pediatric delirium)(?:\b|:)", text):
        return "y"
    if (text in ("ecg", "ekg", "electrocardiogram")
            or re.match(r"^(?:ecg|ekg)(?:\s*:|\s+\d+\s*[- ]?\s*leads?\b)", text)):
        return "z"
    if text in ("sbs", "sbs score", "sbs observations", "state behavioral scale", "state behavioral scale (sbs)"):
        return "k"
    if text in ("orders", "recurring orders", "labs/imaging"):
        return "r"
    if text in ("system readings", "ecls", "ecmo", "ecls settings", "ecmo settings"):
        return "ad"
    for key, value in SECTION_NAMES.items():
        if text == value.casefold():
            return key
    return None


@dataclass
class ParseResult:
    blocks: dict[str, str] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    invalid: set[str] = field(default_factory=set)
    diagnosis_error: str = ""
    diagnoses: list[str] = field(default_factory=list)
    demographics: dict[str, str] = field(default_factory=dict)


def parse_smartphrase(text: str) -> ParseResult:
    """Accept a..z and alternating ab through ag dividers.

    Ambiguous/missing/duplicate boundaries fail closed for that section.
    Issues in a later section do not invalidate a complete, unambiguous a block.
    Patient content is never included in exception or diagnostic strings.
    """
    result = ParseResult()
    if not isinstance(text, str) or not text.strip():
        result.diagnosis_error = "Paste the SmartPhrase text first."
        return result
    if len(text) > MAX_PASTE:
        result.diagnosis_error = "The paste is too large. Use one patient's SmartPhrase."
        return result
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    active: str | None = None
    buffer: list[str] = []
    seen: dict[str, int] = {}
    outside = False
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        marker = DIVIDER.fullmatch(line)
        dietary_marker = DIETARY_DIVIDER.fullmatch(line)
        stool_marker = STOOL_DIVIDER.fullmatch(line)
        ecls_marker = ECLS_DIVIDER.fullmatch(line)
        code_status_marker = CODE_STATUS_DIVIDER.fullmatch(line)
        prn_marker = PRN_DIVIDER.fullmatch(line)
        airway_clearance_marker = AIRWAY_CLEARANCE_DIVIDER.fullmatch(line)
        if marker or dietary_marker or stool_marker or ecls_marker or code_status_marker or prn_marker or airway_clearance_marker:
            key = "ag" if airway_clearance_marker else "af" if prn_marker else "ae" if code_status_marker else "ad" if ecls_marker else "ac" if stool_marker else "ab" if dietary_marker else marker.group(1).lower()
            if active == key:
                seen[key] = seen.get(key, 0) + 1
                if seen[key] > 1:
                    result.invalid.add(key)
                    result.issues.append(f"More than one {SECTION_NAMES[key]} block was found. Paste one patient at a time.")
                else:
                    # Trim blank framing lines, not the final row's TAB cells.
                    # ADS override rows may intentionally have no filled cells
                    # after the name. Their empty columns are still meaningful.
                    start, end = 0, len(buffer)
                    while start < end and not buffer[start].strip():
                        start += 1
                    while end > start and not buffer[end - 1].strip():
                        end -= 1
                    result.blocks[key] = "\n".join(buffer[start:end])
                active, buffer = None, []
            else:
                if active:
                    result.invalid.add(active)
                    result.issues.append(f"{SECTION_NAMES[active]} is missing its closing divider before line {n}.")
                active, buffer = key, []
            continue
        # Mistyped AG boundaries must not leak device rows into other sections.
        near_airway_clearance_marker = (
            len(line) >= 8 and line.isalpha()
            and re.search(r"(?:ag){3,}", line, re.I)
            and sum(char.casefold() == ("a" if index % 2 == 0 else "g")
                    for index, char in enumerate(line)) / len(line) >= 0.75
        )
        if near_airway_clearance_marker:
            result.invalid.add("ag")
            if active:
                result.invalid.add(active)
            result.issues.append(f"Malformed divider on line {n}. Use an uninterrupted alternating ag line for Airway Clearance Device.")
            continue
        # A malformed AF boundary cannot attach medication events to a neighbor.
        near_prn_marker = (
            len(line) >= 8 and line.isalpha()
            and re.search(r"(?:af){3,}", line, re.I)
            and sum(char.casefold() == ("a" if index % 2 == 0 else "f")
                    for index, char in enumerate(line)) / len(line) >= 0.75
        )
        if near_prn_marker:
            result.invalid.add("af")
            if active:
                result.invalid.add(active)
            result.issues.append(f"Malformed divider on line {n}. Use an uninterrupted alternating af line for PRN administrations.")
            continue
        # A mistyped AE boundary must not turn code status into another field.
        near_code_status_marker = (
            len(line) >= 8 and line.isalpha()
            and re.search(r"(?:ae){3,}", line, re.I)
            and sum(char.casefold() == ("a" if index % 2 == 0 else "e")
                    for index, char in enumerate(line)) / len(line) >= 0.75
        )
        if near_code_status_marker:
            result.invalid.add("ae")
            if active:
                result.invalid.add(active)
            result.issues.append(f"Malformed divider on line {n}. Use an uninterrupted alternating ae line for Code Status.")
            continue
        # Never absorb a mistyped AD boundary into the preceding patient section.
        near_ecls_marker = (
            len(line) >= 8 and line.isalpha()
            and re.search(r"(?:ad){3,}", line, re.I)
            and sum(char.casefold() == ("a" if index % 2 == 0 else "d")
                    for index, char in enumerate(line)) / len(line) >= 0.75
        )
        if near_ecls_marker:
            result.invalid.add("ad")
            if active:
                result.invalid.add(active)
            result.issues.append(f"Malformed divider on line {n}. Use an uninterrupted alternating ad line for ECLS settings.")
            continue
        # Reject near-AC dividers rather than consuming stool data into ECG,
        # Dietary Orders or another patient section.
        near_stool_marker = (
            len(line) >= 8 and line.isalpha()
            and re.search(r"(?:ac){3,}", line, re.I)
            and sum(char.casefold() == ("a" if index % 2 == 0 else "c")
                    for index, char in enumerate(line)) / len(line) >= 0.75
        )
        if near_stool_marker:
            result.invalid.add("ac")
            if active:
                result.invalid.add(active)
            result.issues.append(f"Malformed divider on line {n}. Use an uninterrupted alternating ac line for stool data.")
            continue
        # A near-AB divider must not become an ordinary dietary instruction.
        # It is flagged, never repaired or treated as a valid boundary.
        near_dietary_marker = (
            len(line) >= 8 and line.isalpha()
            and re.search(r"(?:ab){3,}", line, re.I)
            and sum(char.casefold() == ("a" if index % 2 == 0 else "b")
                    for index, char in enumerate(line)) / len(line) >= 0.75
        )
        if near_dietary_marker:
            result.invalid.add("ab")
            if active:
                result.invalid.add(active)
            result.issues.append(f"Malformed divider on line {n}. Use an uninterrupted alternating ab line for Dietary Orders.")
            continue
        # A likely divider with one or more wrong letters is NOT silently corrected.
        if (len(line) >= 8 and line.isalpha()
                and re.search(r"([a-z])\1{5,}", line, re.I)
                and max(line.lower().count(c) for c in set(line.lower())) / len(line) >= 0.75):
            result.issues.append(f"Malformed divider on line {n}. Use only one repeated letter on that line.")
            if active:
                result.invalid.add(active)
            continue
        if active:
            buffer.append(raw)
        elif line:
            outside = True
    if active:
        result.invalid.add(active)
        result.issues.append(f"{SECTION_NAMES[active]} is missing its closing divider at the end.")
    if outside:
        result.issues.append("Text outside the paired dividers was not imported.")
    for key, body in list(result.blocks.items()):
        nonempty = [ln.strip() for ln in body.splitlines() if ln.strip()]
        p_start = key in ("p", "q") and (not nonempty or
            re.match(r"^(?:results? from (?:the )?last |blood gases?:?$|latest blood gas:?$|complete blood count:?$|cbc:?$|lab\s+units\b|no results?\b|no lab exists for component:|none$)", nonempty[0], re.I))
        r_start = key == "r" and (not nonempty or _heading(nonempty[0]) == "r" or re.match(r"^no orders?\b", nonempty[0], re.I))
        s_start = key == "s" and (not nonempty or _heading(nonempty[0]) in ("h", "s") or re.match(r"^(?:Intake\s*/\s*Output\s+Summary|Fluid balance:?$|Intake\s|Output\s|Net\s|none$|no data$|not documented$|no results?\b)", nonempty[0], re.I))
        # M may now start with a user-added Range or Last wrapper rather than ICP Trends.
        m_start = key == "m" and (not nonempty or bool(re.match(
            r"^(?:(?:Last\s+)?(?:ICP(?:\s+Mean)?|CPP)(?:\s+Range)?(?:\s*\(\s*mm\s*Hg\s*\))?\s*:|no data recorded$)",
            nonempty[0].replace("：", ":"), re.I)))
        k_start = key == "k" and (not nonempty or bool(re.match(
            r"^(?:(?:Last|Observed|Recorded|Actual)\s+)?(?:SBS\b|State\s+Behavio(?:u)?r(?:al)?\s+Scale\b)|^(?:results? from |patient vitals? for |Date(?:/Time)?\s|\d{1,2}/\d{1,2}/\d{2,4}\b)",
            nonempty[0], re.I)))
        # T contains device-prefixed lines and may have no heading at all.
        t_start = key in ("t", "u", "v", "w", "x", "y", "z", "ac", "ad", "af", "ag")
        if key == "ag" and nonempty and _heading(nonempty[0]) not in (None, "ag"):
            result.invalid.add(key)
            result.issues.append("Another section heading appears inside Airway Clearance Device. Check the dividers.")
        if key == "af" and nonempty and _heading(nonempty[0]) not in (None, "af"):
            result.invalid.add(key)
            result.issues.append("Another section heading appears inside PRN administrations. Check the dividers.")
        if key == "ac" and nonempty and _heading(nonempty[0]) not in (None, "ac"):
            result.invalid.add(key)
            result.issues.append("Another section heading appears inside Stool / bowel movement. Check the dividers.")
        if key == "ad" and nonempty and _heading(nonempty[0]) not in (None, "ad"):
            result.invalid.add(key)
            result.issues.append("Another section heading appears inside ECLS settings. Check the dividers.")
        dietary_start = key == "ab" and (not nonempty or _heading(nonempty[0]) in ("ab", "x"))
        if not p_start and not r_start and not s_start and not t_start and not m_start and not k_start and not dietary_start and (not nonempty or _heading(nonempty[0]) != key):
            result.invalid.add(key)
            result.issues.append(f"The {SECTION_NAMES[key]} divider pair must begin with its matching heading.")
        elif any(_heading(ln) not in (None, key) and not (key == "g" and _heading(ln) in ("p", "q")) and not (key == "s" and _heading(ln) == "h") and not (key in ("x", "ab") and _heading(ln) in ("x", "ab")) for ln in nonempty[1:]):
            result.invalid.add(key)
            result.issues.append(f"Another section heading appears inside {SECTION_NAMES[key]}. Check the dividers.")
    if "a" not in result.blocks or "a" in result.invalid:
        result.diagnosis_error = "Diagnoses could not be imported safely. Use one complete a-divider pair with Diagnoses: inside."
        return result
    metadata = extract_age_sex(result.blocks["a"], allow_inline_suffix=True)
    if metadata.error:
        result.diagnosis_error = metadata.error
        return result
    result.demographics = metadata.values
    body = metadata.remainder.splitlines()
    # Drop blank lines and the first heading only. Do not alter medical wording/codes.
    lines = [ln.strip() for ln in body if ln.strip()][1:]
    if not lines and result.demographics:
        return result  # A metadata-only update must not erase existing diagnoses.
    if not lines:
        result.diagnosis_error = "The Diagnoses section is empty. Existing content has not been changed."
        return result
    numbered = any(NUMBER_OR_BULLET.match(ln) for ln in lines)
    diagnoses: list[str] = []
    if numbered:
        for ln in lines:
            if NUMBER_OR_BULLET.match(ln):
                value = NUMBER_OR_BULLET.sub("", ln, count=1).strip()
                if value:
                    diagnoses.append(value)
            elif diagnoses:
                diagnoses[-1] += " " + ln
            else:
                diagnoses.append(ln)
    else:
        diagnoses = lines
    result.diagnoses = diagnoses
    if not diagnoses:
        result.diagnosis_error = "No diagnosis text was found. Existing content has not been changed."
    return result
