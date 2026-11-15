"""Synthetic two-choice startup, explicit confirmation, and reset reconciliation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import time

import pytest

from daily_start import START_MARKER, start_daily_list
from difficult_airway import empty_airway
from github_store import ConflictError, StorageError
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


class SaveFailureStore(ReadCountingStore):
    """Archive reads succeed while a write can fail without a remote mutation."""
    def __init__(self, *args, write_failure=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.write_failure = write_failure

    def save(self, candidate, sha):
        if self.write_failure is not None:
            self.calls.append((deepcopy(candidate), sha))
            raise self.write_failure
        return super().save(candidate, sha)


class ConcurrentUpdateStore(ReadCountingStore):
    """A normal save changes the archive after the reset's initial read."""
    def save(self, candidate, sha):
        if not self.calls:
            self.vault["rooms"]["P4112"] = record("P4112", NOW.isoformat())
            self.sha = "concurrent-sha"
        return super().save(candidate, sha)


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
    for key in ("patient_list_ready", "daily_start_preview", "patient_list_start_attempt",
                "patient_list_start_confirmation"):
        ss.pop(key, None)
    return ss


def open_drafts(app):
    ss = app.st.session_state
    ss["drafts"] = deepcopy(ss["vault"]["rooms"])
    ss["base_sheets"] = deepcopy(ss["vault"]["rooms"])
    ss["drafts"]["P4108"]["fields"]["Neurologic"] = "Unsaved synthetic edit"
    ss["drafts"]["UNSAVED"] = new_sheet("UNSAVED")
    ss["base_sheets"]["UNSAVED"] = None
    ss["current_room"] = ss["room_choice"] = "P4108"
    ss["paste"] = "Synthetic unsubmitted paste"
    key = app.edit_key(ss["drafts"]["P4108"], "Neurologic")
    ss[key] = "Latest unsubmitted synthetic edit"
    return key


def forbid_commit(*args, **kwargs):
    raise AssertionError("This action must not write")


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("prepared", [False, True])
def test_continue_from_either_screen_preserves_handoffs_without_reading_or_writing(app, monkeypatch, shared, prepared):
    ss = seeded(app, monkeypatch)
    key = open_drafts(app)
    before = {name: deepcopy(ss[name]) for name in
              ("vault", "vault_sha", "drafts", "base_sheets", "paste", "current_room", "room_choice", key)}
    ss["daily_start_preview"] = {"sentinel": True}
    store = ReadCountingStore(ss["vault"]) if shared else None
    if prepared:
        app.prepare_rounds_handoff(store)
    loads = store.loads if store is not None else 0
    monkeypatch.setattr(app, "commit", forbid_commit)
    guard = app.download_revocation()
    app.continue_patient_list(store)
    assert ss["patient_list_ready"] is True and "daily_start_preview" not in ss
    assert "patient_list_start_confirmation" not in ss
    assert all(ss[name] == value for name, value in before.items())
    assert not guard.is_set()
    if store is not None:
        assert store.loads == loads and not store.calls


