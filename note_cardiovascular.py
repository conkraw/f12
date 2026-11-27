"""Choose a supplied cardiovascular section from current recorded supports."""
from __future__ import annotations

from pathlib import Path
import re

from arterial_pressure import parse_arterial_line
from devices import devices_for_output
from ecls import validate_ecls
from pacemaker import validate_pacemaker
from vitals import monitor_kind, monitor_summary_range


CV_TEMPLATE_NAMES = {
    "art": "ACKCVART",
    "art_cvl": "ACKCVARTCVL",
    "art_cvl_ecls": "ACKCVARTCVLECLS",
    "art_cvl_pacemaker": "ACKCVARTCVLPACEMAKER",
    "cvl": "ACKCVCVL",
    "none": "ACKCVNONE",
}
CV_TEMPLATE_FILES = {
    variant: Path(__file__).parent / "templates" / ("cv_" + variant + ".docx")
    for variant in CV_TEMPLATE_NAMES
}
CV_TEMPLATE_LABELS = {
    "art": "Arterial line monitoring",
    "art_cvl": "Arterial and central venous monitoring",
    "art_cvl_ecls": "ECLS monitoring",
    "art_cvl_pacemaker": "Pacemaker monitoring",
    "cvl": "Central venous monitoring",
    "none": "Basic cardiovascular section",
}

_ART = r"(?:arterial\s+(?:lines?|catheters?)|a[- ]lines?|UAC|umbilical\s+arter(?:y|ial)\s+catheters?)"
_CENTRAL = (
    r"(?:CVC|CVL|PICC|UVC|central(?:\s+venous)?\s+(?:lines?|catheters?)|"
    r"peripherally\s+inserted\s+central\s+catheters?|umbilical\s+venous\s+catheters?|"
    r"port[- ]?a[- ]?cath|implanted\s+port|hemodialysis\s+catheters?)"
)
_PACEMAKER = (
    r"(?:pacemaker|pacer(?:\s+wires?)?|(?:temporary|epicardial)\s+(?:pacing\s+)?wires?|"
    r"pacing\s+wires?|transvenous\s+pacing\s+catheter)"
)
_PATTERNS = {
    "art": re.compile(r"\b" + _ART + r"\b", re.I),
    "central": re.compile(r"\b" + _CENTRAL + r"\b", re.I),
    "pacemaker": re.compile(r"\b" + _PACEMAKER + r"\b", re.I),
    "ecls": re.compile(r"\b(?:ECLS|ECMO|extracorporeal\s+(?:life\s+support|membrane\s+oxygenation))\b", re.I),
}
_HISTORY = re.compile(
    r"\b(?:history(?:\s+of)?|hx(?:\s+of)?|h/o|PMH|PSH|prior|previous(?:ly)?|remote|"
    r"historical|resolved|status\s+post|s/p|family|maternal|paternal)\b", re.I,
)
_FUTURE = re.compile(
    r"\b(?:plan(?:ned|ning)?|consider(?:ing)?|request(?:ed)?|recommend(?:ed)?|needs?|"
    r"will|if|pending|awaiting|anticipated|possible|suspected|concern\s+for|"
    r"evaluate\s+for|evaluation\s+for|risk\s+(?:for|of))\b", re.I,
)
_NEGATIVE = re.compile(r"\b(?:no|not|without|absent|absence\s+of|negative\s+for|denies|denied)\b", re.I)
_ABSENT = (
    r"(?:absent|none|removed|discontinued|no(?=\s*[.,)]?$)|not\s+(?:(?:currently|now)\s+)?"
    r"(?:present|in\s+place|available)|no\s+longer\s+(?:present|in\s+place|available))"
)
_ECLS_STOP = r"(?:off|stopped|decannulated|discontinued|inactive|weaned\s+off|(?:not|no\s+longer)\s+(?:running|on\s+support))"
_VERB = r"(?:(?:is|are|was|were|has\s+been|have\s+been|remains?)\s+)?(?:(?:currently|now)\s+)?"
_MISSING = {"", "none", "n/a", "na", "unknown", "unk", "--", "-", "not recorded", "not documented", "no data recorded"}
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_PRESSURE_UNIT = r"(?:mm\s*hg|cm\s*h[2₂]o|kpa)"


