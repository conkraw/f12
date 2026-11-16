"""Reading legacy score data must not create a network save or PDF warm."""
from copy import deepcopy
import json

import pytest

from importing import import_sections
from models import automatic_vitals, new_sheet, save_sheet_in
from test_callbacks import app, open_room


STAFF = "LEGACY_SCORE_RECORDER_SENTINEL"
OLD_WAT = "3 (11/15/26 0900 : " + STAFF + ", RN)"
NEW_WAT = "WAT-1: 4 (11/16/26 0730 : " + STAFF + ", RN)"


class Store:
    def __init__(self):
        self.saved = []

    def save(self, candidate, sha):
        self.saved.append(deepcopy(candidate))
        return "saved-test-sha"


def setup_saved(app, monkeypatch, *, source="l", value=OLD_WAT, warning=False):
    open_room(app)
    ss = app.st.session_state
    sheet = ss["drafts"]["P4102"]
    label = "CAPD" if source == "y" else "WAT-1 total score (0-12)"
    sheet["neuro_vitals"][source] = [
        {"label": label, "value": value, "section": "Neurologic", "include": True}
    ]
    if warning:
        body = "CAPD: 99" if source == "y" else "WAT Score:\nWAT-1: 99"
        pasted = source * 24 + "\n" + body + "\n" + source * 24
        result = import_sections(sheet, pasted, ss["vault"]["settings"])
        assert result.errors and source in result.sheet["import_warnings"]
        sheet = result.sheet
    ss["vault"] = save_sheet_in(ss["vault"], sheet)
    other = new_sheet("P4104")
    other["fields"]["Diagnoses"] = "SYNTHETIC UNCHANGED ROOM"
    app.refresh_empty_group_layout(other, ss["vault"]["settings"])
    ss["vault"] = save_sheet_in(ss["vault"], other)
    ss["drafts"]["P4102"] = deepcopy(ss["vault"]["rooms"]["P4102"])
    ss["base_sheets"]["P4102"] = deepcopy(ss["vault"]["rooms"]["P4102"])
    warmed = []
    monkeypatch.setattr(app, "warm_handoff_pdf", lambda sheet: warmed.append(deepcopy(sheet)))
    key = "neuro_" + sheet["id"] + "_" + source + "_0"
    return ss, key, Store(), warmed


@pytest.mark.parametrize("widget", [None, "3 (11/15/26)", OLD_WAT])
@pytest.mark.parametrize("warning", [False, True])
def test_untouched_legacy_score_does_not_save_or_warm(app, monkeypatch, widget, warning):
    ss, key, store, warmed = setup_saved(app, monkeypatch, warning=warning)
    before = deepcopy(ss["vault"])
    draft = deepcopy(ss["drafts"]["P4102"])
    if widget is not None:
        ss[key] = widget
        ss[key + "_include"] = True
    assert app.editor_snapshot("P4102") == draft
    assert app.autosave_before_room_change(store)
    assert app.autosave_before_print_all(store)
    assert store.saved == [] and warmed == []
    assert ss["vault"] == before and ss["drafts"]["P4102"] == draft
    if not warning:
        output = automatic_vitals(draft)["Neurologic"]
        assert "WAT-1: 3 (11/15/26)" in output
        assert STAFF not in output and "0900" not in output


@pytest.mark.parametrize("widget", [None, ""])
def test_unreadable_legacy_value_stays_unchanged_when_editor_shows_blank(app, monkeypatch, widget):
    ss, key, store, warmed = setup_saved(app, monkeypatch, value="Unreadable " + STAFF)
    before = deepcopy(ss["vault"])
    if widget is not None:
        ss[key] = widget
    assert app.editor_snapshot("P4102") == ss["drafts"]["P4102"]
    assert app.autosave_before_room_change(store)
    assert not store.saved and not warmed
    assert ss["vault"] == before
    assert STAFF not in automatic_vitals(ss["drafts"]["P4102"])["Neurologic"]


@pytest.mark.parametrize("source,value", [("l", "3 (11/15/26)"), ("y", "6 (11/15/26)")])
@pytest.mark.parametrize("widgets", [False, True])
def test_unchanged_canonical_scores_skip_editor_normalization(app, monkeypatch, source, value, widgets):
    ss, key, store, warmed = setup_saved(app, monkeypatch, source=source, value=value)
    if widgets:
        ss[key], ss[key + "_include"] = value, True

    def unexpected(*args):
        raise AssertionError("An unchanged canonical score was normalized again.")

    monkeypatch.setattr(app, "normalize_score_rows", unexpected)
    assert app.editor_snapshot("P4102") == ss["drafts"]["P4102"]
    assert app.autosave_before_room_change(store)
    assert not store.saved and not warmed


