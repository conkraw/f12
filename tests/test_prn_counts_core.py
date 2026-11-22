"""PRN event and reporting-window checks with synthetic records only."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from lab_windows import display_clock
from prn_counts import (
    EASTERN, MEDICATIONS, canonical_medication, clear_review, confirm_review,
    empty_prn, event_time, parse_prn, prn_counts, prn_window, validate_prn,
)


def moment(text):
    return event_time(text)


NOW = moment("2026-11-22 04:00")


def volume(drug, stamp="11/22/26 0141", amount="1"):
    return f"Volume (mL) {drug}: {amount} mL ({stamp} : PRIVATE_CLINICIAN_SENTINEL, RN)"


def manual(drug, stamp, doses):
    return {"medication": drug, "timestamp": moment(stamp).isoformat(),
            "volume_ml": None, "dose_count": doses, "source": "manual"}


def reviewed(events, medications, at=NOW):
    data = empty_prn()
    data["events"] = events
    return confirm_review(data, medications, at)


@pytest.mark.parametrize("name,drug", [
    ("HYDROmorphone (Dilaudid) syringe", "hydromorphone"),
    ("morphine sulfate", "morphine"), ("Sublimaze", "fentanyl"),
    ("Versed", "midazolam"), ("Ketalar", "ketamine"),
    ("Nembutal", "pentobarbital"), ("Norcuron", "vecuronium"),
    ("Zemuron", "rocuronium"),
])
def test_all_requested_drugs_and_aliases(name, drug):
    assert canonical_medication(name) == drug


@pytest.mark.parametrize("name", ["phenobarbital", "unfentanylated", "midazolam/morphine", "", None])
def test_whole_name_and_single_drug_required(name):
    assert canonical_medication(name) == ""


def test_volume_records_remain_unresolved_without_guessing_from_rate_or_volume():
    source = "TIME\tANALGESIA\tSEDATIVES\tPARALYTICS\n"
    source += "0100\t" + volume("Hydromorphone", "11/22/26 0100", "0.89") + "\t\t\n"
    source += "0141\t" + volume("Hydromorphone", amount="1.05") + "\t" + volume("Midazolam", amount="2") + "\t"
    result = parse_prn(source)
    assert not result.error
    assert len(result.data["events"]) == 3
    assert all(event["dose_count"] is None for event in result.data["events"])
    assert prn_counts({"prn": result.data}, NOW) == {}
    with pytest.raises(ValueError, match="Resolve every"):
        confirm_review(result.data, ["hydromorphone"], NOW)
    saved = json.dumps(result.data)
    assert "PRIVATE_CLINICIAN_SENTINEL" not in saved
    assert "Volume" not in saved


def test_exact_repeated_source_entry_is_not_double_counted():
    record = volume("Morphine")
    result = parse_prn("0141\t" + record + "\n0141\t" + record)
    assert not result.error
    assert len(result.data["events"]) == 1
    result.data["events"][0]["dose_count"] = 1
    data = confirm_review(result.data, ["morphine"], NOW)
    assert prn_counts({"prn": data}, NOW) == {"morphine": 1}


def test_explicit_prn_record_is_one_dose_but_capture_still_requires_review():
    result = parse_prn("Fentanyl PRN administered: 10 mcg (11/22/26 0141 : Chart May, RN)")
    assert not result.error
    assert result.data["events"][0]["dose_count"] == 1
    assert result.data["events"][0]["source"] == "explicit_prn"
    assert prn_counts({"prn": result.data}, NOW) == {}
    data = confirm_review(result.data, "fentanyl", NOW)
    assert prn_counts({"prn": data}, NOW) == {"fentanyl": 1}


@pytest.mark.parametrize("source", [
    "Fentanyl bolus: 10 mcg (11/22/26 0141 : Chart Author)",
    "Fentanyl PRN not given (11/22/26 0141 : Chart Author)",
    "Fentanyl PRN given x2 (11/22/26 0141 : Chart Author)",
    "Fentanyl PRN given if agitated (11/22/26 0141 : Chart Author)",
    "Fentanyl PRN administered yesterday",
    "@FLOWDATETIME(1234:0141)@",
])
def test_bolus_order_negation_aggregate_and_unresolved_links_are_not_counts(source):
    result = parse_prn(source)
    assert result.error
    assert result.data is None


@pytest.mark.parametrize("source", ["", "\n\t", "No data recorded", "TIME\tANALGESIA\tSEDATIVES\tPARALYTICS\n0000\t\t\t"])
def test_empty_source_does_not_make_zero_counts(source):
    result = parse_prn(source)
    assert not result.error
    assert prn_counts({"prn": result.data}, NOW) == {}
    assert prn_counts({}, NOW) == {}
    data = confirm_review(result.data, ["rocuronium"], NOW)
    assert prn_counts({"prn": data}, NOW) == {"rocuronium": 0}


def test_zero_volume_requires_review_and_resolved_zero_is_not_an_administration():
    result = parse_prn(volume("Ketamine", amount="0"))
    assert not result.error
    assert result.data["events"][0]["dose_count"] is None
    result.data["events"][0]["dose_count"] = 0
    data = confirm_review(result.data, ["ketamine"], NOW)
    assert prn_counts({"prn": data}, NOW) == {"ketamine": 0}


def test_4am_window_includes_7am_and_current_minute_but_excludes_old_and_future():
    events = [manual("morphine", stamp, 1) for stamp in (
        "2026-11-21 06:59", "2026-11-21 07:00", "2026-11-21 23:59",
        "2026-11-22 00:00", "2026-11-22 04:00", "2026-11-22 04:01",
    )]
    data = reviewed(events, ["morphine"])
    start, end = prn_window(NOW)
    assert start == moment("2026-11-21 07:00")
    assert end == NOW
    assert prn_counts({"prn": data}, NOW) == {"morphine": 4}


def test_exactly_7am_resets_review_and_moves_start_to_today():
    events = [manual("midazolam", stamp, 1) for stamp in (
        "2026-11-22 06:59", "2026-11-22 07:00", "2026-11-22 07:01")]
    before = moment("2026-11-22 06:59")
    data = reviewed(events, ["midazolam"], before)
    assert prn_counts({"prn": data}, before) == {"midazolam": 1}
    seven = moment("2026-11-22 07:00")
    assert prn_window(seven)[0] == seven
    assert prn_counts({"prn": data}, seven) == {}
    data = confirm_review(data, ["midazolam"], seven)
    assert prn_counts({"prn": data}, seven) == {"midazolam": 1}
    assert prn_counts({"prn": data}, moment("2026-11-22 08:00")) == {"midazolam": 2}


def test_review_is_invalidated_by_edit_missing_dose_addition_and_next_day():
    data = reviewed([manual("vecuronium", "2026-11-22 01:00", 1)], ["vecuronium"])
    assert prn_counts({"prn": data}, NOW) == {"vecuronium": 1}
    edited = deepcopy(data)
    edited["events"][0]["dose_count"] = 2
    assert prn_counts({"prn": edited}, NOW) == {}
    edited = deepcopy(data)
    edited["events"].append(manual("vecuronium", "2026-11-22 02:00", 1))
    assert prn_counts({"prn": edited}, NOW) == {}
    assert prn_counts({"prn": data}, moment("2026-11-23 04:00")) == {}
    assert prn_counts({"prn": clear_review(data, "vecuronium")}, NOW) == {}


def test_unresolved_future_entry_becomes_visible_before_count_can_advance():
    data = reviewed([
        manual("pentobarbital", "2026-11-22 02:00", 1),
        manual("pentobarbital", "2026-11-22 05:00", None),
    ], ["pentobarbital"])
    assert prn_counts({"prn": data}, NOW) == {"pentobarbital": 1}
    assert prn_counts({"prn": data}, moment("2026-11-22 05:00")) == {}


def test_approval_for_one_drug_does_not_resolve_another():
    data = reviewed([
        manual("fentanyl", "2026-11-22 02:00", 2),
        manual("ketamine", "2026-11-22 02:01", None),
    ], ["fentanyl"])
    assert prn_counts({"prn": data}, NOW) == {"fentanyl": 2}
    assert prn_counts({"prn": data, "import_warnings": {"af": []}}, NOW) == {}


def test_export_context_clock_controls_counts_and_other_drugs_can_be_confirmed_zero():
    data = reviewed([manual("morphine", "2026-11-22 01:00", 1)], MEDICATIONS)
    with display_clock(NOW):
        counts = prn_counts({"prn": data})
        assert counts["morphine"] == 1
        assert counts["rocuronium"] == 0
    with display_clock(moment("2026-11-22 07:00")):
        assert prn_counts({"prn": data}) == {}


@pytest.mark.parametrize("value", [
    "2026-03-08 02:30", "2026-11-01 01:30", "11/01/26 0130",
    "2026-02-30 04:00", "11/22/26", "0400", "2026-11-22 24:00",
])
def test_missing_invalid_and_uncertain_dst_timestamps_fail(value):
    with pytest.raises(ValueError):
        event_time(value)


def test_explicit_offsets_disambiguate_fall_dst_and_window_uses_local_7am():
    first = moment("2026-11-01T01:30:00-04:00")
    second = moment("2026-11-01T01:30:00-05:00")
    assert (second.astimezone(timezone.utc) - first.astimezone(timezone.utc)).total_seconds() == 3600
    now = moment("2026-11-01 06:59")
    data = reviewed([
        manual("morphine", first.isoformat(), 1),
        manual("morphine", second.isoformat(), 1),
    ], ["morphine"], now)
    start, end = prn_window(now)
    assert start == moment("2026-10-31 07:00")
    assert (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() == 89940
    assert prn_counts({"prn": data}, now) == {"morphine": 2}


def test_spring_dst_window_keeps_previous_local_7am_without_forcing_24_hours():
    start, end = prn_window(moment("2026-03-08 06:59"))
    assert start == moment("2026-03-07 07:00")
    assert (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() == 82740


@pytest.mark.parametrize("stamp", ["11/22/26", "99/22/26 0141", "11/22/26 2460", "11/01/26 0130"])
def test_bad_source_date_rejects_entire_block_without_partial_count(stamp):
    source = volume("Morphine") + "\n" + volume("Morphine", stamp)
    result = parse_prn(source)
    assert result.error and result.data is None


@pytest.mark.parametrize("field,value", [
    ("dose_count", -1), ("dose_count", 0.5), ("dose_count", True), ("dose_count", 101),
    ("volume_ml", float("nan")), ("volume_ml", -1),
    ("source", ["volume"]), ("medication", "unsupported"),
    ("timestamp", "2026-11-22 01:00"),
])
def test_saved_invalid_values_raise_and_count_display_fails_closed(field, value):
    data = reviewed([manual("morphine", "2026-11-22 01:00", 1)], ["morphine"])
    data["events"][0][field] = value
    with pytest.raises(ValueError):
        validate_prn(data)
    assert prn_counts({"prn": data}, NOW) == {}


def test_raw_source_fields_and_names_cannot_enter_persisted_schema():
    data = empty_prn()
    data["events"].append(manual("morphine", "2026-11-22 01:00", 1))
    data["events"][0]["clinician"] = "PRIVATE_CLINICIAN_SENTINEL"
    with pytest.raises(ValueError):
        validate_prn(data)


def test_af_marker_pair_and_record_limit():
    marker = "af" * 16
    result = parse_prn(marker + "\n" + volume("Morphine") + "\n" + marker)
    assert not result.error and len(result.data["events"]) == 1
    assert parse_prn(marker + "\n" + volume("Morphine")).error
    data = empty_prn()
    data["events"] = [manual("morphine", "2026-11-22 01:00", 1)] * 4097
    with pytest.raises(ValueError):
        validate_prn(data)