def _blocked(sheet: dict, section: str, hidden_action: str) -> bool:
    flags = (sheet.get("import_warnings") or {}).get(section, [])
    return any(isinstance(item, dict) and (
        item.get("action") in {hidden_action, "not_updated", "not_imported", "previous_retained", "section_boundary"}
        or item.get("code") == "section_boundary"
    ) for item in flags)


def _statements(sheet: dict, settings: dict | None) -> list[str]:
    fields = sheet.get("fields") or {}
    if not isinstance(fields, dict):
        return []
    destination = (settings or {}).get("diagnoses_destination", "Diagnoses")
    keys = list(dict.fromkeys(["Diagnoses", destination, "Cardiovascular"]))
    diagnosis_keys = {"Diagnoses", destination}
    lines = []
    for key in keys:
        value = fields.get(key, "")
        if not isinstance(value, str) or (key in diagnosis_keys and "a" in (sheet.get("import_warnings") or {})):
            continue
        historical = False
        for raw in value.splitlines():
            heading = re.fullmatch(r"\s*([^:]+):\s*", raw)
            if heading:
                title = heading[1]
                if _HISTORY.search(title) or _FUTURE.search(title) or re.search(r"\bpast\b", title, re.I):
                    historical = True
                    continue
                if re.search(r"\b(?:current|active|assessment|diagnoses|cardiovascular|lines|devices)\b", title, re.I):
                    historical = False
                    continue
            if historical:
                continue
            for part in re.split(r"[;]|(?<=[.!])\s+(?=[A-Z])|\b(?:but|however)\b", raw):
                part = re.sub(r"^\s*(?:[•*\-]|\d+[.)])\s*", "", part).strip()
                if part and part not in lines:
                    lines.append(part)
    return lines


def _assertion(line: str, match: re.Match, key: str) -> str:
    before, after = line[:match.start()], line[match.end():]
    # Only a new clause resets a prior qualifier. "No current central line"
    # and "possible current ECMO" must retain their qualifiers.
    transitions = list(re.finditer(
        r"(?:^|[,;]\s*|\b(?:and|but|however)\s+)(?:now|currently|today|new)\b", before, re.I,
    ))
    if transitions:
        before = before[transitions[-1].end():]
    after = re.sub(r"^\s*[,:(-]\s*", "", after).strip()
    # A separate, explicit present-tense clause can follow a negated other
    # line without inheriting that line's negation.
    if "," in before and re.match(_VERB + r"(?:present|in\s+place|patent|inserted|placed)\b", after, re.I):
        before = before.rsplit(",", 1)[1]
    if _HISTORY.search(before) or re.match(_VERB + r"(?:historical|history|remote|prior|previous(?:ly)?|in\s+the\s+past)\b", after, re.I):
        return "history"
    if key == "pacemaker":
        if re.match(r"(?:[- ]*dependent|\s*dependency)\b", after, re.I) and _NEGATIVE.search(before):
            return "unsupported"
        if re.match(_VERB + r"not\s+(?:(?:currently|now)\s+)?dependent\b", after, re.I):
            return "unsupported"
        # Turning pacing off does not remove the pacemaker or its wires.
        before = re.sub(r"\bnot\s+(?:currently\s+)?pacing\b", "", before, flags=re.I)
    before = re.sub(r"\bnot\s+(?:removed|discontinued)\b", "", before, flags=re.I)
    if (_NEGATIVE.search(before)
            or re.match(_VERB + _ABSENT + r"\b", after, re.I)
            or (key == "ecls" and (re.search(r"\b(?:off|decannulated(?:\s+from)?|weaned\s+off)\s+(?:(?:VA|VV)[- ]*)?$", before, re.I)
                                   or re.match(_VERB + _ECLS_STOP + r"\b", after, re.I)
                                   or re.match(r"(?:support\s+)?" + _VERB + r"(?:not\s+(?:(?:currently|now)\s+)?|no\s+longer\s+)(?:indicated|needed|required|used|running|active)\b", after, re.I)))):
        return "negative"
    if (_FUTURE.search(before) or re.match(
        _VERB + r"(?:line\s+)?(?:(?:placement|insertion|cannulation|removal)\s+)?(?:planned|requested|proposed|pending|will|to\s+be|tomorrow)\b",
        after, re.I,
    ) or "?" in before or "?" in after[:3]):
        return "future"
    if key == "ecls" and re.search(r"\bcannula(?:e|s)?\b", line, re.I):
        if not re.search(r"\b(?:on|receiving|continues?\s+on)\s+(?:(?:VA|VV)[- ]*)?(?:ECMO|ECLS)\b|\b(?:ECMO|ECLS)\s+support\b", line, re.I):
            return "unsupported"
    return "positive"


