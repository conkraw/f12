"""A deterministic import rule for the C block, not an airway diagnosis.

Explicit source modes and set/observed fields are preserved separately.
Known non-invasive modes use the C/D support parser. Mode names alone do not
establish airway route. No D/E values, target Vt, observed rate, or equipment
fields are substituted for a C-block setting.
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
    home = home_vent(data)
    family = control_family(data["mode"])
    lines = ["Device: Home Vent"] if home else []
    lines.append("Mode: " + display_mode(data["mode"], home=home))

    def add(source: str, label: str, unit: str = "") -> None:
        value = values.get(source, "").strip()
        if is_present(value):
            lines.append(label + ": " + _measurement(value, unit))

    add("Resp Rate (Set)", "Set RR")
    if family == "PC":
        add("PIP Set (cm H2O)", "Set PIP", "cm H2O")
    elif family in {"PRVC", "VC", "AVAPS", "VSV"}:
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
    if family == "PC":
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
}


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
        known_labels = {normalize(x) for x in LABELS} | {"ti min", "ti max", "observed tve", "observed tvi", "vte", "vti"}
        if inner_key in known_labels or (inner and normalize(inner.group(1)) in known_labels):
            if nested_content == line:
                break
            line = nested_content
            continue
        # A wrapper with a scalar or an explicitly empty value is also supported.
        line = target + ": " + content
        break
    stats = re.match(r"^(.+?)\s+((?:Avg|Min|Max)\s*:.*)$", line, re.I)
    if stats and normalize(stats.group(1)) in {normalize(x) for x in ("PIP Observed (cm H2O)", "Vt Insp ml", "Vt Exp ml", "Vt (observed, mL)", "Vti", "Vte")}:
        line = stats.group(1).strip() + ": " + stats.group(2)
    return line


@dataclass
class VentilationResult:
    data: dict | None = None
    status: str = "empty"
    issues: list[str] = field(default_factory=list)
    error: str = ""


def parse_ventilation(block: str) -> VentilationResult:
    result = VentilationResult()
    aliases = {normalize(label): label for label in LABELS}
    aliases.update({
        "vti": "Vt Insp ml", "observed tvi": "Vt Insp ml",
        "vte": "Vt Exp ml", "observed tve": "Vt Exp ml",
        "vt exp ml": "Vt Exp ml", "vt (exhaled, ml)": "Vt Exp ml",
        "vt expired ml": "Vt Exp ml", "vt expiratory ml": "Vt Exp ml",
        "vt (inspired, ml)": "Vt Insp ml",
    })
    # Subscript characters in labels are typography only. Values stay verbatim.
    def label_key(label: str) -> str:
        return normalize(label.replace("₂", "2"))
    entries: dict[str, str] = {}
    meaningful = []
    for raw in block.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = unwrap_vent_line(raw)
        if not line or normalize(line.rstrip(":")) in ("invasive ventilation", "vent information", "settings", "home ventilator settings"):
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
    if family == "PC":
        required.append("PIP Set (cm H2O)")
    elif family in {"PRVC", "VC", "AVAPS", "VSV"}:
        required.append("Vt (Set, mL)")
    missing = [label for label in required if not entries.get(label, "").strip()]
    if missing:
        result.issues.append("Requested fields absent from C were left out: " + ", ".join(missing) + ".")
    return result
