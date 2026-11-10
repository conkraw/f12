"""M-block ICP/CPP range and last-reading display, without averaging or calculation.

Only explicit range endpoints and recorded last values are used. The older
single-reading M format is left untouched. Error text never contains source data.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
import re

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
UNIT = r"mm\s*Hg"
NAMES = r"(?:ICP(?:\s+Mean)?|CPP|Intracranial\s+Pressure(?:\s+Mean)?|Cerebral\s+Perfusion\s+Pressure)"
PREFIX = re.compile(
    r"^(?P<last>Last\s+)?(?P<name>" + NAMES + r")"
    r"(?P<range>\s+Range)?(?:\s*\(\s*(?P<unit>" + UNIT + r")\s*\))?"
    r"(?=\s|:|$)\s*:?\s*(?P<body>.*)$", re.I)
STATS = re.compile(r"\b(avg|average|min|minimum|max|maximum)\s*:", re.I)
VALUE = re.compile(r"(?:\(S\)\s*)?(?P<flag>\(!\)\s*)?(?P<n>" + NUMBER + r")\s*(?:" + UNIT + r")?", re.I)
PAIR = re.compile(r"(?P<lo>" + NUMBER + r")\s*(?:" + UNIT + r")?\s*(?:-|to)\s*"
                  r"(?P<hi>" + NUMBER + r")\s*(?:" + UNIT + r")?", re.I)
BRACKET_PAIR = re.compile(r"^\[\s*(?P<pair>[^\]]+)\s*\]\s*(?P<tail>.*)$")
MISSING = {"", "none", "--", "-", "---", "n/a", "na", "not documented", "not recorded", "no data", "no data recorded", "no results found"}
ERROR = "An ICP/CPP field could not be read. Use documented Min/Max or a numeric range and a separate Last reading."

@dataclass
class ICPResult:
    rows: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    error: str = ""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ").replace("：", ":").replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")).strip()


def _missing(text: str) -> bool:
    return _clean(text).casefold().rstrip(".") in MISSING


def is_range_format(block: str) -> bool:
    """Do not change the stored rows of the original single-reading importer."""
    for line in block.splitlines():
        m = PREFIX.fullmatch(_clean(line))
        if m and (m["last"] or m["range"] or STATS.search(m["body"])):
            return True
    return False


def _metric(name: str) -> str:
    return "CPP" if name.casefold().startswith(("cpp", "cerebral")) else "ICP"


def _number(text: str) -> str:
    m = VALUE.fullmatch(_clean(text))
    if not m:
        raise ValueError(ERROR)
    return ("(!) " if m["flag"] else "") + m["n"]


def _pair(text: str) -> tuple[str, str]:
    m = PAIR.fullmatch(_clean(text))
    if not m:
        raise ValueError(ERROR)
    if Decimal(m["lo"]) > Decimal(m["hi"]):
        raise ValueError("An ICP/CPP minimum is greater than its maximum. Check the source range.")
    return m["lo"], m["hi"]


def _unwrap(text: str, metric: str) -> str:
    for _ in range(5):
        m = PREFIX.fullmatch(text)
        if not m:
            return text
        if _metric(m["name"]) != metric:
            raise ValueError("An ICP/CPP wrapper names a different measurement. Check the field labels.")
        text = m["body"].strip()
    if PREFIX.fullmatch(text):
        raise ValueError(ERROR)
    return text


def _range(text: str) -> tuple[tuple[str, str] | None, str]:
    """Return explicit endpoints and an optional documented bracket-tail value."""
    if _missing(text):
        return None, ""
    markers = list(STATS.finditer(text))
    if markers:
        if text[:markers[0].start()].strip():
            raise ValueError(ERROR)
        limits = {}
        for i, marker in enumerate(markers):
            key = marker[1].casefold()
            if key in ("avg", "average"):
                continue
            key = "lo" if key.startswith("min") else "hi"
            end = markers[i+1].start() if i+1 < len(markers) else len(text)
            value = _number(text[marker.end():end])
            if "(!)" in value:
                raise ValueError(ERROR)
            if key in limits and Decimal(limits[key]) != Decimal(value):
                raise ValueError("Conflicting ICP/CPP range endpoints were supplied.")
            limits.setdefault(key, value)
        if set(limits) != {"lo", "hi"}:
            raise ValueError("An ICP/CPP summary needs both Min and Max. An average cannot supply a missing endpoint.")
        if Decimal(limits["lo"]) > Decimal(limits["hi"]):
            raise ValueError("An ICP/CPP minimum is greater than its maximum. Check the source range.")
        return (limits["lo"], limits["hi"]), ""
    bracket = BRACKET_PAIR.fullmatch(text)
    if bracket:
        pair = _pair(bracket["pair"])
        tail = bracket["tail"].strip()
        last = "" if not tail or re.fullmatch(UNIT, tail, re.I) else _number(tail)
        return pair, last
    return _pair(text), ""


def _key(value: str) -> tuple:
    """Equivalent numeric typography is not a conflicting duplicate."""
    return tuple(Decimal(n) for n in re.findall(NUMBER, value))


def logical_lines(block: str) -> list[str]:
    """Fold only explicit summary continuations, never another metric's Last line."""
    lines = []
    for raw in block.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        text = _clean(raw)
        if not text:
            continue
        # Pasted summary statistics can wrap at each field.
        if re.match(r"^(?:avg|average|min|minimum|max|maximum)\s*:", text, re.I) and lines:
            lines[-1] += " " + text
        else:
            lines.append(text)
    return lines


