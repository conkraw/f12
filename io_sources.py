"""Choose the documented fluid summary without changing its totals or formatting.

A populated legacy S block remains authoritative. When S is absent or validly
empty, read only an explicit 24-hour summary in H, ending before any shift data.
Never add shift volumes, calculate a net, replace timestamps, or use old saved
values as a source. This selection is independent of current-shift parsing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from fluid_balance import FIELDS, MISSING, FluidBalanceResult, SUMMARY, parse_balance

_SHIFT = re.compile(
    r"^[ \t]*I\s*/?\s*O\s+(?:Current\s+Shift|this\s+shift|"
    r"last\s+\d+\s+(?:completed\s+)?shifts?)\s*:?[^\S\n]*$", re.I | re.M
)
_PERIOD = re.compile(r"(?:last|past)?\s*24\s*(?:hours?|hrs?|h)", re.I)


@dataclass
class BalanceSelection:
    source: str = ""
    result: FluidBalanceResult = field(default_factory=FluidBalanceResult)


def _h_summary(block: str) -> BalanceSelection:
    text = block.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    shift = _SHIFT.search(text)
    prefix = text[:shift.start()] if shift else text
    summaries = [match for line in prefix.splitlines()
                 if (match := SUMMARY.fullmatch(line.strip()))]
    # A last-three-shifts total or unlabelled H amounts are not a 24-hour source.
    if not any(_PERIOD.fullmatch((match.group(1) or "").strip()) for match in summaries):
        return BalanceSelection()
    if len(summaries) != 1:
        return BalanceSelection("h", FluidBalanceResult(
            error="The H block contains more than one fluid summary. Paste one 24-hour snapshot."))
    result = parse_balance(prefix)
    # The legacy parser is reused intact. Diagnostics identify the actual source.
    result.error = result.error.replace("S intake/output", "H intake/output").replace("S block", "H block").replace("S-block", "H-block")
    result.issues = [message.replace(" in S.", " in H.") for message in result.issues]
    return BalanceSelection("h", result)


def select_balance_source(blocks: dict[str, str], invalid: set[str]) -> BalanceSelection:
    """Select one source per paste. An empty S never erases a valid H summary.

    A malformed S does not silently fall back to H. A malformed H with no
    populated S retains the previous totals with an import-review warning.
    """
    if "s" in invalid:
        return BalanceSelection("s", FluidBalanceResult(
            error="The S intake/output section boundaries are not reliable."))
    selected = BalanceSelection()
    if "s" in blocks:
        selected = BalanceSelection("s", parse_balance(blocks["s"]))
        has_values = selected.result.data is not None and any(
            selected.result.data[name].strip().casefold() not in MISSING for name in FIELDS
        )
        if selected.result.error or has_values:
            return selected
    if "h" in invalid:
        return BalanceSelection("h", FluidBalanceResult(
            error="The H intake/output section boundaries are not reliable. Previous totals were retained for review."))
    if "h" in blocks:
        alternate = _h_summary(blocks["h"])
        if alternate.source:
            return alternate
    # With no H summary, an explicitly empty S still clears as it always did.
    return selected
