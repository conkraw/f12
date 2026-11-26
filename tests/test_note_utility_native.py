"""Real Streamlit widget lifecycle tests using synthetic handoffs only.

The generator and Word renderer are replaced by deterministic recorders for
the interaction tests. Real engine and Word integration cases cover the
resulting files separately.
"""
from copy import deepcopy
from io import BytesIO
import sys
import types
from zipfile import ZipFile

import pytest
from streamlit.testing.v1 import AppTest

from note_utility import (
    ADDITIONAL_KEY, DRAFT_KEY, EDITOR_KEY, INVASIVE_KEY, PREFIX, REVOKE_KEY,
    ROOM_KEY, SELECTION_KEY, STYLE_KEY, TYPE_KEY,
)


CATALOG = [
    {"id": "alpha", "label": "Synthetic alpha plan"},
    {"id": "beta", "label": "Synthetic beta plan"},
    {"id": "gamma", "label": "Synthetic additional plan"},
]

SOURCE = '''
from copy import deepcopy
import time
import streamlit as st
from models import new_sheet
from note_utility import render_note_utility, note_download, REVOKE_KEY

ss = st.session_state
if "sources" not in ss:
    ss["sources"] = {}
    for room in ("P4102", "P4104"):
        sheet = new_sheet(room)
        sheet["fields"]["Diagnoses"] = "Synthetic handoff " + room
        ss["sources"][room] = sheet
    ss["authorized"] = True
    ss["calls"] = []
    ss["word_calls"] = []
    ss["saved_settings"] = []
    ss["settings"] = None
    ss["download_handles"] = []

def save(value):
    ss["settings"] = deepcopy(value)
    ss["saved_settings"].append(deepcopy(value))

def make_download(payload, draft):
    handle = note_download(payload, revoked=ss[REVOKE_KEY],
                           expires_at=time.monotonic() + 1000)
    ss["download_handles"].append({
        "kind": "word" if isinstance(payload, bytes) else "text",
        "handle": handle, "payload": payload,
    })
    return handle

render_note_utility(st, authorize=lambda: ss["authorized"],
                    get_sources=lambda: ss["sources"],
                    stored_settings=ss["settings"], save_settings=save,
                    make_download=make_download, current_room="P4102")
'''


def recording_generator(sheet, *, phrase_style, phrase_overrides, selected_ids,
                        settings=None, note_type="progress"):
    import streamlit as st
    ss = st.session_state
    ss["calls"].append({"sheet": deepcopy(sheet), "style": phrase_style,
                        "overrides": deepcopy(phrase_overrides),
                        "selected": deepcopy(selected_ids), "note_type": note_type})
    if ss.get("reject_generation"):
        raise ValueError("Synthetic generation failure")
    selected = ["alpha"] if selected_ids is None else list(selected_ids)
    suggestions = []
    for item in CATALOG:
        if item["id"] in ("alpha", "beta") or item["id"] in selected:
            suggestions.append({**item, "selected": item["id"] in selected,
                                "reasons": ["Synthetic test evidence"],
                                "phrase": "ACKZ" + item["id"].upper()})
    text = "\n".join((sheet["room"], note_type, sheet["fields"]["Diagnoses"],
                      phrase_style, ",".join(selected)))
    return {"text": text, "suggestions": suggestions, "warnings": [],
            "note_type": note_type, "phrase_style": phrase_style}


def recording_word_renderer(result, *, note_type="progress"):
    import streamlit as st
    st.session_state["word_calls"].append({"result": deepcopy(result), "note_type": note_type})
    if st.session_state.get("reject_word"):
        raise ValueError("Synthetic Word rendering failure")
    return b"PK\x03\x04" + note_type.encode() + b"\n" + result["text"].encode()