def parse_icp_cpp(block: str) -> ICPResult:
    out = ICPResult()
    values: dict[tuple[str, str], str] = {}
    pending: tuple[str, str] | None = None

    def add(metric: str, kind: str, value: str):
        key = metric, kind
        if key in values and (_key(values[key]) != _key(value) or ("(!)" in values[key]) != ("(!)" in value)):
            raise ValueError("Conflicting repeated ICP/CPP readings were supplied without an established order.")
        values.setdefault(key, value)

    try:
        for raw in logical_lines(block):
            text = _clean(raw)
            if not text or text.rstrip(":").casefold() in {"icp trends", "icp/cpp", "icp / cpp"}:
                continue
            if _missing(text):
                pending = None
                continue
            m = PREFIX.fullmatch(text)
            if m:
                metric = _metric(m["name"])
                kind = "range" if m["range"] else "last" if m["last"] else "reading"
                body = _unwrap(m["body"], metric)
                # A separate Epic field may follow the user's empty Range/Last wrapper.
                if kind == "reading" and pending and pending[0] == metric:
                    kind = pending[1]
                if not body:
                    pending = (metric, kind)
                    continue
            elif pending:
                metric, kind = pending
                body = text
            else:
                raise ValueError(ERROR)
            pending = None
            if _missing(body):
                continue
            if kind == "range" or (kind == "reading" and (STATS.search(body) or body.startswith("["))):
                pair, last = _range(body)
                if pair:
                    add(metric, "range", pair[0] + "-" + pair[1] + " mm Hg")
                if last:
                    add(metric, "last", last + " mm Hg")
            else:
                add(metric, "last", _number(body) + " mm Hg")
        for metric in ("ICP", "CPP"):
            for kind in ("range", "last"):
                if (metric, kind) in values:
                    label = metric + " Range" if kind == "range" else "Last " + metric
                    out.rows.append({"label": label, "value": values[(metric, kind)], "section": "Neurologic", "include": True})
    except (ValueError, ArithmeticError) as exc:
        out.rows = []
        out.error = str(exc) if isinstance(exc, ValueError) else ERROR
    return out


def validate_icp_cpp_rows(rows: list[dict]) -> None:
    # Original custom M labels remain compatible. New compact rows must be readable.
    if not any(re.fullmatch(r"(?:ICP|CPP) Range|Last (?:ICP|CPP)", r["label"], re.I) for r in rows):
        return
    result = parse_icp_cpp("\n".join(r["label"] + ": " + r["value"] for r in rows))
    if result.error:
        raise ValueError(result.error)


def display_icp_cpp_rows(rows: list[dict]) -> list[dict]:
    if not any(re.fullmatch(r"(?:ICP|CPP) Range|Last (?:ICP|CPP)", r["label"], re.I) for r in rows):
        return rows
    result = parse_icp_cpp("\n".join(r["label"] + ": " + r["value"] for r in rows if r["include"]))
    if result.error:
        raise ValueError(result.error)
    lookup = {r["label"]: r["value"] for r in result.rows}
    output = []
    for metric in ("ICP", "CPP"):
        limits, last = lookup.get(metric + " Range", ""), lookup.get("Last " + metric, "")
        if limits and last:
            value = limits.removesuffix(" mm Hg") + " [" + last + "]"
        else:
            value = limits or last
        if value:
            output.append({"label": metric, "value": value, "section": "Neurologic", "include": True})
    return output
