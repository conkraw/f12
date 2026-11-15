"""Unrestricted new-list resets and archive compatibility using synthetic data."""
from copy import deepcopy
from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo

import pytest

from daily_start import START_MARKER, start_daily_list
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


@pytest.mark.parametrize("stamp", [
    "2020-01-01T12:00:00-05:00",
    "2026-11-10T23:59:59-05:00",
    "2026-11-11T00:00:00-05:00",
    "2026-11-11T04:59:59-05:00",
    "2026-11-11T05:00:00-05:00",
    "2026-11-11T08:29:59-05:00",
    "2026-11-11T08:30:00-05:00",
    "2026-11-11T08:30:00.000001-05:00",
    "2026-11-11T08:30:01-05:00",
    "2026-11-11T09:00:00-05:00",
    "2026-11-11T12:00:00-05:00",
    "2026-11-11T23:59:59-05:00",
    "2026-11-12T06:00:00-05:00",
    None, "", "not a timestamp", "2026-11-10",
    "2026-11-10T12:00:00", "0001-01-01T00:00:00+00:00",
])
def test_every_saved_handoff_is_removed_regardless_of_save_timestamp(stamp):
    vault = vault_with_times({"P4102": stamp})
    before = deepcopy(vault)
    candidate = start_daily_list(vault, NOW)
    assert candidate["rooms"] == {}
    assert vault == before


@pytest.mark.parametrize("hour", range(24))
def test_new_list_can_start_at_every_hour(hour):
    vault = vault_with_times({"P4102": "2026-11-11T09:00:00-05:00", "P4104": None})
    now = datetime(2026, 11, 11, hour, 0, tzinfo=EASTERN)
    candidate = start_daily_list(vault, now)
    assert not candidate["rooms"]
    assert candidate["settings"][START_MARKER] == now.astimezone(timezone.utc).isoformat()


def test_whole_records_removed_without_airway_retention_and_custom_settings_preserved():
    vault = vault_with_times({"P4102": "2026-11-10T07:00:00-05:00",
                              "CUSTOM 1": "2026-11-11T10:00:00-05:00"})
    vault["settings"]["rooms"] += ["CUSTOM 1", "EMPTY CUSTOM"]
    vault["settings"]["medication_mappings"] = [dict(name="synthetic", match="prefix", destination="Neurologic")]
    for sheet in vault["rooms"].values():
        sheet["difficult_airway"] = dict(empty_airway(), enabled=True, plan="Synthetic airway details")
        sheet["labs"] = parse_labs("NA\t140\t11/10/2026").data
    before = deepcopy(vault)
    candidate = start_daily_list(vault, NOW)
    assert candidate["rooms"] == {}
    assert candidate["settings"] == dict(before["settings"], patient_list_started_at=NOW.astimezone(timezone.utc).isoformat())
    assert re.fullmatch(r"[0-9a-f]{32}", candidate["reset_generation"])
    assert candidate["reset_generation"] != before["reset_generation"]
    assert candidate["schema"] == before["schema"] == SCHEMA_VERSION == 34
    validate_vault(candidate)
    assert vault == before


def test_empty_vault_start_records_time_and_rotates_generation_without_creating_handoff():
    vault = new_vault()
    first = start_daily_list(vault, NOW)
    second = start_daily_list(first, NOW)
    assert first["rooms"] == second["rooms"] == {}
    assert first["settings"][START_MARKER] == NOW.astimezone(timezone.utc).isoformat()
    assert len({vault["reset_generation"], first["reset_generation"], second["reset_generation"]}) == 3


def test_repeat_start_same_day_clears_new_handoffs_and_changes_generation():
    early = datetime(2026, 11, 11, 5, 30, tzinfo=EASTERN)
    vault = start_daily_list(new_vault(), early)
    vault["rooms"].update(vault_with_times({"P4102": "2026-11-11T06:00:00-05:00"})["rooms"])
    before = deepcopy(vault)
    candidate = start_daily_list(vault, NOW)
    assert candidate["rooms"] == {}
    assert candidate["reset_generation"] != before["reset_generation"]
    assert candidate["settings"][START_MARKER] == NOW.astimezone(timezone.utc).isoformat()
    assert vault == before


@pytest.mark.parametrize("marker", [
    "2026-11-10T06:00:00-05:00",
    "2026-11-11T06:00:00-05:00",
    "2026-11-11T17:00:00+00:00",
    "2026-11-12T06:00:00-05:00",
])
def test_existing_start_marker_never_prevents_an_intentional_new_list(marker):
    vault = vault_with_times({"P4102": "2026-11-11T10:00:00-05:00"})
    vault["settings"][START_MARKER] = marker
    candidate = start_daily_list(vault, NOW)
    assert not candidate["rooms"]
    assert candidate["reset_generation"] != vault["reset_generation"]
    assert candidate["settings"][START_MARKER] == NOW.astimezone(timezone.utc).isoformat()


@pytest.mark.parametrize("stamp", [
    "2026-03-08T01:30:00-05:00",
    "2026-03-08T03:30:00-04:00",
    "2026-11-01T01:30:00-04:00",
    "2026-11-01T01:30:00-05:00",
    "2026-11-11T16:30:00+05:30",
])
def test_start_marker_records_aware_utc_time_across_offsets_and_dst(stamp):
    now = datetime.fromisoformat(stamp)
    candidate = start_daily_list(new_vault(), now)
    assert candidate["settings"][START_MARKER] == now.astimezone(timezone.utc).isoformat()


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
    assert vault == before


def test_old_schema34_archive_stays_unchanged_without_optional_marker():
    vault = vault_with_times({"P4102": "2026-11-10T06:00:00-05:00"})
    before = deepcopy(vault)
    key = generate_key()
    assert START_MARKER not in vault["settings"]
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == before and upgrade_vault(restored) == before
    assert START_MARKER not in restored["settings"]
    assert vault == before


def test_new_marker_and_complete_reset_roundtrip_in_existing_encrypted_format():
    vault = vault_with_times({"P4102": "2026-11-10T06:00:00-05:00",
                              "P4104": "2026-11-11T09:00:00-05:00"})
    candidate = start_daily_list(vault, NOW)
    key = generate_key()
    encrypted = seal_vault(candidate, key)
    assert b"Synthetic handoff content" not in encrypted
    restored = open_vault(encrypted, key)
    assert restored == candidate and not restored["rooms"]
    repeated = start_daily_list(restored, NOW)
    assert not repeated["rooms"] and repeated["reset_generation"] != restored["reset_generation"]


def test_reset_clock_requires_explicit_timezone():
    with pytest.raises(ValueError, match="timezone"):
        start_daily_list(new_vault(), datetime(2026, 11, 11, 9, 0))
