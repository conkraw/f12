"""Select the latest listed PN and intravenous lipid orders for handoff output.

Source rows, their doses and their recorded rates are never changed. An explicit
order timestamp or scheduled start is used when supplied. Otherwise the later
source occurrence wins. Last Admin and Last Rate are not order timestamps.
Selection precedes visibility filtering so hiding a new bag does not restore an
older bag or a dietary duplicate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from medications import match_name


_LIPID = re.compile(r"^(?:fat\s+emulsion|smoflipid|intralipid|omegaven|clinolipid)\b|\b(?:smoflipid|intralipid|omegaven|clinolipid)\b", re.I)
_PN = re.compile(r"\b(?:TPN|PPN|PN|parenteral\s+nutrition)\b|^(?:clinimix|kabiven|perikabiven)\b", re.I)
_DISCONTINUED = re.compile(r"\[(?:discontinued|removed|cancelled|canceled)\]|^\s*(?:discontinued|removed|cancelled|canceled)\s*:", re.I)
_PREFIXES = re.compile(r"^\s*(?:(?:and|or|followed\s+by)\s*:\s*|\[[^\]]+\]\s*|(?:discontinued|removed|cancelled|canceled)\s*:\s*)+", re.I)
_DATE = r"(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/(?P<year>\d{4}|\d{2}))?"
_EVENT = re.compile(
    r"\b(?P<label>ordered(?:\s+(?:on|at))?|start(?:ing)?(?:\s+(?:on|at))?|scheduled\s+(?:on|at|for))\s*:?\s*"
    + _DATE + r"(?:\s+(?:at\s+)?(?P<time>\d{1,2}:\d{2}|\d{4}))?(?![\d/])", re.I)
_DATE_ONLY = re.compile(r"^\s*" + _DATE + r"\s*$")


@dataclass(frozen=True)
class _OrderStamp:
    when: datetime
    time_known: bool


def parenteral_kind(name: str, route: str = "") -> str:
    """Identify explicitly named PN/lipid products, excluding enteral routes."""
    if route and not re.search(r"\b(?:intravenous|iv|central|peripheral)\b", route, re.I):
        return ""
    name = match_name(_PREFIXES.sub("", str(name)))
    if _LIPID.search(name):
        return "lipid"
    return "pn" if _PN.search(name) else ""


def _event_date(match, reference: datetime | None = None) -> datetime | None:
    month, day = int(match["month"]), int(match["day"])
    year = match["year"]
    time = match.groupdict().get("time") or "0000"
    if ":" in time:
        hour, minute = (int(part) for part in time.split(":"))
    else:
        hour, minute = int(time[:2]), int(time[2:])
    if year:
        year = int(year)
        year += 2000 if year < 70 else 1900 if year < 100 else 0
        years = [year]
    elif reference is not None:
        years = [reference.year - 1, reference.year, reference.year + 1]
    else:
        # A common neutral year compares month/day stamps without consulting
        # the server clock. Full-year source dates supply the reference below.
        years = [2000]
    dates = []
    for year in years:
        try:
            dates.append(datetime(year, month, day, hour, minute))
        except ValueError:
            continue
    if not dates:
        return None
    return min(dates, key=lambda value: abs(value - reference)) if reference else dates[0]


def _order_stamp(row: dict, reference: datetime | None = None) -> _OrderStamp | None:
    text = " | ".join(str(row.get(key, "")) for key in ("name", "source"))
    ordered, starts = [], []
    for match in _EVENT.finditer(text):
        value = _event_date(match, reference)
        if value is not None:
            stamp = _OrderStamp(value, match["time"] is not None)
            (ordered if match["label"].casefold().startswith("ordered") else starts).append(stamp)
    return max(ordered or starts, key=lambda item: (item.when, item.time_known)) if ordered or starts else None


def order_timestamp(row: dict, reference: datetime | None = None) -> datetime | None:
    """Read labelled order/start dates only, never an administration date.

    A missing time is represented as midnight for this compatibility accessor.
    Order selection uses the retained precision, not that placeholder time.
    """
    stamp = _order_stamp(row, reference)
    return stamp.when if stamp is not None else None


def order_timestamp_key(row: dict):
    """Keep date-only and explicitly timed source records distinguishable."""
    return _order_stamp(row)


def _strictly_newer(left: _OrderStamp | None, right: _OrderStamp | None) -> bool:
    if left is None or right is None:
        return False
    if left.when.date() != right.when.date():
        return left.when.date() > right.when.date()
    return left.time_known and right.time_known and left.when > right.when


def _reference_date(rows, dietary, sheet) -> datetime | None:
    dates = []
    for row in (*rows, *dietary):
        if not parenteral_kind(row.get("name", ""), row.get("route", "")):
            continue
        for key in ("name", "source"):
            for match in _EVENT.finditer(str(row.get(key, ""))):
                if match["year"]:
                    value = _event_date(match)
                    if value is not None:
                        dates.append(value)
    if dates:
        return max(dates)
    match = _DATE_ONLY.fullmatch(str((sheet or {}).get("admission_date", "")))
    return _event_date(match) if match and match["year"] else None


def _discontinued(row: dict) -> bool:
    return bool(_DISCONTINUED.search(str(row.get("name", "")))) or row.get("status") in {"discontinued", "cancelled", "canceled", "removed"}


def _candidates(rows, reference, *, medication: bool) -> dict[str, tuple]:
    groups = {}
    previous = None
    for index, row in enumerate(rows):
        kind = parenteral_kind(row.get("name", ""), row.get("route", "") if medication else "")
        stamp = _order_stamp(row, reference) if kind else None
        if (medication and kind == "lipid" and stamp is None and previous is not None
                and previous[0] == "pn" and not previous[2]
                and re.match(r"^\s*And\s*:", row.get("name", ""), re.I)):
            # The connector retains an explicit pairing. Only its scheduling
            # metadata is shared. No dose/rate is borrowed from either bag.
            stamp = previous[1]
        discontinued = _discontinued(row)
        if kind and not discontinued:
            groups.setdefault(kind, []).append((index, row, stamp))
        previous = (kind, stamp, discontinued)
    selected = {}
    for kind, candidates in groups.items():
        # Keep candidates that cannot be proved older. A missing date, or a
        # same-day date without a time, is not evidence of an earlier order.
        # The later source occurrence resolves only those remaining ties.
        choices = [candidate for candidate in candidates if candidate[2] is None]
        dated = [candidate for candidate in candidates if candidate[2] is not None]
        if dated:
            latest_day = max(candidate[2].when.date() for candidate in dated)
            same_day = [candidate for candidate in dated if candidate[2].when.date() == latest_day]
            choices.extend(candidate for candidate in same_day if not candidate[2].time_known)
            timed = [candidate for candidate in same_day if candidate[2].time_known]
            if timed:
                choices.append(max(timed, key=lambda candidate: (candidate[2].when, candidate[0])))
        selected[kind] = max(choices, key=lambda candidate: candidate[0])
    return selected


def _dietary(diet: dict | None, sheet: dict | None) -> list[dict]:
    if sheet is not None:
        if any(item.get("action") == "diet_hidden" for section in ("x", "ab")
               for item in sheet.get("import_warnings", {}).get(section, [])):
            return []
        if diet is None:
            diet = sheet.get("diet")
    return diet.get("parenteral", []) if isinstance(diet, dict) else []


def _selected(rows, diet: dict | None, sheet: dict | None) -> tuple[set[int], set[int]]:
    dietary = _dietary(diet, sheet)
    reference = _reference_date(rows, dietary, sheet)
    medications = _candidates(rows, reference, medication=True)
    orders = _candidates(dietary, reference, medication=False)
    med_indexes, diet_indexes = set(), set()
    for kind in ("pn", "lipid"):
        med, order = medications.get(kind), orders.get(kind)
        if med is None and order is not None:
            diet_indexes.add(order[0])
        elif med is not None:
            # Medication entries carry the dose and visibility choices. Use a
            # dietary entry instead only when both dates establish it is newer.
            if order is not None and _strictly_newer(order[2], med[2]):
                diet_indexes.add(order[0])
            else:
                med_indexes.add(med[0])
    return med_indexes, diet_indexes


def medication_rows_for_display(rows, sheet: dict | None = None, diet: dict | None = None) -> list[dict]:
    """Return ordinary orders plus at most one selected PN and one lipid row.

    Return the selected rows even when hidden. The caller's existing visibility
    rules decide whether to render them, without restoring superseded orders.
    """
    rows = list(rows)
    chosen, _ = _selected(rows, diet, sheet)
    return [row for index, row in enumerate(rows)
            if not parenteral_kind(row.get("name", ""), row.get("route", "")) or index in chosen]


def dietary_rows_for_display(diet: dict | None, medications=(), sheet: dict | None = None) -> list[dict]:
    """Return selected diet-only PN/lipids without reviving hidden med copies."""
    dietary = _dietary(diet, sheet)
    _, chosen = _selected(list(medications), diet, sheet)
    return [row for index, row in enumerate(dietary)
            if not parenteral_kind(row.get("name", "")) or index in chosen]
