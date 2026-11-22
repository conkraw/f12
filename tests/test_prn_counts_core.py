"""Automatic paralytic counts and timestamp checks with synthetic records."""
from copy import deepcopy
from datetime import timezone
import json

import pytest

from lab_windows import display_clock
from prn_counts import (
    COUNTED_MEDICATIONS, MEDICATIONS, automatic_prn_events, canonical_medication,
    clear_review, confirm_review, empty_prn, event_time, parse_prn, prn_counts,
    prn_window, validate_prn,
)


def moment(text):
    return event_time(text)


NOW = moment("2026-11-22 04:00")
ZERO = {"vecuronium": 0, "rocuronium": 0}


def volume(drug, stamp="11/22/26 0141", amount="1"):
    return f"Volume (mL) {drug}: {amount} mL ({stamp} : PRIVATE_CLINICIAN_SENTINEL, RN)"


def manual(drug, stamp, doses):
    return {"medication": drug, "timestamp": moment(stamp).isoformat(),
            "volume_ml": None, "dose_count": doses, "source": "manual"}


def source_event(drug, stamp, amount=1, legacy_doses=None):
    return {"medication": drug, "timestamp": moment(stamp).isoformat(),
            "volume_ml": amount, "dose_count": legacy_doses, "source": "volume"}


def data(*events):
    result = empty_prn()
    result["events"] = list(events)
    return result


@pytest.mark.parametrize("name,drug", [
    ("HYDROmorphone (Dilaudid) syringe", "hydromorphone"),
    ("morphine sulfate", "morphine"), ("Sublimaze", "fentanyl"),
    ("Versed", "midazolam"), ("Ketalar", "ketamine"),
    ("Nembutal", "pentobarbital"), ("Norcuron", "vecuronium"),
    ("Zemuron", "rocuronium"),
])
def test_alias_recognition_retains_legacy_archive_support(name, drug):
    assert canonical_medication(name) == drug


@pytest.mark.parametrize("name", ["phenobarbital", "unfentanylated", "midazolam/morphine", "", None])
def test_whole_name_and_single_drug_required(name):
    assert canonical_medication(name) == ""


def test_mixed_table_keeps_only_paralytics_and_needs_no_confirmation():
    text = "TIME\tANALGESIA\tSEDATIVES\tPARALYTICS\n"
    text += "0100\t" + volume("Hydromorphone", "invalid", "0.89") + "\t@FLOWDATETIME(broken)@\t"
    text += volume("Vecuronium", "11/22/26 0100", "0.89") + "\n"
    text += "0141\tMorphine malformed entry\t" + volume("Midazolam", amount="bad") + "\t"
    text += volume("Rocuronium", amount="2")
    result = parse_prn(text)
    assert not result.error and not result.issues
    assert len(result.data["events"]) == 2
    assert result.data["reviewed"] == {}
    assert prn_counts({"prn": result.data}, NOW) == {"vecuronium": 1, "rocuronium": 1}
    saved = json.dumps(result.data)
    assert "PRIVATE_CLINICIAN_SENTINEL" not in saved
    assert "Hydromorphone" not in saved and "Midazolam" not in saved


@pytest.mark.parametrize("drug", [drug for drug in MEDICATIONS if drug not in COUNTED_MEDICATIONS])
def test_analgesics_and_sedatives_are_ignored_even_when_malformed(drug):
    result = parse_prn(volume(drug, "invalid date", "bad") + "\n" + drug + " PRN given without a date")
    assert not result.error and not result.issues
    assert result.data["events"] == []
    assert prn_counts({"prn": result.data}, NOW) == ZERO


@pytest.mark.parametrize("target_first", [False, True])
def test_excluded_malformed_volume_does_not_hide_target_in_same_cell(target_first):
    entries = [volume("Midazolam", "bad", "bad"), volume("Norcuron")]
    if target_first:
        entries.reverse()
    result = parse_prn(" ".join(entries))
    assert not result.error
    assert prn_counts({"prn": result.data}, NOW) == {"vecuronium": 1, "rocuronium": 0}


def test_unknown_outside_list_volume_and_explicit_other_medication_are_ignored():
    result = parse_prn(volume("Dexmedetomidine", "bad", "bad") +
                       "\nAcetaminophen PRN given: malformed source\n" + volume("Zemuron"))
    assert not result.error and not result.issues
    assert prn_counts({"prn": result.data}, NOW) == {"vecuronium": 0, "rocuronium": 1}


def test_exact_repeated_source_entry_is_not_double_counted():
    record = volume("Vecuronium")
    result = parse_prn("0141\t" + record + "\n0141\t" + record)
    assert not result.error
    assert len(result.data["events"]) == 1
    assert prn_counts({"prn": result.data}, NOW) == {"vecuronium": 1, "rocuronium": 0}


