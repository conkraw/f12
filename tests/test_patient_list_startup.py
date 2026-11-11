"""Synthetic startup callbacks, stale previews, and reset reconciliation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import time

import pytest

from daily_start import START_MARKER, daily_reset_plan, start_daily_list
from difficult_airway import empty_airway
from github_store import StorageError
from handoff_reset import cleared_vault
from models import new_sheet, new_vault
from test_callbacks import app
from test_print_fit_reset import Store
from test_ui_smoke import equip


NOW = datetime(2026, 11, 11, 17, 0, tzinfo=timezone.utc)


class ReadCountingStore(Store):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.loads = 0

    def load(self):
        self.loads += 1
        return super().load()


class LostAcknowledgementStore(ReadCountingStore):
    """The remote write succeeds, but its response does not reach the caller."""
    def save(self, candidate, sha):
        result = super().save(candidate, sha)
        if len(self.calls) == 1:
            raise StorageError("Synthetic save acknowledgement lost")
        return result


def record(room, stamp):
    sheet = new_sheet(room)
    sheet["updated_at"] = stamp
    sheet["fields"]["Diagnoses"] = "Synthetic saved handoff"
    return sheet


def seeded(app, monkeypatch):
    monkeypatch.setattr(app, "patient_list_now", lambda: NOW)
    vault = new_vault()
    for room, stamp in (
        ("P4102", "2026-11-10T15:00:00+00:00"),
        ("P4104", "2026-11-11T11:00:00+00:00"),
        ("P4106", "2026-11-11T09:00:00+00:00"),
        ("P4108", "2026-11-11T14:00:00+00:00"),
        ("P4110", None),
    ):
        vault["rooms"][room] = record(room, stamp)
    vault["rooms"]["P4102"]["difficult_airway"] = dict(
        empty_airway(), enabled=True, plan="Synthetic airway content")
    vault["settings"]["rooms"] += ["CUSTOM EMPTY"]
    ss = app.st.session_state
    ss.update(vault=vault, vault_sha="old-sha", drafts={}, base_sheets={})
    ss.pop("patient_list_ready", None)
    ss.pop("daily_start_preview", None)
    return ss


def forbid_commit(*args, **kwargs):
    raise AssertionError("This action must not write")


def test_continue_enters_workspace_without_mutating_or_saving_handoffs(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    ss["drafts"] = deepcopy(ss["vault"]["rooms"])
    ss["base_sheets"] = deepcopy(ss["vault"]["rooms"])
    ss["drafts"]["P4108"]["fields"]["Neurologic"] = "Unsaved synthetic edit"
    before = {key: deepcopy(ss[key]) for key in ("vault", "drafts", "base_sheets")}
    ss["daily_start_preview"] = {"sentinel": True}
    monkeypatch.setattr(app, "commit", forbid_commit)
    app.continue_patient_list()
    assert ss["patient_list_ready"] is True and "daily_start_preview" not in ss
    assert all(ss[key] == value for key, value in before.items())


def test_prepare_reads_latest_archive_and_only_creates_frozen_preview(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    fresh = deepcopy(ss["vault"])
    fresh["rooms"]["P4112"] = record("P4112", "2026-11-11T16:00:00+00:00")
    store = ReadCountingStore(fresh, sha="fresh-sha")
    before = deepcopy(fresh)
    app.prepare_daily_start(store)
    preview = ss["daily_start_preview"]
    assert store.loads == 1 and not store.calls
    assert ss["vault"] == store.vault == before
    assert preview["source"] == before and preview["source"] is not ss["vault"]
    assert preview["sha"] == ss["vault_sha"] == "fresh-sha"
    assert preview["plan"] == daily_reset_plan(before, NOW)
    assert not ss.get("patient_list_ready")


def test_confirm_removes_only_reviewed_whole_records_and_marks_actual_click_time(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    before = deepcopy(ss["vault"])
    store = ReadCountingStore(before)
    guard = app.download_revocation()
    app.prepare_daily_start(store)
    clicked = NOW + timedelta(minutes=15)
    monkeypatch.setattr(app, "patient_list_now", lambda: clicked)
    app.confirm_daily_start(store)
    assert len(store.calls) == 1 and store.calls[0][1] == "old-sha"
    assert set(ss["vault"]["rooms"]) == {"P4106", "P4108", "P4110"}
    assert ss["vault"] == store.vault
    for room in ss["vault"]["rooms"]:
        assert ss["vault"]["rooms"][room] == before["rooms"][room]
    assert ss["vault"]["settings"] == dict(before["settings"], patient_list_started_at=clicked.isoformat())
    assert ss["vault"]["reset_generation"] != before["reset_generation"]
    assert guard.is_set() and ss["patient_list_ready"]
    assert "daily_start_preview" not in ss and not ss["drafts"]


def test_confirmation_uses_frozen_selection_after_clock_changes(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    ss["vault"]["rooms"]["P4112"] = record("P4112", "2026-11-11T13:00:00+00:00")
    before = deepcopy(ss["vault"])
    store = ReadCountingStore(before)
    monkeypatch.setattr(app, "patient_list_now", lambda: datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc))
    app.prepare_daily_start(store)
    assert "P4112" in [row["room"] for row in ss["daily_start_preview"]["plan"]["keep"]]
    monkeypatch.setattr(app, "patient_list_now", lambda: NOW)
    app.confirm_daily_start(store)
    assert store.vault["rooms"]["P4112"] == before["rooms"]["P4112"]
    assert store.vault["settings"][START_MARKER] == NOW.isoformat()


def test_preview_expires_when_eastern_date_changes(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    before = deepcopy(ss["vault"])
    store = ReadCountingStore(before)
    app.prepare_daily_start(store)
    monkeypatch.setattr(app, "patient_list_now", lambda: datetime(2026, 11, 12, 6, 0, tzinfo=timezone.utc))
    app.confirm_daily_start(store)
    assert not store.calls and ss["vault"] == before
    assert ss["daily_start_preview"]["failed"] and not ss.get("patient_list_ready")


@pytest.mark.parametrize("change", ["contents", "sha"])
def test_local_change_invalidates_preview_before_any_write(app, monkeypatch, change):
    ss = seeded(app, monkeypatch)
    store = ReadCountingStore(ss["vault"])
    app.prepare_daily_start(store)
    if change == "contents":
        ss["vault"]["rooms"]["P4102"]["fields"]["Diagnoses"] = "Changed after preview"
    else:
        ss["vault_sha"] = "changed-local-sha"
    before = deepcopy(ss["vault"])
    app.confirm_daily_start(store)
    assert not store.calls and ss["vault"] == before
    assert ss["daily_start_preview"]["failed"] and not ss.get("patient_list_ready")


def test_sha_conflict_preserves_local_work_and_requires_fresh_review(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    store = ReadCountingStore(ss["vault"])
    app.prepare_daily_start(store)
    before = deepcopy(ss["vault"])
    guard = app.download_revocation()
    store.vault["rooms"]["P4112"] = record("P4112", "2026-11-11T16:00:00+00:00")
    store.sha = "concurrent-sha"
    app.confirm_daily_start(store)
    assert len(store.calls) == 1 and store.calls[0][1] == "old-sha"
    assert ss["vault"] == before and not guard.is_set()
    assert ss["daily_start_preview"]["failed"] and not ss.get("patient_list_ready")
    app.confirm_daily_start(store)
    assert len(store.calls) == 1
    app.prepare_daily_start(store)
    assert store.loads == 2 and ss["daily_start_preview"]["sha"] == "concurrent-sha"
    app.confirm_daily_start(store)
    assert len(store.calls) == 2 and "P4112" in store.vault["rooms"]
    assert ss["patient_list_ready"]


def test_lost_save_acknowledgement_reload_detects_completed_start_without_second_delete(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    before = deepcopy(ss["vault"])
    store = LostAcknowledgementStore(before)
    app.prepare_daily_start(store)
    app.confirm_daily_start(store)
    assert ss["vault"] == before and len(store.calls) == 1
    assert START_MARKER in store.vault["settings"]
    assert ss["daily_start_preview"]["failed"] and not ss.get("patient_list_ready")
    app.confirm_daily_start(store)
    assert len(store.calls) == 1
    store.vault["rooms"]["P4112"] = record("P4112", "2026-11-11T12:00:00+00:00")
    store.sha = "post-reset-addition"
    app.prepare_daily_start(store)
    assert store.loads == 2 and ss["daily_start_preview"]["plan"]["already_started"]
    app.confirm_daily_start(store)
    assert len(store.calls) == 1 and ss["patient_list_ready"]
    assert ss["vault"]["rooms"]["P4112"] == store.vault["rooms"]["P4112"]


def test_failed_preview_reload_cannot_leave_previous_preview_confirmable(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    store = ReadCountingStore(ss["vault"])
    app.prepare_daily_start(store)
    before = deepcopy(ss["vault"])
    store.failure = StorageError("Synthetic read failure")
    app.prepare_daily_start(store)
    app.confirm_daily_start(store)
    assert ss["vault"] == before and not store.calls
    assert not ss.get("daily_start_preview") or ss["daily_start_preview"].get("failed")
    assert not ss.get("patient_list_ready")


def test_already_started_day_opens_without_writing_or_deleting(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    ss["vault"]["settings"][START_MARKER] = "2026-11-11T10:00:00+00:00"
    before = deepcopy(ss["vault"])
    store = ReadCountingStore(before)
    app.prepare_daily_start(store)
    app.confirm_daily_start(store)
    assert not store.calls and ss["vault"] == before and ss["patient_list_ready"]


@pytest.mark.parametrize("callback", ["continue_patient_list", "prepare_daily_start", "confirm_daily_start"])
def test_startup_callbacks_reject_logged_out_session(app, monkeypatch, callback):
    ss = seeded(app, monkeypatch)
    store = ReadCountingStore(ss["vault"])
    ss["daily_start_preview"] = {"source": deepcopy(ss["vault"]), "sha": ss["vault_sha"],
                                 "plan": daily_reset_plan(ss["vault"], NOW)}
    ss["authenticated"] = False
    function = getattr(app, callback)
    function() if callback == "continue_patient_list" else function(store)
    assert not store.calls and not store.loads and not ss


def test_confirmation_rejects_expired_login(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    store = ReadCountingStore(ss["vault"])
    app.prepare_daily_start(store)
    ss["login_at"] = time.monotonic() - 9 * 3600
    app.confirm_daily_start(store)
    assert not store.calls and not ss


def test_selective_reset_reload_preserves_survivor_widgets_and_original_conflict_base(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    old = deepcopy(ss["vault"])
    ss["drafts"] = deepcopy(old["rooms"])
    ss["base_sheets"] = deepcopy(old["rooms"])
    ss["current_room"] = ss["room_choice"] = "P4108"
    ss["paste"] = "Synthetic unsubmitted paste"
    pending_key = app.edit_key(ss["drafts"]["P4108"], "Neurologic")
    ss[pending_key] = "Latest pending survivor edit"
    ss["drafts"]["UNSAVED"] = new_sheet("UNSAVED")
    ss["base_sheets"]["UNSAVED"] = None
    # A new unsaved occupant for a room with an older saved base is not the
    # same handoff as that base, even if the old saved record survives.
    ss["drafts"]["P4110"] = new_sheet("P4110")
    fresh = start_daily_list(old, NOW)
    fresh["rooms"]["P4108"]["fields"]["Respiratory"] = "Concurrent saved edit"
    fresh["rooms"]["P4108"]["updated_at"] = NOW.isoformat()
    fresh["rooms"]["P4106"] = record("P4106", NOW.isoformat())
    store = ReadCountingStore(fresh, sha="reset-sha")
    guard = app.download_revocation()
    app.reload_archive(store)
    assert ss["vault"] == fresh and ss["vault_sha"] == "reset-sha"
    assert set(ss["drafts"]) == {"P4108"}
    assert ss["drafts"]["P4108"]["fields"]["Neurologic"] == "Latest pending survivor edit"
    assert ss["base_sheets"]["P4108"] == old["rooms"]["P4108"]
    assert ss["paste"] == "Synthetic unsubmitted paste"
    assert guard.is_set() and pending_key not in ss
    assert not app.save_rooms(store, ["P4108"])
    assert not store.calls


def test_full_clear_reload_still_discards_every_local_handoff(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    ss["drafts"] = deepcopy(ss["vault"]["rooms"])
    ss["base_sheets"] = deepcopy(ss["vault"]["rooms"])
    ss["current_room"] = "P4108"
    ss["paste"] = "Synthetic paste"
    key = app.edit_key(ss["drafts"]["P4108"], "Neurologic")
    ss[key] = "Synthetic pending edit"
    store = ReadCountingStore(cleared_vault(ss["vault"]), sha="fully-cleared-sha")
    guard = app.download_revocation()
    app.reload_archive(store)
    assert not ss["vault"]["rooms"] and not ss["drafts"] and not ss["base_sheets"]
    assert not ss["paste"] and "current_room" not in ss and key not in ss
    assert guard.is_set()


def test_ordinary_reload_without_reset_keeps_existing_drafts_and_bases(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    ss["drafts"] = deepcopy(ss["vault"]["rooms"])
    ss["base_sheets"] = deepcopy(ss["vault"]["rooms"])
    ss["drafts"]["P4108"]["fields"]["Neurologic"] = "Local draft edit"
    before = {key: deepcopy(ss[key]) for key in ("drafts", "base_sheets")}
    fresh = deepcopy(ss["vault"])
    fresh["rooms"]["P4108"]["fields"]["Neurologic"] = "Remote saved edit"
    app.reload_archive(ReadCountingStore(fresh, sha="newer-sha"))
    assert all(ss[key] == value for key, value in before.items())


def test_startup_render_is_read_only_until_choice_and_ready_short_circuits(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    equip(app, monkeypatch)
    buttons = []
    app.st.button = lambda label, **kwargs: buttons.append((label, kwargs)) or False
    before = deepcopy(ss["vault"])
    store = ReadCountingStore(before)
    assert app.patient_list_startup(store) is False
    assert ss["vault"] == before and not store.calls and not store.loads
    assert any(kwargs.get("on_click") == app.prepare_daily_start for _, kwargs in buttons)
    assert any(kwargs.get("on_click") == app.continue_patient_list for _, kwargs in buttons)
    app.prepare_daily_start(store)
    buttons.clear()
    assert app.patient_list_startup(store) is False
    assert any(kwargs.get("on_click") == app.confirm_daily_start for _, kwargs in buttons)
    assert not store.calls
    app.continue_patient_list()
    buttons.clear()
    assert app.patient_list_startup(store) is True and not buttons


def test_main_shows_startup_choice_before_workspace_and_continue_opens_it(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    store = ReadCountingStore(ss["vault"])
    # Exercise the first authenticated load, before the session owns a vault.
    for key in ("vault", "vault_sha", "drafts", "base_sheets"):
        ss.pop(key, None)
    equip(app, monkeypatch)
    monkeypatch.setattr(app, "load_config", lambda: ({"idle_minutes": 15}, store))
    entered, workspace_choices, buttons = [], [], []
    monkeypatch.setattr(app, "handoff_page", lambda active_store: entered.append(active_store))
    original_radio = app.st.radio
    def radio(label, *args, **kwargs):
        workspace_choices.append(label)
        return original_radio(label, *args, **kwargs)
    app.st.radio = radio
    app.st.button = lambda label, **kwargs: buttons.append((label, kwargs)) or False
    app.main()
    assert store.loads == 1 and not store.calls
    assert not entered and not workspace_choices and not ss.get("patient_list_ready")
    assert any(kwargs.get("on_click") == app.prepare_daily_start for _, kwargs in buttons)
    continue_action = next(kwargs["on_click"] for _, kwargs in buttons
                           if kwargs.get("on_click") == app.continue_patient_list)
    continue_action()
    app.main()
    assert workspace_choices == ["Workspace"] and entered == [store]
    assert ss["patient_list_ready"] and store.loads == 1 and not store.calls


@pytest.mark.parametrize("state,expected_key,expected_callback", [
    ("pending", "daily_start_confirm", "confirm_daily_start"),
    ("failed", "daily_start_reload", "prepare_daily_start"),
    ("already_started", "daily_start_existing", "continue_patient_list"),
])
def test_preview_states_render_only_the_applicable_action_without_writes(
        app, monkeypatch, state, expected_key, expected_callback):
    ss = seeded(app, monkeypatch)
    if state == "already_started":
        ss["vault"]["settings"][START_MARKER] = "2026-11-11T10:00:00+00:00"
    ss["daily_start_preview"] = {"source": deepcopy(ss["vault"]), "sha": ss["vault_sha"],
                                 "plan": daily_reset_plan(ss["vault"], NOW)}
    if state == "failed":
        ss["daily_start_preview"]["failed"] = True
    before = {key: deepcopy(ss[key]) for key in ("vault", "daily_start_preview")}
    store = ReadCountingStore(ss["vault"])
    equip(app, monkeypatch)
    buttons = []
    app.st.button = lambda label, **kwargs: buttons.append((label, kwargs)) or False
    assert app.patient_list_startup(store) is False
    actions = {kwargs["key"]: kwargs for _, kwargs in buttons}
    assert actions[expected_key]["on_click"] == getattr(app, expected_callback)
    primary_keys = {"daily_start_confirm", "daily_start_reload", "daily_start_existing"}
    assert primary_keys.intersection(actions) == {expected_key}
    assert actions["daily_start_cancel"]["on_click"] == app.continue_patient_list
    assert not store.calls and not store.loads and not ss.get("patient_list_ready")
    assert all(ss[key] == value for key, value in before.items())
