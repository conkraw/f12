"""A deterministic import rule for the C block, not an airway diagnosis.

Explicit source modes and set/observed fields are preserved separately.
Known non-invasive modes use the C/D support parser. Mode names alone do not
establish airway route. No D/E values, observed rate, or equipment fields are
substituted for a C-block setting. AVAPS targets retain their own source fields.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import re
from ventilator_modes import spec, display_mode, control_family, strip_setting_marker

VENTILATION_HISTORY_FALLBACK_NOTE = (
    "Mode history unavailable. Showing first reported settings from this paste. Latest mode unconfirmed."
)
CPAP_TRIAL_TITLE = "CPAP Trial Data"

LABELS = (
    "Vent Mode",
    "Resp Rate (Set)",
    "Vt (Set, mL)",
    "Vt (observed, mL)",
    "PEEP (cm H2O)",
    "Mean Airway Pressure",
    "Insp Time (sec)",
    "PIP Observed (cm H2O)",
    "Pressure Support (cm H2O)",
    "Trigger Sensitivity Flow (L/min)",
    "FiO2 (%)",
    "PIP Set (cm H2O)",
    "Vt Insp ml",
    "Vt Exp ml",
    "FiO2 set (%)",
    "Pmin",
    "Pmax",
    "Ti Min",
    "Ti Max",
    "AVAPS rate (cm H2O/min)",
    "AVAPS Respiratory Rate",
    "Vt Set/Target ml",
    "Pressure Support Min (cm H2O)",
    "Pressure Support Max (cm H2O)",
    "AVAPS Observed TV (mL)",
    "NAVA level",
    "EDI peak",
    "EDI min",
    "Resp Rate Observed",
    "Apnea Interval (sec)",
    "Weaning Tidal Volume",
    "Weaning Tolerance",
)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def mode_rule(mode: str) -> str:
    """Return included, excluded or unknown. No clinical inference is performed."""
    text = normalize(strip_setting_marker(mode)).replace("–", "-").replace("—", "-")
    known = spec(mode)
    if known:
        return "excluded" if known[2] else "included"
    if re.search(r"\b(?:bi[ -]?level|bi[ -]?pap|cpap|niv|nippv|hfnc)\b|non[ -]?invasive|high[ -]?flow", text):
        return "excluded"
    # Explicitly supported source labels. Unrecognized labels are never guessed.
    families = (
        "volume targeted pressure control", "pressure regulated volume control",
        "pressure control", "volume control", "synchronized intermittent mandatory ventilation",
        "intermittent mandatory ventilation", "assist control",
    )
    for prefix in families:
        if text == prefix or text.startswith(prefix + " -") or text.startswith(prefix + " ("):
            return "included"
    if re.fullmatch(r"(?:simv|prvc|pcv|vcv|a/c|ac|pc-ac|vc-ac)(?:[ /+()-]+(?:pc|vc|prvc|ps|pressure support|volume control|pressure control))*", text):
        return "included"
    return "unknown"


def validate_ventilation(data: dict | None) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or set(data) not in ({"mode", "values"}, {"mode", "values", "mode_history"}):
        raise ValueError("The saved ventilation block has an invalid structure.")
    if not isinstance(data["mode"], str) or not data["mode"].strip() or len(data["mode"]) > 500 or "\n" in data["mode"] or "\r" in data["mode"]:
        raise ValueError("The ventilation mode is empty or too long.")
    # A timestamped but unrecognized current mode may be retained as source
    # text only. It must never inherit settings from a known, older mode.
    unknown_snapshot = (mode_rule(data["mode"]) == "unknown" and data["values"] == {}
                        and isinstance(data.get("mode_history"), dict)
                        and bool(data["mode_history"].get("reported_at")))
    if mode_rule(data["mode"]) != "included" and not unknown_snapshot:
        raise ValueError("This mode is not included by the automatic invasive-ventilation display rule.")
    values = data["values"]
    if not isinstance(values, dict) or not set(values).issubset(set(LABELS[1:])):
        raise ValueError("The ventilation block contains an unexpected field.")
    for value in values.values():
        if not isinstance(value, str) or len(value) > 500 or "\n" in value or "\r" in value:
            raise ValueError("A ventilation value is invalid or too long.")
    if "mode_history" not in data:
        return
    history = data["mode_history"]
    if not isinstance(history, dict) or set(history) != {"reported_at", "other_modes", "latest_confirmed", "notes"}:
        raise ValueError("The ventilation mode history has an invalid structure.")
    _validate_mode_time(history["reported_at"])
    if type(history["latest_confirmed"]) is not bool:
        raise ValueError("The ventilation mode history certainty flag is invalid.")
    if not isinstance(history["notes"], list) or len(history["notes"]) > 24:
        raise ValueError("The ventilation mode history notes are invalid.")
    if any(not isinstance(note, str) or len(note) > 500 or "\n" in note or "\r" in note for note in history["notes"]):
        raise ValueError("A ventilation mode history note is invalid.")
    records = history["other_modes"]
    if not isinstance(records, list) or len(records) > 64:
        raise ValueError("The ventilation mode history is too long or invalid.")
    seen = {_mode_identity(data["mode"])}
    for record in records:
        if not isinstance(record, dict) or set(record) not in ({"mode", "values", "reported_at"}, {"mode", "values", "reported_at", "include"}):
            raise ValueError("A prior ventilation mode has an invalid structure.")
        mode = record["mode"]
        if not isinstance(mode, str) or not mode.strip() or len(mode) > 500 or "\n" in mode or "\r" in mode:
            raise ValueError("A prior ventilation mode is invalid.")
        identity = _mode_identity(mode)
        if identity in seen:
            raise ValueError("The ventilation history repeats a mode.")
        seen.add(identity)
        _validate_mode_time(record["reported_at"])
        if "include" in record and type(record["include"]) is not bool:
            raise ValueError("A prior ventilation mode visibility flag is invalid.")
        if mode_rule(mode) == "included":
            validate_ventilation({"mode": mode, "values": record["values"]})
        elif mode_rule(mode) == "unknown" and record["values"] == {}:
            pass
        else:
            raise ValueError("A prior mode cannot contain unsupported or non-invasive settings.")


def _validate_mode_time(value: str) -> None:
    if not isinstance(value, str) or (value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value)):
        raise ValueError("A ventilation mode timestamp is invalid.")
    if value:
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("A ventilation mode timestamp is invalid.") from exc


def _mode_identity(mode: str) -> str:
    """Deduplicate display aliases, never merge distinct control-family modes."""
    return normalize(display_mode(mode)).replace("–", "-").replace("—", "-")


def _clean_output(value: str) -> str:
    """Normalize unit typography only. Do not add pressures or derive settings."""
    value = strip_setting_marker(value)
    value = re.sub(r"cm\s*H\s*[2₂]\s*[O0]", "cm H2O", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def _measurement(value: str, unit: str = "") -> str:
    """A field's explicit units may be carried from its source label to output."""
    value = _clean_output(value)
    if unit and re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value):
        return value + " " + unit
    return value