def test_unchanged_display_callback_keeps_legacy_archive_and_warning(app, monkeypatch):
    ss, key, store, warmed = setup_saved(app, monkeypatch, warning=True)
    before = deepcopy(ss["drafts"]["P4102"])
    ss[key] = "3 (11/15/26)"
    app.neuro_row_change("P4102", "l", 0, "value", key)
    assert ss["drafts"]["P4102"] == before
    assert "l" in ss["drafts"]["P4102"]["import_warnings"]
    assert app.autosave_before_room_change(store)
    assert not store.saved and not warmed


@pytest.mark.parametrize("widgets", [False, True])
def test_room_navigation_keeps_untouched_legacy_room_read_only(app, monkeypatch, widgets):
    ss, key, store, warmed = setup_saved(app, monkeypatch)
    before = deepcopy(ss["vault"])
    if widgets:
        ss[key], ss[key + "_include"] = "3 (11/15/26)", True
    ss["room_choice"] = "P4104"
    app.room_changed(store)
    assert ss["current_room"] == "P4104"
    ss["room_choice"] = "P4102"
    app.room_changed(store)
    assert ss["current_room"] == "P4102"
    assert ss["vault"] == before
    assert not store.saved and not warmed


@pytest.mark.parametrize("callback", [False, True])
@pytest.mark.parametrize("source,old,new,expected", [
    ("l", OLD_WAT, NEW_WAT, "4 (11/16/26)"),
    ("l", OLD_WAT, "3 (11/16/26 0730 : " + STAFF + ", RN)", "3 (11/16/26)"),
    ("y", "6 (11/15/26)", "CAPD: 7 (11/16/26 0730 : " + STAFF + ", RN)", "7 (11/16/26)"),
])
def test_real_score_or_date_edit_saves_once_and_keeps_other_room(app, monkeypatch, callback, source, old, new, expected):
    ss, key, store, warmed = setup_saved(app, monkeypatch, source=source, value=old, warning=True)
    other = deepcopy(ss["vault"]["rooms"]["P4104"])
    ss[key] = new
    if callback:
        app.neuro_row_change("P4102", source, 0, "value", key)
    assert app.autosave_before_room_change(store)
    assert len(store.saved) == len(warmed) == 1
    saved = ss["vault"]["rooms"]["P4102"]
    assert saved["neuro_vitals"][source][0]["value"] == expected
    assert source not in saved["import_warnings"]
    assert STAFF not in json.dumps(saved)
    assert ss["vault"]["rooms"]["P4104"] == other
    assert app.autosave_before_room_change(store)
    assert len(store.saved) == len(warmed) == 1


@pytest.mark.parametrize("callback", [False, True])
def test_include_edit_is_real_and_saves_once(app, monkeypatch, callback):
    ss, key, store, warmed = setup_saved(app, monkeypatch)
    ss[key] = "3 (11/15/26)"
    ss[key + "_include"] = False
    if callback:
        app.neuro_row_change("P4102", "l", 0, "include", key + "_include")
    assert app.autosave_before_room_change(store)
    assert len(store.saved) == len(warmed) == 1
    saved = ss["vault"]["rooms"]["P4102"]
    assert not saved["neuro_vitals"]["l"][0]["include"]
    assert STAFF not in json.dumps(saved)
    assert "WAT-1" not in automatic_vitals(saved)["Neurologic"]
    assert app.autosave_before_room_change(store)
    assert len(store.saved) == len(warmed) == 1


@pytest.mark.parametrize("callback", [False, True])
def test_invalid_legacy_edit_preserves_saved_state_without_save_or_warm(app, monkeypatch, callback):
    ss, key, store, warmed = setup_saved(app, monkeypatch, warning=True)
    before, draft = deepcopy(ss["vault"]), deepcopy(ss["drafts"]["P4102"])
    ss[key] = "99 (11/16/26 0730 : " + STAFF + ", RN)"
    if callback:
        app.neuro_row_change("P4102", "l", 0, "value", key)
        assert ss[key] == "3 (11/15/26)"
        assert app.autosave_before_room_change(store)
    else:
        with pytest.raises(ValueError):
            app.editor_snapshot("P4102")
        assert not app.autosave_before_room_change(store)
    assert not store.saved and not warmed
    assert ss["vault"] == before and ss["drafts"]["P4102"] == draft
    assert STAFF not in json.dumps(ss.get("notice"))


def test_other_note_edit_does_not_migrate_untouched_legacy_score(app, monkeypatch):
    ss, key, store, warmed = setup_saved(app, monkeypatch)
    ss[key] = "3 (11/15/26)"
    sheet = ss["drafts"]["P4102"]
    ss[app.edit_key(sheet, "Goals / Follow-up")] = "Synthetic edited follow-up"
    assert app.autosave_before_room_change(store)
    assert len(store.saved) == len(warmed) == 1
    saved = ss["vault"]["rooms"]["P4102"]
    assert saved["neuro_vitals"]["l"][0]["value"] == OLD_WAT
    output = automatic_vitals(saved)["Neurologic"]
    assert "WAT-1: 3 (11/15/26)" in output and STAFF not in output
