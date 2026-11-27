"""Select an original respiratory section from documented current support."""
from __future__ import annotations

from pathlib import Path
import re

from devices import devices_for_output
from noninvasive import mode_kind, valid_setting
from ventilation import home_vent, mode_rule
from ventilator_modes import control_family, spec, strip_setting_marker


RESP_TEMPLATE_NAMES = {
    "pc": "ACKRPC", "prvc": "ACKRPRVC", "avaps": "ACKRAVAPS",
    "bpap": "ACKRBPAP", "hfnc": "ACKRHFNC", "none": "ACKRNONE",
    "nava": "ACKRNAVA", "home_vent": "ACKRHOMEVENT",
}
RESP_TEMPLATE_FILES = {
    variant: Path(__file__).parent / "templates" / ("resp_" + variant + ".docx")
    for variant in RESP_TEMPLATE_NAMES
}
RESP_TEMPLATE_LABELS = {
    "pc": "Pressure control", "prvc": "Volume-targeted ventilation", "avaps": "AVAPS",
    "bpap": "BPAP", "hfnc": "HFNC", "none": "Basic respiratory section",
    "nava": "NAVA", "home_vent": "Home ventilator",
}

_TRIAL = re.compile(r"\b(?:PS\s*[- /]?\s*CPAP|pressure\s+support\s*-\s*continuous\s+positive\s+airway\s+pressure|CPAP\s+trial)\b", re.I)
_HISTORY = re.compile(r"\b(?:history|historical|hx|h/o|PMH|PSH|previous(?:ly)?|prior|remote|resolved|past|status\s+post|s/p)\b", re.I)
_NEGATIVE = re.compile(r"\b(?:no|not|without|denies|denied|negative\s+for)\b", re.I)
_FUTURE = re.compile(r"\b(?:plan(?:ned|ning)?|possible|suspected|consider(?:ing)?|request(?:ed)?|will|if|pending|anticipated|goal|wean\s+to|trial\s+of)\b", re.I)
_ABSENT_DEVICE = re.compile(
    r"\b(?:removed|discontinued|extubated|decannulated|absent|dislodged|"
    r"not\s+(?:(?:currently|now)\s+)?(?:in\s+place|present|in\s+use)|"
    r"no\s+longer\s+(?:in\s+place|present|in\s+use)|"
    r"planned|requested|awaiting|pending\s+(?:placement|insertion)|to\s+be\s+(?:placed|inserted))\b", re.I,
)
_STATUS_PATTERNS = {
    "room_air": re.compile(r"\broom\s+air\b", re.I),
    "nonintubated": re.compile(r"\b(?:extubated|non[- ]?intubated|not\s+(?:currently\s+)?intubated|no\s+longer\s+intubated|without\s+intubation)\b", re.I),
    "off": re.compile(r"\b(?:off\s+(?:the\s+)?ventilator|ventilator\s*(?::|is)?\s*(?:off|discontinued)|ventilator\s+on\s*:\s*(?:no|off|false))\b", re.I),
}
_UNSUPPORTED_NIV = {"CPAP", "AVAPS NIV", "NAVA NIV"}
_DEVICE_NAMES = {"BiPAP", "CPAP", "HFNC", "Nasal cannula", "AVAPS NIV", "NAVA NIV"}


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _trial_mode(mode: str) -> bool:
    known = spec(mode)
    return bool((known and known[1] == "PS") or _TRIAL.search(mode))


def _airways(sheet: dict) -> dict:
    current = {"ETT": False, "Trach": False, "removed": False}
    for section in ("u", "v"):
        flags = (sheet.get("import_warnings") or {}).get(section, [])
        if any(isinstance(item, dict) and (
            item.get("action") in {"not_updated", "not_imported", "previous_retained", "section_boundary"}
            or item.get("code") == "section_boundary"
        ) for item in flags):
            continue
        try:
            snapshot = devices_for_output(sheet, section)
        except (KeyError, TypeError, AttributeError):
            snapshot = None
        for row in snapshot.get("rows", []) if isinstance(snapshot, dict) else []:
            if not isinstance(row, dict) or not row.get("include", True) or row.get("kind") not in {"ETT", "Trach"}:
                continue
            status = _text(row.get("status"))
            text = " ".join(_text(row.get(key)) for key in ("label", "status"))
            text = re.sub(r"\bnot\s+(?:removed|discontinued)\b", "", text, flags=re.I)
            if (row.get("removed", False) or _ABSENT_DEVICE.search(text)
                    or re.fullmatch(r"(?:no|none)[.]?", status, re.I)):
                current["removed"] = True
                continue
            if not _HISTORY.search(text):
                current[row["kind"]] = True
    return current


