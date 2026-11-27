"""Select an original neurologic section from current documented handoff facts."""
from __future__ import annotations

from pathlib import Path
import re

from devices import devices_for_output
from icp_cpp import parse_icp_cpp
from nirs import is_nirs_label, parse_nirs_line
from note_medications import build_note_medications
from ventilation import mode_rule
from ventilator_modes import spec


NEURO_TEMPLATE_NAMES = {
    "ct_patient": "ACKNCTPATIENT",
    "none": "ACKNNONE",
    "icp_monitoring": "ACKNICPMONITORING",
    "intubated": "ACKNINTUBATED",
    "tbi": "ACKNTBI",
    "status_epilepticus": "ACKNSTATUSEPI",
    "extubated": "ACKNEXTUBATED",
}
NEURO_TEMPLATE_FILES = {
    variant: Path(__file__).parent / "templates" / ("neuro_" + variant + ".docx")
    for variant in NEURO_TEMPLATE_NAMES
}
NEURO_TEMPLATE_LABELS = {
    "ct_patient": "Cerebral oximetry / cardiac care",
    "none": "Basic neurologic section",
    "icp_monitoring": "ICP monitoring",
    "intubated": "Intubated / ventilated",
    "tbi": "Traumatic brain injury",
    "status_epilepticus": "Status epilepticus",
    "extubated": "Extubated / nonintubated monitoring",
}

_PATTERNS = {
    "tbi": r"\b(?:TBI|traumatic\s+brain\s+injury)\b",
    "status_epilepticus": r"\b(?:status\s+epilepticus|NCSE)\b",
    "icp": r"\b(?:ICP\s+(?:monitor(?:ing)?|bolt|microsensor)|intracranial\s+pressure\s+monitor(?:ing)?|EVD|external\s+ventricular\s+drain(?:age)?|ventriculostomy)\b",
    "ct": r"\b(?:(?:cardiac|cardiothoracic)\s+(?:surg(?:ery|ical)|post[- ]?op(?:erative)?)|cardiothoracic\s+patient|post[- ]?op(?:erative)?\s+(?:cardiac|cardiothoracic)|cerebral\s+(?:NIRS|oximetry)|(?:NIRS|rSO[2₂])\s+cerebral)\b",
    "intubated": r"\b(?:intubated|re[- ]?intubated|invasive\s+(?:mechanical\s+)?ventilation|mechanically\s+ventilated|endotracheal\s+tube(?:\s+in\s+place)?)\b",
    "nonintubated": r"\b(?:non[- ]?intubated|not\s+(?:currently\s+)?intubated|without\s+(?:endotracheal\s+)?intubation|room\s+air|HFNC|nasal\s+cannula|BiPAP|NIV|NIPPV|CPAP\s+NIV)\b",
    "extubated": r"\b(?:extubated|post[- ]?extubation|after\s+extubation)\b",
    "monitoring": r"\b(?:CAPD|WAT(?:[- ]?1)?|withdrawal\s+(?:monitoring|assessment)|sedation\s+(?:monitoring|wean)|opioid\s+(?:withdrawal|wean)|benzodiazepine\s+(?:withdrawal|wean))\b",
}
_PATTERNS = {key: re.compile(pattern, re.I) for key, pattern in _PATTERNS.items()}
_MISSING = {"", "none", "unknown", "unk", "--", "-", "n/a", "not recorded", "not documented", "not assessed", "no data recorded"}
_HISTORY = re.compile(r"\b(?:history(?:\s+of)?|hx(?:\s+of)?|h/o|PMH|PSH|previous(?:ly)?|prior|remote|resolved|sequelae|status\s+post|s/p|family|maternal|paternal)\b", re.I)
_NEGATIVE = re.compile(r"\b(?:no|not|without|negative\s+for|absence\s+of|denies|denied|ruled\s+out|excluded|neither)\b", re.I)
_FUTURE = re.compile(r"\b(?:possible|suspected|concern\s+for|rule[- ]out|r/o|evaluat(?:e|ion)\s+for|question\s+of|cannot\s+exclude|may\s+have|differential|risk\s+(?:for|of)|plan(?:ned|ning)?|consider(?:ing)?|request(?:ed)?|recommend(?:ed)?|needs?|will|if|pending|anticipated|monitor\s+for)\b", re.I)
_CURRENT = re.compile(r"\b(?:now|currently|current|new\s+onset|ongoing|active|today)\b", re.I)
_STOP_DEVICE = re.compile(r"\b(?:removed|discontinued|extubated|decannulated|absent|not\s+(?:(?:currently|now)\s+)?(?:in\s+place|present|in\s+use)|no\s+longer\s+(?:in\s+place|present|in\s+use)|no\s+(?:EVD|ETT|ICP\s+monitor|trach)|planned|requested|awaiting|pending\s+(?:placement|insertion)|to\s+be\s+(?:placed|inserted))\b", re.I)
_TRIAL_MODE = re.compile(r"\b(?:PS\s*[- /]?\s*CPAP|pressure\s+support\s*-\s*continuous\s+positive\s+airway\s+pressure|CPAP\s+trial)\b", re.I)
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"


