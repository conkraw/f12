"""Narrow support for Epic's EN-space clipboard table, alongside canonical tabs.

A single ordinary space is never interpreted as a column delimiter. EN/EM-space
boundaries must isolate a known route and a plausible frequency. Empty columns
are reconstructed only when their positions are unambiguous. Raw provider and
administration strings are returned for immediate sanitation, never logged here.
"""
from __future__ import annotations
import re
from infusion_rates import is_rate

_SPECIAL = re.compile(r"[\u2000-\u200a]+")
_ROUTE = re.compile(r"^(?:intravenous|iv|intra-?arterial|intracatheter|intramuscular|subcutaneous|subcut|sq|oral|rectal|topical|irrigation|inhalation|inhaled|nebulization|nebulisation|ophthalmic|otic|nasal|each nostril|both eyes|left eye|right eye|left ear|right ear|both ears|apply externally|buccal|sublingual|epidural|intrathecal|per\s+(?:nj|ng|og|g|j|gj|peg)\s+tube)$", re.I)
_FREQ = re.compile(r"^(?:q\s*\d|q\s+(?:am|pm)|continuous\b|once\b|on call\b|prn\b|as needed\b|daily\b|nightly\b|bid|tid|qid|weekly\b|every\b|titrate\b|titratable\b|twice\b|three\b|four\b|at bedtime\b)", re.I)
_EVENT = re.compile(r"^(?:stopped|paused|held|not given|given|rate(?:/dose)?\s+(?:change|changed|verify)|new bag|restart(?:ed)?|discontinued)\b", re.I)


def split_medication_columns(chunk: str) -> tuple[list[str], list[str]]:
    """Return cells and static warnings. Ordinary/tab-delimited input is unchanged."""
    if "\t" in chunk or not _SPECIAL.search(chunk):
        return chunk.split("\t"), []
    cells = [c.strip() for c in _SPECIAL.split(chunk) if c.strip()]
    if len(cells) == 1 and re.search(r"\bADS\s+Override\s+Pull\s*$", cells[0], re.I):
        return cells, []
    routes = [i for i, cell in enumerate(cells) if _ROUTE.fullmatch(cell)]
    if len(routes) != 1 or routes[0] not in (1, 2):
        return [], []
    index = routes[0]
    if index + 1 >= len(cells) or not _FREQ.match(cells[index + 1]):
        return [], []
    name, dose = cells[0], cells[1] if index == 2 else ""
    route, frequency = cells[index:index + 2]
    tail = cells[index + 2:]
    provider = ""
    # An event/numeric token cannot be safely mistaken for a clinician name.
    if tail and not (_EVENT.match(tail[0]) or re.match(r"^[\d.]", tail[0])):
        provider = tail.pop(0)
    if len(tail) > 2:
        return [], []
    rate, admin = "", ""
    warnings = []
    if len(tail) == 2:
        rate, admin = tail
        # A distinct Last Rate column must contain an explicit rate or status.
        before_time = re.split(r"\s+at\s+", rate, maxsplit=1, flags=re.I)[0]
        if not is_rate(before_time) and not _EVENT.match(rate):
            return [], []
    elif len(tail) == 1:
        item = tail[0]
        before_time = re.split(r"\s+at\s+", item, maxsplit=1, flags=re.I)[0]
        if is_rate(before_time):
            warnings.append("The spaced clipboard text has one numeric rate without a reliable Last Rate/Last Admin boundary. That rate was not assigned. Copy the row with tabs or enter the verified rate.")
        elif _EVENT.match(item) or re.match(r"^[\d.]", item):
            admin = item
        else:
            return [], []
    return [name, dose, route, frequency, provider, rate, admin], warnings
