"""Read a W-section pacing snapshot without inferring settings from other data."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from import_review import diagnostic

EDIT_FIELDS = ("mode", "atrial_rate", "ventricular_rate", "rate", "status", "include")
STATUSES = ("Documented", "Off", "Standby")
MISSING = {"", "--", "-", "none", "n/a", "na", "not documented", "no data recorded", "unknown", "unk"}
MODE_FIELDS = {"pacer mode", "pacing mode", "pacemaker mode", "mode"}
RATE_FIELDS = {
    "atrial rate": "atrial_rate", "atrial pacing rate": "atrial_rate", "a rate": "atrial_rate",
    "ventricular rate": "ventricular_rate", "ventricular pacing rate": "ventricular_rate", "v rate": "ventricular_rate",
    "pacer rate": "rate", "pacemaker rate": "rate", "pacing rate": "rate", "rate": "rate",
    "pacer rate setting": "rate", "set rate": "rate",
}
PRESENCE_FIELDS = {"pacemaker", "pacemaker present", "pacer present"}
STATUS_FIELDS = {"pacer status", "pacemaker status", "pacing status"}


@dataclass
class PacemakerResult:
    data: dict | None = None
    error: str = ""
    issues: list[str] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


def _label(value: str) -> str:
    value = re.sub(r"\s*\((?:beats\s*/\s*min(?:ute)?|bpm)\)\s*", " ", value, flags=re.I)
    return _clean(value).rstrip(":").casefold()


def normalize_mode(value: str) -> str:
    value = _clean(value)
    return "" if value.casefold() in MISSING else value.upper()


def normalize_rate(value: str) -> str:
    value = re.sub(r"^\(S\)\s*", "", _clean(value), flags=re.I)
    if value.casefold() in MISSING:
        return ""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:bpm|beats\s*/\s*min(?:ute)?)?", value, re.I)
    if not match:
        raise ValueError("A pacemaker rate could not be read as a single beats-per-minute value.")
    return match.group(1)


def validate_pacemaker(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != set(EDIT_FIELDS):
        raise ValueError("The pacemaker snapshot has an invalid structure.")
    for key in ("mode", "atrial_rate", "ventricular_rate", "rate", "status"):
        value = data[key]
        if not isinstance(value, str) or len(value) > 100 or any(ord(c) < 32 for c in value):
            raise ValueError("A pacemaker field is invalid or too long.")
    if data["status"] not in STATUSES or type(data["include"]) is not bool:
        raise ValueError("The pacemaker display settings are invalid.")
    for key in ("atrial_rate", "ventricular_rate", "rate"):
        if data[key] and not re.fullmatch(r"\d+(?:\.\d+)?", data[key]):
            raise ValueError("Enter a pacemaker rate as a number in bpm, or leave it blank.")


def _chamber(mode: str) -> str:
    # Match explicit mode codes only. Descriptive labels are not assigned a mode.
    match = re.match(r"^([AVD])(?:[AVDO])(?:[ITDO])(?:R)?(?:\b|$)", mode, re.I)
    return match.group(1).upper() if match else ""


def _rate_summary(data: dict) -> str:
    mode = data["mode"] or "Mode UNK"
    a, v, generic = data["atrial_rate"], data["ventricular_rate"], data["rate"]
    chamber = _chamber(data["mode"])
    if chamber in ("A", "V"):
        rate = (a if chamber == "A" else v) or generic
        return mode + (" at " + rate + " bpm" if rate else " | Rate: UNK")
    if chamber == "D" and a and v and float(a) == float(v):
        return mode + " at " + a + " bpm"
    if not a and not v and generic:
        return mode + " at " + generic + " bpm"
    details = []
    if a:
        details.append("Atrial rate: " + a + " bpm")
    if v:
        details.append("Ventricular rate: " + v + " bpm")
    if generic:
        details.append("Set rate: " + generic + " bpm")
    return mode + " | " + " | ".join(details or ["Rate: UNK"])


def format_pacemaker(data: dict | None) -> str:
    validate_pacemaker(data)
    if data is None or not data["include"]:
        return ""
    if data["status"] in ("Off", "Standby"):
        return "Pacemaker: " + data["status"]
    return "Pacemaker: " + _rate_summary(data)


def pacemaker_text(sheet: dict) -> str:
    if any(i["action"] == "pacemaker_hidden" for i in sheet.get("import_warnings", {}).get("w", [])):
        return ""
    return format_pacemaker(sheet.get("pacemaker"))


def parse_pacemaker(text: str) -> PacemakerResult:
    """Parse tab/colon key-value rows from W. No heart rate or output-mA fallback."""
    out = PacemakerResult()
    if not isinstance(text, str) or len(text) > 20000:
        out.error = "The pacemaker section is invalid or too large."
        return out
    found: dict[str, str] = {}
    relevant = False
    substantive = False
    def put(key: str, value: str) -> None:
        if not value:
            return
        if key in found and found[key].casefold() != value.casefold():
            raise ValueError("Conflicting pacemaker fields were supplied. Check the W section against Epic.")
        found[key] = value
    try:
        for raw in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
            line = raw.strip().replace("\u00a0", " ")
            if not line or line.casefold().rstrip(":") in MISSING | {"pacemaker", "pacemaker settings", "pacing"}:
                continue
            if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{2}:?\d{2})?", line):
                continue  # Collection/documentation time is not the pacing rate.
            if re.match(r"^\[\s*removed\s*\]", line, re.I):
                continue
            cells = re.split(r"\t+|:\s*| {2,}", line, maxsplit=1)
            substantive = True
            if len(cells) != 2:
                if _label(line) in MODE_FIELDS | set(RATE_FIELDS) | PRESENCE_FIELDS | STATUS_FIELDS:
                    relevant = True
                continue
            label, value = _label(cells[0]), _clean(cells[1])
            if label in PRESENCE_FIELDS:
                relevant = True
                val = value.casefold()
                if val in {"yes", "present", "on", "active"}:
                    put("presence", "yes")
                elif val in {"no", "none", "absent", "not present", "removed"}:
                    put("presence", "no")
                elif val in {"off", "standby", "not pacing", "disconnected"}:
                    put("status", "Standby" if val == "standby" else "Off")
                elif val not in MISSING:
                    raise ValueError("Pacemaker presence could not be read. Check the W section.")
            elif label in MODE_FIELDS:
                relevant = True
                mode = normalize_mode(value)
                if mode.casefold() in {"off", "standby", "not pacing", "disconnected"}:
                    put("status", "Standby" if mode.casefold() == "standby" else "Off")
                else:
                    put("mode", mode)
            elif label in RATE_FIELDS:
                relevant = True
                put(RATE_FIELDS[label], normalize_rate(value))
            elif label in STATUS_FIELDS:
                relevant = True
                if value.casefold() in {"off", "standby", "not pacing", "disconnected"}:
                    put("status", "Standby" if value.casefold() == "standby" else "Off")
                elif value.casefold() in {"on", "pacing", "active", "yes", "documented"}:
                    put("status", "Documented")
                elif value.casefold() not in MISSING:
                    raise ValueError("Pacemaker status could not be read. Check the W section.")
            # Output, sensing, wire and device-type fields are not rate fields.
        if found.get("presence") == "no":
            return out
        if not relevant:
            if substantive:
                out.error = "No supported pacemaker fields were found. Check the W section."
            return out
        if not found:
            return out
        data = {key: found.get(key, "") for key in ("mode", "atrial_rate", "ventricular_rate", "rate")}
        data.update(status=found.get("status", "Documented"), include=True)
        validate_pacemaker(data)
        # Conflicting generic and chamber-specific rate fields cannot be silently reconciled.
        chamber = _chamber(data["mode"])
        selected = data["atrial_rate"] if chamber == "A" else data["ventricular_rate"] if chamber == "V" else ""
        if data["status"] == "Documented" and selected and data["rate"] and float(selected) != float(data["rate"]):
            raise ValueError("Conflicting pacemaker rate fields were supplied. Check the W section against Epic.")
        if data["status"] == "Documented" and (not data["mode"] or "UNK" in _rate_summary(data)):
            out.diagnostics.append(diagnostic("w", "pacemaker_incomplete", action="field_unknown"))
            out.issues.append("Pacemaker mode or matching rate is missing. The summary shows UNK rather than using heart rate or another chamber's rate.")
        out.data = data
    except ValueError as exc:
        out.error = str(exc)
        out.data = None
        out.diagnostics.clear()
    return out
