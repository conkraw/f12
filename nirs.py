"""Read documented cerebral NIRS ranges and latest values without calculation."""
from __future__ import annotations

from decimal import Decimal
import re


_NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
_NAME = r"(?:nirs(?:\s+cerebral)?(?:\s+range)?|r\s*so[2₂]\s+cerebral|cerebral\s+r\s*so[2₂])"
_PREFIX = re.compile(
    rf"^(?P<last>last\s+)?(?P<name>{_NAME})(?=$|[\s:(%])"
    r"(?P<qualifiers>(?:\s*(?:\(\s*%\s*\)|%))*)\s*:?\s*(?P<body>.*)$", re.I,
)
_STAT = re.compile(r"\b(avg|average|min|minimum|max|maximum)\s*:", re.I)
_MISSING = {"", "no data recorded", "not recorded", "not documented", "none", "n/a", "--", "-"}


def is_nirs_label(label: str) -> bool:
    """Recognize NIRS/cerebral labels, excluding other saturation channels."""
    match = _PREFIX.fullmatch(label.strip())
    return match is not None and not match.group("body").strip()


def _value(text: str, percent_hint: bool = False) -> tuple[str, str] | None:
    match = re.fullmatch(rf"(?P<flag>\(!\)\s*)?(?P<number>{_NUMBER})\s*(?P<unit>%)?", text.strip())
    if match is None:
        return None
    number = match.group("number")
    if not Decimal("0") <= Decimal(number) <= Decimal("100"):
        raise ValueError("NIRS values must be between 0 and 100. Check the source.")
    return (("(!) " if match.group("flag") else "") + number,
            "%" if match.group("unit") or percent_hint else "")


def _formatted(value: tuple[str, str]) -> str:
    return value[0] + value[1]


def parse_nirs_line(text: str) -> tuple[str, str] | None:
    """Return normalized NIRS/Last NIRS, empty labels for absence, or None.

    Missing endpoints stay explicitly labeled. The average never supplies a
    missing endpoint, and values are never sorted, clipped or synthesized.
    """
    match = _PREFIX.fullmatch(text.strip())
    if match is None:
        return None
    label = ("Last " if match.group("last") else "") + "NIRS"
    percent_hint = "%" in match.group("qualifiers")
    body = match.group("body").strip()
    # Epic repeats its channel label after NIRS Range and Last NIRS.
    nested = _PREFIX.fullmatch(body)
    if nested:
        percent_hint = percent_hint or "%" in nested.group("qualifiers")
        body = nested.group("body").strip()
    if body.casefold().rstrip(".:") in _MISSING:
        return "", ""
    if match.group("last"):
        value = _value(body, percent_hint)
        if value is None:
            raise ValueError("The latest NIRS value could not be read. Check the source.")
        return label, _formatted(value)
    markers = list(_STAT.finditer(body))
    if markers and markers[0].start() == 0:
        limits = {}
        recorded = False
        for index, marker in enumerate(markers):
            stat = marker.group(1).casefold()
            end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
            source = body[marker.end():end].strip()
            if source.casefold().rstrip(".:") in _MISSING:
                continue
            recorded = True
            if stat.startswith("av"):
                continue
            stat = "min" if stat.startswith("min") else "max"
            value = _value(source, percent_hint)
            if value is None:
                raise ValueError("NIRS Min/Max need numeric percentage values. Check the source.")
            if stat in limits:
                previous = limits[stat]
                if (Decimal(previous[0].removeprefix("(!) ")) != Decimal(value[0].removeprefix("(!) "))
                        or previous[1] != value[1]):
                    raise ValueError("NIRS has conflicting repeated Min or Max values. Check the source.")
            limits.setdefault(stat, value)
        if set(limits) == {"min", "max"}:
            if limits["min"][1] != limits["max"][1]:
                raise ValueError("NIRS Min and Max use inconsistent percentage units. Check the source.")
            if Decimal(limits["min"][0].removeprefix("(!) ")) > Decimal(limits["max"][0].removeprefix("(!) ")):
                raise ValueError("NIRS Min is greater than Max. Check the source.")
            return label, _formatted(limits["min"]) + " to " + _formatted(limits["max"])
        return (label, body) if recorded else ("", "")
    value = _value(body, percent_hint)
    return label, _formatted(value) if value else body


def nirs_display_rows(rows: list[dict]) -> list[dict]:
    """Combine a compatible, unambiguous last value without changing storage."""
    active = []
    for row in rows:
        if not row["include"]:
            continue
        current = dict(row)
        if current["section"] == "Neurologic":
            try:
                parsed = parse_nirs_line(current["label"] + ": " + current["value"])
            except ValueError:
                parsed = None
            if parsed is not None:
                label, value = parsed
                if not label:
                    continue
                current.update(label=label, value=value)
        active.append(current)
    indices = [i for i, row in enumerate(active)
               if row["section"] == "Neurologic" and row["label"] in ("NIRS", "Last NIRS")]
    if not indices:
        return active
    regular = list(dict.fromkeys(active[i]["value"] for i in indices if active[i]["label"] == "NIRS"))
    latest = list(dict.fromkeys(active[i]["value"] for i in indices if active[i]["label"] == "Last NIRS"))

    def row(label: str, value: str) -> dict:
        return {"label": label, "value": value, "section": "Neurologic", "include": True}

    group = None
    if len(regular) == len(latest) == 1:
        try:
            last = _value(latest[0])
        except ValueError:
            last = None
        if last and (not last[1] or "%" in regular[0]):
            group = [row("NIRS", regular[0] + " [last " + last[0] + "]")]
    if group is None and not regular and len(latest) == 1:
        group = [row("NIRS", "Last: " + latest[0])]
    if group is None:
        group = [row("NIRS", value) for value in regular] + [row("Last NIRS", value) for value in latest]
    out = []
    for index, current in enumerate(active):
        if index == indices[0]:
            out.extend(group)
        if index not in indices:
            out.append(current)
    return out
