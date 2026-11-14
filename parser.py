"""Deterministic SmartPhrase parsing. No OCR, external calls, or clinical inference."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from anthropometrics import extract_age_sex

SECTION_NAMES = {
    "a": "Diagnoses", "b": "Medications", "c": "Invasive Ventilation",
    "d": "Non-invasive Ventilation", "e": "VITALS", "f": "CULTURES",
    "g": "LABS", "h": "INTAKE/OUTPUT", "i": "NUTRITION", "j": "Wound Review",
    "k": "Target Arousal Level", "l": "WAT Score", "m": "ICP Trends", "n": "Date of Admission", "o": "Respiratory Viral Panel", "p": "Blood Gas", "q": "Complete Blood Count", "r": "Orders Placed This Encounter", "s": "Intake / Output totals", "t": "Feeds", "u": "Devices", "v": "Intracranial Pressure Monitor", "w": "Pacemaker", "x": "Diet", "y": "CAPD", "z": "ECG",
}
MAX_PASTE = 150_000
DIVIDER = re.compile(r"^([a-z])\1{7,}$", re.I)
NUMBER_OR_BULLET = re.compile(r"^\s*(?:\d+[.)]\s+|[•\-]\s+)")


def _heading(line: str) -> str | None:
    text = line.replace("：", ":").strip().rstrip(":").strip().casefold()
    if re.match(r"^date of admission\s*:", text):
        return "n"
    if re.match(r"^(?:capd|cornell assessment of pediatric delirium)(?:\b|:)", text):
        return "y"
    if (text in ("ecg", "ekg", "electrocardiogram")
            or re.match(r"^(?:ecg|ekg)(?:\s*:|\s+\d+\s*[- ]?\s*leads?\b)", text)):
        return "z"
    if text in ("sbs", "sbs score", "sbs observations", "state behavioral scale", "state behavioral scale (sbs)"):
        return "k"
    if text in ("orders", "recurring orders", "labs/imaging"):
        return "r"
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
    """Accept matching a..z divider lines of any length >= 8.

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
        if marker:
            key = marker.group(1).lower()
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
        t_start = key in ("t", "u", "v", "w", "x", "y", "z")
        if not p_start and not r_start and not s_start and not t_start and not m_start and not k_start and (not nonempty or _heading(nonempty[0]) != key):
            result.invalid.add(key)
            result.issues.append(f"The {SECTION_NAMES[key]} divider pair must begin with its matching heading.")
        elif any(_heading(ln) not in (None, key) and not (key == "g" and _heading(ln) in ("p", "q")) and not (key == "s" and _heading(ln) == "h") for ln in nonempty[1:]):
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
