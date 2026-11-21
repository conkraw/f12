"""Synthetic Home callback and sidebar checks, including widget cleanup."""
from copy import deepcopy
import json

import pytest

from github_store import ConflictError, StorageError
from medications import parse_medications
from models import new_sheet, new_vault
from test_callbacks import app
from test_ui_smoke import equip


PASTE = "UNIMPORTED_SYNTHETIC_HOME_PASTE"
SAVED_AT = "2026-01-02T03:04:00+00:00"


class Store:
    def __init__(self, vault, failure=None, fail_on=1):
        self.vault = deepcopy(vault)
        self.sha = "original-sha"
        self.calls = []
        self.loads = 0
        self.failure = failure
        self.fail_on = fail_on

    def save(self, candidate, sha):
        self.calls.append((deepcopy(candidate), sha))
        if self.failure is not None and len(self.calls) == self.fail_on:
            raise self.failure
        if sha != self.sha:
            raise ConflictError("Synthetic archive changed")
        self.vault = deepcopy(candidate)
        self.sha = "saved-sha-" + str(len(self.calls))
        return self.sha

    def load(self):
        self.loads += 1
        return deepcopy(self.vault), self.sha


def populated(app, rooms=("P4102", "P4104")):
    vault = new_vault()
    for room in rooms:
        sheet = new_sheet(room)
        sheet["updated_at"] = SAVED_AT
        sheet["fields"]["Diagnoses"] = "Synthetic saved " + room
        vault["rooms"][room] = sheet
    ss = app.st.session_state
    ss.update(vault=vault, vault_sha="original-sha", drafts=deepcopy(vault["rooms"]),
              base_sheets=deepcopy(vault["rooms"]), patient_list_ready=True,
              page="Handoff", active_workspace="Handoff", paste=PASTE,
              handoff_tab="Edit handoff", handoff_active_tab="Edit handoff")
    if rooms:
        ss.update(current_room=rooms[0], room_choice=rooms[0])
    return ss


def pending_field(app, text="Synthetic just-blurred note"):
    ss = app.st.session_state
    sheet = ss["drafts"][ss["current_room"]]
    key = app.edit_key(sheet, "Respiratory")
    ss[key] = text
    return key


def must_not_run(*args, **kwargs):
    raise AssertionError("Home must not clear the census, log out, or prepare PDFs")


def test_home_saves_all_open_work_and_returns_to_start_without_logout(app, monkeypatch):
    ss = populated(app, ("P4102", "P4104", "P4106"))
    key = pending_field(app)
    ss["drafts"]["P4104"]["fields"]["Other"] = "Synthetic other open draft"
    new = new_sheet("P4112")
    new["fields"]["Other"] = "Synthetic unsaved new handoff"
    ss["drafts"]["P4112"] = new
    ss["base_sheets"]["P4112"] = None
    ss.update(page="Admin", active_workspace="Admin", daily_start_preview={"old": True},
              patient_list_start_attempt={"old": True},
              patient_list_start_confirmation={"old": True})
    clean = deepcopy(ss["vault"]["rooms"]["P4106"])
    settings = deepcopy(ss["vault"]["settings"])
    login_at = ss["login_at"]
    store = Store(ss["vault"])
    for name in ("warm_handoff_pdf", "clear_all_handoffs", "discard_all_handoff_state", "clear_session"):
        monkeypatch.setattr(app, name, must_not_run)

    assert app.return_home(store) is True

    assert set(store.vault["rooms"]) == {"P4102", "P4104", "P4106", "P4112"}
    assert store.vault["rooms"]["P4102"]["fields"]["Respiratory"] == "Synthetic just-blurred note"
    assert store.vault["rooms"]["P4104"]["fields"]["Other"] == "Synthetic other open draft"
    assert store.vault["rooms"]["P4112"]["fields"]["Other"] == "Synthetic unsaved new handoff"
    assert store.vault["rooms"]["P4106"] == clean
    assert ss["drafts"] == ss["base_sheets"] == store.vault["rooms"]
    assert ss["vault"] == store.vault
    assert ss["vault"]["settings"] == settings
    assert ss["patient_list_ready"] is False
    assert ss["page"] == ss["active_workspace"] == "Handoff"
    assert ss["handoff_tab"] == ss["handoff_active_tab"] == "Preview / print"
    assert ss["current_room"] == ss["room_choice"] == "P4102"
    assert ss["paste"] == PASTE
    assert ss["home_resume_state"]["paste"] == PASTE
    assert PASTE not in json.dumps(store.vault)
    assert all(PASTE not in json.dumps(candidate) for candidate, _ in store.calls)
    assert ss["authenticated"] is True and ss["login_at"] == login_at
    assert not any(name in ss for name in ("admin_unlocked", "admin_grant_hash", "admin_login_at", "admin_last_activity"))
    assert not any(name in ss for name in ("daily_start_preview", "patient_list_start_attempt", "patient_list_start_confirmation"))
    assert key not in ss
    assert ss["notice"][0] == "success"


