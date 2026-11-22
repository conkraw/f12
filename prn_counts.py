"""Count reviewed PRN administrations in the current 7am reporting window.

Epic's generic Volume (mL) rows can include continuous infusions, split volume
chartings, and missing administrations. A volume is never converted into a
dose count. Each imported volume starts unresolved, and a reviewer must confirm
complete administration capture for each medication before a number is shown.
Only sanitized medication keys, timestamps, volumes, counts, and review hashes
are stored. Source text and clinician names are deliberately discarded.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from zoneinfo import ZoneInfo

from lab_windows import clock


EASTERN = ZoneInfo("America/New_York")
MEDICATIONS = (
    "hydromorphone", "morphine", "fentanyl", "midazolam", "ketamine",
    "pentobarbital", "vecuronium", "rocuronium",
)
LABELS = {medication: medication.capitalize() for medication in MEDICATIONS}
ALIASES = {
    "hydromorphone": ("hydromorphone", "dilaudid"),
    "morphine": ("morphine",),
    "fentanyl": ("fentanyl", "sublimaze"),
    "midazolam": ("midazolam", "versed"),
    "ketamine": ("ketamine", "ketalar"),
    "pentobarbital": ("pentobarbital", "nembutal"),
    "vecuronium": ("vecuronium", "norcuron"),
    "rocuronium": ("rocuronium", "zemuron"),
}
MAX_EVENTS = 4096
MAX_TEXT = 500_000
MAX_DOSES = 100
_EVENT_KEYS = {"medication", "timestamp", "volume_ml", "dose_count", "source"}
_SOURCES = {"volume", "explicit_prn", "manual"}
_DIVIDER = re.compile(r"^\s*(?:af){4,}a?\s*$", re.I)
_VOLUME_START = re.compile(r"\bVolume\s*\(\s*mL\s*\)", re.I)
_VOLUME = re.compile(
    r"\bVolume\s*\(\s*mL\s*\)\s*(?P<drug>[^:\r\n\t]+?)\s*:\s*"
    r"(?P<volume>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*mL\b\s*"
    r"\((?P<stamp>[^()\r\n]*)\)", re.I,
)
_LOCAL_STAMP = re.compile(
    r"(?P<date>\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?|\d{4})"
    r"(?P<offset>\s+(?:[+-]\d{2}:?\d{2}|Z))?(?=\s*(?::|\)|$))", re.I,
)
_ISO_STAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?", re.I,
)
_STORED_STAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?[+-]\d{2}:\d{2}",
)
_PRN_POSITIVE = re.compile(r"\bPRN\s+(?:administered|given)\b", re.I)
_PRN_UNCERTAIN = re.compile(
    r"\b(?:not|never|held|withheld|missed|refused|cancelled|canceled|planned|"
    r"ordered|scheduled|pending|consider|if|may|should|reported|possibly)\b"
    r"|\b\d+\s*(?:doses|times)\b|\bx\s*\d+\b", re.I,
)


def empty_prn() -> dict:
    return {"version": 1, "events": [], "reviewed": {}}


@dataclass
class PRNResult:
    data: dict | None = None
    error: str = ""
    issues: list[str] = field(default_factory=list)


def canonical_medication(name: str) -> str:
    """Return one whole-name drug match, or an empty key for ambiguous names."""
    if not isinstance(name, str) or len(name) > 2000:
        return ""
    found = [key for key, aliases in ALIASES.items()
             if any(re.search(r"\b" + re.escape(alias) + r"\b", name, re.I)
                    for alias in aliases)]
    return found[0] if len(found) == 1 else ""


def _localize(local: datetime) -> datetime:
    """Reject missing and repeated Eastern clock times unless offset is given."""
    possible = set()
    for fold in (0, 1):
        instant = local.replace(tzinfo=EASTERN, fold=fold).astimezone(timezone.utc)
        if instant.astimezone(EASTERN).replace(tzinfo=None) == local:
            possible.add(instant)
    if len(possible) != 1:
        raise ValueError("A PRN timestamp falls in an ambiguous or nonexistent local clock hour. Supply its UTC offset.")
    return possible.pop().astimezone(EASTERN)


def event_time(value: str | datetime) -> datetime:
    """Read a complete timestamp and return an aware Eastern datetime.

    Local Epic dates require both date and time. A known offset disambiguates
    the fall daylight-saving transition. Date-only and time-only values fail.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and len(value) <= 64:
        value = value.strip()
        if _ISO_STAMP.fullmatch(value):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
            except ValueError as exc:
                raise ValueError("A PRN timestamp is not a valid date and time.") from exc
        else:
            match = _LOCAL_STAMP.fullmatch(value)
            if not match:
                raise ValueError("Each PRN entry requires a complete administration date and time.")
            date = match.group("date")
            clock_part = match.group("time")
            offset = (match.group("offset") or "").strip()
            form = "%m/%d/%Y" if len(date.rsplit("/", 1)[-1]) == 4 else "%m/%d/%y"
            form += " " + ("%H:%M:%S" if clock_part.count(":") == 2 else "%H:%M" if ":" in clock_part else "%H%M")
            text = date + " " + clock_part
            if offset:
                form += " %z"
                text += " " + offset.upper()
            try:
                parsed = datetime.strptime(text, form)
            except ValueError as exc:
                raise ValueError("A PRN timestamp is not a valid date and time.") from exc
    else:
        raise ValueError("Each PRN entry requires a complete administration date and time.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return _localize(parsed)
    return parsed.astimezone(EASTERN)


def prn_window(as_of: datetime | None = None) -> tuple[datetime, datetime]:
    """Use the same fixed printing clock as the other time-windowed displays."""
    end = clock(as_of)
    day = end.date() - timedelta(days=1 if end.timetz().replace(tzinfo=None) < time(7) else 0)
    return datetime.combine(day, time(7), EASTERN), end


def _within(event: dict, start: datetime, end: datetime) -> bool:
    instant = event_time(event["timestamp"]).astimezone(timezone.utc)
    return start.astimezone(timezone.utc) <= instant <= end.astimezone(timezone.utc)


def validate_prn(data: dict | None) -> None:
    """Validate persisted PRN data without accepting raw or identifying text."""
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != {"version", "events", "reviewed"}:
        raise ValueError("Saved PRN data has an invalid structure.")
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("Saved PRN data has an unsupported version.")
    if not isinstance(data["events"], list) or len(data["events"]) > MAX_EVENTS:
        raise ValueError("Saved PRN data contains too many entries.")
    confirmed_instants = set()
    for event in data["events"]:
        if not isinstance(event, dict) or set(event) != _EVENT_KEYS:
            raise ValueError("A saved PRN entry has an invalid structure.")
        if not isinstance(event["medication"], str) or event["medication"] not in MEDICATIONS or not isinstance(event["source"], str) or event["source"] not in _SOURCES:
            raise ValueError("A saved PRN entry has an unsupported medication or source.")
        stamp = event["timestamp"]
        if not isinstance(stamp, str) or len(stamp) > 40 or not _STORED_STAMP.fullmatch(stamp):
            raise ValueError("A saved PRN entry needs a complete timestamp with a UTC offset.")
        if event_time(stamp).isoformat() != stamp:
            raise ValueError("Saved PRN timestamps must use the correct Eastern UTC offset.")
        volume = event["volume_ml"]
        if volume is not None and (type(volume) not in (int, float) or not 0 <= volume <= 1_000_000 or not math.isfinite(volume)):
            raise ValueError("A PRN volume is invalid.")
        doses = event["dose_count"]
        if doses is not None and (type(doses) is not int or not 0 <= doses <= MAX_DOSES):
            raise ValueError("PRN dose counts must be whole numbers from 0 to 100, or unresolved.")
        if doses:
            # A repeated volume and a manually added dose can refer to the
            # same administration. Multiple real doses at one timestamp are
            # recorded as one row with their verified dose count.
            instant = (event["medication"], event_time(stamp).astimezone(timezone.utc))
            if instant in confirmed_instants:
                raise ValueError("Combine PRN doses at the same administration time into one row. Set duplicate volume rows to 0.")
            confirmed_instants.add(instant)
    reviews = data["reviewed"]
    if not isinstance(reviews, dict) or len(reviews) > len(MEDICATIONS):
        raise ValueError("Saved PRN review data is invalid.")
    for drug, review in reviews.items():
        if drug not in MEDICATIONS or not isinstance(review, dict) or set(review) != {"window_start", "signature"}:
            raise ValueError("Saved PRN review data is invalid.")
        start = review["window_start"]
        if not isinstance(start, str) or len(start) > 40 or not _STORED_STAMP.fullmatch(start):
            raise ValueError("A PRN review needs its reporting window.")
        local = event_time(start)
        if local.isoformat() != start or local.timetz().replace(tzinfo=None) != time(7):
            raise ValueError("A PRN review must start at 7am Eastern.")
        if not isinstance(review["signature"], str) or not re.fullmatch(r"[a-f0-9]{64}", review["signature"]):
            raise ValueError("A PRN review signature is invalid.")


def _timestamp_from_source(text: str) -> str:
    """Read only the initial time and discard the following clinician text."""
    value = text.strip()
    match = _LOCAL_STAMP.match(value)
    if not match:
        # ISO timestamps in an explicitly dated PRN line are also supported.
        match = _ISO_STAMP.match(value)
        if not match or value[match.end():].strip() and not value[match.end():].lstrip().startswith(":"):
            raise ValueError("Each PRN entry requires a complete administration date and time.")
    return event_time(match.group(0).strip()).isoformat()


def _volume_event(match: re.Match) -> dict | None:
    drug = canonical_medication(match.group("drug"))
    if not drug:
        return None
    volume = float(match.group("volume"))
    if not math.isfinite(volume) or not 0 <= volume <= 1_000_000:
        raise ValueError("A PRN volume is invalid.")
    return {"medication": drug, "timestamp": _timestamp_from_source(match.group("stamp")),
            "volume_ml": volume, "dose_count": None, "source": "volume"}


def _explicit_event(cell: str) -> dict | None:
    """Accept a single positive PRN administration, never a generic bolus."""
    if not _PRN_POSITIVE.search(cell):
        return None
    # All source formats must explicitly identify one medication and one time.
    stamps = list(_LOCAL_STAMP.finditer(cell))
    if not stamps:
        stamps = list(_ISO_STAMP.finditer(cell))
    if len(stamps) != 1:
        raise ValueError("Each PRN administration needs one complete date and time.")
    # In supported source lines the administration description precedes the
    # timestamp. Ignore all trailing clinician text when interpreting status.
    description = cell[:stamps[0].start()].rstrip(" (")
    if not _PRN_POSITIVE.search(description) or _PRN_UNCERTAIN.search(description):
        raise ValueError("A PRN administration entry contains an uncertain or multiple-dose status. Review it in the source record.")
    drug = canonical_medication(description)
    if not drug:
        raise ValueError("A PRN administration entry does not identify one supported medication.")
    # The time may appear inside a clinician annotation. Never retain that text.
    return {"medication": drug, "timestamp": event_time(stamps[0].group(0).strip()).isoformat(),
            "volume_ml": None, "dose_count": 1, "source": "explicit_prn"}


def parse_prn(text: str) -> PRNResult:
    """Parse an AF block, retaining volume records as unresolved review rows.

    Missing or malformed supported entries fail closed, so a partially parsed
    table cannot appear to be complete. Paired AF markers are accepted for
    callers that supply the entire block. Empty rows never create zero counts.
    """
    out = PRNResult()
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        out.error = "The PRN block is invalid or too large. No PRN data was imported."
        return out
    lines = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").splitlines()
    markers = [i for i, line in enumerate(lines) if _DIVIDER.fullmatch(line)]
    if markers:
        if len(markers) != 2:
            out.error = "The PRN block requires one complete pair of AF dividers."
            return out
        lines = lines[markers[0] + 1:markers[1]]
    data = empty_prn()
    seen = set()
    ignored = False
    duplicates = False
    try:
        for raw in lines:
            line = raw.strip()
            if not line or re.fullmatch(r"TIME\s+ANALGESIA\s+SEDATIVES\s+PARALYTICS", line, re.I):
                continue
            if re.fullmatch(r"(?:PRNs?|PRN\s+(?:administrations?|medications?|events?))\s*:?", line, re.I):
                continue
            if re.match(r"^\d{4}(?:\s|$)", line):
                row_time = line[:4]
                if int(row_time[:2]) > 23 or int(row_time[2:]) > 59:
                    raise ValueError("A PRN table row contains an invalid clock time.")
                line = line[4:].strip()
            if not line or line.casefold() in {"no data recorded", "no results found", "none", "-", "--"}:
                continue
            # Each tab cell may contain several exported Volume entries.
            for cell in re.split(r"\t+", line):
                cell = cell.strip()
                if not cell or cell.casefold() in {"no data recorded", "none", "-", "--"}:
                    continue
                records = []
                starts = list(_VOLUME_START.finditer(cell))
                if starts:
                    matches = list(_VOLUME.finditer(cell))
                    if len(matches) != len(starts):
                        raise ValueError("A PRN volume entry is missing a readable medication, volume, date, or time.")
                    remaining = _VOLUME.sub("", cell).strip(" ,|\n")
                    if remaining:
                        raise ValueError("A PRN volume cell includes unrecognized content. Review the source record.")
                    for match in matches:
                        event = _volume_event(match)
                        if event is not None:
                            records.append(event)
                        else:
                            ignored = True
                else:
                    event = _explicit_event(cell)
                    if event is None:
                        raise ValueError("A PRN entry is not a dated volume or an explicitly administered PRN dose.")
                    records.append(event)
                for event in records:
                    key = json.dumps(event, sort_keys=True, separators=(",", ":"))
                    if key in seen:
                        duplicates = True
                        continue
                    seen.add(key)
                    data["events"].append(event)
                    if len(data["events"]) > MAX_EVENTS:
                        raise ValueError("The PRN block contains too many entries.")
        data["events"].sort(key=lambda event: (event["timestamp"], event["medication"], event["source"]))
        validate_prn(data)
    except (ValueError, OverflowError) as exc:
        out.error = str(exc)
        return out
    if data["events"]:
        out.issues.append("PRN counts require verification against medication administrations. Volume entries may include infusions or omit doses.")
    if ignored:
        out.issues.append("Volume entries for medications outside the selected PRN list were ignored.")
    if duplicates:
        out.issues.append("Identical repeated PRN source entries were included only once.")
    out.data = data
    return out


def review_signature(data: dict, medication: str) -> str:
    """Bind a medication's approval to its exact current events."""
    drug = canonical_medication(medication)
    if not drug:
        raise ValueError("Select one supported PRN medication.")
    rows = [event for event in data["events"] if event["medication"] == drug]
    serialized = sorted(json.dumps(event, sort_keys=True, separators=(",", ":")) for event in rows)
    return sha256(json.dumps(serialized, separators=(",", ":")).encode("utf-8")).hexdigest()


def clear_review(data: dict, medications=None) -> dict:
    validate_prn(data)
    if data is None:
        return empty_prn()
    updated = deepcopy(data)
    selected = MEDICATIONS if medications is None else medications
    if isinstance(selected, str):
        selected = [selected]
    for medication in selected:
        drug = canonical_medication(medication)
        if not drug:
            raise ValueError("Select supported PRN medications.")
        updated["reviewed"].pop(drug, None)
    return updated


def confirm_review(data: dict, medications, as_of: datetime | None = None) -> dict:
    """Explicitly attest complete capture after resolving doses and missing rows.

    This function must be called only following the user's review action, never
    automatically after import. A selected medication with no events becomes
    an explicitly confirmed zero for this reporting window.
    """
    validate_prn(data)
    if data is None:
        raise ValueError("Review the PRN administration data first.")
    if isinstance(medications, str):
        medications = [medications]
    selected = []
    for medication in medications:
        drug = canonical_medication(medication)
        if not drug:
            raise ValueError("Select supported PRN medications.")
        if drug not in selected:
            selected.append(drug)
    start, end = prn_window(as_of)
    for event in data["events"]:
        if event["medication"] in selected and _within(event, start, end) and event["dose_count"] is None:
            raise ValueError("Resolve every in-window entry for the selected medication. Enter 0 for infusion or other non-PRN volume, and add any missing administrations.")
    updated = deepcopy(data)
    for drug in selected:
        updated["reviewed"][drug] = {"window_start": start.isoformat(), "signature": review_signature(updated, drug)}
    return updated


def prn_counts(sheet: dict, as_of: datetime | None = None) -> dict[str, int]:
    """Return only current-window, completely reviewed administration counts."""
    if not isinstance(sheet, dict) or "af" in sheet.get("import_warnings", {}):
        return {}
    data = sheet.get("prn")
    try:
        validate_prn(data)
        if data is None:
            return {}
        start, end = prn_window(as_of)
        counts = {}
        for drug in MEDICATIONS:
            review = data["reviewed"].get(drug)
            if not review or review["window_start"] != start.isoformat() or review["signature"] != review_signature(data, drug):
                continue
            rows = [event for event in data["events"] if event["medication"] == drug and _within(event, start, end)]
            if any(event["dose_count"] is None for event in rows):
                continue
            counts[drug] = sum(event["dose_count"] for event in rows)
        return counts
    except (ValueError, TypeError, KeyError, OverflowError):
        return {}