def _text_evidence(lines: list[str]) -> tuple[dict, dict]:
    positive = {key: False for key in _PATTERNS}
    absent = dict(positive)
    for line in lines:
        for key, pattern in _PATTERNS.items():
            for match in pattern.finditer(line):
                state = _assertion(line, match, key)
                positive[key] |= state == "positive"
                absent[key] |= state == "negative"
        if (re.search(r"\bno\s+(?:current\s+)?(?:invasive\s+|vascular\s+)?lines\b", line, re.I)
                or re.fullmatch(r"(?:current\s+)?(?:lines|vascular\s+access)\s*:\s*" + _ABSENT + r"[.]?", line, re.I)):
            absent["art"] = absent["central"] = True
    return positive, absent


def _device_evidence(sheet: dict) -> tuple[dict, dict]:
    positive = {key: False for key in ("art", "central", "pacemaker")}
    absent = dict(positive)
    for section, hidden in (("u", "devices_hidden"), ("v", "neuro_devices_hidden")):
        if _blocked(sheet, section, hidden):
            continue
        try:
            snapshot = devices_for_output(sheet, section)
        except (TypeError, KeyError, AttributeError):
            continue
        if not isinstance(snapshot, dict):
            continue
        for row in snapshot.get("rows", []):
            if not isinstance(row, dict) or not row.get("include", True):
                continue
            label, status = str(row.get("label", "")), str(row.get("status", ""))
            kind = row.get("kind", "")
            keys = {"Arterial line": ["art"], "CVC": ["central"], "PICC": ["central"]}.get(kind)
            if keys is None:
                keys = [key for key in positive if _PATTERNS[key].search(label)] if kind == "Other" else []
            for key in keys:
                if row.get("removed", False):
                    absent[key] = True
                    continue
                fallback = {"art": "Arterial line", "central": "Central line", "pacemaker": "Pacemaker"}[key]
                source = label if _PATTERNS[key].search(label) else fallback
                source += ": " + status
                match = _PATTERNS[key].search(source)
                state = _assertion(source, match, key)
                # Status-only markers also occur after dates/site descriptions
                # in a device label, so evaluate the saved status directly.
                state_status = _assertion(fallback + ": " + status, _PATTERNS[key].search(fallback), key)
                if state == "negative" or state_status == "negative":
                    absent[key] = True
                elif state == "positive" and state_status == "positive":
                    positive[key] = True
    return positive, absent


def _readable_pressure(value: str) -> bool:
    if value.strip().casefold().rstrip(".") in _MISSING or not re.search(_NUMBER, value):
        return False
    if _HISTORY.search(value) or _FUTURE.search(value) or _NEGATIVE.search(value) or re.search(r"\b(?:removed|discontinued|stopped)\b", value, re.I):
        return False
    remaining = re.sub(_PRESSURE_UNIT, "", value, flags=re.I)
    remaining = re.sub(r"\b(?:to|avg|average|min|minimum|max|maximum|last)\b", "", remaining, flags=re.I)
    return bool(re.fullmatch(r"[\d\s.+\-–/:(),!\[\]]+", remaining))


def _pressure_evidence(sheet: dict) -> dict:
    found = {"art": False, "central": False}
    if "e" in (sheet.get("import_warnings") or {}):
        return found
    for row in sheet.get("vitals") or []:
        if not isinstance(row, dict) or not row.get("include", True) or row.get("section") != "Cardiovascular":
            continue
        label, value = str(row.get("label", "")), str(row.get("value", ""))
        if not _readable_pressure(value):
            continue
        try:
            arterial = parse_arterial_line(label + ": " + value)
            if arterial and arterial[0] and _readable_pressure(arterial[1]):
                found["art"] = True
            cvp_label = re.sub(r"^Last\s+", "", label, flags=re.I)
            if monitor_kind(cvp_label) == "CVP":
                parsed = monitor_summary_range(cvp_label + ": " + value)
                if parsed is None or _readable_pressure(parsed[1]):
                    found["central"] = True
        except (ValueError, TypeError):
            continue
    return found


