"""Read selected recurring lab/imaging orders from SmartPhrase R.

This is a display filter, not an active-order reconciliation or scheduling engine.
Only order name, recurring Timing and Number of Occurrences are retained. Reasons,
provider details and other instructions do not enter the saved order snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import uuid

MAX_ORDERS = 1000
MAX_BLOCK = 150_000


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ").strip()).casefold()


@dataclass(frozen=True)
class OrderKind:
    key: str
    label: str
    category: str


def classify_order(name: str) -> OrderKind | None:
    """Explicit aliases only. Do not turn CMP into BMP or merge gas specimens."""
    text = normalized(name)
    text = re.sub(r"[._]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if re.search(r"\b(?:discontinued|cancelled|canceled)\b", text):
        return None
    # Retain the radiographic view/qualifier in the duplicate identity.
    if (re.match(r"^(?:xr|xray|x-ray|radiograph(?:y)?(?: of)?|chest x-ray|chest xray|cxr)\b", text)
            and (re.search(r"\bchest\b", text) or text.startswith("cxr"))):
        rest = re.sub(r"^(?:xr|xray|x-ray|radiograph(?:y)?(?: of)?)\s+chest\b", "", text).strip()
        rest = re.sub(r"^(?:chest x-ray|chest xray|cxr)\b", "", rest).strip()
        rest = re.sub(r"\bviews?\b", "view", rest)
        rest = re.sub(r"\s+", " ", rest).strip(" -:,()")
        return OrderKind("chest:" + rest, "Chest X-ray" + (" (" + rest + ")" if rest else ""), "Chest X-ray")
    if re.fullmatch(r"(?:cbc|complete blood count)(?:\s*[,/-]?\s*(?:auto|automated|with|and|w/|w|without|no|\+|\s)*(?:differential|diff))?", text):
        # A plain CBC is not silently equated to an explicitly ordered differential.
        diff = bool(re.search(r"\b(?:differential|diff)\b", text))
        without = bool(re.search(r"\b(?:without|no)\b", text))
        suffix = ":without_diff" if without else ":diff" if diff else ""
        label = "CBC without diff" if without else "CBC with diff" if diff else "CBC"
        return OrderKind("cbc" + suffix, label, "CBC")
    if text in ("basic metabolic panel", "bmp", "basic metabolic panel (bmp)"):
        return OrderKind("bmp", "BMP", "BMP")
    if text in ("magnesium", "mg", "magnesium level"):
        return OrderKind("magnesium", "Magnesium", "Magnesium")
    if text in ("phosphorus", "phosphorous", "phosphate", "phos", "phosphorus level", "phosphorous level"):
        return OrderKind("phosphorus", "Phosphorus", "Phosphorus")
    coag = {
        "aptt": ("aptt", "aPTT"), "ptt": ("aptt", "aPTT"),
        "activated partial thromboplastin time": ("aptt", "aPTT"),
        "partial thromboplastin time": ("aptt", "aPTT"),
        "protime-inr": ("pt_inr", "PT/INR"), "protime inr": ("pt_inr", "PT/INR"),
        "pt/inr": ("pt_inr", "PT/INR"), "pt-inr": ("pt_inr", "PT/INR"),
        "prothrombin time/inr": ("pt_inr", "PT/INR"),
        "prothrombin time": ("pt", "PT"), "protime": ("pt", "PT"), "pt": ("pt", "PT"),
        "inr": ("inr", "INR"), "fibrinogen": ("fibrinogen", "Fibrinogen"),
        "coagulation profile": ("coagulation_profile", "Coagulation profile"),
        "coagulation panel": ("coagulation_profile", "Coagulation profile"),
        "pt/ptt": ("pt_ptt", "PT/PTT"), "pt and ptt": ("pt_ptt", "PT/PTT"),
        "pt/ptt/inr": ("pt_ptt_inr", "PT/PTT/INR"),
    }
    if text in coag:
        key, label = coag[text]
        return OrderKind(key, label, "Coagulation")
    # Keep additives (for example lactate or Hgb/O2 sat) and assay names distinct.
    gas = (bool(re.match(r"^(?:(?:venous|arterial|capillary) )?blood gas(?:es)?\b", text))
           or bool(re.fullmatch(r"[vac]bg", text))
           or bool(re.match(r"^(?:poc|poct)\s+(?:cg[48]|eg7)\b", text)))
    if gas:
        specimen = ("VEN" if re.search(r"\b(?:venous|ven)\b", text) or text == "vbg" else
                    "ART" if re.search(r"\b(?:arterial|art)\b", text) or text == "abg" else
                    "CAP" if re.search(r"\b(?:capillary|cap)\b", text) or text == "cbg" else "")
        # Exact plain-gas synonyms share a key, different panels do not.
        plain = re.sub(r"\b(?:venous|ven|arterial|art|capillary|cap|blood|gas(?:es)?|abg|vbg|cbg)\b", "", text)
        plain = re.sub(r"[\s,()-]+", "", plain)
        key = "gas:" + specimen + (":" + text if plain else "")
        label = "Blood gas" + (" " + specimen if specimen else "")
        cartridge = re.search(r"\b(cg[48]|eg7)\b", text)
        if cartridge:
            label += " (" + cartridge.group(1).upper() + ")"
        elif re.fullmatch(r"(?:venous|arterial|capillary) blood gas(?:es)? w/ hgb and o2 sat", text):
            label = "Gas " + specimen + " + Hgb/O2 sat"
        elif plain:
            # The original test name prevents loss of a panel's distinguishing contents.
            label = re.sub(r"\s+", " ", name).strip()
        return OrderKind(key, label, "Blood gas")
    if re.fullmatch(r"(?:lactic acid|lactate)(?:\s*[,(-]?\s*(?:level|plasma|serum|blood|venous|arterial|capillary)\s*\)?)*", text):
        specimen = next((s for s in ("venous", "arterial", "capillary", "plasma", "serum", "blood") if s in text), "")
        return OrderKind("lactate:" + specimen, "Lactic acid" + (" (" + specimen + ")" if specimen else ""), "Lactic acid")
    return None


def recurring_frequency(timing: str) -> str | None:
    """Return a readable repeat interval, never infer it from an occurrence count."""
    match = re.fullmatch(r"\s*recurring\s*\((.*)\)\s*", timing, re.I)
    if not match:
        return None
    value = normalized(match.group(1))
    if (not value or re.search(r"\b(?:once|stat|prn|as needed|on call)\b", value)
            or value in ("continuous", "until discontinued", "per protocol", "diet effective now", "now", "routine")):
        return None
    named = {
        "morning draw": "Morning draw", "daily": "Daily", "daily imaging": "Daily imaging",
        "daily imgaging": "Daily imaging", "daily imgaing": "Daily imaging",
        "nightly": "Nightly", "weekly": "Weekly", "monthly": "Monthly",
        "every morning": "Every morning", "every evening": "Every evening",
        "every night": "Nightly", "every shift": "Every shift",
        "twice daily": "BID", "bid": "BID", "three times daily": "TID", "tid": "TID",
        "four times daily": "QID", "qid": "QID", "hourly": "Q1H",
    }
    if value in named:
        return named[value]
    interval = re.fullmatch(r"(?:every\s*|q\s*)(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m|days?|d|weeks?|w)", value)
    if interval:
        number = int(interval.group(1))
        if number < 1 or number > 10000:
            return None
        unit = interval.group(2)[0]
        suffix = {"h": "H", "m": "MIN", "d": "D", "w": "WK"}[unit]
        return "Q" + str(number) + suffix
    # Preserve named weekdays without treating non-cadence prose as a schedule.
    if re.fullmatch(r"(?:every\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s*(?:,|/|and|-|\s)\s*(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))*", value):
        return value.title()
    return None


def empty_orders() -> dict:
    return {"rows": []}


def validate_orders(data: dict | None) -> None:
    if data is None:  # Legacy sheets before any R section was supplied.
        return
    if not isinstance(data, dict) or set(data) != {"rows"} or not isinstance(data["rows"], list) or len(data["rows"]) > MAX_ORDERS:
        raise ValueError("The recurring-order snapshot is invalid or too large.")
    ids = set()
    for row in data["rows"]:
        if not isinstance(row, dict) or set(row) != {"id", "name", "timing", "occurrences", "include", "source_index"}:
            raise ValueError("A recurring-order row has an invalid structure.")
        if not isinstance(row["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", row["id"]) or row["id"] in ids:
            raise ValueError("Recurring-order identifiers must be unique and valid.")
        ids.add(row["id"])
        for key in ("name", "timing"):
            if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > 500 or any(c in row[key] for c in "\r\n\t"):
                raise ValueError("A recurring-order name or timing is invalid.")
        if classify_order(row["name"]) is None or recurring_frequency(row["timing"]) is None:
            raise ValueError("Use a supported lab/imaging test and an explicit recurring schedule.")
        if row["occurrences"] is not None and (type(row["occurrences"]) is not int or not 0 <= row["occurrences"] <= 1_000_000):
            raise ValueError("Number of occurrences must be a non-negative whole number, or blank when not supplied.")
        if type(row["include"]) is not bool or type(row["source_index"]) is not int or row["source_index"] < 0:
            raise ValueError("A recurring-order inclusion flag or source position is invalid.")


def selected_orders(data: dict | None) -> list[dict]:
    """Highest count for equivalent test plus exact normalized schedule.

    Different specimens, views, test panels and schedules are never collapsed.
    Count ties retain source order. Missing count cannot beat an explicit count.
    Original candidate rows are retained for the editor, not deleted.
    """
    validate_orders(data)
    winners = {}
    for row in sorted(data["rows"] if data else [], key=lambda r: r["source_index"]):
        if not row["include"]:
            continue
        key = (classify_order(row["name"]).key, recurring_frequency(row["timing"]))
        old = winners.get(key)
        count = row["occurrences"] if row["occurrences"] is not None else -1
        old_count = old["occurrences"] if old and old["occurrences"] is not None else -1
        if old is None or count > old_count:
            winners[key] = row
    return sorted(winners.values(), key=lambda r: r["source_index"])


def order_label(row: dict) -> str:
    kind = classify_order(row["name"])
    return kind.label if kind else row["name"]


def order_line(row: dict) -> str:
    number = row["occurrences"]
    count = "occurrences not listed" if number is None else str(number) + (" occurrence" if number == 1 else " occurrences")
    return order_label(row) + " | " + str(recurring_frequency(row["timing"])) + " | " + count


def orders_text(data: dict | None) -> str:
    return "\n".join(order_line(row) for row in selected_orders(data))


@dataclass
class OrdersResult:
    data: dict = field(default_factory=empty_orders)
    issues: list[str] = field(default_factory=list)
    error: str = ""


def parse_orders(block: str) -> OrdersResult:
    result = OrdersResult()
    if not isinstance(block, str) or len(block) > MAX_BLOCK:
        result.error = "The R orders block is invalid or too large. Nothing was imported."
        return result
    text = block.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    sections: list[tuple[str, list[str]]] = []
    preface = []
    for raw in text.splitlines():
        line = raw.strip()
        bullet = re.match(r"^[•●▪]\s*(.*)$|^-\s+(.*)$", line)
        if bullet:
            name = (bullet.group(1) if bullet.group(1) is not None else bullet.group(2)).strip()
            sections.append((name, []))
        elif sections:
            sections[-1][1].append(line)
        elif line:
            preface.append(line)
    if len(sections) > 5000:
        result.error = "Too many source orders were found in R. Nothing was imported."
        return result
    # Only these framing lines are valid before the first bullet.
    allowed_heading = re.compile(r"^(?:orders placed this encounter|orders|procedures|labs\s*/\s*imaging|recurring orders)\s*:?$", re.I)
    allowed_empty = re.compile(r"^(?:none|no (?:orders?|results?)(?: found)?(?:.*)?|not documented)\s*\.?$", re.I)
    if any(not allowed_heading.fullmatch(p) and not allowed_empty.fullmatch(p) for p in preface):
        result.error = "The R block has text before the first order that is not a recognized heading. Check its bullet layout. Nothing was imported."
        return result
    unsupported = 0
    for index, (name, details) in enumerate(sections):
        kind = classify_order(name)
        if kind is None:
            continue
        # Do not append other structured instructions to the title or reuse their numbers.
        timings = []
        counts = []
        for i, line in enumerate(details):
            m = re.match(r"^(Timing|Number of Occurrences)\s*:\s*(.*)$", line, re.I)
            if not m:
                continue
            value = m.group(2).strip()
            if not value and i + 1 < len(details) and not re.match(r"^[\w /-]+\s*:", details[i + 1]):
                value = details[i + 1].strip()
            (timings if m.group(1).casefold() == "timing" else counts).append(value)
        if not timings:
            # A supported test without timing could be one-time. Never guess.
            unsupported += 1
            continue
        unique = list(dict.fromkeys(normalized(t) for t in timings))
        if len(unique) != 1:
            result.error = "A selected lab/imaging order has conflicting Timing fields in R. Nothing was imported."
            return result
        timing = re.sub(r"\s+", " ", timings[0]).strip()
        frequency = recurring_frequency(timing)
        if frequency is None:
            value = normalized(timing)
            if ("recurring" in value and not re.search(r"\b(?:once|stat|prn|as needed|on call)\b", value)):
                unsupported += 1
            continue
        if not counts:
            number = None
            result.issues.append("A recurring lab/imaging order has no Number of Occurrences. Its count is shown as not listed.")
        else:
            clean = [c.strip() for c in counts]
            if any(not re.fullmatch(r"\d+(?:,\d{3})*", c) for c in clean):
                result.error = "A recurring lab/imaging order has an unreadable Number of Occurrences in R. Nothing was imported."
                return result
            numbers = {int(c.replace(",", "")) for c in clean}
            if len(numbers) != 1 or max(numbers) > 1_000_000:
                result.error = "A recurring lab/imaging order has conflicting or excessive occurrence counts in R. Nothing was imported."
                return result
            number = numbers.pop()
        result.data["rows"].append({"id": uuid.uuid4().hex, "name": name, "timing": timing,
                                    "occurrences": number, "include": True, "source_index": index})
    if unsupported:
        result.issues.append(str(unsupported) + " selected-type orders had missing or unsupported repeating schedules and were not added to Labs/Imaging.")
    try:
        validate_orders(result.data)
    except ValueError as exc:
        result.error = str(exc)
    # Repeated missing-count notices add noise but no useful information.
    result.issues = list(dict.fromkeys(result.issues))
    return result
