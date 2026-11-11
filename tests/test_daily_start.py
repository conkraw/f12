"""Daily list reset boundaries and archive compatibility using synthetic data."""
from copy import deepcopy
from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo

import pytest

from daily_start import START_MARKER, daily_reset_plan, start_daily_list, started_today
from difficult_airway import empty_airway
from labs import parse_labs
from models import SCHEMA_VERSION, ValidationError, new_sheet, new_vault, upgrade_vault, validate_vault
from security import generate_key, open_vault, seal_vault


EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=EASTERN)


def vault_with_times(times):
    vault = new_vault()
    for room, stamp in times.items():
        sheet = new_sheet(room)
        sheet["updated_at"] = stamp
        sheet["fields"]["Diagnoses"] = "Synthetic handoff content"
        vault["rooms"][room] = sheet
    return vault


def removed_rooms(vault, now=NOW):
    return [row["room"] for row in daily_reset_plan(vault, now)["remove"]]


@pytest.mark.parametrize("stamp,remove", [
    ("2020-01-01T12:00:00-05:00", True),
    ("2026-11-10T23:59:59-05:00", True),
    ("2026-11-11T00:00:00-05:00", False),
    ("2026-11-11T04:59:59-05:00", False),
    ("2026-11-11T05:00:00-05:00", True),
    ("2026-11-11T08:29:59-05:00", True),
    ("2026-11-11T08:30:00-05:00", True),
    ("2026-11-11T08:30:00.000001-05:00", False),
    ("2026-11-11T08:30:01-05:00", False),
    ("2026-11-11T09:00:00-05:00", False),
    ("2026-11-11T12:00:00-05:00", False),
    ("2026-11-11T12:00:01-05:00", False),
    ("2026-11-12T06:00:00-05:00", False),
])
def test_literal_last_saved_date_and_inclusive_morning_window(stamp, remove):
    vault = vault_with_times({"P4102": stamp})
    assert bool(removed_rooms(vault)) is remove


@pytest.mark.parametrize("stamp", [None, "", "not a timestamp", "2026-11-10",
                                    "2026-11-10T12:00:00", "0001-01-01T00:00:00+00:00"])
def test_unknown_invalid_naive_or_unconvertible_save_times_are_retained(stamp):
    vault = vault_with_times({"P4102": stamp})
    before = deepcopy(vault)
    plan = daily_reset_plan(vault, NOW)
    assert not plan["remove"]
    assert plan["keep"][0]["reason"] == "Save time unavailable"
    assert vault == before


@pytest.mark.parametrize("stamp,remove", [
    ("2026-11-11T04:59:59+00:00", True),
    ("2026-11-11T05:00:00+00:00", False),
    ("2026-11-11T10:00:00+00:00", True),
    ("2026-11-11T13:30:00+00:00", True),
    ("2026-11-11T13:30:01+00:00", False),
])
def test_eastern_date_and_window_are_independent_of_utc_date(stamp, remove):
    assert bool(removed_rooms(vault_with_times({"P4102": stamp}))) is remove


@pytest.mark.parametrize("day,stamp,remove", [
    ("2026-03-08", "2026-03-07T23:59:59-05:00", True),
    ("2026-03-08", "2026-03-08T04:59:59-04:00", False),
    ("2026-03-08", "2026-03-08T05:00:00-04:00", True),
    ("2026-03-08", "2026-03-08T08:30:00-04:00", True),
    ("2026-03-08", "2026-03-08T08:30:01-04:00", False),
    ("2026-11-01", "2026-11-01T01:30:00-04:00", False),
    ("2026-11-01", "2026-11-01T01:30:00-05:00", False),
    ("2026-11-01", "2026-11-01T05:00:00-05:00", True),
    ("2026-11-01", "2026-11-01T08:30:00-05:00", True),
    ("2026-11-01", "2026-11-01T08:30:01-05:00", False),
])
def test_daylight_saving_transitions_use_local_calendar_times(day, stamp, remove):
    now = datetime.fromisoformat(day + "T12:00:00").replace(tzinfo=EASTERN)
    assert bool(removed_rooms(vault_with_times({"P4102": stamp}), now)) is remove


