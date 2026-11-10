"""Positive-only display of the separated O / Respiratory Viral Panel block.

This is literal result parsing, not a diagnosis of current infection. Names are
explicit UI aliases. The source component, result and date remain available for
review. Unknown codes stay unchanged, and combined targets are never split.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import uuid
from labs import date_parts, DATE_TAIL

MAX_ROWS = 500
ALIASES = {
    "ADENOVIRDNA": "Adenovirus",
    "HUMRHINENRNA": "Rhinovirus/enterovirus",
    "FLUAVIRUSRNA": "Influenza A",
    "FLUBVIRUSRNA": "Influenza B",
    "PARAFLU1RNA": "Parainfluenza 1",
    "PARAFLU2RNA": "Parainfluenza 2",
    "PARAFLU3RNA": "Parainfluenza 3",
    "PARAFLU4RNA": "Parainfluenza 4",
    "RESPSYNVRNA": "RSV",
    # SARSRNA is not expanded to a specific virus without verified local metadata.
    # A positive unfamiliar code remains visible, never discarded.
}
# Documented text aliases do not introduce a more specific species or subtype.
TEXT_ALIASES = {
    "human rhinovirus/enterovirus": "Rhinovirus/enterovirus",
    "human rhinovirus / enterovirus": "Rhinovirus/enterovirus",
    "rhinovirus/enterovirus": "Rhinovirus/enterovirus",
    "respiratory syncytial virus": "RSV",
    "rsv": "RSV",
    "rhinovirus": "Rhinovirus",
    "adenovirus": "Adenovirus",
    "influenza a": "Influenza A",
    "influenza b": "Influenza B",
    "sars-cov-2": "SARS-CoV-2",
    "human metapneumovirus": "Human metapneumovirus",
}
FLAGS = re.compile(r"(?:\s*(?:\((?:A|AB|ABNORMAL|H|L|HH|LL)\)|\[(?:A|AB|ABNORMAL)\]|\*))+$", re.I)
POSITIVE = {"detected", "positive"}
NEGATIVE = {"not detected", "negative", "undetected", "non detected", "non-detected"}
NONRESULT = {"", "--", "none", "n/a", "not documented", "no results found", "no data"}


def component_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def display_name(component: str) -> str:
    source = component.strip()
    return ALIASES.get(source.upper(), TEXT_ALIASES.get(component_key(source), source))


def result_status(value: str) -> str:
    text = re.sub(r"\s+", " ", value.replace("\u00a0", " ").strip())
    text = FLAGS.sub("", text).strip().casefold()
    if text in POSITIVE:
        return "positive"
    if text in NEGATIVE:
        return "negative"
    return "unresolved"


def empty_viral_panel() -> dict:
    return {"rows": []}


def validate_viral_panel(data: dict) -> None:
    if not isinstance(data, dict) or set(data) != {"rows"}:
        raise ValueError("The respiratory viral panel has an invalid structure.")
    if not isinstance(data["rows"], list) or len(data["rows"]) > MAX_ROWS:
        raise ValueError("The respiratory viral panel is invalid or too large.")
    ids = set()
    for row in data["rows"]:
        if not isinstance(row, dict) or set(row) != {"id", "component", "name", "result", "date", "include"}:
            raise ValueError("A respiratory viral panel row has an invalid structure.")
        if not isinstance(row["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", row["id"]) or row["id"] in ids:
            raise ValueError("Respiratory viral panel row identifiers must be unique.")
        ids.add(row["id"])
        for key, limit in (("component", 200), ("name", 200), ("result", 500), ("date", 80)):
            value = row[key]
            if (not isinstance(value, str) or len(value) > limit
                    or any(ord(c) < 32 for c in value)
                    or (key != "result" and not value.strip())):
                raise ValueError("A respiratory viral panel field is empty or invalid.")
        try:
            date_parts(row["date"])
        except ValueError:
            raise ValueError("A respiratory viral panel date could not be read. Use the source date and optional time.") from None
        if not isinstance(row["include"], bool):
            raise ValueError("A respiratory viral panel inclusion setting is invalid.")
    _latest_groups(data)


def _latest_groups(data: dict) -> list[list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in data["rows"]:
        grouped.setdefault(component_key(row["component"]), []).append(row)
    selected = []
    for rows in grouped.values():
        latest_day = max(date_parts(r["date"])[0].date() for r in rows)
        recent = [r for r in rows if date_parts(r["date"])[0].date() == latest_day]
        if all(date_parts(r["date"])[1] for r in recent):
            newest = max(date_parts(r["date"])[0] for r in recent)
            recent = [r for r in recent if date_parts(r["date"])[0] == newest]
        statuses = {result_status(r["result"]) for r in recent}
        if "positive" in statuses and len(statuses) > 1:
            raise ValueError("Conflicting latest respiratory viral results have no clear order. Add verified collection times or correct the O block. Nothing was imported.")
        selected.append(recent)
    return selected


def positive_names(data: dict) -> list[str]:
    validate_viral_panel(data)
    names, seen = [], set()
    for recent in _latest_groups(data):
        row = next((r for r in recent if r["include"] and result_status(r["result"]) == "positive"), None)
        if row is None:
            continue
        name = row["name"].strip()
        key = component_key(name)
        if key not in seen:
            names.append(name)
            seen.add(key)
    return names


def viral_text(data: dict) -> str:
    names = positive_names(data)
    return "Rapid Viral Panel: " + ", ".join(names) if names else ""


@dataclass
class ViralResult:
    data: dict = field(default_factory=empty_viral_panel)
    issues: list[str] = field(default_factory=list)
    error: str = ""


def parse_viral_panel(block: str) -> ViralResult:
    out = ViralResult()
    try:
        if not isinstance(block, str):
            raise ValueError("The respiratory viral panel text is invalid.")
        for number, raw in enumerate(block.replace("\r\n", "\n").replace("\r", "\n").splitlines(), 1):
            line = raw.replace("\u00a0", " ").strip()
            if (line.casefold().rstrip(":.") in NONRESULT
                    or line.casefold().rstrip(":") in {"respiratory viral panel", "lab results"}
                    or re.match(r"^no results found(?:\s+for\b|\s*[.:]|$)", line, re.I)):
                continue
            cells = [c.strip() for c in line.split("\t")] if "\t" in line else re.split(r"\s{2,}", line)
            if [component_key(c) for c in cells] == ["component", "value", "date"] or re.fullmatch(r"component\s+value\s+date", line, re.I):
                continue
            if len(cells) == 3:
                component, value, date = cells
            else:
                # Permit collapsed spacing only with a one-token component and
                # a complete dated row. Multiword labels need tabs/2+ spaces.
                dated = DATE_TAIL.search(line)
                if not dated:
                    raise ValueError(f"Respiratory viral panel row {number} could not be separated safely. Keep Component, Value and Date columns.")
                prefix = line[:dated.start()].strip()
                match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_./+-]*)\s+(.+)", prefix)
                if not match:
                    raise ValueError(f"Respiratory viral panel row {number} could not be separated safely. Keep Component, Value and Date columns.")
                component, value, date = match.group(1), match.group(2), dated.group("date")
            out.data["rows"].append({"id": uuid.uuid4().hex, "component": component,
                                     "name": display_name(component), "result": value,
                                     "date": date, "include": True})
            if len(out.data["rows"]) > MAX_ROWS:
                raise ValueError("The respiratory viral panel has too many rows. Paste one patient at a time.")
        validate_viral_panel(out.data)
        if any(result_status(r["result"]) == "unresolved" for r in out.data["rows"]):
            out.issues.append("Some respiratory viral results are pending, inconclusive or unrecognized. Only explicit Detected or Positive results print. Review the retained rows under Labs / Vitals.")
        if any(r["name"] == r["component"] and result_status(r["result"]) == "positive" for r in out.data["rows"]):
            out.issues.append("A positive respiratory component has no display-name alias. Its source label was kept unchanged and can be edited under Labs / Vitals.")
    except ValueError as exc:
        out.error = str(exc)
        out.data = empty_viral_panel()
    return out
