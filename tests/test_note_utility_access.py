"""Admin, revocation, and existing-handoff boundaries for the note utility."""
from copy import deepcopy
from threading import Event
import time
from types import SimpleNamespace

import pytest

from admin_access import lock_admin
from models import new_sheet
from note_utility import (
    DRAFT_KEY, EDITOR_KEY, PREFIX, REVOKE_KEY,
    create_note_draft, note_download, note_sources,
)
from test_callbacks import app, open_room, TEST_ADMIN_CONFIG


def generated(sheet, **kwargs):
    return {"text": "Synthetic review note", "suggestions": [], "warnings": [],
            "note_type": kwargs.get("note_type", "progress")}


def rendered(result, *, note_type="progress"):
    return b"PK\x03\x04Synthetic Word note"


def seeded_draft(app, payload_kind="word"):
    open_room(app)
    ss = app.st.session_state
    sheet = ss["drafts"]["P4102"]
    sheet["fields"]["Diagnoses"] = "Synthetic handoff"
    assert create_note_draft(ss, sheet, authorize=app.require_admin,
                             settings={}, generator=generated, word_renderer=rendered)
    payload = ss[DRAFT_KEY]["word_bytes"] if payload_kind == "word" else ss[EDITOR_KEY]
    handle = app.utility_note_download(payload, ss[DRAFT_KEY], None)
    assert handle() == (rendered({}) if payload_kind == "word" else b"Synthetic review note")
    return ss, sheet, ss[REVOKE_KEY], handle


def test_generation_action_checks_access_before_importing_engine_or_touching_handoff():
    sheet = new_sheet("P4102")
    before = deepcopy(sheet)
    guard = Event()
    state = {DRAFT_KEY: {"old": True}, EDITOR_KEY: "Synthetic old draft",
             REVOKE_KEY: guard, "handoff_field": "Synthetic retained handoff"}
    calls = []
    assert create_note_draft(state, sheet, authorize=lambda: False, settings={},
                             generator=lambda *a, **k: calls.append("engine"),
                             word_renderer=lambda *a, **k: calls.append("word")) is False
    assert not calls
    assert guard.is_set()
    assert DRAFT_KEY not in state and EDITOR_KEY not in state
    assert state["handoff_field"] == "Synthetic retained handoff"
    assert sheet == before


def test_generation_uses_a_copy_and_keeps_patient_note_out_of_vault(app):
    open_room(app)
    ss = app.st.session_state
    before = deepcopy(ss["vault"])
    sheet = ss["drafts"]["P4102"]
    original = deepcopy(sheet)

    def mutating_generator(value, **kwargs):
        value["fields"]["Diagnoses"] = "Synthetic generator mutation"
        return generated(value)

    assert create_note_draft(ss, sheet, authorize=app.require_admin,
                             settings={}, generator=mutating_generator, word_renderer=rendered)
    assert sheet == original
    assert ss["vault"] == before
    assert ss[EDITOR_KEY] == "Synthetic review note"
    assert ss[DRAFT_KEY]["word_bytes"] == rendered({})


@pytest.mark.parametrize("action", ["lock", "logout", "home", "reset", "leave"])
@pytest.mark.parametrize("payload_kind", ["word", "text"])
def test_existing_note_download_is_revoked_by_session_and_navigation_actions(app, action, payload_kind):
    ss, sheet, guard, handle = seeded_draft(app, payload_kind)
    if action == "lock":
        app.lock_admin_page()
    elif action == "logout":
        app.clear_session()
    elif action == "home":
        ss["patient_list_ready"] = True
        assert app.return_home(None)
        assert ss["vault"]["rooms"][sheet["room"]]["id"] == sheet["id"]
    elif action == "reset":
        app.clear_all_handoffs(None)
        assert ss["vault"]["rooms"] == {}
    else:
        ss["page"] = "Handoff"
        ss["active_workspace"] = "Utilities"
        app.workspace_changed(None)
    assert guard.is_set()
    assert not any(key.startswith(PREFIX) for key in ss)
    with pytest.raises(ValueError, match="expired"):
        handle()