def _statements(sheet: dict, settings: dict | None) -> list[str]:
    fields = sheet.get("fields") or {}
    if not isinstance(fields, dict):
        return []
    destination = (settings or {}).get("diagnoses_destination", "Diagnoses")
    diagnosis_keys = {"Diagnoses", destination} - {"", None}
    keys = list(dict.fromkeys(["Diagnoses", destination, "Neurologic", "Respiratory", "Cardiovascular"]))
    warnings = sheet.get("import_warnings") or {}
    result = []
    for key in keys:
        value = fields.get(key, "")
        if not isinstance(value, str) or (key in diagnosis_keys and "a" in warnings):
            continue
        historical_context = False
        for raw in value.splitlines():
            heading = re.fullmatch(r"\s*([^:]+):\s*", raw)
            if heading:
                name = heading[1]
                if _HISTORY.search(name) or re.search(r"\b(?:planned|requested|goals|past)\b", name, re.I):
                    historical_context = True
                    continue
                if re.search(r"\b(?:current|active|assessment|diagnoses|neurologic|respiratory|cardiovascular)\b", name, re.I):
                    historical_context = False
                    continue
            if historical_context:
                continue
            for line in re.split(r"[;]|(?<=[.!])\s+(?=[A-Z])|\b(?:but|however)\b", raw):
                line = re.sub(r"^\s*(?:[•*\-]|\d+[.)])\s*", "", line).strip()
                if line and line not in result:
                    result.append(line)
    return result


def _assertion(line: str, match: re.Match, key: str) -> str:
    before, after = line[:match.start()], line[match.end():]
    explicit_current = bool(_CURRENT.search(before))
    # Current is often an adjective inside a negation or uncertainty phrase.
    # Reset history only at an explicit new clause, never in "no current TBI"
    # or "not currently intubated".
    transitions = list(re.finditer(
        r"(?:^|[,;]\s*|\b(?:and|but|however)\s+)(?:now|currently|today|new\s+onset)\b",
        before, re.I,
    ))
    if transitions:
        before = before[transitions[-1].end():]
    after = re.sub(r"^\s*[,:(-]\s*", "", after)
    # A nonintubated phrase contains its own negation of intubation.
    if key == "intubated" and re.search(r"\bnon[- ]*$", before, re.I):
        return "negative"
    if (_NEGATIVE.search(before) or re.match(
        r"\s*(?:(?:is|was|has\s+been|remains)\s+)?(?:ruled\s+out|excluded|absent|none|negative|not\s+(?:(?:currently|now)\s+)?(?:present|active|in\s+place)|no\s+longer\s+(?:present|active|in\s+place)|removed|discontinued|stopped)\b",
        after, re.I,
    )):
        return "negative"
    history = bool(_HISTORY.search(before) or re.match(
        r"\s*(?:(?:is|was|has)\s+)?(?:resolved|historical|remote|sequelae|in\s+the\s+past)\b", after, re.I,
    ))
    if key == "ct" and re.search(r"\b(?:POD\s*#?\s*\d+|post[- ]?op(?:erative)?)\b", line, re.I):
        history = bool(re.search(r"\b(?:history|previous|prior|remote|family|maternal|paternal)\b", before, re.I))
    if history:
        return "history"
    if (_FUTURE.search(before) or re.match(
        r"\s*(?:(?:placement|insertion|removal)\s+)?(?:\?|(?:unlikely|not\s+confirmed|unconfirmed|not\s+ruled\s+out|possible|suspected|planned|requested|will|to\s+be|tomorrow|prophylaxis|prevention|screening)\b)",
        after, re.I,
    ) or "?" in before or "?" in after[:3]):
        return "uncertain"
    if key == "ct":
        phrase = match[0].casefold()
        # A surgical history or a CHD label alone does not establish current
        # cardiac postoperative care. Cerebral monitoring is independent.
        if "surg" in phrase and not re.search(
            r"\b(?:POD\s*#?\s*\d+|post[- ]?op(?:erative)?)\b|\b(?:underwent|after|following)\s+(?:cardiac|cardiothoracic)\s+surgery\s+(?:today|yesterday)\b", line, re.I,
        ):
            return "uncertain"
    return "current" if explicit_current else "positive"