def _observed(value: str, unit: str = "mL") -> str:
    """Retain reported averages/ranges, never calculate them from single values."""
    text = _clean_output(value)
    if re.search(r"\b(?:Avg|Min|Max)\s*:", text, re.I):
        # Units in Vt Insp ml / Vt Exp ml apply to the whole range.
        fields = re.findall(r"\b(Avg|Min|Max)\s*:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))", text, re.I)
        if fields and len(fields) == len(re.findall(r"\b(?:Avg|Min|Max)\s*:", text, re.I)):
            return " ".join(name.title() + ": " + number for name, number in fields) + " " + unit
    return _measurement(text, unit)


def _avaps_rate_unit_needs_review(value: str) -> bool:
    """Do not discard a label/value unit disagreement or guess a conversion."""
    text = _clean_output(value)
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return False
    return re.search(r"\bcm H2O\s*/\s*min(?:ute)?s?\b", text, re.I) is None


def _nava_observed(value: str, unit: str) -> str:
    """Display documented bounds without deriving a range from an average."""
    text = _clean_output(value)
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
    unit_pattern = {
        "µV": r"[µμu]V",
        "cm H2O": r"cm\s*H2O",
        "mL": r"mL",
        "breaths/min": r"(?:breaths?\s*/\s*min(?:ute)?|breaths?\s+per\s+minute|bpm)",
    }[unit]
    statistic = rf"(?:Avg|Min|Max)\s*:\s*{number}(?:\s*{unit_pattern})?"
    if re.fullmatch(rf"(?:\s*{statistic}\s*)+", text, re.I):
        fields = re.findall(rf"\b(Avg|Min|Max)\s*:\s*({number})", text, re.I)
        bounds = {name.casefold(): value for name, value in fields}
        if len(bounds) == len(fields) and "min" in bounds and "max" in bounds:
            if float(bounds["min"]) <= float(bounds["max"]):
                return bounds["min"] + "–" + bounds["max"] + " " + unit
        # Keep partial or reversed bounds explicitly labeled for review.
        return _observed(text, unit)
    interval = re.fullmatch(rf"({number})\s*(?:-|–|to)\s*({number})(?:\s*{unit_pattern})?", text, re.I)
    if interval and float(interval[1]) <= float(interval[2]):
        return interval[1] + "–" + interval[2] + " " + unit
    # Preserve an annotation or unexpected unit rather than silently dropping it.
    return _measurement(text, unit)


def _format_nava(data: dict) -> str:
    values = data["values"]
    lines = ["Mode: " + display_mode(data["mode"])]

    def add(source: str, label: str, unit: str, observed: bool = False) -> None:
        value = values.get(source, "")
        if is_present(value):
            formatted = _nava_observed(value, unit) if observed else _measurement(value, unit)
            lines.append(label + ": " + formatted)

    add("NAVA level", "NAVA Level", "cm H2O/µV")
    add("PEEP (cm H2O)", "Set PEEP", "cm H2O")
    fio2 = "FiO2 set (%)" if is_present(values.get("FiO2 set (%)", "")) else "FiO2 (%)"
    add(fio2, "FiO2", "%")
    add("EDI peak", "Edi Peak", "µV", observed=True)
    add("EDI min", "Edi Min", "µV", observed=True)
    add("PIP Observed (cm H2O)", "Observed PIP", "cm H2O", observed=True)
    for source in ("Vt (observed, mL)", "Vt Exp ml", "Vt Insp ml"):
        if is_present(values.get(source, "")):
            add(source, "Observed TV", "mL", observed=True)
            break
    add("Resp Rate Observed", "Observed RR", "breaths/min", observed=True)
    add("Apnea Interval (sec)", "Apnea Time", "sec")
    return "\n".join(lines)


def home_vent(data: dict | None) -> bool:
    if not data:
        return False
    # A heading alone, blank, or a placeholder does not create a home vent.
    value = _clean_output(data["values"].get("Pmin", ""))
    return bool(re.match(r"^[+]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s|cm|$)", value, re.I))