@pytest.fixture
def native(monkeypatch):
    engine = types.ModuleType("note_generator")
    engine.generate_note = recording_generator
    engine.get_phrase_catalog = lambda: deepcopy(CATALOG)
    monkeypatch.setitem(sys.modules, "note_generator", engine)
    renderer = types.ModuleType("note_word")
    renderer.render_note_docx = recording_word_renderer
    monkeypatch.setitem(sys.modules, "note_word", renderer)
    at = AppTest.from_string(SOURCE, default_timeout=10).run()
    assert not at.exception
    return at


def generate(at):
    at.button(key=PREFIX + "generate").click().run()
    assert not at.exception
    assert not at.error, [item.value for item in at.error]


def downloads(at):
    """Return the most recently prepared handle for each format."""
    return {entry["kind"]: entry for entry in at.session_state["download_handles"]}


def assert_revoked(handles):
    for entry in handles.values():
        with pytest.raises(ValueError, match="expired"):
            entry["handle"]()


def test_open_rerun_and_settings_changes_do_not_generate(native):
    assert native.session_state["calls"] == []
    assert native.session_state["word_calls"] == []
    assert not native.text_area
    native.run()
    native.radio(key=STYLE_KEY).set_value("dot").run()
    native.text_input(key=INVASIVE_KEY).set_value("ACKZSYNTHETICINVASIVE").run()
    native.button(key=PREFIX + "save_settings").click().run()
    assert not native.exception
    assert not native.error
    assert native.session_state["calls"] == []
    assert native.session_state["word_calls"] == []
    assert native.session_state["saved_settings"] == [{
        "phrase_style": "dot",
        "phrase_overrides": {"acute_hypoxemic_invasive": "ACKZSYNTHETICINVASIVE"},
    }]


def test_only_generate_and_update_rebuild_while_preview_and_files_stay_matched(native):
    before = deepcopy(native.session_state["sources"])
    generate(native)
    assert len(native.session_state["calls"]) == 1
    assert len(native.session_state["word_calls"]) == 1
    preview = native.text_area(key=EDITOR_KEY).value
    assert native.text_area(key=EDITOR_KEY).disabled
    prepared = downloads(native)
    word_bytes = prepared["word"]["handle"]()
    assert prepared["text"]["handle"]() == preview.encode()
    native.radio(key=STYLE_KEY).set_value("dot").run()
    native.button(key=PREFIX + "save_settings").click().run()
    native.run()
    assert not native.exception
    assert len(native.session_state["calls"]) == 1
    assert len(native.session_state["word_calls"]) == 1
    assert native.text_area(key=EDITOR_KEY).value == preview
    assert downloads(native)["word"]["handle"]() == word_bytes
    assert downloads(native)["word"]["handle"]() == word_bytes
    assert len(native.session_state["word_calls"]) == 1
    assert native.session_state["sources"] == before
    generate(native)
    assert len(native.session_state["calls"]) == 2
    assert len(native.session_state["word_calls"]) == 2
    assert native.session_state["calls"][-1]["style"] == "dot"
    assert native.text_area(key=EDITOR_KEY).value != preview
    assert_revoked(prepared)


def test_plan_choices_wait_for_update_and_survive_the_next_run(native):
    generate(native)
    old_downloads = downloads(native)
    native.multiselect(key=SELECTION_KEY).set_value(["beta"]).run()
    native.multiselect(key=ADDITIONAL_KEY).set_value(["gamma"]).run()
    assert len(native.session_state["calls"]) == 1
    assert len(native.session_state["word_calls"]) == 1
    assert native.text_area(key=EDITOR_KEY).value.endswith("alpha")
    native.button(key=PREFIX + "update").click().run()
    assert not native.exception
    assert not native.error
    assert len(native.session_state["calls"]) == 2
    assert len(native.session_state["word_calls"]) == 2
    assert native.session_state["calls"][-1]["selected"] == ["beta", "gamma"]
    assert native.text_area(key=EDITOR_KEY).value.endswith("beta,gamma")
    assert_revoked(old_downloads)
    native.run()
    assert not native.exception
    assert native.multiselect(key=SELECTION_KEY).value == ["beta", "gamma"]
    assert native.multiselect(key=ADDITIONAL_KEY).value == []
    assert len(native.session_state["calls"]) == 2
    assert len(native.session_state["word_calls"]) == 2
    native.multiselect(key=SELECTION_KEY).set_value([]).run()
    assert len(native.session_state["calls"]) == 2
    native.button(key=PREFIX + "update").click().run()
    native.run()
    assert not native.exception
    assert not native.error
    assert native.multiselect(key=SELECTION_KEY).value == []
    assert native.session_state["calls"][-1]["selected"] == []


