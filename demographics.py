"""Parse explicitly recorded dosing weight and admission date, without inference.

The I block owns measured/dosing weights. The N block owns admission date.
Dosing-weight values are never substituted for measured weight or calculated
from doses, pump rates, relative ages, or any prior handoff.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import re

WEIGHT = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kg|g|lbs?|oz)\b(?!/)", re.I)
DOSE_HEADING = re.compile(r"^\s*(?:dosing\s+weight|dose\s+calculation\s+weight|dcw)\b\s*:?[ \t]*(.*)$", re.I)
DATE_PREFIX = re.compile(r"^(\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))(?=\s|$)")
MISSING = {"", "-", "--", "---", "n/a", "na", "none", "not documented", "not recorded", "no data", "no results found"}


def validate_dosing_weight(value: str) -> None:
    if not isinstance(value, str) or len(value)>80 or "\n" in value or "\r" in value:
        raise ValueError("The dosing weight is invalid.")
    if not value:
        return
    match=WEIGHT.fullmatch(value.strip())
    if not match or Decimal(match.group("value"))<=0:
        raise ValueError("Enter a recorded dosing weight with its unit, or leave it blank.")


def admission_date_value(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"(?:\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})|\d{4}-\d{2}-\d{2})", value.strip()):
        raise ValueError("Enter a complete admission date, such as 10/11/2026, or leave it blank.")
    for form in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(),form)
        except ValueError:
            pass
    raise ValueError("The admission date is not a valid calendar date. Nothing was imported.")


def validate_admission_date(value: str) -> None:
    if not isinstance(value,str) or len(value)>32:
        raise ValueError("The saved admission date is invalid.")
    if value:
        admission_date_value(value)


@dataclass
class AdmissionResult:
    date: str = ""
    error: str = ""


def parse_admission(block: str) -> AdmissionResult:
    out=AdmissionResult()
    for raw in block.replace("\r\n","\n").replace("\r","\n").splitlines():
        text=raw.replace("\u00a0"," ").strip()
        if re.fullmatch(r"date of admission\s*:?",text,re.I):
            continue
        match=re.match(r"^date of admission\s*:\s*(.*)$",text,re.I)
        value=(match.group(1) if match else text).strip()
        if value.casefold().rstrip(".") in MISSING:
            continue
        try:
            date=admission_date_value(value)
            if out.date and admission_date_value(out.date)!=date:
                raise ValueError("Conflicting admission dates were supplied. Nothing was imported.")
        except ValueError as exc:
            out.error=str(exc)
            return out
        if not out.date:
            out.date=value
    return out


@dataclass
class DosingResult:
    measured_block: str = ""
    dosing_weight: str = ""
    issues: list[str] = field(default_factory=list)
    error: str = ""


def separate_dosing_weight(block: str) -> DosingResult:
    """Keep the labelled dose-weight area away from measured-weight parsing.

    Epic may repeat Dosing Weight / Dosing on separate lines and add a relative
    timestamp. Only an explicit weight within that area is accepted.
    """
    out=DosingResult()
    measured=[]
    candidates=[]
    in_dosing=False
    for raw in block.replace("\r\n","\n").replace("\r","\n").splitlines():
        text=raw.replace("\u00a0"," ").strip()
        heading=DOSE_HEADING.match(text)
        if heading:
            in_dosing=True
            text=heading.group(1).strip()
        elif in_dosing and re.match(r"^(?:wt readings|(?:weight|wt)\s*:)",text,re.I):
            in_dosing=False
        if not in_dosing:
            measured.append(raw)
            continue
        low=re.sub(r"\s+"," ",text.casefold()).rstrip(".")
        if low in MISSING or low.rstrip(":")=="dosing" or text.startswith("*"):
            continue
        if re.fullmatch(r"(?:\d+\s+(?:minutes?|hours?|days?|weeks?|months?)\s+ago|today|yesterday)",low):
            continue  # Age of chart entry is not an admission or collection date.
        date_match=DATE_PREFIX.match(text)
        candidate=text[date_match.end():].strip() if date_match else text
        match=WEIGHT.match(candidate)
        if not match:
            out.error="A labelled dosing-weight value could not be read. Nothing was imported."
            return out
        tail=candidate[match.end():].strip()
        if tail and not (tail.startswith(("(","*")) or re.fullmatch(r"\d+\s+(?:minutes?|hours?|days?|weeks?|months?)\s+ago",tail,re.I)):
            out.error="A labelled dosing-weight row contains unrecognized text. Nothing was imported."
            return out
        value=match.group("value")+" "+match.group("unit")
        try:
            validate_dosing_weight(value)
            date=admission_date_value(date_match.group(1)) if date_match else None
        except ValueError as exc:
            out.error=str(exc)
            return out
        candidates.append((date,value))
    out.measured_block="\n".join(measured)
    if candidates:
        if len({value for _,value in candidates})>1:
            if not all(date is not None for date,_ in candidates):
                out.error="Different dosing weights were supplied without complete dates. Nothing was imported."
                return out
            candidates.sort(key=lambda item:item[0],reverse=True)
            if len({value for date,value in candidates if date==candidates[0][0]})>1:
                out.error="Conflicting dosing weights share the same date. Nothing was imported."
                return out
            out.issues.append("Multiple dated dosing weights were supplied. The newest dated value is shown.")
        out.dosing_weight=candidates[0][1]
    return out


def demographic_weight_text(nutrition: dict | None, dosing_weight: str) -> str:
    """Show weight, optional Z-score, then dosing weight or the display-only 'none'.

    Missing dosing weights stay empty in storage. This label must never be used
    to infer a dose or make an otherwise blank room eligible for Print all.
    """
    from observations import validate_nutrition
    validate_nutrition(nutrition)
    validate_dosing_weight(dosing_weight)
    rows = []
    if nutrition and nutrition["include"]:
        rows.append("Weight: " + nutrition["weight"])
        if nutrition["z_score"]:
            rows.append("Z-score: " + nutrition["z_score"])
    rows.append("Dosing weight: " + (dosing_weight or "none"))
    return "\n".join(rows)
