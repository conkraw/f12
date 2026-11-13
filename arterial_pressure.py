"""Presentation of documented arterial pressures, without calculating a MAP.

Only explicit arterial labels are recognized. Recorded BP pairs stay paired.
The same helper reads older rows split at their first ``Min:``/``Avg:`` colon,
so recalled handoffs gain the new layout without changing their saved values.
"""
from __future__ import annotations

from decimal import Decimal
import re

_NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
_UNIT = r"(?:mm\s*hg|cm\s*h[2₂]o|kpa)"
_NAME = (
    r"(?:arterial(?:\s+line)?\s+(?:blood\s+pressure|mean\s+arterial\s+pressure|bp|map|pressure)"
    r"|art\.?\s+(?:line\s+)?(?:bp|map)|abp)"
)
_PREFIX = re.compile(
    rf"^(?P<last>last\s+)?(?P<name>{_NAME})(?=$|[\s:(])"
    rf"(?P<qualifiers>(?:\s*\(\s*{_UNIT}\s*\))*)\s*:?\s*(?P<body>.*)$", re.I,
)
_STAT = re.compile(r"\b(avg|average|min|minimum|max|maximum)\s*:", re.I)
_MISSING = {"", "no data recorded", "not recorded", "not documented", "none", "n/a", "--", "-"}
_CUFF = re.compile(r"^(?:bp|blood\s+pressure|cuff\s*(?:bp|blood\s+pressure))$", re.I)


def _unit(text: str) -> str:
    key = re.sub(r"\s+", "", text.casefold().replace("₂", "2"))
    return {"": "", "mmhg": "mmHg", "cmh2o": "cmH2O", "kpa": "kPa"}[key]


def _kind(name: str) -> str:
    return "ART MAP" if re.search(r"\bmap\b|\bmean\b", name, re.I) else "ART BP"


def _value(text: str, kind: str, hint: str = "") -> tuple[str, str] | None:
    number = rf"{_NUMBER}\s*/\s*{_NUMBER}" if kind == "ART BP" else _NUMBER
    match = re.fullmatch(rf"(?P<flag>\(!\)\s*)?(?P<number>{number})\s*(?P<unit>{_UNIT})?", text.strip(), re.I)
    if match is None:
        return None
    units = _unit(match.group("unit") or "") or hint
    if hint and units != hint:
        raise ValueError(kind + " has conflicting pressure units. Check the source.")
    value = re.sub(r"\s*/\s*", "/", match.group("number"))
    return (("(!) " if match.group("flag") else "") + value, units)


def _format_value(value: tuple[str, str]) -> str:
    return value[0] + (" " + value[1] if value[1] else "")