def _format_single_ventilation(data: dict | None) -> str:
    if data is None:
        return ""
    values = data["values"]
    family = control_family(data["mode"])
    if family == "NAVA":
        return _format_nava(data)
    home = home_vent(data)
    cpap_trial = _mode_identity(data["mode"]) == _mode_identity("PS-CPAP")
    lines = [CPAP_TRIAL_TITLE] if cpap_trial else []
    if home:
        lines.append("Device: Home Vent")
    lines.append("Mode: " + display_mode(data["mode"], home=home))

    def add(source: str, label: str, unit: str = "") -> None:
        value = values.get(source, "").strip()
        if is_present(value):
            lines.append(label + ": " + _measurement(value, unit))

    # The general respiratory observations already report the rate. Keep
    # the stored source value but omit the duplicate from a PS-CPAP trial.
    if not cpap_trial:
        add("Resp Rate (Set)", "Set RR")
    if family == "AVAPS":
        # Epic's AVAPS rate field explicitly uses pressure/time units. Keep
        # it distinct from an actual recorded respiratory-rate setting.
        add("AVAPS Respiratory Rate", "AVAPS Respiratory Rate")
        rate = values.get("AVAPS rate (cm H2O/min)", "")
        rate_label = "AVAPS rate (cm H2O/min)" if is_present(rate) and _avaps_rate_unit_needs_review(rate) else "AVAPS rate"
        add("AVAPS rate (cm H2O/min)", rate_label, "cm H2O/min")
    if family == "PC":
        add("PIP Set (cm H2O)", "Set PIP", "cm H2O")
    elif family == "AVAPS":
        if is_present(values.get("Vt Set/Target ml", "")):
            add("Vt Set/Target ml", "Target TV", "mL")
        else:
            add("Vt (Set, mL)", "Set TV", "mL")
    elif family in {"PRVC", "VC", "VSV"}:
        add("Vt (Set, mL)", "Set TV", "mL")
    elif family != "PS":
        # No mode-specific interpretation is invented for other supported modes.
        add("PIP Set (cm H2O)", "Set PIP", "cm H2O")
        add("Vt (Set, mL)", "Set TV", "mL")
    # A measured PIP remains relevant in a volume-targeted mode or home vent.
    # Keep it separate from the set PIP. Never derive or substitute a setting.
    observed_pip = values.get("PIP Observed (cm H2O)", "")
    if is_present(observed_pip):
        lines.append("Observed PIP: " + _observed(observed_pip, "cm H2O"))
    if family == "AVAPS":
        # Keep a dedicated AVAPS observation separate from the conventional
        # observation that may coexist in the SmartPhrase's generic template.
        for source in ("AVAPS Observed TV (mL)", "Vt (observed, mL)", "Vt Exp ml", "Vt Insp ml"):
            if is_present(values.get(source, "")):
                lines.append("Observed TV: " + _observed(values[source]))
                break
    elif family == "PC":
        # Preserve source selection and phase in stored values. The compact handoff
        # uses the generic TV label for either phase, never relabeling Insp as Exp.
        if is_present(values.get("Vt Exp ml", "")):
            lines.append("Observed TV: " + _observed(values["Vt Exp ml"]))
        elif is_present(values.get("Vt Insp ml", "")):
            lines.append("Observed TV: " + _observed(values["Vt Insp ml"]))
        elif is_present(values.get("Vt (observed, mL)", "")):
            lines.append("Observed TV: " + _observed(values["Vt (observed, mL)"]))
    add("PEEP (cm H2O)", "Set PEEP", "cm H2O")
    add("Insp Time (sec)", "Inspiratory Time", "sec")
    add("Pressure Support (cm H2O)", "Pressure Support", "cm H2O")
    if family == "AVAPS":
        add("Pressure Support Min (cm H2O)", "PS Min", "cm H2O")
        add("Pressure Support Max (cm H2O)", "PS Max", "cm H2O")
    if home:
        add("Pmin", "Pmin", "cm H2O")
        add("Pmax", "Pmax", "cm H2O")
        add("Ti Min", "Tmin", "sec")
        add("Ti Max", "Tmax", "sec")
    # A set FiO2 is not an observed FiO2. Prefer the explicit set value when present.
    if is_present(values.get("FiO2 set (%)", "")):
        add("FiO2 set (%)", "FiO2", "%")
    else:
        add("FiO2 (%)", "FiO2", "%")
    if family == "PS":
        if is_present(values.get("Weaning Tidal Volume", "")):
            lines.append("Weaning TV: " + _nava_observed(values["Weaning Tidal Volume"], "mL"))
        add("Weaning Tolerance", "Weaning Tolerance")
    return "\n".join(lines)


