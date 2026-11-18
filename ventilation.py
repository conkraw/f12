"""A deterministic import rule for the C block, not an airway diagnosis.

Explicit source modes and set/observed fields are preserved separately.
Known non-invasive modes use the C/D support parser. Mode names alone do not
establish airway route. No D/E values, observed rate, or equipment fields are
substituted for a C-block setting. AVAPS targets retain their own source fields.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re
from ventilator_modes import spec, display_mode, control_family, strip_setting_marker

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
    if not isinstance(data, dict) or set(data) != {"mode", "values"}:
        raise ValueError("The saved ventilation block has an invalid structure.")
    if not isinstance(data["mode"], str) or not data["mode"].strip() or len(data["mode"]) > 500 or "\n" in data["mode"] or "\r" in data["mode"]:
        raise ValueError("The ventilation mode is empty or too long.")
    if mode_rule(data["mode"]) != "included":
        raise ValueError("This mode is not included by the automatic invasive-ventilation display rule.")
    values = data["values"]
    if not isinstance(values, dict) or not set(values).issubset(set(LABELS[1:])):
        raise ValueError("The ventilation block contains an unexpected field.")
    for value in values.values():
        if not isinstance(value, str) or len(value) > 500 or "\n" in value or "\r" in value:
            raise ValueError("A ventilation value is invalid or too long.")


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


def format_ventilation(data: dict | None) -> str:
    validate_ventilation(data)
    if data is None:
        return ""
    values = data["values"]
    family = control_family(data["mode"])
    if family == "NAVA":
        return _format_nava(data)
    home = home_vent(data)
    lines = ["Device: Home Vent"] if home else []
    lines.append("Mode: " + display_mode(data["mode"], home=home))

    def add(source: str, label: str, unit: str = "") -> None:
        value = values.get(source, "").strip()
        if is_present(value):
            lines.append(label + ": " + _measurement(value, unit))

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
    return "\n".join(lines)


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
    if stats and normalize(stats.group(1)) in {normalize(x) for x in ("PIP Observed (cm H2O)", "Vt Insp ml", "Vt Exp ml", "Vt (observed, mL)", "Vti", "Vte", "EDI peak", "EDI min", "Resp Rate Observed")}:
        line = stats.group(1).strip() + ": " + stats.group(2)
    return line


def select_ventilation_source(block: str) -> str:
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


def parse_ventilation(block: str) -> VentilationResult:
    result = VentilationResult()
    aliases = {normalize(label): label for label in LABELS}
    aliases.update(AVAPS_LABEL_ALIASES)
    aliases.update(OBSERVED_VOLUME_ALIASES)
    # Subscript characters in labels are typography only. Values stay verbatim.
    def label_key(label: str) -> str:
        return normalize(label.replace("₂", "2"))
    entries: dict[str, str] = {}
    meaningful = []
    source = select_ventilation_source(block)
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