def test_home_remembers_pending_medication_mapping(app):
    ss = populated(app, ("P4102",))
    source = "Medications:\n• synthetic example tablet\t2 mg\tOral\tDaily"
    rows = parse_medications(source).rows
    assert len(rows) == 1
    for place in (ss["vault"]["rooms"], ss["drafts"], ss["base_sheets"]):
        place["P4102"]["medications"] = deepcopy(rows)
    ss["med_draft_" + rows[0]["id"] + "_section"] = "Neurologic"
    store = Store(ss["vault"])

    assert app.return_home(store) is True

    assert store.vault["rooms"]["P4102"]["medications"][0]["section"] == "Neurologic"
    rules = store.vault["settings"]["medication_mappings"]
    assert parse_medications(source, rules).rows[0]["section"] == "Neurologic"
    assert ss["drafts"]["P4102"]["medications"][0]["section"] == "Neurologic"


@pytest.mark.parametrize("rooms", [(), ("P4102",)])
def test_home_with_no_changes_needs_no_archive_write(app, rooms):
    ss = populated(app, rooms)
    before = deepcopy(ss["vault"])
    store = Store(before)

    assert app.return_home(store) is True

    assert store.calls == []
    assert ss["vault"] == before
    assert ss["drafts"] == before["rooms"]
    assert ss["patient_list_ready"] is False
    assert ss["authenticated"] is True


def test_home_without_shared_storage_keeps_saved_work_in_session(app):
    ss = populated(app, ("P4102",))
    pending_field(app)

    assert app.return_home() is True

    assert ss["vault"]["rooms"]["P4102"]["fields"]["Respiratory"] == "Synthetic just-blurred note"
    assert ss["notice"][0] == "info"
    assert "session" in ss["notice"][1]
    assert "Shared storage is not enabled" in ss["notice"][1]
    assert ss["authenticated"] is True


@pytest.mark.parametrize("failure", [StorageError("Synthetic offline"),
                                     ConflictError("Synthetic remote conflict"),
                                     RuntimeError("Synthetic unexpected failure")])
def test_failed_home_save_keeps_current_workspace_and_pending_values(app, failure):
    ss = populated(app)
    key = pending_field(app)
    keep = {name: deepcopy(ss[name]) for name in
            ("vault", "drafts", "base_sheets", "paste", "current_room", "room_choice",
             "page", "active_workspace", "handoff_tab", "handoff_active_tab")}
    store = Store(ss["vault"], failure=failure)

    assert app.return_home(store) is False

    assert all(ss[name] == value for name, value in keep.items())
    assert store.vault == keep["vault"]
    assert ss[key] == "Synthetic just-blurred note"
    assert ss["patient_list_ready"] is True
    assert ss["authenticated"] is True and ss["admin_unlocked"] is True
    assert ss["notice"][0] == "error"
    assert "home_resume_state" not in ss