def test_updated_at_only_never_creation_import_or_admission_dates():
    vault = vault_with_times({"P4102": "2026-11-11T09:00:00-05:00",
                              "P4104": "2026-11-10T09:00:00-05:00"})
    vault["rooms"]["P4102"]["created_at"] = "2026-11-01T08:00:00-05:00"
    vault["rooms"]["P4102"]["admission_date"] = "11/01/2026"
    vault["rooms"]["P4104"]["created_at"] = "2026-11-11T10:00:00-05:00"
    assert removed_rooms(vault) == ["P4104"]


def test_preview_has_only_room_saved_time_reason_metadata_and_is_read_only():
    vault = vault_with_times({"P4102": "2026-11-11T07:00:00-05:00", "P4104": None})
    before = deepcopy(vault)
    plan = daily_reset_plan(vault, NOW)
    assert set(plan) == {"date", "as_of", "already_started", "started_at", "remove", "keep"}
    assert plan["date"] == "2026-11-11" and plan["as_of"] == NOW.astimezone(timezone.utc).isoformat()
    assert plan["already_started"] is False and plan["started_at"] == ""
    assert set(plan["remove"][0]) == {"room", "last_saved", "saved_at", "reason"}
    assert "07:00:00 AM EST" in plan["remove"][0]["last_saved"]
    assert plan["remove"][0]["saved_at"] == "2026-11-11T12:00:00+00:00"
    assert plan["keep"][0]["saved_at"] == ""
    assert "Synthetic handoff content" not in repr(plan)
    assert vault == before


def test_future_morning_result_is_not_deleted_and_preview_clock_can_be_frozen():
    vault = vault_with_times({"P4102": "2026-11-11T07:00:00-05:00"})
    early = datetime(2026, 11, 11, 6, 0, 0, 123456, tzinfo=EASTERN)
    plan = daily_reset_plan(vault, early)
    assert not plan["remove"] and plan["keep"][0]["reason"] == "Future save time"
    frozen_candidate = start_daily_list(vault, datetime.fromisoformat(plan["as_of"]))
    assert frozen_candidate["rooms"] == vault["rooms"]
    assert frozen_candidate["settings"][START_MARKER] == plan["as_of"]
    assert removed_rooms(vault, NOW) == ["P4102"]


def test_selected_whole_records_deleted_without_airway_retention_and_other_settings_unchanged():
    vault = vault_with_times({"P4102": "2026-11-10T07:00:00-05:00",
                              "CUSTOM 1": "2026-11-11T10:00:00-05:00"})
    vault["settings"]["rooms"] += ["CUSTOM 1", "EMPTY CUSTOM"]
    vault["settings"]["medication_mappings"] = [dict(name="synthetic", match="prefix", destination="Neurologic")]
    for sheet in vault["rooms"].values():
        sheet["difficult_airway"] = dict(empty_airway(), enabled=True, plan="Synthetic airway details")
        sheet["labs"] = parse_labs("NA\t140\t11/10/2026").data
    before = deepcopy(vault)
    candidate = start_daily_list(vault, NOW)
    assert set(candidate["rooms"]) == {"CUSTOM 1"}
    assert candidate["rooms"]["CUSTOM 1"] == before["rooms"]["CUSTOM 1"]
    assert candidate["settings"] == dict(before["settings"], patient_list_started_at=NOW.astimezone(timezone.utc).isoformat())
    assert re.fullmatch(r"[0-9a-f]{32}", candidate["reset_generation"])
    assert candidate["reset_generation"] != before["reset_generation"]
    assert candidate["schema"] == before["schema"] == SCHEMA_VERSION == 34
    validate_vault(candidate)
    assert vault == before


def test_first_start_with_no_eligible_rooms_still_marks_day_and_changes_generation():
    vault = vault_with_times({"P4102": "2026-11-11T04:00:00-05:00"})
    candidate = start_daily_list(vault, NOW)
    assert candidate["rooms"] == vault["rooms"]
    assert candidate["reset_generation"] != vault["reset_generation"]
    assert started_today(candidate, NOW)