def parse_arterial_line(text: str) -> tuple[str, str] | None:
    """Return a normalized label/value, ('', '') for absence, or None.

    Average-only or partial summaries retain their supplied statistic labels.
    Missing endpoints are not filled from the average or a latest reading.
    Other ordinary arterial value formats remain verbatim for review.
    """
    match = _PREFIX.fullmatch(text.strip())
    if match is None:
        return None
    kind = _kind(match.group("name"))
    label = ("Last " if match.group("last") else "") + kind
    hints = {_unit(m.group()) for m in re.finditer(_UNIT, match.group("qualifiers"), re.I)}
    if len(hints) > 1:
        raise ValueError(kind + " has conflicting pressure units in its label. Check the source.")
    hint = next(iter(hints), "")
    body = match.group("body").strip()
    # Epic repeats the full field name after its "Last Arterial ...:" label.
    nested = _PREFIX.fullmatch(body)
    if match.group("last") and nested and _kind(nested.group("name")) == kind:
        nested_hints = {_unit(m.group()) for m in re.finditer(_UNIT, nested.group("qualifiers"), re.I)}
        hints.update(nested_hints)
        if len(hints) > 1:
            raise ValueError(kind + " has conflicting pressure units. Check the source.")
        hint = next(iter(hints), "")
        body = nested.group("body").strip()
    if body.casefold().rstrip(".:") in _MISSING:
        return "", ""
    if match.group("last"):
        value = _value(body, kind, hint)
        return label, _format_value(value) if value else body
    markers = list(_STAT.finditer(body))
    if markers and markers[0].start() == 0:
        limits = {}
        for index, marker in enumerate(markers):
            stat = marker.group(1).lower()
            if stat.startswith("av"):
                continue
            stat = "min" if stat.startswith("min") else "max"
            end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
            source = body[marker.end():end].strip()
            if source.casefold().rstrip(".:") in _MISSING:
                continue
            value = _value(source, kind, hint)
            if value is None:
                raise ValueError(kind + " Min/Max could not be read. Check the recorded values and units.")
            if stat in limits and limits[stat] != value:
                raise ValueError(kind + " has conflicting repeated Min or Max values. Check the source.")
            limits[stat] = value
        if set(limits) == {"min", "max"}:
            if limits["min"][1] != limits["max"][1]:
                raise ValueError(kind + " Min and Max use different or incomplete units. Check the source.")
            if kind == "ART MAP":
                low = limits["min"][0].removeprefix("(!) ")
                high = limits["max"][0].removeprefix("(!) ")
                if Decimal(low) > Decimal(high):
                    raise ValueError("ART MAP Min is greater than Max. Check the source.")
            units = limits["min"][1]
            return label, limits["min"][0] + " to " + limits["max"][0] + (" " + units if units else "")
        # Keep incomplete evidence explicit. Do not turn an average into a range.
        return label, body
    value = _value(body, kind, hint)
    return label, _format_value(value) if value else body


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _combined(rows: list[dict], kind: str) -> list[dict]:
    regular = _deduplicate([r["value"] for r in rows if r["label"] == kind])
    latest = _deduplicate([r["value"] for r in rows if r["label"] == "Last " + kind])
    def row(label: str, value: str) -> dict:
        return {"label": label, "value": value, "section": "Cardiovascular", "include": True}
    if len(regular) == 1 and len(latest) == 1:
        last = _value(latest[0], kind)
        range_units = {_unit(m.group()) for m in re.finditer(_UNIT, regular[0], re.I)}
        # A single compatible latest value can share the range's line. A unit
        # mismatch or conflicting latest values must stay separately labeled.
        compatible = last is not None and (not last[1] or range_units == {last[1]})
        if compatible:
            return [row(kind, regular[0] + " [last " + last[0] + "]")]
    if not regular and len(latest) == 1:
        return [row(kind, "Last: " + latest[0])]
    return ([row(kind, v) for v in regular] +
            [row("Last " + kind, v) for v in latest])


def arterial_display_rows(rows: list[dict]) -> list[dict]:
    """Return active display rows, preserving the caller's stored records.

    Cuff BP, arterial BP and arterial MAP are consecutive when any arterial
    pressure reading is present. Other vitals and explicit section overrides
    are retained. Malformed legacy rows are displayed unchanged, never dropped.
    """
    active = []
    for row in rows:
        if not row["include"]:
            continue
        current = dict(row)
        if current["section"] == "Cardiovascular":
            try:
                parsed = parse_arterial_line(current["label"] + ": " + current["value"])
            except ValueError:
                parsed = None
            if parsed is not None:
                label, value = parsed
                if not label:
                    continue
                current.update(label=label, value=value)
        active.append(current)
    arterial = [i for i, r in enumerate(active)
                if r["section"] == "Cardiovascular" and r["label"] in
                {"ART BP", "Last ART BP", "ART MAP", "Last ART MAP"}]
    if not arterial:
        return active
    cuffs = [i for i, r in enumerate(active)
             if r["section"] == "Cardiovascular" and _CUFF.fullmatch(r["label"].strip())]
    insertion = cuffs[0] if cuffs else arterial[0]
    group = [dict(active[i], label="Cuff", value="BP " + active[i]["value"]) for i in cuffs]
    art_rows = [active[i] for i in arterial]
    group.extend(_combined(art_rows, "ART BP"))
    group.extend(_combined(art_rows, "ART MAP"))
    replaced = set(cuffs + arterial)
    out = []
    for index, row in enumerate(active):
        if index == insertion:
            out.extend(group)
        if index not in replaced:
            out.append(row)
    return out