@pytest.mark.parametrize("replacement", [False, True])
def test_current_handoff_edit_or_patient_replacement_invalidates_draft(native, replacement):
    generate(native)
    event = native.session_state[REVOKE_KEY]
    old_downloads = downloads(native)
    sources = deepcopy(native.session_state["sources"])
    if replacement:
        sources["P4102"]["id"] = "f" * 32
    else:
        sources["P4102"]["fields"]["Neurologic"] = "Synthetic changed handoff"
    native.session_state["sources"] = sources
    native.run()
    assert not native.exception
    assert DRAFT_KEY not in native.session_state
    assert not native.text_area
    assert event.is_set()
    assert len(native.session_state["calls"]) == 1
    assert_revoked(old_downloads)


def test_patient_switch_revokes_old_output_without_generating_new_note(native):
    generate(native)
    old_downloads = downloads(native)
    native.selectbox(key=ROOM_KEY).set_value("P4104").run()
    assert not native.exception
    assert DRAFT_KEY not in native.session_state
    assert not native.text_area
    assert len(native.session_state["calls"]) == 1
    assert_revoked(old_downloads)
    generate(native)
    assert native.text_area(key=EDITOR_KEY).value.startswith("P4104\n")
    assert len(native.session_state["calls"]) == 2


def test_expired_access_removes_draft_and_widgets_before_generation(native):
    generate(native)
    old_downloads = downloads(native)
    native.session_state["authorized"] = False
    native.button(key=PREFIX + "generate").click().run()
    assert not native.exception
    assert len(native.session_state["calls"]) == 1
    assert DRAFT_KEY not in native.session_state
    assert not native.button
    assert not native.text_area
    assert_revoked(old_downloads)


@pytest.mark.parametrize("failure", ["reject_generation", "reject_word"])
def test_generation_or_word_error_preserves_previous_review_draft(native, failure):
    generate(native)
    prior = native.text_area(key=EDITOR_KEY).value
    prior_word = downloads(native)["word"]["handle"]()
    guard = native.session_state[REVOKE_KEY]
    native.session_state[failure] = True
    native.button(key=PREFIX + "update").click().run()
    assert not native.exception
    expected = "Synthetic generation failure" if failure == "reject_generation" else "Synthetic Word rendering failure"
    assert native.error[0].value == expected
    assert native.text_area(key=EDITOR_KEY).value == prior
    assert downloads(native)["word"]["handle"]() == prior_word
    assert native.session_state[REVOKE_KEY] is guard
    assert not guard.is_set()


def test_note_type_switch_clears_both_downloads_without_generating(native):
    generate(native)
    prepared = downloads(native)
    native.radio(key=TYPE_KEY).set_value("attestation").run()
    assert not native.exception
    assert native.session_state[TYPE_KEY] == "attestation"
    assert DRAFT_KEY not in native.session_state
    assert not native.text_area
    assert len(native.session_state["calls"]) == 1
    assert len(native.session_state["word_calls"]) == 1
    assert_revoked(prepared)
    generate(native)
    assert native.session_state["calls"][-1]["note_type"] == "attestation"
    assert native.session_state["word_calls"][-1]["note_type"] == "attestation"
    assert native.session_state[DRAFT_KEY]["note_type"] == "attestation"
    assert "attestation" in native.text_area(key=EDITOR_KEY).value
    native.radio(key=TYPE_KEY).set_value("progress").run()
    assert len(native.session_state["calls"]) == 2
    assert len(native.session_state["word_calls"]) == 2
    assert DRAFT_KEY not in native.session_state