def test_prepare_reads_latest_list_and_opens_warning_without_clearing_or_saving(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    key = open_drafts(app)
    before = {name: deepcopy(ss[name]) for name in
              ("drafts", "base_sheets", "paste", "current_room", "room_choice", key)}
    ss["patient_list_start_confirmation"] = {"obsolete": True}
    fresh = deepcopy(ss["vault"])
    fresh["rooms"]["P4112"] = record("P4112", NOW.isoformat())
    store = ReadCountingStore(fresh, sha="latest-before-warning")
    guard = app.download_revocation()
    monkeypatch.setattr(app, "commit", forbid_commit)
    app.prepare_rounds_handoff(store)
    assert store.loads == 1 and not store.calls
    assert ss["vault"] == store.vault == fresh
    assert all(ss[name] == value for name, value in before.items())
    confirmation = ss["patient_list_start_confirmation"]
    assert confirmation["source"] == fresh and confirmation["source"] is not ss["vault"]
    assert confirmation["sha"] == "latest-before-warning"
    assert not ss.get("patient_list_ready") and not guard.is_set()


@pytest.mark.parametrize("shared", [False, True])
def test_unprepared_confirmation_does_nothing(app, monkeypatch, shared):
    ss = seeded(app, monkeypatch)
    key = open_drafts(app)
    before = {name: deepcopy(ss[name]) for name in
              ("vault", "vault_sha", "drafts", "base_sheets", "paste", "room_choice", key)}
    store = ReadCountingStore(ss["vault"]) if shared else None
    guard = app.download_revocation()
    app.create_rounds_handoff(store)
    assert all(ss[name] == value for name, value in before.items())
    assert not ss.get("patient_list_ready") and not guard.is_set()
    if store is not None:
        assert not store.loads and not store.calls


def test_create_reads_latest_list_and_clears_all_saved_and_open_handoffs_in_one_write(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    key = open_drafts(app)
    ss["page"] = "Print all"
    ss["daily_start_preview"] = {"obsolete": True}
    ss["print_rooms"] = ["P4108"]
    ss["removed_room"] = {"room": "OLD REMOVAL"}
    fresh = deepcopy(ss["vault"])
    fresh["rooms"]["P4112"] = record("P4112", "2026-11-12T16:00:00+00:00")
    fresh["settings"]["rooms"] += ["LATEST CUSTOM"]
    store = ReadCountingStore(fresh, sha="fresh-sha")
    guard = app.download_revocation()
    app.prepare_rounds_handoff(store)
    app.create_rounds_handoff(store)
    assert store.loads == 2 and len(store.calls) == 1
    assert store.calls[0][1] == "fresh-sha"
    assert ss["vault"] == store.vault and not ss["vault"]["rooms"]
    assert ss["vault"]["settings"] == dict(fresh["settings"], patient_list_started_at=NOW.isoformat())
    assert ss["vault"]["reset_generation"] != fresh["reset_generation"]
    assert not ss["drafts"] and not ss["base_sheets"] and not ss["paste"]
    assert ss["room_choice"] == "Choose a room" and "current_room" not in ss
    assert all(name not in ss for name in (key, "print_rooms", "removed_room", "daily_start_preview",
                                         "patient_list_start_attempt", "patient_list_start_confirmation"))
    assert guard.is_set() and not app.download_revocation().is_set()
    assert ss["patient_list_ready"] and ss["page"] == "Handoff"


@pytest.mark.parametrize("hour", [0, 4, 6, 9, 12, 19, 23])
def test_create_works_at_any_hour_even_if_a_list_was_started_that_day(app, monkeypatch, hour):
    ss = seeded(app, monkeypatch)
    ss["vault"]["settings"][START_MARKER] = "2026-11-11T05:00:00+00:00"
    clicked = NOW.replace(hour=hour)
    monkeypatch.setattr(app, "patient_list_now", lambda: clicked)
    store = ReadCountingStore(ss["vault"])
    app.prepare_rounds_handoff(store)
    app.create_rounds_handoff(store)
    assert len(store.calls) == 1 and not store.vault["rooms"]
    assert store.vault["settings"][START_MARKER] == clicked.isoformat()
    assert ss["patient_list_ready"]


def test_new_login_can_intentionally_create_another_blank_list_on_the_same_day(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    store = ReadCountingStore(ss["vault"])
    app.prepare_rounds_handoff(store)
    app.create_rounds_handoff(store)
    first_generation = store.vault["reset_generation"]
    store.vault["rooms"]["P4112"] = record("P4112", NOW.isoformat())
    store.sha = "new-patient-after-first-start"
    ss.pop("patient_list_ready")
    later = NOW + timedelta(hours=2)
    monkeypatch.setattr(app, "patient_list_now", lambda: later)
    app.prepare_rounds_handoff(store)
    app.create_rounds_handoff(store)
    assert store.loads == 4 and len(store.calls) == 2
    assert not store.vault["rooms"] and not ss["drafts"]
    assert store.vault["reset_generation"] != first_generation
    assert store.vault["settings"][START_MARKER] == later.isoformat()
    assert ss["patient_list_ready"]


def test_session_only_create_starts_blank_and_preserves_custom_room_settings(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    open_drafts(app)
    rooms = deepcopy(ss["vault"]["settings"]["rooms"])
    app.prepare_rounds_handoff(None)
    app.create_rounds_handoff(None)
    assert not ss["vault"]["rooms"] and not ss["drafts"] and not ss["base_sheets"]
    assert ss["vault"]["settings"]["rooms"] == rooms
    assert ss["patient_list_ready"] and ss["page"] == "Handoff"
    assert ss["notice"][0] == "info"


@pytest.mark.parametrize("phase", ["prepare", "confirm"])
def test_failed_load_never_writes_or_discards_open_work(app, monkeypatch, phase):
    ss = seeded(app, monkeypatch)
    key = open_drafts(app)
    before = {name: deepcopy(ss[name]) for name in
              ("vault", "vault_sha", "drafts", "base_sheets", "paste", "room_choice", key)}
    store = ReadCountingStore(ss["vault"])
    if phase == "confirm":
        app.prepare_rounds_handoff(store)
    else:
        ss["patient_list_start_confirmation"] = {"obsolete": True}
    store.failure = StorageError("Synthetic read failure")
    guard = app.download_revocation()
    if phase == "prepare":
        app.prepare_rounds_handoff(store)
        assert "patient_list_start_confirmation" not in ss
        app.create_rounds_handoff(store)
    else:
        app.create_rounds_handoff(store)
    assert store.loads == (1 if phase == "prepare" else 2) and not store.calls
    assert all(ss[name] == value for name, value in before.items())
    assert not ss.get("patient_list_ready") and not guard.is_set()
    assert ss["notice"][0] == "error"


@pytest.mark.parametrize("failure", [
    StorageError("Synthetic write failure"),
    ConflictError("Synthetic stale version"),
    RuntimeError("Synthetic unexpected failure"),
])
def test_failed_save_keeps_open_work_and_records_attempt_without_automatic_retry(app, monkeypatch, failure):
    ss = seeded(app, monkeypatch)
    key = open_drafts(app)
    before = {name: deepcopy(ss[name]) for name in
              ("vault", "vault_sha", "drafts", "base_sheets", "paste", "room_choice", key)}
    store = SaveFailureStore(ss["vault"], write_failure=failure)
    guard = app.download_revocation()
    app.prepare_rounds_handoff(store)
    app.create_rounds_handoff(store)
    assert store.loads == 2 and len(store.calls) == 1
    assert all(ss[name] == value for name, value in before.items())
    assert store.vault == before["vault"]
    assert not ss.get("patient_list_ready") and not guard.is_set()
    attempt = ss["patient_list_start_attempt"]
    assert attempt["source_generation"] == before["vault"]["reset_generation"]
    assert attempt["target_generation"] == store.calls[0][0]["reset_generation"]
    assert attempt["target_generation"] != attempt["source_generation"]


def test_explicit_retry_can_clear_when_failed_write_did_not_change_generation(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    store = SaveFailureStore(ss["vault"], write_failure=StorageError("Offline"))
    app.prepare_rounds_handoff(store)
    app.create_rounds_handoff(store)
    assert len(store.calls) == 1 and not ss.get("patient_list_ready")
    store.write_failure = None
    app.create_rounds_handoff(store)
    assert store.loads == 3 and len(store.calls) == 2
    assert not store.vault["rooms"] and ss["patient_list_ready"]
    assert "patient_list_start_attempt" not in ss


def test_concurrent_normal_save_requires_refreshed_warning_before_retry_can_clear(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    before = deepcopy(ss["vault"])
    store = ConcurrentUpdateStore(before)
    app.prepare_rounds_handoff(store)
    app.create_rounds_handoff(store)
    assert store.loads == 2 and len(store.calls) == 1
    assert ss["vault"] == before and not ss.get("patient_list_ready")
    assert "P4112" in store.vault["rooms"]
    app.create_rounds_handoff(store)
    assert store.loads == 3 and len(store.calls) == 1
    assert "P4112" in store.vault["rooms"] and not ss.get("patient_list_ready")
    assert ss["patient_list_start_confirmation"]["sha"] == "concurrent-sha"
    app.create_rounds_handoff(store)
    assert store.loads == 4 and len(store.calls) == 2
    assert store.calls[1][1] == "concurrent-sha"
    assert not store.vault["rooms"] and ss["patient_list_ready"]


def test_lost_acknowledgement_retry_preserves_patients_added_after_completed_reset(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    open_drafts(app)
    before = deepcopy(ss["vault"])
    store = LostAcknowledgementStore(before)
    app.prepare_rounds_handoff(store)
    app.create_rounds_handoff(store)
    assert ss["vault"] == before and len(store.calls) == 1
    assert not store.vault["rooms"] and not ss.get("patient_list_ready")
    assert ss["patient_list_start_attempt"]["target_generation"] == store.vault["reset_generation"]
    added = record("P4112", NOW.isoformat())
    store.vault["rooms"]["P4112"] = added
    store.sha = "post-reset-addition"
    app.create_rounds_handoff(store)
    assert store.loads == 3 and len(store.calls) == 1
    assert ss["vault"] == store.vault and ss["vault"]["rooms"] == {"P4112": added}
    assert not ss["drafts"] and not ss["base_sheets"] and not ss["paste"]
    assert ss["patient_list_ready"] and "patient_list_start_attempt" not in ss


def test_retry_after_another_session_reset_opens_refreshed_list_without_clearing_again(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    store = SaveFailureStore(ss["vault"], write_failure=StorageError("Unconfirmed"))
    app.prepare_rounds_handoff(store)
    app.create_rounds_handoff(store)
    attempted_generation = ss["patient_list_start_attempt"]["target_generation"]
    store.vault = start_daily_list(store.vault, NOW)
    assert store.vault["reset_generation"] != attempted_generation
    added = record("P4112", NOW.isoformat())
    store.vault["rooms"]["P4112"] = added
    store.sha = "another-session-reset"
    store.write_failure = None
    app.create_rounds_handoff(store)
    assert store.loads == 3 and len(store.calls) == 1
    assert ss["vault"]["rooms"] == {"P4112": added} and ss["patient_list_ready"]


@pytest.mark.parametrize("remote_reset", [False, True])
def test_continue_after_unconfirmed_start_reloads_read_only_before_opening(app, monkeypatch, remote_reset):
    ss = seeded(app, monkeypatch)
    open_drafts(app)
    store = SaveFailureStore(ss["vault"], write_failure=StorageError("Unconfirmed"))
    app.prepare_rounds_handoff(store)
    app.create_rounds_handoff(store)
    before_drafts = deepcopy(ss["drafts"])
    if remote_reset:
        store.vault = start_daily_list(store.vault, NOW)
    store.vault["rooms"]["P4112"] = record("P4112", NOW.isoformat())
    store.sha = "newer-current-list"
    app.continue_patient_list(store)
    assert store.loads == 3 and len(store.calls) == 1
    assert ss["vault"] == store.vault and "P4112" in ss["vault"]["rooms"]
    assert ss["patient_list_ready"] and "patient_list_start_attempt" not in ss
    assert ss["drafts"] == ({} if remote_reset else before_drafts)


def test_continue_after_unconfirmed_start_blocks_when_read_fails(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    key = open_drafts(app)
    store = SaveFailureStore(ss["vault"], write_failure=StorageError("Unconfirmed"))
    app.prepare_rounds_handoff(store)
    app.create_rounds_handoff(store)
    before = {name: deepcopy(ss[name]) for name in
              ("vault", "drafts", "base_sheets", "paste", key, "patient_list_start_attempt")}
    store.failure = StorageError("Read unavailable")
    app.continue_patient_list(store)
    assert store.loads == 3 and len(store.calls) == 1
    assert all(ss[name] == value for name, value in before.items())
    assert not ss.get("patient_list_ready")


@pytest.mark.parametrize("change", ["sha", "added_patient", "edited_patient"])
def test_stale_confirmation_refreshes_warning_without_deleting_new_information(app, monkeypatch, change):
    ss = seeded(app, monkeypatch)
    key = open_drafts(app)
    store = ReadCountingStore(ss["vault"])
    app.prepare_rounds_handoff(store)
    before = {name: deepcopy(ss[name]) for name in
              ("drafts", "base_sheets", "paste", "current_room", "room_choice", key)}
    if change == "sha":
        store.sha = "changed-sha-same-content"
    elif change == "added_patient":
        store.vault["rooms"]["P4112"] = record("P4112", NOW.isoformat())
    else:
        store.vault["rooms"]["P4102"]["fields"]["Neurologic"] = "Newly saved clinical information"
    latest = deepcopy(store.vault)
    guard = app.download_revocation()
    app.create_rounds_handoff(store)
    assert store.loads == 2 and not store.calls
    assert store.vault == ss["vault"] == latest
    assert all(ss[name] == value for name, value in before.items())
    assert not ss.get("patient_list_ready") and not guard.is_set()
    confirmation = ss["patient_list_start_confirmation"]
    assert confirmation["source"] == latest and confirmation["source"] is not ss["vault"]
    assert confirmation["sha"] == store.sha
    assert ss["notice"][0] == "warning"
    app.create_rounds_handoff(store)
    assert store.loads == 3 and len(store.calls) == 1
    assert not store.vault["rooms"] and ss["patient_list_ready"]


@pytest.mark.parametrize("callback", ["continue_patient_list", "prepare_rounds_handoff", "create_rounds_handoff"])
@pytest.mark.parametrize("session", ["logged_out", "idle_expired", "login_expired"])
def test_startup_callbacks_reject_invalid_sessions_before_read_or_write(app, monkeypatch, callback, session):
    ss = seeded(app, monkeypatch)
    store = ReadCountingStore(ss["vault"])
    ss["patient_list_start_confirmation"] = {"source": deepcopy(ss["vault"]), "sha": ss["vault_sha"]}
    if session == "logged_out":
        ss["authenticated"] = False
    elif session == "idle_expired":
        ss["last_activity"] = time.monotonic() - 1000
    else:
        ss["login_at"] = time.monotonic() - 9 * 3600
    getattr(app, callback)(store)
    assert not store.calls and not store.loads and not ss


def test_reset_reload_preserves_survivor_widgets_and_original_conflict_base(app, monkeypatch):
    """Older selective resets and unchanged record identities remain compatible."""
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
    ss["drafts"]["P4110"] = new_sheet("P4110")
    fresh = start_daily_list(old, NOW)
    fresh["rooms"] = {room: deepcopy(old["rooms"][room]) for room in ("P4106", "P4108", "P4110")}
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
    key = open_drafts(app)
    store = ReadCountingStore(cleared_vault(ss["vault"]), sha="fully-cleared-sha")
    guard = app.download_revocation()
    app.reload_archive(store)
    assert not ss["vault"]["rooms"] and not ss["drafts"] and not ss["base_sheets"]
    assert not ss["paste"] and "current_room" not in ss and key not in ss
    assert guard.is_set()


def test_ordinary_reload_without_reset_keeps_existing_drafts_and_bases(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    open_drafts(app)
    before = {key: deepcopy(ss[key]) for key in ("drafts", "base_sheets")}
    fresh = deepcopy(ss["vault"])
    fresh["rooms"]["P4108"]["fields"]["Neurologic"] = "Remote saved edit"
    app.reload_archive(ReadCountingStore(fresh, sha="newer-sha"))
    assert all(ss[key] == value for key, value in before.items())


@pytest.mark.parametrize("obsolete_preview", [None, {"failed": True}, {"plan": {"already_started": True}}])
def test_startup_renders_exactly_two_choices_without_reading_or_writing(app, monkeypatch, obsolete_preview):
    ss = seeded(app, monkeypatch)
    if obsolete_preview is not None:
        ss["daily_start_preview"] = obsolete_preview
    equip(app, monkeypatch)
    buttons, captions = [], []
    app.st.button = lambda label, **kwargs: buttons.append((label, kwargs)) or False
    app.st.caption = lambda text, **kwargs: captions.append(text)
    before = deepcopy(ss["vault"])
    store = ReadCountingStore(before)
    assert app.patient_list_startup(store) is False
    assert ss["vault"] == before and not store.calls and not store.loads
    actions = {kwargs.get("key"): (label, kwargs) for label, kwargs in buttons}
    create_label, create_opts = actions["patient_list_create"]
    keep_label, keep_opts = actions["patient_list_continue"]
    assert create_label == "START HERE: Create an Updated Handoff"
    assert keep_label == "Add a Patient or Print Current List"
    assert create_opts["on_click"] == app.prepare_rounds_handoff
    assert keep_opts["on_click"] == app.continue_patient_list
    assert create_opts["args"] == keep_opts["args"] == (store,)
    assert len(buttons) == 3 and sum(label == "Log out" for label, _ in buttons) == 1
    assert not any(term in " ".join(captions) for term in ("5:00", "8:30", "already started"))
    app.continue_patient_list(store)
    buttons.clear()
    assert app.patient_list_startup(store) is True and not buttons


def test_warning_render_requires_move_forward_and_never_deletes_on_repeated_render(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    open_drafts(app)
    store = ReadCountingStore(ss["vault"])
    app.prepare_rounds_handoff(store)
    equip(app, monkeypatch)
    buttons, texts = [], []
    app.st.button = lambda label, **kwargs: buttons.append((label, kwargs)) or False
    for name in ("warning", "caption", "subheader", "markdown", "text", "info"):
        setattr(app.st, name, lambda text, **kwargs: texts.append(str(text)))
    before = {name: deepcopy(ss[name]) for name in
              ("vault", "drafts", "base_sheets", "paste", "patient_list_start_confirmation")}
    guard = app.download_revocation()
    for _ in range(2):
        buttons.clear()
        assert app.patient_list_startup(store) is False
        actions = {kwargs.get("key"): (label, kwargs) for label, kwargs in buttons}
        assert "patient_list_create" not in actions
        confirm_label, confirm_opts = actions["patient_list_confirm"]
        keep_label, keep_opts = actions["patient_list_continue"]
        assert confirm_label == "Move Forward and Delete Previous Handoffs"
        assert confirm_opts["on_click"] == app.create_rounds_handoff and confirm_opts["args"] == (store,)
        assert keep_label == "Add a Patient or Print Current List"
        assert keep_opts["on_click"] == app.continue_patient_list and keep_opts["args"] == (store,)
        assert len(buttons) == 3 and sum(label == "Log out" for label, _ in buttons) == 1
        assert all(ss[name] == value for name, value in before.items())
        assert store.loads == 1 and not store.calls and not guard.is_set()
    visible_text = " ".join(texts)
    assert "ALL" in visible_text and "deleted" in visible_text.lower()
    assert "Add a Patient or Print Current List" in visible_text


def test_prepare_does_not_reopen_warning_after_workspace_is_ready(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    store = ReadCountingStore(ss["vault"])
    app.continue_patient_list(store)
    before = deepcopy(ss["vault"])
    app.prepare_rounds_handoff(store)
    assert ss["vault"] == before and not store.loads and not store.calls
    assert ss["patient_list_ready"] and "patient_list_start_confirmation" not in ss


def test_main_shows_startup_choice_before_workspace_and_continue_opens_it(app, monkeypatch):
    ss = seeded(app, monkeypatch)
    store = ReadCountingStore(ss["vault"])
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
    assert any(kwargs.get("on_click") == app.prepare_rounds_handoff for _, kwargs in buttons)
    continue_options = next(kwargs for _, kwargs in buttons
                            if kwargs.get("on_click") == app.continue_patient_list)
    continue_options["on_click"](*continue_options["args"])
    app.main()
    assert workspace_choices == ["Workspace"] and entered == [store]
    assert ss["patient_list_ready"] and store.loads == 1 and not store.calls