def test_local_current_room_conflict_blocks_home_without_overwrite(app):
    ss = populated(app)
    key = pending_field(app)
    ss["vault"]["rooms"]["P4102"]["fields"]["Other"] = "Synthetic newer saved edit"
    store = Store(ss["vault"])
    draft = deepcopy(ss["drafts"]["P4102"])

    assert app.return_home(store) is False

    assert store.calls == []
    assert ss["vault"]["rooms"]["P4102"]["fields"]["Other"] == "Synthetic newer saved edit"
    assert ss["drafts"]["P4102"] == draft
    assert ss[key] == "Synthetic just-blurred note"
    assert ss["patient_list_ready"] is True and ss["paste"] == PASTE
    assert ss["notice"][0] == "error"


@pytest.mark.parametrize("later_failure", ["storage", "local_conflict"])
def test_later_room_failure_blocks_navigation_and_keeps_remaining_work(app, later_failure):
    ss = populated(app)
    key = pending_field(app)
    ss["drafts"]["P4104"]["fields"]["Other"] = "Synthetic pending second room"
    if later_failure == "local_conflict":
        ss["vault"]["rooms"]["P4104"]["fields"]["Diagnoses"] = "Synthetic concurrent second room"
    store = Store(ss["vault"], failure=StorageError("Synthetic second write failed")
                  if later_failure == "storage" else None, fail_on=2)
    second_saved = deepcopy(store.vault["rooms"]["P4104"])

    assert app.return_home(store) is False

    assert store.vault["rooms"]["P4102"]["fields"]["Respiratory"] == "Synthetic just-blurred note"
    assert store.vault["rooms"]["P4104"] == second_saved
    assert ss["drafts"]["P4104"]["fields"]["Other"] == "Synthetic pending second room"
    assert ss[key] == "Synthetic just-blurred note"
    assert ss["paste"] == PASTE
    assert ss["current_room"] == ss["room_choice"] == "P4102"
    assert ss["patient_list_ready"] is True
    assert ss["page"] == ss["active_workspace"] == "Handoff"
    assert ss["notice"][0] == "error"
    assert "All handoff changes are saved" not in ss["notice"][1]
    assert "home_resume_state" not in ss


@pytest.mark.parametrize("invalid_room", ["P4102", "P4104"])
def test_invalid_edit_blocks_home_and_stays_available_to_correct(app, invalid_room):
    ss = populated(app)
    invalid = "x" * (app.MAX_FIELD + 1)
    if invalid_room == "P4102":
        key = pending_field(app, invalid)
    else:
        ss["drafts"][invalid_room]["fields"]["Respiratory"] = invalid
    before = deepcopy(ss["vault"])
    store = Store(before)

    assert app.return_home(store) is False

    assert store.calls == [] and ss["vault"] == before
    if invalid_room == "P4102":
        assert ss[key] == invalid
    else:
        assert ss["drafts"][invalid_room]["fields"]["Respiratory"] == invalid
    assert ss["patient_list_ready"] is True and ss["paste"] == PASTE
    assert ss["notice"][0] == "error"


def test_home_restores_original_two_choices_and_continue_after_widget_cleanup(app, monkeypatch):
    ss = populated(app)
    pending_field(app)
    store = Store(ss["vault"])
    assert app.return_home(store) is True
    saved = deepcopy(store.vault)
    writes = len(store.calls)
    equip(app, monkeypatch)
    buttons = []
    app.st.button = lambda label, **kwargs: buttons.append((label, kwargs)) or False

    assert app.patient_list_startup(store) is False

    by_key = {kwargs.get("key"): (label, kwargs) for label, kwargs in buttons}
    assert set(by_key) == {"patient_list_create", "patient_list_continue", "patient_list_logout"}
    assert by_key["patient_list_create"][1]["on_click"] is app.prepare_rounds_handoff
    assert by_key["patient_list_continue"][1]["on_click"] is app.continue_patient_list
    assert by_key["patient_list_continue"][1]["args"] == (store,)
    assert len(store.calls) == writes and store.vault == saved

    # Streamlit removes keys for widgets hidden by the start screen.
    ss.pop("paste")
    ss.pop("room_choice")
    app.continue_patient_list(store)

    assert ss["patient_list_ready"] is True
    assert ss["current_room"] == ss["room_choice"] == "P4102"
    assert ss["paste"] == PASTE
    assert ss["drafts"]["P4102"] == saved["rooms"]["P4102"]
    assert ss["vault"] == saved and len(store.calls) == writes
    assert store.loads == 0
    assert ss["authenticated"] is True
    assert "home_resume_state" not in ss
    assert PASTE not in json.dumps(store.vault)