def _evidence(lines: list[str], key: str) -> tuple[bool, bool]:
    states = {_assertion(line, match, key) for line in lines for match in _PATTERNS[key].finditer(line)}
    active = bool(states & {"positive", "current"})
    blocked = bool(states & {"negative", "uncertain"} or ("history" in states and "current" not in states))
    return active and not blocked, active and blocked


def _device_evidence(sheet: dict) -> dict:
    found = {"ett": False, "trach": False, "icp": False, "removed_ett": False, "removed_icp": False}
    for section in ("u", "v"):
        try:
            snapshot = devices_for_output(sheet, section)
        except (TypeError, KeyError, AttributeError):
            snapshot = None
        if not isinstance(snapshot, dict):
            continue
        for row in snapshot.get("rows", []):
            if not isinstance(row, dict) or not row.get("include", True):
                continue
            kind = row.get("kind")
            if kind not in {"ETT", "Trach", "EVD", "ICP monitor"}:
                continue
            text = " ".join(str(row.get(key, "")) for key in ("label", "status"))
            text = re.sub(r"\bnot\s+(?:removed|discontinued)\b", "", text, flags=re.I)
            removed = bool(row.get("removed", False) or _STOP_DEVICE.search(text))
            if removed:
                if kind == "ETT":
                    found["removed_ett"] = True
                elif kind in {"EVD", "ICP monitor"}:
                    found["removed_icp"] = True
                continue
            found[{"ETT": "ett", "Trach": "trach", "EVD": "icp", "ICP monitor": "icp"}[kind]] = True
    return found


def _support(sheet: dict, devices: dict, evidence: dict) -> dict:
    warnings = sheet.get("import_warnings") or {}
    current_niv = False
    vent = sheet.get("ventilation") or {}
    mode = ""
    if "cd" not in warnings:
        history = vent.get("mode_history") or {}
        if history.get("latest_confirmed") is not False and ("sbs_vent_mode" not in sheet or sheet["sbs_vent_mode"]):
            mode = str(vent.get("mode", "")).strip()
        for row in sheet.get("noninvasive") or []:
            if (isinstance(row, dict) and row.get("include", True) and row.get("device")
                    and not row.get("pressure_inferred") and not row.get("flow_inferred")):
                current_niv = True
    known = spec(mode) if mode else None
    trial = bool(_TRIAL_MODE.search(mode))
    noninvasive_mode = bool(mode and not trial and ((known and known[2]) or mode_rule(mode) == "excluded"))
    mode_invasive = bool(mode and not trial and mode_rule(mode) == "included")
    extubated = evidence["extubated"][0]
    nonintubated = current_niv or noninvasive_mode or evidence["nonintubated"][0] or extubated
    airway = devices["ett"]
    # Removed ETT history can coexist with a new current tube or trach. Without
    # that corroboration, do not revive old ventilator settings after removal.
    if devices["removed_ett"] and not (airway or devices["trach"] or evidence["intubated"][0]):
        mode_invasive = False
    if extubated and not airway:
        mode_invasive = False
    invasive = airway or mode_invasive or evidence["intubated"][0]
    conflict = bool(invasive and nonintubated)
    # A current included ETT is stronger than an unqualified extubation event
    # in prose, which may describe an earlier event before reintubation.
    if airway and not (current_niv or noninvasive_mode or evidence["nonintubated"][0]):
        invasive, nonintubated = True, False
    elif conflict:
        invasive, nonintubated = False, False
    return {"invasive": invasive, "nonintubated": nonintubated,
            "extubated": extubated and not invasive and not conflict, "conflict": conflict}


def _current_nirs(sheet: dict) -> bool:
    if "e" in (sheet.get("import_warnings") or {}):
        return False
    for row in sheet.get("vitals") or []:
        if not isinstance(row, dict) or not row.get("include", True) or row.get("section") != "Neurologic":
            continue
        label, value = str(row.get("label", "")), str(row.get("value", ""))
        if not is_nirs_label(label) or not re.search(_NUMBER, value):
            continue
        if _HISTORY.search(value) or _NEGATIVE.search(value) or _FUTURE.search(value) or _STOP_DEVICE.search(value):
            continue
        try:
            parsed = parse_nirs_line(label + ": " + value)
        except ValueError:
            continue
        if parsed and parsed[1]:
            return True
    return False