def test_different_volume_entries_at_same_time_are_distinct_source_records():
    result = parse_prn(volume("Rocuronium", amount="1") + " " + volume("Rocuronium", amount="2"))
    assert not result.error
    assert prn_counts({"prn": result.data}, NOW) == {"vecuronium": 0, "rocuronium": 2}


def test_explicit_paralytic_administration_is_one_without_review():
    result = parse_prn("Vecuronium PRN administered: 1 mg (11/22/26 0141 : Chart May, RN)")
    assert not result.error and not result.issues
    assert result.data["events"][0]["source"] == "explicit_prn"
    assert prn_counts({"prn": result.data}, NOW) == {"vecuronium": 1, "rocuronium": 0}


@pytest.mark.parametrize("text", [
    "Vecuronium bolus: 1 mg (11/22/26 0141 : Chart Author)",
    "Vecuronium PRN not given (11/22/26 0141 : Chart Author)",
    "Vecuronium PRN given x2 (11/22/26 0141 : Chart Author)",
    "Rocuronium PRN given if needed (11/22/26 0141 : Chart Author)",
    "Vecuronium PRN administered yesterday",
    "@FLOWDATETIME(1234:0141)@",
    "Volume (mL) Vecuronium: bad mL (11/22/26 0141)",
    "Volume (mL) Vecuronium / Rocuronium: 1 mL (11/22/26 0141)",
])
def test_unreadable_or_uncertain_paralytic_entries_do_not_make_partial_counts(text):
    result = parse_prn(volume("Vecuronium") + "\n" + text)
    assert result.error and result.data is None


@pytest.mark.parametrize("text", ["", "\n\t", "No data recorded", "TIME\tANALGESIA\tSEDATIVES\tPARALYTICS\n0000\t\t\t"])
def test_valid_empty_af_means_zero_but_missing_af_has_no_count(text):
    result = parse_prn(text)
    assert not result.error
    assert prn_counts({"prn": result.data}, NOW) == ZERO
    assert prn_counts({}, NOW) == {}
    assert prn_counts({"prn": None}, NOW) == {}


def test_zero_volume_is_not_counted_and_positive_volume_is_one_not_milliliters():
    result = parse_prn(volume("Vecuronium", amount="0") + "\n" + volume("Rocuronium", amount="20"))
    assert not result.error
    assert prn_counts({"prn": result.data}, NOW) == {"vecuronium": 0, "rocuronium": 1}


def test_4am_window_includes_7am_and_now_but_excludes_old_and_future():
    records = data(*(source_event("vecuronium", stamp) for stamp in (
        "2026-11-21 06:59", "2026-11-21 07:00", "2026-11-21 23:59",
        "2026-11-22 00:00", "2026-11-22 04:00", "2026-11-22 04:01")))
    start, end = prn_window(NOW)
    assert start == moment("2026-11-21 07:00") and end == NOW
    assert prn_counts({"prn": records}, NOW) == {"vecuronium": 4, "rocuronium": 0}


def test_exactly_7am_rolls_over_automatically_and_future_entries_enter_later():
    records = data(*(source_event("rocuronium", stamp) for stamp in (
        "2026-11-22 06:59", "2026-11-22 07:00", "2026-11-22 07:01")))
    assert prn_counts({"prn": records}, moment("2026-11-22 06:59"))["rocuronium"] == 1
    seven = moment("2026-11-22 07:00")
    assert prn_window(seven)[0] == seven
    assert prn_counts({"prn": records}, seven)["rocuronium"] == 1
    assert prn_counts({"prn": records}, moment("2026-11-22 08:00"))["rocuronium"] == 2
    assert prn_counts({"prn": records}, moment("2026-11-23 08:00")) == ZERO


def test_no_review_or_infusion_gate_and_old_volume_decisions_do_not_override_counts():
    records = data(source_event("vecuronium", "2026-11-22 01:00", legacy_doses=0),
                   source_event("vecuronium", "2026-11-22 02:00", legacy_doses=None))
    sheet = {"prn": records, "medications": [{"name": "vecuronium infusion", "frequency": "Continuous"}]}
    before = deepcopy(sheet)
    assert prn_counts(sheet, NOW) == {"vecuronium": 2, "rocuronium": 0}
    assert sheet == before and records["reviewed"] == {}


def test_old_eight_drug_archives_open_but_only_paralytics_are_counted():
    records = data(*(manual(drug, "2026-11-22 01:00", 3) for drug in MEDICATIONS))
    records = confirm_review(records, MEDICATIONS, NOW)
    validate_prn(records)
    assert prn_counts({"prn": records}, NOW) == {"vecuronium": 3, "rocuronium": 3}
    assert prn_counts({"prn": clear_review(records)}, NOW) == {"vecuronium": 3, "rocuronium": 3}
    assert prn_counts({"prn": records, "import_warnings": {"af": []}}, NOW) == {}