@pytest.mark.parametrize("changed_identity", ["saved", "draft", "both"])
def test_continue_never_restores_old_paste_to_a_different_patient(app, changed_identity):
    ss = populated(app, ("P4102",))
    assert app.return_home() is True
    replacement = new_sheet("P4102")
    if changed_identity in ("saved", "both"):
        ss["vault"]["rooms"]["P4102"] = deepcopy(replacement)
    if changed_identity in ("draft", "both"):
        ss["drafts"]["P4102"] = deepcopy(replacement)
    ss.pop("paste")
    ss.pop("room_choice")

    app.continue_patient_list()

    assert ss["patient_list_ready"] is True
    assert ss.get("paste", "") != PASTE
    assert "home_resume_state" not in ss


def test_only_existing_explicit_confirmation_clears_list_after_home(app):
    ss = populated(app)
    pending_field(app)
    store = Store(ss["vault"])
    assert app.return_home(store) is True
    saved = deepcopy(store.vault)
    writes = len(store.calls)
    settings = deepcopy(saved["settings"])

    app.create_rounds_handoff(store)
    assert store.vault == saved and len(store.calls) == writes
    app.prepare_rounds_handoff(store)
    assert store.vault == saved and len(store.calls) == writes
    assert ss["patient_list_start_confirmation"]["source"] == saved
    assert ss["home_resume_state"]["paste"] == PASTE

    app.create_rounds_handoff(store)

    assert len(store.calls) == writes + 1
    assert ss["vault"]["rooms"] == ss["drafts"] == ss["base_sheets"] == {}
    assert store.vault["rooms"] == {}
    assert ss["paste"] == "" and ss["room_choice"] == "Choose a room"
    assert "home_resume_state" not in ss
    assert ss["authenticated"] is True and ss["patient_list_ready"] is True
    assert all(ss["vault"]["settings"][name] == value for name, value in settings.items())


def test_home_is_first_sidebar_control_and_uses_save_callback(app, monkeypatch):
    ss = populated(app)
    store = Store(ss["vault"])
    equip(app, monkeypatch)
    events = []
    sidebar_open = False

    class Sidebar:
        def __enter__(self):
            nonlocal sidebar_open
            sidebar_open = True
            return self

        def __exit__(self, *args):
            nonlocal sidebar_open
            sidebar_open = False

    app.st.sidebar = Sidebar()

    def button(label, **kwargs):
        if sidebar_open:
            events.append(("button", label, kwargs))
        return False

    def header(label, **kwargs):
        if sidebar_open:
            events.append(("header", label, kwargs))

    app.st.button = button
    app.st.header = header
    monkeypatch.setattr(app, "load_config", lambda: ({"idle_minutes": 15, "password_hash": "synthetic"}, store))
    monkeypatch.setattr(app, "idle_guard", lambda minutes: None)
    monkeypatch.setattr(app, "respiratory_parser_ready", lambda: True)
    monkeypatch.setattr(app, "handoff_page", lambda store: None)

    app.main()

    assert events[0][:2] == ("button", "Home")
    options = events[0][2]
    assert options["key"] == "home_screen"
    assert options["on_click"] is app.return_home
    assert options["args"] == (store,)
    assert options["use_container_width"] is True
    assert events[1][:2] == ("header", "PICU Handoff")
    assert store.calls == [] and ss["patient_list_ready"] is True