def test_empty_vault_start_records_day_without_creating_a_handoff():
    candidate = start_daily_list(new_vault(), NOW)
    assert candidate["rooms"] == {} and started_today(candidate, NOW)


def test_repeat_login_start_keeps_new_morning_handoff_and_all_metadata():
    early = datetime(2026, 11, 11, 5, 30, tzinfo=EASTERN)
    vault = start_daily_list(new_vault(), early)
    vault["rooms"].update(vault_with_times({"P4102": "2026-11-11T06:00:00-05:00"})["rooms"])
    before = deepcopy(vault)
    plan = daily_reset_plan(vault, NOW)
    assert plan["already_started"] and not plan["remove"]
    assert [row["room"] for row in plan["keep"]] == ["P4102"]
    candidate = start_daily_list(vault, NOW)
    assert candidate == before and candidate is not vault
    assert candidate["rooms"] is not vault["rooms"]
    assert vault == before


def test_next_eastern_day_allows_new_start():
    vault = start_daily_list(new_vault(), NOW)
    vault["rooms"].update(vault_with_times({"P4102": "2026-11-11T10:00:00-05:00"})["rooms"])
    tomorrow = datetime(2026, 11, 12, 9, 0, tzinfo=EASTERN)
    assert not started_today(vault, tomorrow)
    candidate = start_daily_list(vault, tomorrow)
    assert not candidate["rooms"] and started_today(candidate, tomorrow)
    assert candidate["reset_generation"] != vault["reset_generation"]


@pytest.mark.parametrize("marker,expected", [
    ("2026-11-12T04:30:00Z", True),
    ("2026-11-11T04:30:00Z", False),
    ("2026-11-11T05:00:00Z", True),
])
def test_started_marker_uses_eastern_date_not_utc_date(marker, expected):
    vault = new_vault()
    vault["settings"][START_MARKER] = marker
    late = datetime(2026, 11, 11, 23, 45, tzinfo=EASTERN)
    assert started_today(vault, late) is expected


@pytest.mark.parametrize("marker", [None, "", 1, [], {}, "not a timestamp", "2026-11-11",
                                     "2026-11-11T06:00:00", "2026-11-11\n06:00:00-05:00"])
def test_invalid_optional_start_marker_rejected_without_mutation(marker):
    vault = new_vault()
    vault["settings"][START_MARKER] = marker
    before = deepcopy(vault)
    with pytest.raises(ValidationError, match="patient-list start time"):
        validate_vault(vault)
    assert vault == before


@pytest.mark.parametrize("marker", ["2026-11-11T06:00:00-05:00", "2026-11-11T11:00:00Z",
                                     "2026-11-11T16:30:00+05:30"])
def test_valid_aware_iso_marker_is_accepted_verbatim(marker):
    vault = new_vault()
    vault["settings"][START_MARKER] = marker
    before = deepcopy(vault)
    validate_vault(vault)
    assert started_today(vault, NOW) and vault == before


def test_old_schema34_archive_stays_unchanged_without_optional_marker():
    vault = vault_with_times({"P4102": "2026-11-10T06:00:00-05:00"})
    before = deepcopy(vault)
    key = generate_key()
    assert START_MARKER not in vault["settings"]
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == before and upgrade_vault(restored) == before
    assert START_MARKER not in restored["settings"]
    assert vault == before


def test_new_marker_and_selective_reset_roundtrip_in_existing_encrypted_format():
    vault = vault_with_times({"P4102": "2026-11-10T06:00:00-05:00",
                              "P4104": "2026-11-11T09:00:00-05:00"})
    candidate = start_daily_list(vault, NOW)
    key = generate_key()
    encrypted = seal_vault(candidate, key)
    assert b"Synthetic handoff content" not in encrypted
    restored = open_vault(encrypted, key)
    assert restored == candidate and start_daily_list(restored, NOW) == candidate


@pytest.mark.parametrize("function", [daily_reset_plan, start_daily_list, started_today])
def test_reset_clock_requires_explicit_timezone(function):
    with pytest.raises(ValueError, match="timezone"):
        function(new_vault(), datetime(2026, 11, 11, 9, 0))