def _display_mode_time(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%m/%d/%y %H:%M") if value else ""


def _format_mode_with_time(data: dict, reported_at: str) -> str:
    lines = _format_single_ventilation(data).splitlines()
    when = _display_mode_time(reported_at)
    if when:
        lines = [line + " (" + when + ")" if line.startswith("Mode: ") else line for line in lines]
    if not data["values"]:
        lines.append("Settings not available for this mode in the paste.")
    return "\n".join(lines)


def format_ventilation(data: dict | None) -> str:
    validate_ventilation(data)
    if data is None:
        return ""
    history = data.get("mode_history")
    if history is None:
        return _format_single_ventilation(data)
    blocks = [_format_mode_with_time(data, history["reported_at"])]
    records = [record for record in history["other_modes"] if record.get("include", True)]
    blocks.extend(_format_mode_with_time(record, record["reported_at"]) for record in records)
    text = "\n---\n".join(blocks)
    if history["notes"]:
        text += "\n\nMode history review: " + " ".join(history["notes"])
    return text


MISSING_VALUES = {"", "--", "-", "none", "n/a", "na", "no data recorded", "not documented", "no results found"}


def is_present(value: str) -> bool:
    return normalize(strip_setting_marker(value).rstrip(".")) not in MISSING_VALUES


WRAPPERS = {
    "mode": "Vent Mode", "respiratory rate": "Resp Rate (Set)",
    "set pip": "PIP Set (cm H2O)", "observed pip": "PIP Observed (cm H2O)",
    "set tv": "Vt (Set, mL)", "observed tv": "Vt (observed, mL)",
    "set peep": "PEEP (cm H2O)", "inspiratory time": "Insp Time (sec)",
    "fio2": "FiO2 (%)", "pressure support": "Pressure Support (cm H2O)",
    "pmin": "Pmin", "pmax": "Pmax", "timin": "Ti Min", "timax": "Ti Max",
    "tmin": "Ti Min", "tmax": "Ti Max",
    "avaps respiratory rate": "AVAPS Respiratory Rate",
    "avaps target tv": "Vt Set/Target ml",
    "observed avaps tv": "AVAPS Observed TV (mL)",
    "ps min": "Pressure Support Min (cm H2O)",
    "ps max": "Pressure Support Max (cm H2O)",
    "nava level": "NAVA level",
    "set fio2": "FiO2 (%)",
    "edi peak": "EDI peak",
    "edi min": "EDI min",
    "observed tidal volume": "Vt (observed, mL)",
    "observed respiratory rate": "Resp Rate Observed",
    "apnea time": "Apnea Interval (sec)",
    "weaning tidal volumes": "Weaning Tidal Volume",
    "weaning tidal volume": "Weaning Tidal Volume",
    "weaning tolerance": "Weaning Tolerance",
}

# Typography aliases do not change a field's meaning or unit. Include them
# when unwrapping a nested SmartLink label as well as when reading the value.
AVAPS_LABEL_ALIASES = {
    "avaps rate (cmh2o/min)": "AVAPS rate (cm H2O/min)",
    "avaps rate (cm h20/min)": "AVAPS rate (cm H2O/min)",
    "avaps rate (cmh20/min)": "AVAPS rate (cm H2O/min)",
    "pressure support min (cmh2o)": "Pressure Support Min (cm H2O)",
    "pressure support min (cm h20)": "Pressure Support Min (cm H2O)",
    "pressure support min (cmh20)": "Pressure Support Min (cm H2O)",
    "pressure support max (cmh2o)": "Pressure Support Max (cm H2O)",
    "pressure support max (cm h20)": "Pressure Support Max (cm H2O)",
    "pressure support max (cmh20)": "Pressure Support Max (cm H2O)",
}

OBSERVED_VOLUME_ALIASES = {
    "vti": "Vt Insp ml", "observed tvi": "Vt Insp ml",
    "vte": "Vt Exp ml", "observed tve": "Vt Exp ml",
    "vt exp ml": "Vt Exp ml", "vt (exhaled, ml)": "Vt Exp ml",
    "vt expired ml": "Vt Exp ml", "vt expiratory ml": "Vt Exp ml",
    "vt (inspired, ml)": "Vt Insp ml",
}
OBSERVED_VOLUME_LABELS = {
    normalize(label) for label in ("Vt (observed, mL)", "Vt Insp ml", "Vt Exp ml")
} | set(OBSERVED_VOLUME_ALIASES)


def unwrap_vent_line(raw: str) -> str:
    """Remove only the known SmartPhrase wrappers, not arbitrary source text.

    Stats labels without a colon before Avg must be split before that Avg,
    rather than mistaking the colon after Avg for the parameter separator.
    """
    line = strip_setting_marker(raw).replace("₂", "2")
    for _ in range(4):
        match = re.match(r"^([^:]+):\s*(.*)$", line)
        if not match:
            break
        outer, content = normalize(match.group(1)), match.group(2).strip()
        target = WRAPPERS.get(outer)
        if not target:
            break
        # A marker can precede a nested source label as well as its value.
        # Keep final scalar/mode values verbatim in the retained record.
        nested_content = strip_setting_marker(content)
        inner = re.match(r"^(.+?)\s+(?:Avg|Min|Max)\s*:", nested_content, re.I)
        inner_key = normalize(nested_content.split(":", 1)[0]) if ":" in nested_content else ""
        if target == "AVAPS Observed TV (mL)":
            # The same inner Epic labels also appear under generic Observed TV.
            # Preserve the AVAPS wrapper's source scope so stale AVAPS values
            # cannot replace or conflict with active conventional-mode values.
            if inner_key in OBSERVED_VOLUME_LABELS:
                line = target + ": " + nested_content.split(":", 1)[1].strip()
            elif inner and normalize(inner.group(1)) in OBSERVED_VOLUME_LABELS:
                line = target + ": " + nested_content[len(inner.group(1)):].strip()
            else:
                # Unknown nested content stays within its explicit AVAPS scope.
                # In particular it must not route into a generic C-block field.
                line = target + ": " + content
            break
        known_labels = {normalize(x) for x in LABELS} | set(AVAPS_LABEL_ALIASES) | {"ti min", "ti max", "observed tve", "observed tvi", "vte", "vti"}
        if inner_key in known_labels or (inner and normalize(inner.group(1)) in known_labels):
            if nested_content == line:
                break
            line = nested_content
            continue
        # A wrapper with a scalar or an explicitly empty value is also supported.
        line = target + ": " + content
        break
    stats = re.match(r"^(.+?)\s+((?:Avg|Min|Max)\s*:.*)$", line, re.I)
    if stats and normalize(stats.group(1)) in {normalize(x) for x in ("PIP Observed (cm H2O)", "Vt Insp ml", "Vt Exp ml", "Vt (observed, mL)", "Vti", "Vte", "EDI peak", "EDI min", "Resp Rate Observed", "Weaning Tidal Volume")}:
        line = stats.group(1).strip() + ": " + stats.group(2)
    return line


def _select_legacy_source(block: str) -> str:
    """Scope dedicated NAVA values before either C-block field reader runs.

    Only a documented invasive NAVA mode selects this subsection. Its fields
    replace generic values as a group, including when they are blank. Other
    modes ignore the subsection, so carried-forward NAVA settings cannot leak
    into conventional ventilation or NIV.
    """
    normalized_block = block.replace("\r\n", "\n").replace("\r", "\n")
    if not re.search(r"(?im)^[ \t]*(?:\(\s*S\s*\)\s*)*NAVA\s+(?:Ventilator\s+)?Settings[ \t]*:?[ \t]*$", normalized_block):
        return block
    general: list[str] = []
    nava: list[str] = []
    control_lines: list[str] = []
    first_mode = ""
    found = False
    in_nava = False
    field_labels = {normalize(label) for label in LABELS} | set(WRAPPERS)
    section_headings = {"invasive ventilation", "non-invasive ventilation", "vent information", "settings",
                        "home ventilator settings", "average volume-assured pressure support settings", "avaps settings"}
    for raw in normalized_block.splitlines():
        line = strip_setting_marker(raw).strip()
        heading = normalize(line.rstrip(":"))
        if heading in {"nava ventilator settings", "nava settings"}:
            found = in_nava = True
            continue
        unwrapped = unwrap_vent_line(raw)
        label, separator, value = unwrapped.partition(":")
        label = normalize(label)
        if separator and label in {"vent mode", "ventilator on"}:
            # Mode conflicts and the existing SBS on/off guard apply to all C.
            control_lines.append(raw)
            if label == "vent mode" and not first_mode and is_present(value):
                first_mode = value.strip()
            continue
        # A new heading or outer SmartPhrase delimiter ends the subsection.
        # A nested blank SmartLink is still a field, not a section heading.
        if in_nava and (heading in section_headings or re.fullmatch(r"([a-zA-Z])\1{7,}", line)
                        or (line.endswith(":") and label not in field_labels)):
            in_nava = False
        (nava if in_nava else general).append(raw)
    if not found:
        return block
    known = spec(first_mode)
    if known and known[1] == "NAVA" and not known[2]:
        # Preserve all mode lines so conflicting modes still fail validation.
        return "\n".join(control_lines + nava)
    return "\n".join(control_lines + general)


@dataclass
class VentilationResult:
    data: dict | None = None
    status: str = "empty"
    issues: list[str] = field(default_factory=list)
    error: str = ""


def has_ventilation_history(block: str | None) -> bool:
    """Detect the history boundary without invoking the mode-history parser."""
    return any(normalize(strip_setting_marker(line).rstrip(":")) == "all vent modes"
               for line in (block or "").replace("\r\n", "\n").replace("\r", "\n").splitlines())


def _check_first_reported_conflicts(lines: list[str]) -> None:
    """Do not hide contradictory original fields behind a dedicated subsection."""
    aliases = {normalize(label): label for label in LABELS}
    aliases.update(AVAPS_LABEL_ALIASES)
    aliases.update(OBSERVED_VOLUME_ALIASES)
    aliases["ventilator on"] = "Ventilator On"
    entries: dict[str, str] = {}
    for raw in lines:
        label, separator, value = unwrap_vent_line(raw).partition(":")
        label = aliases.get(normalize(label.replace("₂", "2")))
        if not separator or label is None or not is_present(value):
            continue
        value = normalize(strip_setting_marker(value))
        if len(value) > 500:
            raise ValueError("A requested ventilation value is too long. Nothing was imported.")
        if label in entries and entries[label] != value:
            raise ValueError("The C block contains conflicting repeated ventilation fields. Nothing was imported.")
        entries[label] = value


def select_first_reported_ventilation_source(block: str) -> str:
    """Read only the original snapshot, independently of all history helpers.

    Stop at the history boundary. Keep original control lines so a conflicting
    mode or an Off flag cannot disappear during fallback source selection.
    """
    sections: dict[str, list[str]] = {"main": []}
    controls: list[str] = []
    first_mode = ""
    scope = "main"
    started = False
    for raw in block.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = strip_setting_marker(raw).strip()
        heading = normalize(line.rstrip(":"))
        if heading in {"all vent modes", "non-invasive ventilation", "noninvasive ventilation"}:
            break
        if re.fullmatch(r"([a-zA-Z])\1{7,}", line):
            if started:
                break
            continue
        if line:
            started = True
        section = {
            "invasive ventilation": "main", "vent information": "main", "settings": "main",
            "home ventilator settings": "home",
            "average volume-assured pressure support settings": "avaps", "avaps settings": "avaps",
            "nava ventilator settings": "nava", "nava settings": "nava",
            "cpap trial settings": "ps_cpap", "ps-cpap settings": "ps_cpap",
            "pressure support - continuous positive airway pressure settings": "ps_cpap",
        }.get(heading)
        if section is None:
            explicit = re.fullmatch(r"(.+?)\s+(?:ventilator\s+)?settings", heading, re.I)
            if explicit:
                section = ("mode:" + normalize(display_mode(explicit[1]))
                           if mode_rule(explicit[1]) == "included" else "unused:" + heading)
        if section is not None:
            scope = section
            sections.setdefault(scope, [])
            continue
        label, separator, value = unwrap_vent_line(raw).partition(":")
        label = normalize(label)
        if separator and label in {"vent mode", "ventilator on"}:
            controls.append(raw)
            if label == "vent mode" and not first_mode and is_present(value):
                first_mode = value.strip()
            continue
        sections.setdefault(scope, []).append(raw)
    # Contradictions inside the first snapshot must still block fallback even
    # if a dedicated NAVA/CPAP subsection would otherwise replace these fields.
    _check_first_reported_conflicts(controls + sections.get("main", []))
    identity = normalize(display_mode(first_mode))
    known = spec(first_mode)
    family = control_family(first_mode)
    if "mode:" + identity in sections:
        selected = sections["mode:" + identity]
    elif known and not known[2] and family == "NAVA" and "nava" in sections:
        selected = sections["nava"]
    elif identity == normalize(display_mode("PS-CPAP")) and "ps_cpap" in sections:
        selected = sections["ps_cpap"]
    else:
        selected = sections.get("main", []) + sections.get("home", [])
        if known and not known[2] and family == "AVAPS":
            selected = selected + sections.get("avaps", [])
    source_lines = controls + selected
    _check_first_reported_conflicts(source_lines)
    return "\n".join(source_lines)


def _split_ventilation_sections(block: str) -> dict:
    """Retain source boundaries before reading any repeated SmartLink fields."""
    sections: dict[str, list[str]] = {"main": []}
    controls: list[str] = []
    modes: list[str] = []
    history: list[str] = []
    history_present = False
    scope = "main"
    for raw in block.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = strip_setting_marker(raw).strip()
        heading = normalize(line.rstrip(":"))
        if heading == "all vent modes":
            history_present = True
            scope = "history"
            continue
        section = {
            "invasive ventilation": "main", "vent information": "main", "settings": "main",
            "home ventilator settings": "home",
            "average volume-assured pressure support settings": "avaps", "avaps settings": "avaps",
            "nava ventilator settings": "nava", "nava settings": "nava",
            "cpap trial settings": "ps_cpap", "ps-cpap settings": "ps_cpap",
            "pressure support - continuous positive airway pressure settings": "ps_cpap",
        }.get(heading)
        if section is None:
            explicit = re.fullmatch(r"(.+?)\s+(?:ventilator\s+)?settings", heading, re.I)
            if explicit and mode_rule(explicit[1]) == "included":
                section = "mode:" + _mode_identity(explicit[1])
            elif explicit:
                section = "unmapped:" + heading
        if section is not None:
            scope = section
            sections.setdefault(scope, [])
            continue
        if heading in {"non-invasive ventilation", "noninvasive ventilation"} or re.fullmatch(r"([a-zA-Z])\1{7,}", line):
            scope = "ignore"
            continue
        if scope == "history":
            history.append(raw)
            continue
        if scope == "ignore":
            continue
        unwrapped = unwrap_vent_line(raw)
        label, separator, value = unwrapped.partition(":")
        if separator and normalize(label) in {"vent mode", "ventilator on"}:
            controls.append(raw)
            if normalize(label) == "vent mode" and is_present(value):
                modes.append(value.strip())
            continue
        sections.setdefault(scope, []).append(raw)
    return {"sections": sections, "controls": controls, "modes": modes,
            "history": history, "history_present": history_present}


def _expand_mode_flow_tables(lines: list[str]) -> tuple[list[str], bool]:
    """Pair each Epic mode cell with its own timestamp, preserving empty cells.

    Epic repeats a timestamp header and Vent Mode row when a flow table wraps.
    Convert those rows to the existing history format before deduplication and
    chronological selection. The table contains mode times, not setting times.
    """
    expanded: list[str] = []
    times: list[str] | None = None
    table_seen = False
    date_start = re.compile(r"^\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s|$)")
    timestamp = re.compile(r"\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})\s+\d{1,2}:?\d{2}(?:\s*[AP]M)?", re.I)
    for raw in lines:
        # Do not strip the raw line first: leading/trailing tabs are empty
        # cells, and removing an interior empty cell would shift its mode.
        cells = raw.split("\t") if "\t" in raw else re.split(r" {2,}", raw.strip())
        cells = [strip_setting_marker(cell).strip() for cell in cells]
        first = normalize(cells[0].rstrip(":"))
        header = cells[1:] if first in {"", "date", "time", "date/time"} else cells
        if header and any(date_start.match(cell) for cell in header) and (
                first in {"", "date", "time", "date/time"} or date_start.match(cells[0])):
            times = header
            table_seen = True
            continue
        if first == "vent mode" and len(cells) > 1:
            table_seen = True
            values = cells[1:]
            if not any(is_present(value) for value in values):
                times = None
                continue
            if times is None or any(is_present(value) for value in values[len(times):]):
                # An unaligned row cannot safely assign a mode to a time.
                expanded.append("Vent Mode")
                times = None
                continue
            for index, value in enumerate(values[:len(times)]):
                if not is_present(value):
                    continue
                stamp = times[index]
                suffix = " (" + stamp + ")" if timestamp.fullmatch(stamp) else ""
                expanded.append("Vent Mode: " + value + suffix)
            times = None
            continue
        expanded.append(raw)
    return expanded, table_seen


def _read_mode_history(lines: list[str]) -> tuple[list[dict], list[str]]:
    """Read only mode names and times. Never retain charting-author suffixes."""
    entries: dict[str, dict] = {}
    invalid_time = False
    malformed = False
    for raw in lines:
        line = unwrap_vent_line(raw)
        label, separator, value = line.partition(":")
        if not separator or normalize(label) != "vent mode":
            if re.search(r"\bvent\s+mode\b", line, re.I):
                malformed = True
            continue
        value = strip_setting_marker(value).strip()
        if not is_present(value):
            continue
        mode, when = value, ""
        # The parenthesis is a chart record, not part of the mode name.
        suffix = re.search(r"\s*\(([^()]*)\)\s*$", value)
        embedded_date = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", value)
        if suffix and (":" in suffix[1] or re.search(r"\d{1,2}/\d{1,2}", suffix[1])
                       or re.search(r",\s*(?:RN|RRT|MD|DO|PA-C|APRN)\b", suffix[1], re.I)):
            mode = value[:suffix.start()].strip()
            stamp = re.match(r"\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{1,2}:?\d{2})(?:\s*([AP]M))?(?:\s*:.*)?\s*$", suffix[1], re.I)
            if stamp:
                clock = stamp[2].replace(":", "").zfill(4)
                year_format = "%Y" if len(stamp[1].rsplit("/", 1)[1]) == 4 else "%y"
                try:
                    parsed = datetime.strptime(stamp[1] + " " + clock + (" " + stamp[3].upper() if stamp[3] else ""),
                                               "%m/%d/" + year_format + " " + ("%I%M %p" if stamp[3] else "%H%M"))
                    when = parsed.isoformat(timespec="minutes")
                except ValueError:
                    pass
        elif embedded_date:
            # Missing/adjacent parentheses and unparenthesized chart entries
            # still must not persist the timestamp's author suffix.
            mode = value[:embedded_date.start()].rstrip(" (")
        elif "(" in value and value.count("(") != value.count(")"):
            mode = value.split("(", 1)[0].strip()
        # A colon is not part of a supported mode label. Keep a safe prefix
        # even when an unrecognized charting suffix has no valid timestamp.
        mode = mode.split(":", 1)[0].strip()
        mode = re.sub(r"\s+", " ", mode)
        if not mode or len(mode) > 500:
            malformed = True
            continue
        if not when:
            invalid_time = True
        identity = _mode_identity(mode)
        existing = entries.get(identity)
        if existing is None or when > existing["reported_at"]:
            entries[identity] = {"mode": mode, "reported_at": when}
    notes = []
    if invalid_time:
        notes.append("Some mode entries have missing or invalid times, so the latest mode cannot be confirmed.")
    if malformed:
        notes.append("Some mode history entries could not be read, so the latest mode cannot be confirmed.")
    records = sorted(entries.values(), key=lambda record: (record["reported_at"], _mode_identity(record["mode"])), reverse=True)
    return records, notes


def _source_for_record(parts: dict, mode: str, *, allow_generic: bool) -> str:
    sections = parts["sections"]
    explicit = "mode:" + _mode_identity(mode)
    known = spec(mode)
    family = control_family(mode)
    if explicit in sections:
        lines = sections[explicit]
    elif known and not known[2] and family == "NAVA" and "nava" in sections:
        lines = sections["nava"]
    elif _mode_identity(mode) == _mode_identity("PS-CPAP") and "ps_cpap" in sections:
        lines = sections["ps_cpap"]
    elif allow_generic:
        lines = sections.get("main", []) + sections.get("home", [])
        if family == "AVAPS":
            lines = lines + sections.get("avaps", [])
    elif known and not known[2] and family == "AVAPS" and "avaps" in sections:
        lines = sections["avaps"]
    else:
        lines = []
    return "\n".join(lines)


def _history_context(block: str) -> dict | None:
    block = block.replace("\r\n", "\n").replace("\r", "\n")
    if not re.search(r"(?im)^[ \t]*(?:\(\s*S\s*\)\s*)*All\s+Vent\s+Modes\s*:?[ \t]*$", block):
        return None
    parts = _split_ventilation_sections(block)
    history_lines, flow_table = _expand_mode_flow_tables(parts["history"])
    records, notes = _read_mode_history(history_lines)
    if not records and not notes:
        return None
    original = parts["modes"][0] if parts["modes"] else ""
    original_identity = _mode_identity(original) if original else ""
    generic_ok = len({_mode_identity(mode) for mode in parts["modes"]}) <= 1
    if not generic_ok:
        notes.append("The initial settings contain conflicting mode labels. Generic settings were omitted.")
    dated = [record for record in records if record["reported_at"]]
    newest = [record for record in dated if record["reported_at"] == dated[0]["reported_at"]] if dated else []
    confirmed = bool(newest) and not notes
    chosen = original
    if len(newest) > 1:
        confirmed = False
        notes.append("Different modes share the newest timestamp. The latest mode needs review.")
    elif newest:
        newest_mode = newest[0]["mode"]
        if mode_rule(newest_mode) == "unknown":
            if flow_table:
                chosen = newest_mode
                notes.append("The newest recorded mode is unrecognized. Its name was retained without inferred settings.")
            else:
                confirmed = False
                notes.append("The newest recorded mode is unrecognized. The displayed main mode may be older.")
        else:
            chosen = newest_mode
    if not chosen or (mode_rule(chosen) == "unknown" and not flow_table):
        fallback = next((record["mode"] for record in records if mode_rule(record["mode"]) == "included"), "")
        chosen = fallback or chosen
        confirmed = False
    if not chosen:
        chosen = records[0]["mode"] if records else ""
    if original and chosen and _mode_identity(chosen) != original_identity and len(newest) == 1 and mode_rule(newest[0]["mode"]) != "unknown":
        notes.append("The latest recorded mode differs from the initial Mode field. Only settings explicitly assigned to that mode were used.")
    selected_identity = _mode_identity(chosen) if chosen else ""
    selected_record = next((record for record in records if _mode_identity(record["mode"]) == selected_identity), None)
    when = selected_record["reported_at"] if selected_record else ""
    allow_generic = generic_ok and (selected_identity == original_identity or (flow_table and not original))
    selected_source = ("" if flow_table and mode_rule(chosen) == "unknown"
                       else _source_for_record(parts, chosen, allow_generic=allow_generic))
    controls = [line for line in parts["controls"] if normalize(unwrap_vent_line(line).partition(":")[0]) == "ventilator on"]
    source = "\n".join((["Vent Mode: " + chosen] if chosen else []) + controls + [selected_source])
    others = []
    omitted_niv = False
    for record in records:
        if _mode_identity(record["mode"]) == selected_identity:
            continue
        if mode_rule(record["mode"]) == "excluded":
            omitted_niv = True
            continue
        other_source = _source_for_record(parts, record["mode"], allow_generic=generic_ok and _mode_identity(record["mode"]) == original_identity)
        # A documented PS-CPAP trial remains relevant after returning to the
        # current ventilator mode. Keep its own timestamp and scoped settings,
        # while other historical flow-table modes stay hidden by default.
        show_trial = (bool(record["reported_at"])
                      and _mode_identity(record["mode"]) == _mode_identity("PS-CPAP"))
        others.append({**record, "source": other_source, **({"include": show_trial} if flow_table else {})})
    if omitted_niv:
        notes.append("Recorded non-invasive modes were omitted from this invasive ventilation list.")
    if len(others) > 64:
        others = others[:64]
        notes.append("Additional mode history exceeded the display limit and needs review.")
    return {"source": source, "reported_at": when, "latest_confirmed": confirmed,
            "notes": notes, "other_modes": others, "mode": chosen, "flow_table": flow_table}


def select_ventilation_source(block: str) -> str:
    """Use the same current-mode source for imports, support parsing, and SBS."""
    history = _history_context(block) if has_ventilation_history(block) else None
    if history is not None:
        return history["source"]
    parts = _split_ventilation_sections(block)
    # An empty history heading must not introduce extra repeated mode fields.
    scoped_other = any(name.startswith(("mode:", "unmapped:")) for name in parts["sections"])
    if parts["history_present"] or "ps_cpap" in parts["sections"] or scoped_other:
        original = parts["modes"][0] if parts["modes"] else ""
        if "mode:" + _mode_identity(original) in parts["sections"]:
            return "\n".join(parts["controls"] + [_source_for_record(parts, original, allow_generic=True)])
        if _mode_identity(original) == _mode_identity("PS-CPAP") and "ps_cpap" in parts["sections"]:
            return "\n".join(parts["controls"] + parts["sections"]["ps_cpap"])
        reconstructed = list(parts["controls"])
        for name, rows in parts["sections"].items():
            if name == "ps_cpap" or name.startswith(("mode:", "unmapped:")):
                continue
            if name == "nava":
                reconstructed.append("NAVA Ventilator Settings:")
            elif name == "home":
                reconstructed.append("Home Ventilator Settings:")
            elif name == "avaps":
                reconstructed.append("Average Volume-Assured Pressure Support Settings:")
            elif name == "main":
                reconstructed.append("Invasive Ventilation:")
            reconstructed.extend(rows)
        return _select_legacy_source("\n".join(reconstructed))
    return _select_legacy_source(block)


def _parse_single_ventilation(block: str, *, source_is_selected: bool = False) -> VentilationResult:
    result = VentilationResult()
    aliases = {normalize(label): label for label in LABELS}
    aliases.update(AVAPS_LABEL_ALIASES)
    aliases.update(OBSERVED_VOLUME_ALIASES)
    # Subscript characters in labels are typography only. Values stay verbatim.
    def label_key(label: str) -> str:
        return normalize(label.replace("₂", "2"))
    entries: dict[str, str] = {}
    meaningful = []
    source = block if source_is_selected else select_ventilation_source(block)
    for raw in source.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = unwrap_vent_line(raw)
        if not line or normalize(line.rstrip(":")) in ("invasive ventilation", "vent information", "settings", "home ventilator settings", "average volume-assured pressure support settings", "avaps settings"):
            continue
        meaningful.append(line)
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        label = aliases.get(label_key(label))
        if label is None:
            continue
        value = value.strip()
        if not is_present(value):
            continue
        if len(value) > 500:
            result.error = "A requested ventilation value is too long. Nothing was imported."
            return result
        if label in entries and normalize(strip_setting_marker(entries[label])) != normalize(strip_setting_marker(value)):
            result.error = "The C block contains conflicting repeated ventilation fields. Nothing was imported."
            return result
        entries[label] = value
    mode = entries.get("Vent Mode", "").strip()
    if not mode:
        if not meaningful or all(normalize(x.rstrip(".")) in ("none", "no invasive ventilation", "not documented", "no results found") for x in meaningful):
            result.status = "empty"
        else:
            result.error = "No Vent Mode was found in the C block. The previous handoff was not changed."
        return result
    result.status = mode_rule(mode)
    if result.status == "excluded":
        result.issues.append("The C-block mode is excluded by your display rule (for example, BiLevel or CPAP). No invasive ventilation block was added.")
        return result
    if result.status == "unknown":
        result.issues.append("The C-block mode is not recognized by the automatic display rule. No invasive ventilation block was added. You can document it in Respiratory notes.")
        return result
    result.data = {"mode": mode, "values": {label: entries[label] for label in LABELS[1:] if entries.get(label, "").strip()}}
    try:
        validate_ventilation(result.data)
    except ValueError as exc:
        result.data = None
        result.error = str(exc)
        return result
    family = control_family(mode)
    required = ["Resp Rate (Set)", "PEEP (cm H2O)"]
    if family == "NAVA":
        required = ["NAVA level", "PEEP (cm H2O)"]
        if not any(is_present(entries.get(label, "")) for label in ("FiO2 (%)", "FiO2 set (%)")):
            required.append("FiO2 (%)")
    elif family == "PC":
        required.append("PIP Set (cm H2O)")
    elif family == "PS":
        required = ["Pressure Support (cm H2O)", "PEEP (cm H2O)"]
    elif family == "AVAPS":
        if not is_present(entries.get("Vt Set/Target ml", "")):
            required.append("Vt (Set, mL)")
        if is_present(entries.get("AVAPS Respiratory Rate", "")):
            required.remove("Resp Rate (Set)")
    elif family in {"PRVC", "VC", "VSV"}:
        required.append("Vt (Set, mL)")
    missing = [label for label in required if not entries.get(label, "").strip()]
    if missing:
        result.issues.append("Requested fields absent from C were left out: " + ", ".join(missing) + ".")
    if family == "AVAPS" and is_present(entries.get("AVAPS rate (cm H2O/min)", "")) and _avaps_rate_unit_needs_review(entries["AVAPS rate (cm H2O/min)"]):
        result.issues.append("The AVAPS rate value does not match its source field's cm H2O/min unit. The source label and value were retained for review.")
    return result


def parse_ventilation(block: str) -> VentilationResult:
    """Import a current snapshot and separately scoped, deduplicated mode history."""
    history = _history_context(block) if has_ventilation_history(block) else None
    if history is None:
        return _parse_single_ventilation(block)
    if history["flow_table"] and mode_rule(history["mode"]) == "unknown" and history["reported_at"]:
        result = VentilationResult(data={"mode": history["mode"], "values": {}}, status="unknown")
    else:
        result = _parse_single_ventilation(history["source"])
    result.issues.extend(history["notes"])
    if result.error or result.data is None:
        return result
    notes = list(history["notes"])
    other_modes = []
    for record in history["other_modes"]:
        values = {}
        if mode_rule(record["mode"]) == "included":
            parsed = _parse_single_ventilation("Vent Mode: " + record["mode"] + "\n" + record["source"])
            if parsed.error:
                note = "Conflicting settings for " + display_mode(record["mode"])[:160] + " were omitted. Review its source settings."
                notes.append(note)
                result.issues.append(note)
            elif parsed.data is not None:
                values = parsed.data["values"]
        else:
            note = "Unrecognized recorded mode " + record["mode"][:160] + " was retained without inferred settings."
            notes.append(note)
            result.issues.append(note)
        other_modes.append({"mode": record["mode"], "values": values, "reported_at": record["reported_at"],
                            **({"include": record["include"]} if "include" in record else {})})
    result.data["mode_history"] = {
        "reported_at": history["reported_at"],
        "other_modes": other_modes,
        "latest_confirmed": history["latest_confirmed"],
        "notes": list(dict.fromkeys(notes))[:24],
    }
    try:
        validate_ventilation(result.data)
    except ValueError as exc:
        result.data = None
        result.error = str(exc)
    return result


def parse_first_reported_ventilation(block: str) -> VentilationResult:
    """Fallback to supported first settings in this paste, without history work."""
    try:
        source = select_first_reported_ventilation_source(block)
    except ValueError as exc:
        return VentilationResult(error=str(exc))
    for raw in source.splitlines():
        label, separator, value = unwrap_vent_line(raw).partition(":")
        if separator and normalize(label) == "ventilator on" and normalize(strip_setting_marker(value)) in {"no", "off", "false"}:
            return VentilationResult(status="excluded", error="The first reported settings mark the ventilator Off. No invasive fallback was added.")
    result = _parse_single_ventilation(source, source_is_selected=True)
    if result.error:
        return result
    if result.data is None or result.status != "included":
        result.error = "No supported initial invasive mode was available for the first reported settings fallback."
        result.data = None
        return result
    displayed_settings = [line for line in _format_single_ventilation(result.data).splitlines()
                          if line and line != CPAP_TRIAL_TITLE
                          and not line.startswith(("Mode:", "Device:"))]
    if not result.data["values"] or not displayed_settings:
        result.error = "No first reported ventilator settings were available in this paste."
        result.data = None
        return result
    result.data["mode_history"] = {
        "reported_at": "", "other_modes": [], "latest_confirmed": False,
        "notes": [VENTILATION_HISTORY_FALLBACK_NOTE],
    }
    result.issues.append(VENTILATION_HISTORY_FALLBACK_NOTE)
    validate_ventilation(result.data)
    return result