@pytest.mark.parametrize("expiration", ["app_idle", "admin_idle", "admin_absolute"])
@pytest.mark.parametrize("payload_kind", ["word", "text"])
def test_expiration_revokes_existing_note_and_blocks_new_utility_calls(app, expiration, payload_kind):
    ss, _, guard, handle = seeded_draft(app, payload_kind)
    now = time.monotonic()
    if expiration == "app_idle":
        ss["last_activity"] = now - 1000
    elif expiration == "admin_idle":
        ss["admin_last_activity"] = now - 1000
    else:
        ss["admin_login_at"] = now - 4000
    assert app.require_admin() is False
    assert guard.is_set()
    with pytest.raises(ValueError, match="expired"):
        handle()
    assert DRAFT_KEY not in ss


@pytest.mark.parametrize('payload_kind', ['word','text'])
def test_username_config_change_revokes_note_and_prepared_download(app,payload_kind):
    ss, _, guard, handle=seeded_draft(app,payload_kind)
    config={**TEST_ADMIN_CONFIG,'admin_username':'replacement-admin'}
    app.st.secrets=SimpleNamespace(to_dict=lambda:{'app':config})
    assert app.require_admin() is False
    assert guard.is_set()
    assert not any(key.startswith(PREFIX) for key in ss)
    with pytest.raises(ValueError,match='expired'):
        handle()


def test_locked_settings_callback_cannot_write_and_routine_handoff_still_saves(app):
    ss, sheet, guard, handle = seeded_draft(app)
    lock_admin(ss)
    original = deepcopy(ss["vault"])
    with pytest.raises(ValueError, match="Unlock Admin"):
        app.save_note_utility_settings({"phrase_style": "dot"}, None)
    assert ss["vault"] == original
    with pytest.raises(ValueError, match="Unlock Admin"):
        app.utility_note_download(b"PK\x03\x04Synthetic forged note", {"room": sheet["room"]}, None)
    sheet["fields"]["Neurologic"] = "Synthetic normal handoff edit"
    app.save_room(None)
    assert ss["vault"]["rooms"][sheet["room"]]["fields"]["Neurologic"] == "Synthetic normal handoff edit"
    assert guard.is_set()


def test_changed_current_handoff_cannot_issue_new_download(app):
    ss, sheet, _, _ = seeded_draft(app)
    draft = ss[DRAFT_KEY]
    sheet["fields"]["Respiratory"] = "Synthetic changed support"
    with pytest.raises(ValueError, match="handoff changed"):
        app.utility_note_download(draft["word_bytes"], draft, None)


@pytest.mark.parametrize("payload", ["Synthetic note", b"PK\x03\x04Synthetic note"])
def test_note_download_expiry_and_storage_failure_are_fail_closed(payload):
    expired = note_download(payload, revoked=Event(),
                            expires_at=time.monotonic() - 1)
    with pytest.raises(ValueError, match="expired"):
        expired()

    def changed():
        raise ValueError("Synthetic census changed")

    blocked = note_download(payload, revoked=Event(),
                            expires_at=time.monotonic() + 1000,
                            check_current=changed)
    with pytest.raises(ValueError, match="census changed"):
        blocked()


def test_note_sources_uses_current_drafts_and_omits_empty_handoffs():
    saved = new_sheet("P4102")
    saved["fields"]["Diagnoses"] = "Synthetic saved diagnosis"
    edited = deepcopy(saved)
    edited["fields"]["Diagnoses"] = "Synthetic current diagnosis"
    empty = new_sheet("P4104")
    vault = {"rooms": {"P4102": saved, "P4104": empty}}
    before = deepcopy(vault)
    result = note_sources(vault, {"P4102": edited})
    assert set(result) == {"P4102"}
    assert result["P4102"]["fields"]["Diagnoses"] == "Synthetic current diagnosis"
    assert vault == before
