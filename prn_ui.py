"""Explicit review of PRN administration records before numeric output.

The editable table stores only normalized medication events. It never retains
the original SmartPhrase, clinician names, or patient identifiers. A submitted
form replaces only the selected medication's records and review decision.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re
from typing import Callable


def _missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        import pandas as pd
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _integer(value, label: str, maximum: int) -> int | None:
    if _missing(value):
        return None
    if isinstance(value, bool):
        raise ValueError(label + " must be a whole number.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(label + " must be a whole number.") from None
    if not math.isfinite(number) or not number.is_integer() or not 0 <= number <= maximum:
        raise ValueError(label + " must be a whole number from 0 to " + str(maximum) + ".")
    return int(number)


def _local_label(timestamp: str) -> str:
    from prn_counts import event_time
    from zoneinfo import ZoneInfo
    return event_time(timestamp).astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M")


def prn_editor_rows(data: dict, medication: str) -> list[dict]:
    """Build editable rows while retaining an opaque reference to source data."""
    from prn_counts import validate_prn
    validate_prn(data)
    selected = [event for event in data["events"] if event["medication"] == medication]
    return [{"__row": index, "timestamp": _local_label(event["timestamp"]),
             "volume_ml": event["volume_ml"], "dose_count": event["dose_count"]}
            for index, event in enumerate(selected)]


def prepare_prn_review(data: dict, medication: str, rows: list[dict], *,
                       expected_window: str | None = None,
                       as_of: datetime | None = None) -> dict:
    """Validate a submitted medication table and confirm its current window.

    No input is mutated. A readonly volume or hidden reference cannot change
    another medication's records. New rows are explicitly manual records.
    """
    from prn_counts import (MEDICATIONS, clear_review, confirm_review, event_time,
                            prn_window, validate_prn)
    validate_prn(data)
    if medication not in MEDICATIONS or not isinstance(rows, list) or len(rows) > 12000:
        raise ValueError("The PRN review table is invalid.")
    start, end = prn_window(as_of)
    if expected_window is not None and expected_window != start.isoformat():
        raise ValueError("The PRN day changed at 7 a.m. Reopen this review before confirming the new count.")
    selected = [event for event in data["events"] if event["medication"] == medication]
    prepared = []
    references = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"__row", "timestamp", "volume_ml", "dose_count"}:
            raise ValueError("The PRN review table is invalid.")
        reference = _integer(row.get("__row"), "The PRN row reference", max(len(selected), 1))
        stamp = row.get("timestamp")
        count = _integer(row.get("dose_count"), "PRN doses", 100)
        if reference is None and _missing(stamp) and count is None:
            continue
        if not isinstance(stamp, str) or not stamp.strip():
            raise ValueError("Every PRN record needs an administration date and time.")
        if reference is not None:
            if reference >= len(selected) or reference in references:
                raise ValueError("A PRN row reference is invalid or repeated. Reopen the review.")
            references.add(reference)
            event = deepcopy(selected[reference])
            # Preserve a supplied UTC offset, including an explicitly identified
            # DST fold, when the local display value has not been edited.
            timestamp = (event["timestamp"] if stamp.strip() == _local_label(event["timestamp"])
                         else event_time(stamp.strip()).isoformat())
        else:
            event = {"medication": medication, "volume_ml": None, "source": "manual"}
            timestamp = event_time(stamp.strip()).isoformat()
        event.update(timestamp=timestamp, dose_count=count)
        prepared.append(event)
    candidate = deepcopy(data)
    candidate["events"] = [event for event in candidate["events"]
                           if event["medication"] != medication] + prepared
    candidate = clear_review(candidate, [medication])
    validate_prn(candidate)
    return confirm_review(candidate, [medication], as_of=end)


def prn_widget_token(sheet: dict, window_start: datetime) -> str:
    """A different patient, source, decision, or day receives fresh widgets."""
    data = sheet.get("prn")
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return "prn_" + sheet["id"] + "_" + window_start.strftime("%Y%m%d") + "_" + digest


def _medication_options(sheet: dict, data: dict) -> list[str]:
    from prn_counts import MEDICATIONS, canonical_medication
    present = {event["medication"] for event in data["events"]}
    for row in sheet.get("medications", []):
        if (row.get("include", True) and not row.get("hidden", False)
                and re.search(r"\bprn\b|\bas needed\b", row.get("frequency", ""), re.I)):
            medication = canonical_medication(row.get("name", ""))
            if medication:
                present.add(medication)
    return [medication for medication in MEDICATIONS if medication in present] + [
        medication for medication in MEDICATIONS if medication not in present]


def render_prn_editor(sheet: dict, on_update: Callable[[dict], None]) -> None:
    """Render one compact, explicitly submitted review form at a time."""
    import pandas as pd
    import streamlit as st
    from prn_counts import LABELS, prn_counts, prn_window, validate_prn

    data = sheet.get("prn") or {"version": 1, "events": [], "reviewed": {}}
    validate_prn(data)
    start, end = prn_window()
    counts = prn_counts(sheet, as_of=end)
    pending = any(event["medication"] not in counts for event in data["events"])
    with st.expander("PRN counts", expanded=pending):
        st.caption("Volume entries can include infusions, combined doses, or missing administrations. "
                   "Verify actual administration times and PRN doses against the MAR before confirming.")
        st.caption("Current count window: " + start.strftime("%m/%d/%Y %I:%M %p") + " to " +
                   end.strftime("%m/%d/%Y %I:%M %p") + " Eastern. Dates and times stay off the handoff's PRN counts.")
        if counts:
            st.caption("Confirmed: " + ", ".join(LABELS[key] + " " + str(value)
                                                for key, value in counts.items()))
        elif not data["events"]:
            st.caption("No AF records are available. You can add verified administrations below, "
                       "or confirm zero after checking the MAR.")
        token = prn_widget_token(sheet, start)
        medication = st.selectbox("Medication for PRN review", _medication_options(sheet, data),
                                  format_func=lambda value: LABELS[value], key=token + "_medication")
        rows = prn_editor_rows(data, medication)
        frame = pd.DataFrame(rows, columns=["__row", "timestamp", "volume_ml", "dose_count"])
        frame["__row"] = pd.array(frame["__row"], dtype="Int64")
        frame["volume_ml"] = pd.array(frame["volume_ml"], dtype="Float64")
        # Let the validator see a fractional edit instead of allowing the
        # editor's integer conversion to silently truncate it to one dose.
        frame["dose_count"] = pd.array(frame["dose_count"], dtype="Float64")
        st.caption("Use the actual administration date and time, YYYY-MM-DD HH:MM. "
                   "Enter 0 for an infusion or other non-PRN entry, or the verified number of PRN doses. "
                   "Add rows for missing administrations. Only this medication is changed.")
        with st.form(token + "_" + medication + "_form", border=False):
            edited = st.data_editor(
                frame, key=token + "_" + medication + "_rows", hide_index=True,
                num_rows="dynamic", width="stretch", height=330,
                disabled=["__row", "volume_ml"],
                column_config={
                    "__row": None,
                    "timestamp": st.column_config.TextColumn("Administration date / time", required=True),
                    "volume_ml": st.column_config.NumberColumn("Source volume (mL)", format="%.2f"),
                    "dose_count": st.column_config.NumberColumn("Confirmed PRN doses", min_value=0,
                                                                max_value=100, step=1, format="%d"),
                })
            submitted = st.form_submit_button("Confirm " + LABELS[medication] + " PRN count")
        if submitted:
            try:
                candidate = prepare_prn_review(data, medication, edited.to_dict("records"),
                                               expected_window=start.isoformat())
                on_update(candidate)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.rerun()
