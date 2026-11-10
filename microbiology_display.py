"""Safe display markup for recorded culture organisms and positive viral targets.

This module changes presentation only. It does not infer infection, alter stored
results, or interpret organism significance. All source strings are escaped.
"""
from __future__ import annotations
from html import escape
import re
from cultures import compact_groups, culture_display
from labs import short_date
from viral import positive_names


def is_organism_result(value: str) -> bool:
    """Emphasize named results, not negative, pending or administrative text."""
    text = re.sub(r"\s+", " ", value).strip()
    low = text.casefold()
    if not re.search(r"[a-z]", low):
        return False
    if re.search(r"\b(?:no growth|not detected|not isolated|not recovered|negative|no organisms?|no pathogen|no significant growth|no bacteria|no fungus|no fungi)\b", low):
        return False
    if re.search(r"^(?:pending|in process|in progress|preliminary|final|not performed|cancelled|canceled|unable to|insufficient|specimen rejected|test not|culture in progress|culture pending|results? pending)\b", low):
        return False
    if re.search(r"\b(?:normal|usual|mixed) (?:respiratory |oral |skin |urogenital |bacterial |commensal )?flora\b", low):
        return False
    if low in {"none", "n/a", "unknown", "no result", "no results", "see comment", "see comments"}:
        return False
    return True


def culture_markup(data: dict, esc=escape, empty_none: bool = False) -> str:
    groups = compact_groups(data)
    if not groups:
        return "<b>Cultures:</b> None" if empty_none and not data["rows"] else ""
    lines = ["<b>Cultures</b>"]
    for group in groups:
        values = ["<b>" + esc(value) + "</b>" if is_organism_result(value) else esc(culture_display(value))
                  for value in group["organisms"]]
        lines.append(esc(short_date(group["date"])) + " | " + esc(group["specimen"]) + " | " + " / ".join(dict.fromkeys(values)))
    return "\n".join(lines)


def viral_markup(data: dict, esc=escape) -> str:
    names = positive_names(data)
    return "Rapid Viral Panel: " + ", ".join("<b>" + esc(name) + "</b>" for name in names) if names else ""