def _pacemaker_evidence(sheet: dict, warnings: list[str]) -> bool:
    if _blocked(sheet, "w", "pacemaker_hidden"):
        return False
    data = sheet.get("pacemaker")
    try:
        validate_pacemaker(data)
    except (ValueError, TypeError, KeyError):
        warnings.append("The pacemaker record needs review before selecting its cardiovascular section.")
        return False
    if data is None or not data["include"]:
        return False
    # A present-but-inactive device remains relevant to the supplied template.
    mode = str(data.get("mode", "")).strip()
    return not re.fullmatch(_ABSENT, mode, re.I)


def _ecls_evidence(sheet: dict, warnings: list[str]) -> bool:
    if _blocked(sheet, "ad", "ecls_hidden"):
        return False
    data = sheet.get("ecls")
    try:
        validate_ecls(data)
    except (ValueError, TypeError, KeyError):
        warnings.append("The ECLS record needs review before selecting its cardiovascular section.")
        return False
    if data is None:
        return False
    # A recorded VA/VV mode or pumping value is support evidence. A cannula or
    # oxygenator-day entry alone does not establish current support.
    return data["mode"] in {"VA", "VV"} or any(data[key] and data[key] != "0" for key in ("blood_flow_l_min", "rpm"))


def select_cardiovascular_variant(sheet: dict, settings: dict | None = None) -> dict:
    """Select ECLS, pacemaker, both lines, arterial, central, then basic.

    Only current included records or explicit current statements contribute.
    Source-labeled pressure measurements can supply missing line evidence.
    Current absence/removal suppresses retained settings and measurements.
    No medication establishes a device or support, and inputs are read only.
    """
    sheet = sheet if isinstance(sheet, dict) else {}
    warnings = []
    prose, absent = _text_evidence(_statements(sheet, settings))
    devices, removed = _device_evidence(sheet)
    pressures = _pressure_evidence(sheet)
    evidence = {
        "art": devices["art"] or pressures["art"] or prose["art"],
        "central": devices["central"] or pressures["central"] or prose["central"],
        "pacemaker": devices["pacemaker"] or _pacemaker_evidence(sheet, warnings) or prose["pacemaker"],
        "ecls": _ecls_evidence(sheet, warnings) or prose["ecls"],
    }
    for key in evidence:
        # A removed old line may coexist with a separate active replacement.
        row_absence = removed.get(key, False) and not devices.get(key, False)
        if absent[key] or row_absence:
            if evidence[key]:
                warnings.append("Current absence or removal conflicts with retained cardiovascular findings. The affected support was not used.")
            evidence[key] = False
    if evidence["ecls"]:
        variant, reason = "art_cvl_ecls", "Current ECLS support is documented."
        if evidence["pacemaker"]:
            reason += " A current pacemaker or pacing wires are also documented."
    elif evidence["pacemaker"]:
        variant, reason = "art_cvl_pacemaker", "A current pacemaker or pacing wires are documented, including inactive or standby pacing."
    elif evidence["art"] and evidence["central"]:
        variant, reason = "art_cvl", "Current arterial and central venous access or their source-labeled pressure monitoring are documented."
    elif evidence["art"]:
        variant, reason = "art", "Current arterial access or source-labeled arterial pressure monitoring is documented."
    elif evidence["central"]:
        variant, reason = "cvl", "Current central venous access or source-labeled central venous pressure monitoring is documented."
    else:
        variant, reason = "none", "No current arterial line, central line, ECLS or pacemaker is documented."
    return {
        "variant": variant, "phrase": CV_TEMPLATE_NAMES[variant],
        "label": CV_TEMPLATE_LABELS[variant], "reason": reason,
        "warning": " ".join(dict.fromkeys(warnings)),
        "include_pacemaker": bool(evidence["pacemaker"]),
    }
