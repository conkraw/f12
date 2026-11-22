"""Real Streamlit runtime form behavior, using synthetic events and AppTest.

AppTest reads the Arrow table and applies keyed editor state to its actual
Streamlit widget. These are runtime tests rather than browser screenshot tests.
"""
from datetime import datetime

import pytest
from streamlit.testing.v1 import AppTest

from prn_counts import prn_counts


NOW = datetime.fromisoformat("2026-11-22T04:00:00-05:00")
SOURCE = '''
from copy import deepcopy
from datetime import datetime
import streamlit as st
from lab_windows import display_clock
from prn_ui import render_prn_editor

if "sheet" not in st.session_state:
    st.session_state["sheet"] = {
        "id": "a" * 32, "medications": [],
        "prn": {"version": 1, "reviewed": {}, "events": [
            {"medication": "hydromorphone", "timestamp": "2026-11-22T01:41:00-05:00",
             "volume_ml": 1.05, "dose_count": None, "source": "volume"}]}}
    st.session_state["saves"] = 0
    st.session_state["now"] = "2026-11-22T04:00:00-05:00"

def save(value):
    if st.session_state.get("reject_save"):
        raise ValueError("The room changed. Reopen the review.")
    st.session_state["sheet"]["prn"] = deepcopy(value)
    st.session_state["saves"] += 1

with display_clock(datetime.fromisoformat(st.session_state["now"])):
    render_prn_editor(st.session_state["sheet"], save)
'''


@pytest.fixture
def native():
    at = AppTest.from_string(SOURCE).run()
    assert not at.exception
    return at


def edit(at, *, edited=None, added=None, deleted=None):
    key = at.data_editor[0].key
    at.session_state[key] = {"edited_rows": edited or {}, "added_rows": added or [],
                              "deleted_rows": deleted or []}
    at.button[0].click().run()
    assert not at.exception


def test_native_table_renders_unresolved_null_and_requires_review(native):
    assert native.data_editor[0].editing_mode == "dynamic"
    assert native.data_editor[0].value.to_dict("records")[0]["dose_count"] is None
    native.button[0].click().run()
    assert not native.exception
    assert native.session_state["saves"] == 0
    assert "Resolve every in-window entry" in native.error[0].value


def test_native_confirm_saves_once_and_refreshes_widget_identity(native):
    old_key = native.data_editor[0].key
    edit(native, edited={0: {"dose_count": 1}})
    assert not native.error
    assert native.session_state["saves"] == 1
    assert prn_counts(native.session_state["sheet"], as_of=NOW) == {"hydromorphone": 1}
    assert native.data_editor[0].key != old_key


def test_native_fractional_count_is_not_silently_truncated(native):
    edit(native, edited={0: {"dose_count": 1.5}})
    assert native.session_state["saves"] == 0
    assert "whole number" in native.error[0].value


def test_native_add_missing_event_and_exclude_infusion(native):
    edit(native, edited={0: {"dose_count": 0}},
         added=[{"timestamp": "2026-11-22 02:30", "dose_count": 2}])
    assert not native.error
    sheet = native.session_state["sheet"]
    assert prn_counts(sheet, as_of=NOW) == {"hydromorphone": 2}
    assert [event["source"] for event in sheet["prn"]["events"]] == ["volume", "manual"]
    assert sheet["prn"]["events"][1]["volume_ml"] is None


def test_native_empty_medication_can_add_verified_dose(native):
    native.selectbox[0].select("morphine").run()
    assert not native.exception
    assert native.data_editor[0].value.empty
    edit(native, added=[{"timestamp": "2026-11-22 03:00", "dose_count": 1}])
    assert not native.error
    assert prn_counts(native.session_state["sheet"], as_of=NOW) == {"morphine": 1}
    assert native.session_state["sheet"]["prn"]["events"][0]["dose_count"] is None


def test_native_confirm_zero_and_delete_source_row_are_explicit(native):
    edit(native, deleted=[0])
    assert not native.error
    assert native.session_state["saves"] == 1
    assert native.session_state["sheet"]["prn"]["events"] == []
    assert prn_counts(native.session_state["sheet"], as_of=NOW) == {"hydromorphone": 0}


def test_native_callback_failure_does_not_save_or_reset_editor(native):
    old_key = native.data_editor[0].key
    native.session_state["reject_save"] = True
    edit(native, edited={0: {"dose_count": 1}})
    assert native.session_state["saves"] == 0
    assert native.data_editor[0].key == old_key
    assert native.error[0].value == "The room changed. Reopen the review."


def test_native_old_editor_submission_does_not_apply_to_replaced_source(native):
    old_key = native.data_editor[0].key
    native.session_state[old_key] = {"edited_rows": {0: {"dose_count": 1}},
                                    "added_rows": [], "deleted_rows": []}
    sheet = native.session_state["sheet"]
    sheet["prn"]["events"][0]["timestamp"] = "2026-11-22T03:50:00-05:00"
    native.session_state["sheet"] = sheet
    native.button[0].click().run()
    assert not native.exception
    assert native.session_state["saves"] == 0
    assert native.data_editor[0].key != old_key
    assert native.session_state["sheet"]["prn"]["events"][0]["dose_count"] is None