def test_shared_helper_keeps_full_timeline_dedupes_and_does_not_mutate():
    first = source_event("vecuronium", "2026-11-21 01:00")
    records = data(source_event("vecuronium", "2026-11-22 05:00"), first,
                   dict(first, dose_count=0), manual("vecuronium", "2026-11-22 02:00", 2),
                   source_event("midazolam", "2026-11-22 01:00"))
    before = deepcopy(records)
    assert automatic_prn_events(records, "Norcuron") == [
        (moment("2026-11-21 01:00"), 1), (moment("2026-11-22 02:00"), 2),
        (moment("2026-11-22 05:00"), 1)]
    assert automatic_prn_events(records, "midazolam") == []
    assert records == before


def test_export_context_clock_controls_counts_without_new_confirmation():
    records = data(source_event("vecuronium", "2026-11-22 01:00"))
    with display_clock(NOW):
        assert prn_counts({"prn": records}) == {"vecuronium": 1, "rocuronium": 0}
    with display_clock(moment("2026-11-22 07:00")):
        assert prn_counts({"prn": records}) == ZERO


@pytest.mark.parametrize("value", [
    "2026-03-08 02:30", "2026-11-01 01:30", "11/01/26 0130",
    "2026-02-30 04:00", "11/22/26", "0400", "2026-11-22 24:00",
])
def test_missing_invalid_and_uncertain_dst_timestamps_fail(value):
    with pytest.raises(ValueError):
        event_time(value)


@pytest.mark.parametrize("value", ["9999-12-31 23:59", "0001-01-01T00:00:00+00:00"])
def test_unrepresentable_timezone_conversion_is_a_validation_error(value):
    with pytest.raises(ValueError, match="not a valid date and time"):
        event_time(value)


def test_fall_dst_offsets_remain_distinct_and_window_uses_local_7am():
    first = moment("2026-11-01T01:30:00-04:00")
    second = moment("2026-11-01T01:30:00-05:00")
    assert (second.astimezone(timezone.utc) - first.astimezone(timezone.utc)).total_seconds() == 3600
    now = moment("2026-11-01 06:59")
    records = data(source_event("vecuronium", second.isoformat()), source_event("vecuronium", first.isoformat()))
    start, end = prn_window(now)
    assert start == moment("2026-10-31 07:00")
    assert (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() == 89940
    assert prn_counts({"prn": records}, now) == {"vecuronium": 2, "rocuronium": 0}
    assert [value.astimezone(timezone.utc) for value, _ in automatic_prn_events(records, "vecuronium")] == [
        first.astimezone(timezone.utc), second.astimezone(timezone.utc)]


def test_spring_dst_window_keeps_previous_local_7am_without_forcing_24_hours():
    start, end = prn_window(moment("2026-03-08 06:59"))
    assert start == moment("2026-03-07 07:00")
    assert (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() == 82740


@pytest.mark.parametrize("stamp", ["11/22/26", "99/22/26 0141", "11/22/26 2460", "11/01/26 0130"])
def test_bad_target_source_date_rejects_entire_block_without_partial_count(stamp):
    result = parse_prn(volume("Vecuronium") + "\n" + volume("Vecuronium", stamp))
    assert result.error and result.data is None


@pytest.mark.parametrize("field,value", [
    ("dose_count", -1), ("dose_count", 0.5), ("dose_count", True), ("dose_count", 101),
    ("volume_ml", float("nan")), ("volume_ml", -1),
    ("source", ["volume"]), ("medication", "unsupported"),
    ("timestamp", "2026-11-22 01:00"),
])
def test_saved_invalid_values_raise_and_count_display_fails_closed(field, value):
    records = data(manual("vecuronium", "2026-11-22 01:00", 1))
    records["events"][0][field] = value
    with pytest.raises(ValueError):
        validate_prn(records)
    assert prn_counts({"prn": records}, NOW) == {}


def test_raw_source_fields_and_names_cannot_enter_persisted_schema():
    records = data(manual("vecuronium", "2026-11-22 01:00", 1))
    records["events"][0]["clinician"] = "PRIVATE_CLINICIAN_SENTINEL"
    with pytest.raises(ValueError):
        validate_prn(records)


def test_af_marker_pair_and_record_limit():
    marker = "af" * 16
    result = parse_prn(marker + "\n" + volume("Vecuronium") + "\n" + marker)
    assert not result.error and len(result.data["events"]) == 1
    assert parse_prn(marker + "\n" + volume("Vecuronium")).error
    records = data(*([source_event("vecuronium", "2026-11-22 01:00")] * 4097))
    with pytest.raises(ValueError):
        validate_prn(records)
