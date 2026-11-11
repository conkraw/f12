"""Parse Epic medication table rows, never infer a dose or therapeutic system.

TAB boundaries are authoritative. Providers and raw Last Admin are never retained.
Sanitized numeric Last Admin rates/status/times are kept for continuous infusions.
Mapping rules match medication-name prefixes/exact names, not patient doses.
Epic Followed by / And / Or connectors stay on the next separate order, outside table columns.
Source annotations remain editable. The handoff hides And/Or and START ON labels.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field
import re
import uuid
from infusion_rates import (ADMIN_FIELDS, continuous_order, parse_last_admin, validate_admin_fields,
                            administration_display, admin_display_text, show_recorded_pump_rate, requested_titration)
from medication_columns import split_medication_columns
from output_text import medication_name_output

DESTINATIONS = ("Neurologic", "Respiratory", "Cardiovascular", "FEN / GI", "Hematology",
                "Infectious Disease", "Labs", "Skin / Wounds", "Other Medications")
BULLET = re.compile(r"^\s*[•●▪◦\-]\s*")
SPACE = re.compile(r"\s+")
CONNECTOR = re.compile(r"^(followed\s+by|and|or)\s*:?$", re.I)
CONNECTOR_LABELS = {"followed by": "Followed by", "and": "And", "or": "Or"}
FOLLOW_PREFIX = re.compile(r"^followed\s+by\s*:?\s+", re.I)
AND_PREFIX = re.compile(r"^and\s*:\s+", re.I)
OR_PREFIX = re.compile(r"^or\s*:\s+", re.I)
STATUS_PREFIX = re.compile(r"^\[(?:held by provider|discontinued)\]\s*", re.I)
SCHEDULE_PREFIX = re.compile(r"^\[START\s+ON\s+[^\]\r\n]+\]\s*", re.I)
RATE = re.compile(r"^\s*(\d+(?:\.\d+)?\s*(?:m[lL]|[uµμ]g|mcg|mg|g|units?|Units?|mEq)(?:\s*/\s*(?:kg|hr|min|h|day|24h)){1,3})\b", re.I)
FIELDS = {"id", "name", "dose", "route", "frequency", "last_rate", "rate_time", "section",
          "custom_text", "include", "warnings", "hidden"}


def clean(value: str) -> str:
    return SPACE.sub(" ", value.replace("\u00a0", " ")).strip()


def normalized(value: str) -> str:
    return clean(value).casefold()


def _without_context(value: str, *, strip_schedule: bool) -> str:
    """Remove known display annotations for matching, not from the source record.

    Visibility keeps start dates so hiding one scheduled taper step does not hide
    another dated step with the same formulation. Routing ignores dates so an
    existing drug rule still applies. Unknown bracketed text is not discarded.
    """
    value = clean(value)
    patterns = (FOLLOW_PREFIX, AND_PREFIX, OR_PREFIX, STATUS_PREFIX, SCHEDULE_PREFIX) if strip_schedule else (FOLLOW_PREFIX, AND_PREFIX, OR_PREFIX, STATUS_PREFIX)
    while value:
        previous = value
        for pattern in patterns:
            value = pattern.sub("", value, count=1).strip()
        if value == previous:
            break
    return value


def match_name(value: str) -> str:
    return normalized(_without_context(value, strip_schedule=True))


def is_bupivacaine(name: str) -> bool:
    """Match the named ingredient, including combination products.

    This is the requested display placement only. The recorded route is never
    inferred or changed, even when it is not an epidural route.
    """
    return bool(re.search(r"(?<![a-z0-9])bupivacaine(?![a-z0-9])", match_name(name)))


def visibility_name(value: str) -> str:
    return normalized(_without_context(value, strip_schedule=False))


def _matches(name_key: str, term: str, match: str) -> bool:
    return name_key == term or (match == "prefix" and name_key.startswith(term)
        and len(name_key) > len(term) and not name_key[len(term)].isalnum())


def _destination_rule_matches(name: str, rule: dict) -> bool:
    term = normalized(rule["name"])
    # Keep explicitly date-qualified legacy rules working without broadening them.
    return any(_matches(key, term, rule["match"])
               for key in (match_name(name), visibility_name(name)))


def suggested_key(name: str) -> str:
    """A stable name prefix, used only after a user chooses a destination."""
    head = re.split(r"\(|\d", _without_context(name, strip_schedule=True), maxsplit=1)[0].strip()
    head = re.split(r"\s+(?:in\s+(?:NaCl|sodium chloride)|injection|infusion|syringe|nebulizer|ophthalmic|cream)\b", head, maxsplit=1, flags=re.I)[0]
    head = re.sub(r"\s+(?:NCS|PF|neo/ped)$", "", head, flags=re.I).strip(" ,-:;")
    head = re.sub(r"\s+continuous$", "", head, flags=re.I).strip()
    return normalized(head or name)


def destination_for(name: str, rules: list[dict]) -> str:
    if is_bupivacaine(name):
        return "Neurologic"
    choices = []
    for rule in rules:
        term = normalized(rule["name"])
        if _destination_rule_matches(name, rule):
            choices.append((rule["match"] == "exact", len(term), rule["destination"]))
    return max(choices)[2] if choices else "Other Medications"


def validate_rules(rules: list[dict]) -> None:
    if not isinstance(rules, list) or len(rules) > 1500:
        raise ValueError("The medication mapping list is invalid or too large.")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"name", "match", "destination"}:
            raise ValueError("A medication mapping has an invalid structure.")
        if not isinstance(rule["name"], str) or not 2 <= len(rule["name"]) <= 250 or '\n' in rule['name'] or '\t' in rule['name']:
            raise ValueError("Use a medication name of 2 to 250 characters, on one line.")
        if rule["match"] not in ("prefix", "exact") or rule["destination"] not in DESTINATIONS:
            raise ValueError("A medication mapping has an invalid destination or match type.")
        key = (normalized(rule["name"]), rule["match"])
        if key in seen:
            raise ValueError("Duplicate medication mappings were found.")
        seen.add(key)


def upsert_rule(rules: list[dict], name: str, destination: str, match: str = "prefix") -> list[dict]:
    rule = {"name": normalized(name), "match": match, "destination": destination}
    candidate = [deepcopy(r) for r in rules if (normalized(r["name"]), r["match"]) != (rule["name"], match)]
    candidate.append(rule)
    candidate.sort(key=lambda r: (r["name"], r["match"]))
    validate_rules(candidate)
    return candidate


def validate_medication(row: dict) -> None:
    if not isinstance(row, dict) or not FIELDS.issubset(row) or set(row) - FIELDS - {"infusion_mode", "gi_mode", "group_mode", "category_path"} - set(ADMIN_FIELDS):
        raise ValueError("A medication entry has an invalid structure.")
    if "category_path" in row:
        from categories import validate_snapshot
        validate_snapshot(row["category_path"])
    validate_admin_fields(row)
    if row.get("infusion_mode", "auto") not in ("auto", "infusion", "other"):
        raise ValueError("Choose a valid infusion display setting.")
    from fen_gi import MODES as GI_MODES
    from medication_groups import MODES as GROUP_MODES
    if row.get("gi_mode", "auto") not in GI_MODES:
        raise ValueError("Choose a valid FEN/GI display setting.")
    if row.get("group_mode", "auto") not in GROUP_MODES:
        raise ValueError("Choose a valid medication group.")
    if not isinstance(row["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", row["id"]):
        raise ValueError("A medication identifier is invalid.")
    for key in ("name", "dose", "route", "frequency", "last_rate", "rate_time", "custom_text"):
        if not isinstance(row[key], str) or len(row[key]) > 4000:
            raise ValueError("A medication entry is too long or invalid.")
    if not row["name"].strip() or row["section"] not in DESTINATIONS or not isinstance(row["include"], bool) or not isinstance(row["hidden"], bool):
        raise ValueError("Check the medication name, destination, and inclusion setting.")
    if not isinstance(row["warnings"], list) or len(row["warnings"]) > 20 or any(not isinstance(v,str) or len(v)>500 for v in row["warnings"]):
        raise ValueError("Medication review warnings are invalid.")


def format_medication(row: dict) -> str:
    """Use explicit dose column. Keep different formulation/ordered doses visible."""
    if row.get("custom_text", "").strip():
        return row["custom_text"].strip()
    # Clean only the local display name. Matching, schedules and rate selection
    # below continue to receive the complete original row.
    name = medication_name_output(row.get("_display_name") or row["name"])
    dose = row["dose"].strip()
    text = name
    normalized_title, normalized_dose = normalized(name), normalized(dose)
    start = len(normalized_title) - len(normalized_dose)
    # 190 mg must NOT count as an existing 90 mg or 0 mg dose.
    duplicate_dose = bool(normalized_dose and normalized_title.endswith(normalized_dose)
                          and (start == 0 or normalized_title[start-1].isspace()
                               or normalized_title[start-1] in "(="))
    admin_view = administration_display(row)
    if admin_view:
        text += " | " + admin_display_text(row)
    elif dose and not duplicate_dose:
        text += " | Dose: " + dose
    continuous = bool(re.search(r"\bcontinuous\b", row["frequency"], re.I))
    # A pump rate on an intermittent medication is not a replacement for its dose.
    if continuous and row["last_rate"] and show_recorded_pump_rate(row):
        primary_rate = admin_view[1] if admin_view else dose
        if normalized(primary_rate) != normalized(row["last_rate"]):
            text += " @ " + row["last_rate"]
    if row["route"].strip():
        text += " | " + row["route"].strip()
    if row["frequency"].strip():
        text += " | " + row["frequency"].strip()
    return text


def remap(rows: list[dict], rules: list[dict], visibility: list[dict] | None = None) -> list[dict]:
    result = deepcopy(rows)
    for row in result:
        row["section"] = destination_for(row["name"], rules)
        if visibility is not None:
            row["hidden"] = hidden_for(row["name"], visibility)
    return result


@dataclass
class MedicationResult:
    rows: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    error: str = ""
    empty_confirmed: bool = False


def parse_medications(block: str, rules: list[dict] | None = None, visibility: list[dict] | None = None) -> MedicationResult:
    """Receive only a validated B block, not the entire SmartPhrase.

    The standard table is Medication, Dose, Route, Frequency, Provider,
    Last Rate, Last Admin. Tabs preserve blank dose/rate cells. A malformed
    row stops the import, rather than guessing medication boundaries. Explicit
    EN-space clipboard columns are supported only with unambiguous route and
    frequency anchors. Ordinary space-separated prose is not treated as a table.
    Standalone Followed by, And, and Or connectors belong to the next separate order.
    START ON labels are preserved as source text, never compared with the server clock.
    """
    result = MedicationResult()
    rules = rules or []
    chunks: list[str] = []
    current = ""
    pending_sequence = ""
    leftovers = []

    def sequence_error(message: str) -> None:
        result.issues.append(message)
        result.error = "The medication sequence is incomplete. Nothing has been applied."

    def finish_current() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    def mark_sequence(label: str) -> None:
        nonlocal pending_sequence
        finish_current()
        if not chunks:
            sequence_error("A " + label + " line has no preceding medication. Copy the complete sequence.")
        if pending_sequence:
            sequence_error("Repeated medication connector lines have no medication between them. Check the original table.")
        pending_sequence = label

    def begin_order(value: str) -> None:
        nonlocal current, pending_sequence
        finish_current()
        # Preserve the source relationship in the editable source name. No
        # extra schema fields and no doses/frequencies are supplied or inferred.
        current = (pending_sequence + ": " if pending_sequence else "") + value
        pending_sequence = ""

    text = block.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if normalized(line.rstrip(':')) in ("medications", "current facility-administered medications"):
            continue
        if re.match(r"^Medication\s+Dose\s+Route\s+Frequency\b", line, flags=re.I):
            continue
        if normalized(line.rstrip('.')) in ("no current facility-administered medications", "no medications", "none"):
            result.empty_confirmed = True
            continue
        # This connector is table structure, NOT another column of Last Admin.
        # Accept ordinary whitespace, table indentation, and bullet-only forms.
        connector = CONNECTOR.fullmatch(clean(BULLET.sub("", raw, count=1)))
        if connector:
            mark_sequence(CONNECTOR_LABELS[normalized(connector.group(1))])
            continue

        # Some clipboard versions place the connector in a final TAB cell.
        # Remove only that exact cell, leaving every preceding blank cell intact.
        after_row_sequence = ""
        cells = raw.split("\t")
        last_nonempty = next((i for i in range(len(cells)-1, -1, -1) if cells[i].strip()), None)
        trailing_connector = (CONNECTOR.fullmatch(clean(cells[last_nonempty]))
                              if last_nonempty is not None and last_nonempty >= 4 else None)
        if trailing_connector:
            after_row_sequence = CONNECTOR_LABELS[normalized(trailing_connector.group(1))]
            raw = "\t".join(cells[:last_nonempty])

        if BULLET.match(raw):
            # Do not strip tabs. A trailing empty field is meaningful.
            begin_order(BULLET.sub("", raw, count=1))
        elif pending_sequence:
            # A complete tabular row can follow a connector even if its bullet
            # was omitted. A free-text fragment cannot safely identify the order.
            if "\t" in raw and len(raw.split("\t")) >= 4:
                begin_order(raw.lstrip(' '))
            else:
                leftovers.append(raw.strip())
        elif "\t" in raw and not current:
            begin_order(raw.lstrip(' '))
        elif current:
            if len(current.split("\t")) >= 4 and len(raw.split("\t")) >= 4:
                # Unbulleted, explicitly tab-separated table rows, not arbitrary
                # space-delimited text. Preserve order and empty interior cells.
                begin_order(raw.lstrip(' '))
            else:
                # Newline inside a cell/name before the next order.
                current += " " + raw.lstrip(' ')
        else:
            leftovers.append(raw.strip())
        if after_row_sequence:
            mark_sequence(after_row_sequence)
    finish_current()
    if pending_sequence:
        sequence_error("A " + pending_sequence + " line has no next medication. Copy the complete sequence.")
    if leftovers:
        result.issues.append("Some text in the medication block was not a table row. Check that the full Epic table was copied.")
        result.error = "The medication block contains unrecognized text. Nothing has been applied. Copy the table again with its column tabs."
    if len(chunks) > 300:
        result.error = "Too many medication rows. Paste one patient at a time."
        return result
    for index, chunk in enumerate(chunks, 1):
        source_cols, clipboard_warnings = split_medication_columns(chunk)
        cols = [clean(c) for c in source_cols]
        while len(cols) > 7 and not cols[-1]:
            cols.pop()
        # A clearly labelled ADS Override Pull can legitimately be a name-only
        # source row after clipboard trimming. Only pad when every later cell
        # is blank and the marker ends the name. Never rescue an ordinary order
        # or silently drop nonempty dose/route/frequency fragments.
        if (cols and re.search(r"\bADS\s+Override\s+Pull\s*$", cols[0], re.I)
                and not any(cols[1:])):
            cols = [cols[0]] + [''] * 6
        # Allow omitted trailing empty cells, but never infer missing internal columns.
        if len(cols) < 4 or len(cols) > 7:
            result.issues.append(f"Medication row {index}: columns could not be separated safely. Copy directly from Epic with tabs between cells.")
            result.error = "At least one medication row could not be read safely. Nothing has been applied."
            continue
        cols += [''] * (7-len(cols))
        name, dose, route, frequency, _provider, raw_rate, _last_admin = cols
        override_pull = bool(re.search(r"\bADS\s+Override\s+Pull\b", name, re.I))
        if not name or ((not route or not frequency) and not override_pull):
            result.issues.append(f"Medication row {index}: name, route, or frequency is missing. Check the original table.")
            result.error = "At least one medication row is incomplete. Nothing has been applied."
            continue
        warnings = list(clipboard_warnings)
        if override_pull:
            warnings.append("ADS Override Pull: retained as a separate source entry. Blank dose, route or frequency are not inferred. Hide this exact entry if it should not print.")
        rate, rate_time = '', ''
        if raw_rate:
            m = RATE.match(raw_rate)
            if m:
                rate = clean(m.group(1))
                tail = raw_rate[m.end():].strip()
                if tail.lower().startswith('at '):
                    rate_time = tail[3:].strip()
                elif tail:
                    warnings.append("The Last Rate field contained extra text. Verify the rate against Epic.")
            else:
                warnings.append("The Last Rate field could not be read as a numeric rate. Check Epic and edit the handoff wording if needed.")
        continuous = bool(re.search(r"\bcontinuous\b", frequency, re.I))
        if not dose:
            if continuous and rate:
                warnings.append("Dose was blank. The handoff uses Last Rate. Verify that the recorded rate is current.")
            else:
                warnings.append("Dose was blank in the source. No dose has been inferred.")
        if continuous and rate:
            warnings.append("The pump-rate entry comes from Last Rate, not a live pump feed.")
            if re.match(r'^0(?:\.0+)?\s', rate):
                warnings.append("The last recorded rate is zero. This does not establish that the order was discontinued.")
        row = {"id": uuid.uuid4().hex, "name": name, "dose": dose, "route": route,
               "frequency": frequency, "last_rate": rate, "rate_time": rate_time,
               "section": destination_for(name, rules), "custom_text": "", "include": True,
               "warnings": warnings, "hidden": hidden_for(name, visibility or [])}
        if continuous_order(row):
            row.update(parse_last_admin(_last_admin))
            if row["last_admin_status"] == "rate":
                warnings.append("The displayed dose-rate is the documented Last Admin rate, not a live pump reading. The ordered Dose remains in the editor.")
            elif row["last_admin_status"] in ("stopped", "paused", "held", "not_given", "not_administered", "discontinued"):
                warnings.append("Last Admin records a non-running or not-given event. The order is retained, but its older pump rate is not shown as current.")
            elif requested_titration(row):
                warnings.append("No unambiguous numeric rate was available in Last Admin. The handoff shows UNK rather than using an ordered titration range.")
        validate_medication(row)
        result.rows.append(row)
    if not result.rows and not result.error and not result.empty_confirmed:
        result.error = "No medication rows were found. Existing medications have not been changed."
    if result.rows and result.empty_confirmed:
        result.error = "The block says no medications but also contains orders. Check the source before importing."
    return result


def rule_for_inline_mapping(name: str, rules: list[dict]) -> tuple[str, str]:
    """Reuse the most specific matching rule, else a dose-free name prefix.

    Prefer a more-specific generated formulation prefix over a broad matched
    prefix (for example heparin flush rather than heparin). Exact rules remain
    editable without creating a conflicting lower-priority rule.
    """
    matches = [rule for rule in rules if _destination_rule_matches(name, rule)]
    suggested = suggested_key(name)
    if matches:
        best = max(matches, key=lambda r: (r["match"] == "exact", len(normalized(r["name"]))))
        if best["match"] == "exact" or len(normalized(best["name"])) >= len(suggested):
            return best["name"], best["match"]
    return suggested, "prefix"


def validate_visibility(rules: list[dict]) -> None:
    if not isinstance(rules, list) or len(rules) > 2000:
        raise ValueError("The medication visibility rules are invalid or too large.")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"name", "match", "hidden"}:
            raise ValueError("A medication visibility rule has an invalid structure.")
        if not isinstance(rule["name"], str) or not 2 <= len(rule["name"]) <= 4000 or any(c in rule["name"] for c in "\n\r\t"):
            raise ValueError("Use a medication name on one line.")
        if rule["match"] not in ("prefix", "exact") or not isinstance(rule["hidden"], bool):
            raise ValueError("A medication visibility rule is invalid.")
        key = (normalized(rule["name"]), rule["match"])
        if key in seen:
            raise ValueError("Medication visibility rules must be unique.")
        seen.add(key)


def hidden_for(name: str, rules: list[dict]) -> bool:
    name_key = visibility_name(name)
    choices = []
    for rule in rules:
        term = normalized(rule["name"])
        matched = _matches(name_key, term, rule["match"])
        if rule["match"] == "prefix":
            matched = matched or _matches(match_name(name), term, "prefix")
        if matched:
            choices.append((rule["match"] == "exact", len(term), rule["hidden"]))
    return max(choices)[2] if choices else False


def set_visibility_rule(rules: list[dict], name: str, hidden: bool, match: str = "exact") -> list[dict]:
    """An inline hide defaults to the exact formulation, not a broad drug family."""
    key = visibility_name(name) if match == "exact" else match_name(name)
    result = [deepcopy(r) for r in rules if (normalized(r["name"]), r["match"]) != (key, match)]
    result.append({"name": key, "match": match, "hidden": hidden})
    result.sort(key=lambda r: (r["name"], r["match"]))
    validate_visibility(result)
    return result


def visible(row: dict) -> bool:
    return row["include"] and not row.get("hidden", False)