def _current_icp(sheet: dict, devices: dict, lines: list[str]) -> bool:
    if "m" in (sheet.get("import_warnings") or {}) or (devices["removed_icp"] and not devices["icp"]):
        return False
    if any(_assertion(line, match, "icp") == "negative"
           for line in lines for match in _PATTERNS["icp"].finditer(line)):
        return False
    rows = (sheet.get("neuro_vitals") or {}).get("m", [])
    recorded = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("include", True):
            continue
        label, value = str(row.get("label", "")), str(row.get("value", "")).strip()
        if value.casefold().rstrip(".") in _MISSING:
            continue
        if _HISTORY.search(value) or _FUTURE.search(value) or _STOP_DEVICE.search(value):
            continue
        recorded.append(label + ": " + value)
    if not recorded:
        return False
    parsed = parse_icp_cpp("\n".join(recorded))
    return not parsed.error and bool(parsed.rows)


def _monitoring(sheet: dict, evidence: dict, medications: dict | None) -> bool:
    if evidence["monitoring"][0]:
        return True
    neuro = sheet.get("neuro_vitals") or {}
    warnings = sheet.get("import_warnings") or {}
    for section in ("y", "l"):
        if section in warnings:
            continue
        for row in neuro.get(section, []):
            if not isinstance(row, dict) or not row.get("include", True):
                continue
            value = str(row.get("value", "")).strip()
            if _HISTORY.search(value) or _FUTURE.search(value) or _STOP_DEVICE.search(value):
                continue
            if value.casefold().rstrip(".") not in _MISSING and re.search(_NUMBER, value):
                return True
    if "b" in warnings:
        return False
    if medications is None:
        medications = build_note_medications(sheet)
    for entry in (medications or {}).get("entries", []):
        if not entry.get("active"):
            continue
        path = entry.get("category_path") or {}
        category = " ".join(str(path.get(key, "")) for key in ("name", "parent_name"))
        if re.search(r"\b(?:sedatives?|sedation|withdrawal|wean|taper)\b", category, re.I):
            return True
        name = str(entry.get("source_name") or entry.get("name") or "")
        if re.search(r"\b(?:dexmedetomidine|midazolam|propofol|methadone)\b", name, re.I):
            return True
        if entry.get("group") == "Drips" and re.search(r"\b(?:fentanyl|morphine|hydromorphone|ketamine)\b", name, re.I):
            return True
    return False


def _result(variant: str, reason: str, warnings: list[str]) -> dict:
    return {"variant": variant, "phrase": NEURO_TEMPLATE_NAMES[variant],
            "label": NEURO_TEMPLATE_LABELS[variant], "reason": reason,
            "warning": " ".join(dict.fromkeys(warnings))}


def select_neuro_variant(sheet: dict, *, settings: dict | None = None,
                         medications: dict | None = None) -> dict:
    """Return variant, exact phrase, label, reason, and optional warning.

    Priority is TBI, ICP/EVD, status epilepticus, cerebral oximetry/cardiac care,
    invasive support, then documented nonintubated monitoring or extubation.
    No medication establishes TBI or status epilepticus. Hidden observations,
    removed devices and proposed findings never establish current support.
    Inputs are read only. Unknown cases use the basic supplied section.
    """
    sheet = sheet if isinstance(sheet, dict) else {}
    lines = _statements(sheet, settings)
    evidence = {key: _evidence(lines, key) for key in _PATTERNS}
    devices = _device_evidence(sheet)
    warnings = []
    if any(conflict for _, conflict in evidence.values()):
        warnings.append("Conflicting or uncertain neurologic statements were not used to choose a specific section.")
    if evidence["tbi"][0]:
        return _result("tbi", "Current handoff documents traumatic brain injury.", warnings)
    if devices["icp"] or (evidence["icp"][0] and not devices["removed_icp"]):
        return _result("icp_monitoring", "A current ICP monitor, EVD, or active intracranial monitoring is documented.", warnings)
    if _current_icp(sheet, devices, lines):
        return _result("icp_monitoring", "Current included ICP/CPP monitoring measurements are documented.", warnings)
    if evidence["status_epilepticus"][0]:
        return _result("status_epilepticus", "Current handoff documents status epilepticus.", warnings)
    if _current_nirs(sheet) or evidence["ct"][0]:
        return _result("ct_patient", "Current cerebral oximetry or cardiac postoperative care is documented.", warnings)
    support = _support(sheet, devices, evidence)
    if support["conflict"]:
        warnings.append("Current airway findings conflict. The section uses the best supported current findings.")
    if support["invasive"]:
        return _result("intubated", "A current endotracheal tube or invasive ventilation is documented.", warnings)
    if support["extubated"]:
        return _result("extubated", "Current handoff explicitly documents extubation.", warnings)
    if support["nonintubated"] and _monitoring(sheet, evidence, medications):
        return _result("extubated", "Nonintubated support with sedation, delirium, or withdrawal monitoring is documented.", warnings)
    return _result("none", "No more specific current neurologic findings are documented.", warnings)
