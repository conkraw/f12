"""C/D display rules for documented settings, not proof of current bedside use.

A named BiPAP mode needs both D-block pressures. When Vent Mode is absent,
both pressures can instead produce a visibly pressure-based BiPAP entry.
An explicit unknown/invasive mode, invasive airway, or Ventilator On: No
prevents that fallback. Standard nasal cannula and HFNC use their delivery
labels, never a numerical flow threshold. Values are not recalculated.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re
from ventilation import normalize, parse_ventilation, unwrap_vent_line
from ventilator_modes import spec, strip_setting_marker

DEVICE_FIELDS = {
    "BiPAP": ("IPAP", "EPAP", "FiO2"),
    "CPAP": ("EPAP", "FiO2"),
    "HFNC": ("Flow", "FiO2"),
    "Nasal cannula": ("Flow", "FiO2"),
    "AVAPS NIV": ("Set RR", "Set TV", "IPAP", "EPAP", "FiO2"),
    "NAVA NIV": ("Set RR", "EPAP", "FiO2"),
}


def key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.replace("₂", "2").casefold()).replace("cmh20", "cmh2o")


ALIASES = {
    "mode": ("Vent Mode",),
    "delivery": ("O2 Delivery Method", "Oxygen Delivery Method"),
    "ipap": ("Total Inspiratory Pressure (cm H2O)", "IPAP (cm H2O)", "IPAP"),
    "epap": ("Expiratory Positive Airway Pressure (EPAP) (cmH20)", "EPAP (cm H2O)", "EPAP"),
    "peep": ("PEEP (cm H2O)", "CPAP (cm H2O)"),
    "fio2": ("FiO2 (%)", "FiO2"),
    "fio2_set": ("FiO2 set (%)",),
    "flow": ("O2 Flow Rate (L/min)", "Oxygen Flow Rate (L/min)"),
    "on": ("Ventilator On",),
    "rr": ("Resp Rate (Set)",),
    "tv": ("Vt (Set, mL)",),
}
LOOKUP = {key(label): canonical for canonical, labels in ALIASES.items() for label in labels}
MISSING = {"", "--", "-", "n/a", "na", "none", "not documented"}


def clean(value: str) -> str:
    # Epic's (S) annotation is not part of the numerical setting.
    return re.sub(r"\s+", " ", strip_setting_marker(value)).strip()


def read_fields(block: str | None, block_name: str) -> dict[str, str]:
    entries = {}
    for raw in (block or "").splitlines():
        line = unwrap_vent_line(raw) if block_name == "C" else raw
        if ":" not in line:
            continue
        label, raw = line.split(":", 1)
        name = LOOKUP.get(key(label))
        if name is None:
            continue
        value = clean(raw.lstrip(":"))
        if normalize(value) in MISSING or normalize(value) == "no data recorded":
            continue
        if len(value) > 500:
            raise ValueError("A respiratory field is too long. Nothing was imported.")
        if name in entries and entries[name] != value:
            raise ValueError("The " + block_name + " block has conflicting repeated respiratory fields. Nothing was imported.")
        entries[name] = value
    return entries


def number(value: str) -> float | None:
    match = re.match(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))(?:\s|%|$)", value)
    return float(match.group(1)) if match else None


def present(value: str) -> bool:
    return normalize(value) not in MISSING


def valid_setting(value: str, setting: str) -> bool:
    n = number(value)
    if n is None:
        return False
    if setting in ("ipap", "flow"):
        return n > 0
    if setting == "fio2":
        return 0 < n <= 100
    return n >= 0


def mode_kind(mode: str) -> str | None:
    text = normalize(mode)
    known = spec(mode)
    if known and known[0] in ("AVAPS NIV", "NAVA NIV"):
        return known[0]
    bilevel = bool(re.search(r"\b(?:bi[ -]?level|bi[ -]?pap)\b", text))
    cpap = bool(re.search(r"\bcpap\b|continuous positive airway pressure", text))
    if bilevel == cpap:
        return None
    return "BiPAP" if bilevel else "CPAP"


def validate_noninvasive(devices: list[dict]) -> None:
    if not isinstance(devices, list) or len(devices) > len(DEVICE_FIELDS):
        raise ValueError("The non-invasive support list is invalid.")
    seen = set()
    for item in devices:
        if not isinstance(item, dict) or set(item) != {"device", "values", "flow_inferred", "pressure_inferred"}:
            raise ValueError("A non-invasive support entry has an invalid structure.")
        device = item["device"]
        if not isinstance(device, str) or device not in DEVICE_FIELDS or device in seen:
            raise ValueError("Non-invasive support device names must be supported and unique.")
        seen.add(device)
        if type(item["flow_inferred"]) is not bool or (item["flow_inferred"] and device != "HFNC"):
            raise ValueError("The respiratory flow-source flag is invalid.")
        if type(item["pressure_inferred"]) is not bool or (item["pressure_inferred"] and device != "BiPAP"):
            raise ValueError("The respiratory pressure-source flag is invalid.")
        values = item["values"]
        if not isinstance(values, dict) or not set(values).issubset(DEVICE_FIELDS[device]):
            raise ValueError("A non-invasive support entry contains an unexpected field.")
        for value in values.values():
            if not isinstance(value, str) or len(value) > 500 or "\n" in value or "\r" in value:
                raise ValueError("A non-invasive support value is invalid or too long.")
        required = ("IPAP", "EPAP") if device == "BiPAP" else (("EPAP",) if device == "CPAP" else ())
        if any(not valid_setting(values.get(label, ""), label.casefold()) for label in required):
            raise ValueError("BiPAP requires both IPAP and EPAP. CPAP requires a pressure. Remove a device when it is no longer used.")
        for label in ("Flow", "FiO2"):
            if present(values.get(label, "")) and not valid_setting(values[label], label.casefold()):
                raise ValueError("Flow must be positive and FiO2 must be a positive numerical setting no greater than 100.")
        if device == "HFNC" and item["flow_inferred"] and not valid_setting(values.get("Flow", ""), "flow"):
            raise ValueError("A flow-based HFNC entry requires a positive recorded flow.")


def format_noninvasive(devices: list[dict]) -> str:
    validate_noninvasive(devices)
    lines = []
    for item in devices:
        suffix = " (flow-based)" if item["flow_inferred"] else (" (pressure-based)" if item["pressure_inferred"] else "")
        label = item["device"] + suffix
        values = [field + ": " + item["values"][field].strip()
                  for field in DEVICE_FIELDS[item["device"]] if item["values"].get(field, "").strip()]
        lines.append(label + (" | " + " | ".join(values) if values else ""))
    return "\n".join(lines)


@dataclass
class SupportResult:
    invasive: dict | None = None
    devices: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    error: str = ""


def parse_respiratory(c_block: str | None, d_block: str | None) -> SupportResult:
    """Parse this paste only. Never recover a missing mode/pressure from old data."""
    result = SupportResult()
    try:
        c = read_fields(c_block, "C")
        d = read_fields(d_block, "D")
    except ValueError as exc:
        result.error = str(exc)
        return result
    mode_present = present(c.get("mode", ""))
    kind = mode_kind(c.get("mode", "")) if mode_present else None
    # C may contain only equipment lines and FiO2 after a mode disappears.
    # That is not a malformed respiratory paste and must not block A/B/D.
    if c_block is not None and mode_present:
        parsed = parse_ventilation(c_block)
        if parsed.error:
            result.error = parsed.error
            return result
        result.invasive = parsed.data
        if spec(c.get("mode", "")) and spec(c["mode"])[1] == "PS":
            delivered = normalize(d.get("delivery", ""))
            if re.search(r"high[ -]?flow|nasal cannula|mask", delivered):
                result.invasive = None
                result.issues.append("PS-CPAP settings coexist with a non-invasive delivery label. The non-invasive display rules were used; verify any carried-forward ventilator fields.")
        if parsed.status != "excluded" and kind is None:
            result.issues.extend(parsed.issues)
    if result.invasive is not None:
        if any(present(d.get(k, "")) for k in ("ipap", "epap", "flow")) or "high flow" in normalize(d.get("delivery", "")):
            result.issues.append("C contains a supported invasive mode. D-block non-invasive settings were not added to it. Check the source if these represent alternating support.")
        return result

    def setting(entries: dict, name: str) -> str:
        value = entries.get(name, "")
        if not present(value):
            return ""
        if not valid_setting(value, name):
            result.issues.append("A non-invasive " + name.upper() + " value was not a usable numerical setting and was omitted.")
            return ""
        return value

    def add_device(device: str, values: dict, flow_inferred: bool = False, pressure_inferred: bool = False) -> None:
        result.devices.append({"device": device, "values": {k: v for k, v in values.items() if v},
                               "flow_inferred": flow_inferred, "pressure_inferred": pressure_inferred})
        if not values.get("FiO2"):
            result.issues.append(device + " has no usable FiO2 in this paste. No FiO2 was invented.")

    ipap, epap = setting(d, "ipap"), setting(d, "epap")
    c_fio2, d_fio2 = setting(c, "fio2"), setting(d, "fio2")
    if not c_fio2 and valid_setting(c.get("fio2_set", ""), "fio2"):
        c_fio2 = c["fio2_set"]
    pressure_fio2 = c_fio2 or d_fio2
    delivery = normalize(d.get("delivery", "")).replace("-", " ")
    invasive_airway = bool(re.search(r"endotracheal|\bett\b|tracheostomy|\btrach\b", delivery))
    off = normalize(c.get("on", "")) in ("no", "false", "off")
    if off and (kind or ipap or epap):
        result.issues.append("Ventilator On is No/Off. The pressure-device entry was omitted.")
    elif kind == "BiPAP":
        if ipap and epap:
            add_device("BiPAP", {"IPAP": ipap, "EPAP": epap, "FiO2": pressure_fio2})
        else:
            result.issues.append("BiLevel mode is present, but both D-block IPAP and EPAP are required. No BiPAP entry was added.")
    elif kind == "CPAP":
        peep = setting(c, "peep")
        if epap and peep and number(epap) != number(peep):
            result.error = "CPAP pressure differs between C-block PEEP and D-block EPAP. Nothing was imported. Check the pasted settings."
            return result
        pressure = epap or peep
        if pressure:
            add_device("CPAP", {"EPAP": pressure, "FiO2": pressure_fio2})
        else:
            result.issues.append("CPAP mode is present without EPAP or PEEP. No CPAP entry was added.")
    elif kind in ("AVAPS NIV", "NAVA NIV"):
        # Preserve explicit NIV mode names. Do not recast these as BiPAP or infer
        # undisclosed target volumes, pressure bounds, or NAVA gain.
        values = {"Set RR": setting(c, "rr"), "EPAP": epap or setting(c, "peep"), "FiO2": pressure_fio2}
        if kind == "AVAPS NIV":
            values.update({"Set TV": setting(c, "tv"), "IPAP": ipap})
        add_device(kind, values)
        result.issues.append("Only the documented conventional settings for this NIV mode were retained. Review any additional device-specific settings in Epic.")
    elif not mode_present and ipap and epap and not invasive_airway:
        # Preserve the documented pair, but do not assert that BiPAP is current.
        # D is the source of these pressures, so prefer its FiO2 for this fallback.
        add_device("BiPAP", {"IPAP": ipap, "EPAP": epap, "FiO2": d_fio2 or c_fio2}, pressure_inferred=True)
        result.issues.append("Vent Mode is absent. Both D-block pressures were retained as BiPAP (pressure-based). These may be carried-forward settings, not proof of current or simultaneous device use. Remove the entry if it is no longer applicable.")
        if not d_fio2 and c_fio2:
            result.issues.append("The pressure-based entry uses C-block FiO2 because D has no FiO2. No device-specific value was inferred.")
    elif ipap or epap:
        result.issues.append("Pressures were found without enough compatible information to identify a pressure device. A missing mode needs both IPAP and EPAP and no invasive-airway label. Unknown modes are not guessed.")
    if kind and not c_fio2 and d_fio2 and result.devices:
        result.issues.append("The pressure device uses D-block FiO2 because C has no FiO2. The source does not provide separate device-specific FiO2 values.")

    explicit_hfnc = bool(re.search(r"\bhh?fnc\b|high\s*flow(?:\s+nasal)?(?:\s+cannula)?", delivery))
    explicit_nc = not explicit_hfnc and bool(re.search(r"\bnasal\s+cannula\b|\blow\s*flow\s+cannula\b|\blfnc\b|^nc$", delivery))
    pressure_mask = "mask" in delivery and bool(re.search(r"cpap|bi[ -]?pap|bilevel", delivery))
    flow = setting(d, "flow")
    inferred = not explicit_hfnc and not explicit_nc and bool(flow) and pressure_mask and bool(result.devices)
    if explicit_hfnc or explicit_nc:
        device = "HFNC" if explicit_hfnc else "Nasal cannula"
        if number(d.get("flow", "")) == 0:
            result.issues.append(device + " has a recorded zero flow. No flowing-device entry was added.")
        else:
            add_device(device, {"Flow": flow, "FiO2": d_fio2})
            if not flow:
                result.issues.append(device + " is explicitly listed but its flow is missing. Enter the verified flow in the support editor.")
    elif inferred:
        # Existing user-defined convention remains visible as an inference.
        add_device("HFNC", {"Flow": flow, "FiO2": d_fio2}, flow_inferred=True)
        result.issues.append("HFNC was added from O2 Flow Rate using your mask-plus-flow convention. The source labels the delivery as a CPAP/Bi-PAP mask, not HFNC. It is marked flow-based in the handoff and can be removed in the editor.")
    elif flow:
        result.issues.append("A flow was recorded without a recognized cannula label or the configured pressure-mask pattern. It was not relabeled as HFNC or nasal cannula.")
    if not mode_present and c_block is not None and not result.devices:
        result.issues.append("No Vent Mode or supported D-block device was found in this paste. No respiratory device was invented.")
    try:
        validate_noninvasive(result.devices)
    except ValueError as exc:
        result.error = str(exc)
    return result