def _affirmed(line: str, match: re.Match) -> bool:
    before, after = line[:match.start()], line[match.end():]
    transitions = list(re.finditer(r"(?:^|[,;]\s*|\b(?:and|but|however)\s+)(?:now|currently|today)\b", before, re.I))
    if transitions:
        before = before[transitions[-1].end():]
    if _HISTORY.search(before) or _NEGATIVE.search(before) or _FUTURE.search(before):
        return False
    after = re.sub(r"^\s*[,:(-]\s*", "", after)
    if re.match(
        r"\s*(?:(?:is|are|was|were)\s+)?(?:(?:currently|now)\s+)?"
        r"(?:(?:no|none)(?=\s*(?:$|[.,)]))|not\s+(?:(?:currently|now)\s+)?"
        r"(?:yet|tolerated|confirmed|current|achieved|completed|performed|attempted|"
        r"present|used|in\s+use|established|applicable|possible|done)\b)", after, re.I,
    ):
        return False
    if re.match(r"\s*(?:\?|(?:planned|requested|possible|suspected|tomorrow|historical|previously|in\s+the\s+past|not\s+(?:current|confirmed))\b)", after, re.I):
        return False
    return "?" not in before and "?" not in after[:3]


def _documented_status(sheet: dict) -> dict:
    """Only explicit current respiratory statements can contradict a snapshot."""
    result = {key: False for key in _STATUS_PATTERNS}
    fields = sheet.get("fields") or {}
    text = _text(fields.get("Respiratory")) if isinstance(fields, dict) else ""
    historical_context = False
    for raw in text.splitlines():
        heading = re.fullmatch(r"\s*([^:]+):\s*", raw)
        if heading:
            if _HISTORY.search(heading[1]) or _FUTURE.search(heading[1]):
                historical_context = True
                continue
            if re.search(r"\b(?:current|active|assessment|respiratory)\b", heading[1], re.I):
                historical_context = False
                continue
        if historical_context:
            continue
        for line in re.split(r"[;]|(?<=[.!])\s+(?=[A-Z])|\b(?:but|however)\b", raw):
            for key, pattern in _STATUS_PATTERNS.items():
                if any(_affirmed(line, match) for match in pattern.finditer(line)):
                    result[key] = True
    return result


def _noninvasive(sheet: dict, trial_source: bool) -> tuple[set[str], bool]:
    explicit = set()
    inferred_or_invalid = False
    for row in sheet.get("noninvasive") or []:
        if not isinstance(row, dict) or not row.get("include", True) or row.get("removed", False):
            continue
        if _ABSENT_DEVICE.search(_text(row.get("status"))):
            continue
        name = row.get("device")
        if name not in _DEVICE_NAMES:
            inferred_or_invalid = True
            continue
        # A PS-CPAP source can create a pressure-based CPAP row beside an
        # explicitly named HFNC delivery. A trial never establishes mask CPAP.
        if trial_source and name == "CPAP":
            inferred_or_invalid = True
            continue
        if row.get("pressure_inferred") or row.get("flow_inferred"):
            inferred_or_invalid = True
            continue
        values = row.get("values") or {}
        if not isinstance(values, dict):
            inferred_or_invalid = True
            continue
        if name == "BiPAP" and not all(valid_setting(strip_setting_marker(_text(values.get(key))), key.lower()) for key in ("IPAP", "EPAP")):
            inferred_or_invalid = True
            continue
        if name in {"HFNC", "Nasal cannula"} and _text(values.get("Flow")) and not valid_setting(strip_setting_marker(_text(values["Flow"])), "flow"):
            inferred_or_invalid = True
            continue
        explicit.add(name)
    return explicit, inferred_or_invalid


def _mode_variant(mode: str, snapshot: dict) -> str | None:
    known = spec(mode)
    if _trial_mode(mode) or (known and known[2]) or mode_rule(mode) != "included":
        return None
    family = control_family(mode)
    if family == "AVAPS":
        return "avaps"
    if family == "NAVA":
        return "nava"
    if family not in {"PC", "PRVC", "VC", "VSV"}:
        return None
    try:
        if home_vent(snapshot):
            return "home_vent"
    except (KeyError, TypeError, AttributeError):
        pass
    if family == "PC":
        return "pc"
    if family in {"PRVC", "VC", "VSV"}:
        return "prvc"
    return None


_REASONS = {
    "pc": "The current recorded mode uses pressure-control ventilation.",
    "prvc": "The current volume-targeted ventilation fits the supplied set-volume section.",
    "avaps": "Current invasive AVAPS ventilation is documented.",
    "nava": "Current invasive NAVA ventilation is documented.",
    "home_vent": "The current ventilator snapshot has recorded Pmin and meets the handoff's Home Vent rule.",
    "bpap": "Current explicitly named BPAP support is documented.",
    "hfnc": "Current explicitly named HFNC support is documented.",
}


