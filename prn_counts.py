"""Count vecuronium and rocuronium entries from yesterday's 7am to printing.

Each positive imported volume entry for either paralytic contributes one count.
No review or infusion check is required. Other medications are not counted.
The existing eight-drug storage schema and review fields remain readable for
older archives. Source text and clinician names are never retained.
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
COUNTED_MEDICATIONS = ("vecuronium", "rocuronium")
COUNT_CAP = 6
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
_TABLE_LABEL = re.compile(r"Volume\s*\(\s*mL\s*\)\s*(?P<drug>[^:\r\n\t]+?)\s*:?", re.I)
_TABLE_DATE_START = re.compile(r"(?:\d{1,2}/\d{1,2}/\d{2,4}\s|\d{4}-\d{2}-\d{2}[T ])")
_TABLE_VOLUME = re.compile(r"(?P<volume>[+-]?(?:\d+(?:\.\d*)?|\.\d+))(?:\s*mL)?", re.I)
_EMPTY_CELLS = {"", "no data recorded", "no results found", "none", "-", "--"}
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
    try:
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return _localize(parsed)
        return parsed.astimezone(EASTERN)
    except OverflowError as exc:
        raise ValueError("A PRN timestamp is not a valid date and time.") from exc


def prn_window(as_of: datetime | None = None) -> tuple[datetime, datetime]:
    """Start at 7am on the Eastern calendar day before the printing clock."""
    end = clock(as_of)
    day = end.date() - timedelta(days=1)
    return datetime.combine(day, time(7), EASTERN), end


def prn_count_suffix(count: int | None) -> str:
    """Format an exact count below the six-entry table limit, or its minimum."""
    if type(count) is not int or count < 0:
        return ""
    return f" ≥{COUNT_CAP}" if count >= COUNT_CAP else f" × {count}"


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
    if drug not in COUNTED_MEDICATIONS:
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
    if drug not in COUNTED_MEDICATIONS:
        raise ValueError("A PRN administration entry does not identify one supported medication.")
    # The time may appear inside a clinician annotation. Never retain that text.
    return {"medication": drug, "timestamp": event_time(stamps[0].group(0).strip()).isoformat(),
            "volume_ml": None, "dose_count": 1, "source": "explicit_prn"}


def _mentions_counted(text: str) -> bool:
    return any(re.search(r"\b" + re.escape(alias) + r"\b", text, re.I)
               for drug in COUNTED_MEDICATIONS for alias in ALIASES[drug])


def _known_excluded(text: str) -> bool:
    return not _mentions_counted(text) and any(
        re.search(r"\b" + re.escape(alias) + r"\b", text, re.I)
        for drug in MEDICATIONS if drug not in COUNTED_MEDICATIONS
        for alias in ALIASES[drug])


def _expand_horizontal_tables(lines: list[str]):
    """Normalize dated Epic column tables into the existing volume format.

    Tabs, including empty cells, determine the column alignment. Repeated date
    headers replace the active header so wrapped tables retain every event.
    Only normalized medication, volume, and timestamp values are yielded.
    """
    timestamps = None
    for raw in lines:
        cells = [cell.strip() for cell in raw.split("\t")]
        first = cells[0]
        if not raw.strip():
            continue
        date_cells = cells[1:] if not first else cells
        if (not first or _TABLE_DATE_START.match(first)) and any(
                _TABLE_DATE_START.match(cell) for cell in date_cells):
            timestamps = [event_time(cell).isoformat() if cell else None for cell in date_cells]
            continue
        if timestamps is not None and len(cells) == 1 and first.casefold() == "other":
            continue
        label = _TABLE_LABEL.fullmatch(first)
        if label and (timestamps is not None or len(cells) > 1):
            drug_text = label.group("drug")
            if not _mentions_counted(drug_text):
                continue
            drug = canonical_medication(drug_text)
            if drug not in COUNTED_MEDICATIONS:
                raise ValueError("A PRN volume entry does not identify one supported medication.")
            if timestamps is None:
                raise ValueError("A PRN volume table requires a complete administration date and time for each column.")
            for index, cell in enumerate(cells[1:]):
                if cell.casefold() in _EMPTY_CELLS:
                    continue
                if index >= len(timestamps) or timestamps[index] is None:
                    raise ValueError("A PRN volume table cell is missing its administration date and time.")
                match = _TABLE_VOLUME.fullmatch(cell)
                if not match:
                    raise ValueError("A PRN volume table cell does not contain a readable volume in mL.")
                yield f"Volume (mL) {drug}: {match.group('volume')} mL ({timestamps[index]})"
            continue
        timestamps = None
        yield raw


def parse_prn(text: str) -> PRNResult:
    """Retain only dated paralytic entries from the AF block.

    Analgesic and sedative cells are ignored even when their contents are
    malformed. Malformed paralytic entries still reject the block rather than
    turning an incomplete import into a count. Empty valid AF blocks mean zero.
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
    duplicates = False
    excluded_columns = set()
    try:
        for raw in _expand_horizontal_tables(lines):
            line = raw.strip()
            if not line:
                continue
            headings = [cell.strip().upper() for cell in raw.split("\t")]
            if headings and headings[0] == "TIME" and "PARALYTICS" in headings:
                excluded_columns = {index for index, label in enumerate(headings)
                                    if label in {"ANALGESIA", "SEDATIVES"}}
                continue
            if re.fullmatch(r"TIME\s+ANALGESIA\s+SEDATIVES\s+PARALYTICS", line, re.I):
                continue
            if re.fullmatch(r"(?:PRNs?|PRN\s+(?:administrations?|medications?|events?))\s*:?", line, re.I):
                continue
            invalid_row_time = False
            cells = raw.split("\t")
            if re.match(r"^\d{4}(?:\s|$)", line):
                row_time = line[:4]
                invalid_row_time = int(row_time[:2]) > 23 or int(row_time[2:]) > 59
                line = line[4:].strip()
                cells[0] = re.sub(r"^\s*\d{4}(?=\s|$)", "", cells[0], count=1)
            if not line or line.casefold() in {"no data recorded", "no results found", "none", "-", "--"}:
                continue
            # Each tab cell may contain several exported Volume entries.
            for column, cell in enumerate(cells):
                cell = cell.strip()
                if column in excluded_columns and not _mentions_counted(cell):
                    continue
                if not cell or cell.casefold() in {"no data recorded", "no results found", "none", "-", "--"}:
                    continue
                records = []
                starts = list(_VOLUME_START.finditer(cell))
                if starts:
                    prefix = cell[:starts[0].start()].strip(" ,|\n")
                    if prefix and not _known_excluded(prefix):
                        raise ValueError("A PRN volume cell includes unrecognized content. Review the source record.")
                    for index, start in enumerate(starts):
                        end = starts[index + 1].start() if index + 1 < len(starts) else len(cell)
                        entry = cell[start.start():end].strip(" ,|\n")
                        drug_text = cell[start.end():end].split(":", 1)[0]
                        if not _mentions_counted(drug_text):
                            continue
                        if canonical_medication(drug_text) not in COUNTED_MEDICATIONS:
                            raise ValueError("A PRN volume entry does not identify one supported medication.")
                        match = _VOLUME.fullmatch(entry)
                        if not match:
                            raise ValueError("A PRN volume entry is missing a readable medication, volume, date, or time.")
                        event = _volume_event(match)
                        if event is not None:
                            records.append(event)
                else:
                    if _known_excluded(cell) or (not _mentions_counted(cell) and _PRN_POSITIVE.search(cell)):
                        continue
                    event = _explicit_event(cell)
                    if event is None:
                        raise ValueError("A PRN entry is not a dated volume or an explicitly administered PRN dose.")
                    records.append(event)
                if records and invalid_row_time:
                    raise ValueError("A PRN table row contains an invalid clock time.")
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
    """Maintain legacy review records for compatibility with older workflows.

    Current automatic paralytic counting does not call or require this helper.
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


def automatic_prn_events(data: dict | None, medication: str) -> list[tuple[datetime, int]]:
    """Return unique positive target entries, without applying a date window.

    Python exports and live HTML use this same normalization. Positive source
    volumes count once regardless of a legacy manual review decision. Explicit
    administrations count once, and positive legacy manual totals are retained.
    The input is never mutated and old confirmation signatures are not needed.
    """
    validate_prn(data)
    drug = canonical_medication(medication)
    if data is None or drug not in COUNTED_MEDICATIONS:
        return []
    result = []
    seen = set()
    for event in data["events"]:
        if event["medication"] != drug:
            continue
        instant = event_time(event["timestamp"])
        if event["source"] == "volume":
            volume = event["volume_ml"]
            count = int(volume is not None and volume > 0)
            identity = (instant.astimezone(timezone.utc), "volume", volume)
        elif event["source"] == "explicit_prn":
            count = 1
            identity = (instant.astimezone(timezone.utc), "explicit_prn")
        else:
            count = event["dose_count"] or 0
            identity = (instant.astimezone(timezone.utc), "manual", count)
        if not count or identity in seen:
            continue
        seen.add(identity)
        result.append((instant, count))
    return sorted(result, key=lambda event: event[0].astimezone(timezone.utc))


def prn_counts(sheet: dict, as_of: datetime | None = None) -> dict[str, int]:
    """Return capped paralytic counts from yesterday's 7am through printing."""
    if not isinstance(sheet, dict) or "af" in sheet.get("import_warnings", {}):
        return {}
    data = sheet.get("prn")
    try:
        validate_prn(data)
        if data is None:
            return {}
        start, end = prn_window(as_of)
        start_utc, end_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        return {drug: min(COUNT_CAP, sum(count for instant, count in automatic_prn_events(data, drug)
                                        if start_utc <= instant.astimezone(timezone.utc) <= end_utc))
                for drug in COUNTED_MEDICATIONS}
    except (ValueError, TypeError, KeyError, OverflowError):
        return {}