def test_real_engine_renders_template_and_updates_plan_in_native_runtime():
    """One integration case catches interface drift between UI and engine."""
    at = AppTest.from_string(SOURCE, default_timeout=10).run()
    sources = deepcopy(at.session_state["sources"])
    sources["P4102"]["fields"]["Diagnoses"] = "Hypokalemia"
    at.session_state["sources"] = sources
    at.run()
    generate(at)
    text = at.text_area(key=EDITOR_KEY).value
    assert "PEDIATRIC CRITICAL CARE MEDICINE PROGRESS NOTE" in text
    assert "@ACKZHYPOKALEMIA@" in text
    with ZipFile(BytesIO(downloads(at)["word"]["handle"]())) as package:
        assert b"ACKZHYPOKALEMIA" in package.read("word/document.xml")
    assert "gastric_ulcer_risk" not in at.multiselect(key=SELECTION_KEY).value
    at.multiselect(key=ADDITIONAL_KEY).set_value(["gastric_ulcer_risk"]).run()
    assert "@ACKZATRISKFORGASTRICULCERS@" not in at.text_area(key=EDITOR_KEY).value
    at.button(key=PREFIX + "update").click().run()
    at.run()
    assert not at.exception
    assert not at.error
    assert "@ACKZATRISKFORGASTRICULCERS@" in at.text_area(key=EDITOR_KEY).value
    assert set(at.multiselect(key=SELECTION_KEY).value) == {"hypokalemia", "gastric_ulcer_risk"}
    assert at.session_state["sources"] == sources


def test_real_attestation_word_omits_medications_and_keeps_selected_plan_reference():
    from medications import parse_medications

    at = AppTest.from_string(SOURCE, default_timeout=10).run()
    sources = deepcopy(at.session_state["sources"])
    orders = parse_medications(
        "Medications:\n• pantoprazole injection 20 mg\t20 mg\tIntravenous\tDaily\t\t\t"
    )
    assert not orders.error
    orders.rows[0]["section"] = "FEN / GI"
    sources["P4102"]["medications"] = orders.rows
    at.session_state["sources"] = sources
    at.radio(key=TYPE_KEY).set_value("attestation").run()
    generate(at)
    text = at.text_area(key=EDITOR_KEY).value
    assert "pantoprazole" not in text.lower()
    assert "@ACKZATRISKFORGASTRICULCERS@" in text
    assert "Drips" not in text and "Scheduled medications" not in text
    with ZipFile(BytesIO(downloads(at)["word"]["handle"]())) as package:
        document = package.read("word/document.xml").decode("utf-8")
    assert "pantoprazole" not in document.lower()
    assert "ACKZATRISKFORGASTRICULCERS" in document
    assert at.session_state[DRAFT_KEY]["note_type"] == "attestation"
    assert at.session_state["sources"] == sources


def test_authorization_revoked_during_word_rendering_discards_new_document():
    from models import new_sheet
    from note_utility import create_note_draft

    sheet = new_sheet("P4102")
    state = {"handoff_field": "Synthetic retained handoff"}
    access = {"allowed": True}
    authorize = lambda: access["allowed"]

    def generator(source, **kwargs):
        return {"text": "Synthetic note", "suggestions": [], "warnings": []}

    assert create_note_draft(
        state, sheet, authorize=authorize, settings={}, generator=generator,
        word_renderer=lambda result, **kwargs: b"PKprevious Word document",
    )
    old_guard = state[REVOKE_KEY]

    def revoke_while_rendering(result, **kwargs):
        access["allowed"] = False
        return b"PKnew Word document"

    assert create_note_draft(
        state, sheet, authorize=authorize, settings={}, generator=generator,
        word_renderer=revoke_while_rendering,
    ) is False
    assert old_guard.is_set()
    assert DRAFT_KEY not in state
    assert EDITOR_KEY not in state
    assert REVOKE_KEY not in state
    assert state == {"handoff_field": "Synthetic retained handoff"}