def _result(variant: str, reason: str, warning: str = "") -> dict:
    return {"variant": variant, "phrase": RESP_TEMPLATE_NAMES[variant],
            "label": RESP_TEMPLATE_LABELS[variant], "reason": reason,
            "warning": warning}


def select_respiratory_variant(sheet: dict, settings: dict | None = None) -> dict:
    """Return variant, exact phrase, label, reason, and optional warning.

    Positive choices use the primary confirmed support snapshot. Other modes,
    medication names, device brands and isolated airway devices cannot supply a
    mode. Specialized invasive AVAPS/NAVA bodies precede the existing Home Vent
    rule, then pressure- or volume-targeted layouts. Source inputs are unchanged.
    ``settings`` is accepted for the shared note-selector interface.
    """
    sheet = sheet if isinstance(sheet, dict) else {}
    warnings = sheet.get("import_warnings") or {}
    if any(key in warnings for key in ("cd", "c", "d")):
        return _result("none", "The respiratory import needs review.",
                       "Retained respiratory settings were not used after a failed import. The basic respiratory section was selected.")
    airways = _airways(sheet)
    documented = _documented_status(sheet)
    snapshot = sheet.get("ventilation") or {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    mode = _text(snapshot.get("mode")) if snapshot.get("include", True) else ""
    source_mode = _text(sheet.get("sbs_vent_mode"))
    trial_source = _trial_mode(mode or source_mode)
    devices, weak_devices = _noninvasive(sheet, trial_source)
    history = snapshot.get("mode_history") or {}
    uncertain = isinstance(history, dict) and history.get("latest_confirmed") is False
    off = documented["off"] or bool(mode and "sbs_vent_mode" in sheet and not source_mode)
    removed = airways["removed"] and not (airways["ETT"] or airways["Trach"])
    no_invasive = documented["room_air"] or documented["nonintubated"]
    discarded_mode = bool(mode and (uncertain or off or removed or no_invasive))
    if uncertain or off or removed or no_invasive:
        mode = ""
    if _trial_mode(mode):
        # A pressure-support trial does not establish the underlying mode.
        # An independently named current cannula/mask remains usable.
        mode = ""

    # Explicit room air, an ETT, or multiple independently named devices can
    # conflict with a pressure/cannula snapshot. Do not choose by list order.
    if (len(devices) > 1 or (devices and (documented["room_air"] or airways["ETT"]))
            or (airways["ETT"] and no_invasive)):
        return _result("none", "Current respiratory support is conflicting.",
                       "Current respiratory sources disagree. The basic respiratory section was selected.")
    device = next(iter(devices), "")
    if off and device in {"BiPAP", "CPAP", "AVAPS NIV", "NAVA NIV"}:
        return _result("none", "The pressure-device record conflicts with documented Ventilator Off.",
                       "Ventilator Off conflicts with pressure support. The basic respiratory section was selected.")
    if mode:
        known = spec(mode)
        mode_niv = bool(known and known[2]) or mode_rule(mode) == "excluded"
        if device:
            same_niv = mode_niv and (mode_kind(mode) == device or (known and known[0] == device))
            if not same_niv:
                return _result("none", "The primary mode and support device disagree.",
                               "Current respiratory sources disagree. The basic respiratory section was selected.")
        variant = _mode_variant(mode, snapshot)
        if variant:
            return _result(variant, _REASONS[variant])
        if device == "BiPAP":
            return _result("bpap", _REASONS["bpap"])
        return _result("none", "The current mode has no matching supplied respiratory section.",
                       "The recorded mode is a trial, unsupported mode, or NIV mode without a matching supplied section. The basic respiratory section was selected.")
    if device in _UNSUPPORTED_NIV:
        return _result("none", "The documented NIV mode has no matching supplied respiratory section.",
                       "No matching CPAP, AVAPS NIV, or NAVA NIV section was supplied. The basic respiratory section was selected.")
    if device in {"BiPAP", "HFNC"}:
        variant = "bpap" if device == "BiPAP" else "hfnc"
        warning = ("Retained or unconfirmed ventilator settings were omitted in favor of the current named support device."
                   if discarded_mode else "")
        return _result(variant, _REASONS[variant], warning)
    if device == "Nasal cannula" or documented["room_air"]:
        return _result("none", "Room air or standard nasal cannula fits the basic respiratory section.")
    if discarded_mode:
        return _result("none", "The retained ventilator mode does not establish current support.",
                       "The ventilator mode is unconfirmed, off, or contradicted by current airway documentation. The basic respiratory section was selected.")
    if weak_devices or source_mode or trial_source or airways["ETT"]:
        return _result("none", "There is no matching confirmed current support snapshot.",
                       "Incomplete, inferred, or trial support did not establish a matching current mode. The basic respiratory section was selected.")
    return _result("none", "No matching current respiratory support is documented.")
