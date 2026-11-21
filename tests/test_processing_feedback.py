"""Synthetic processing feedback checks with real import and save callbacks."""
from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from github_store import ConflictError, StorageError
from models import new_sheet, new_vault, save_sheet_in
from processing_feedback import MAX_SAMPLES, ProcessingFeedback, TIMING_KEY
from test_callbacks import app, open_room
from test_room_replacement import Store


NEW = "aaaaaaaa\nDiagnoses:\n1. SYNTHETIC_NEW_HANDOFF\naaaaaaaa"


class FeedbackUI:
    def __init__(self):
        self.events = []
        self.open = False

    @contextmanager
    def spinner(self, text, *, show_time=False):
        self.events.append(("spinner", text, show_time))
        self.open = True
        try:
            yield
        finally:
            self.open = False
            self.events.append(("spinner_closed",))

    def progress(self, value, *, text):
        self.events.append(("progress", value, text))
        return self

    def empty(self):
        self.events.append(("cleared",))

    @property
    def updates(self):
        return [event for event in self.events if event[0] == "progress"]


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def setup(app, monkeypatch, *, visible=True):
    sheet = new_sheet("P4102")
    sheet["fields"]["Diagnoses"] = "SYNTHETIC_PREVIOUS_HANDOFF"
    ss = app.st.session_state
    ss.update(vault=save_sheet_in(new_vault(), sheet), vault_sha="old-sha")
    open_room(app)
    ss["paste"] = NEW
    monkeypatch.setattr(app, "respiratory_parser_ready", lambda: True)
    ui = FeedbackUI()
    if visible:
        app.st.spinner = ui.spinner
        app.st.progress = ui.progress
    return ss, ui


def assert_closed_without_success(ui):
    assert not ui.open
    assert ui.events[-2:] == [("cleared",), ("spinner_closed",)]
    assert all(value < 1 for _, value, _ in ui.updates)
    assert not any("Processing finished" in text for _, _, text in ui.updates)


def test_success_shows_actual_stages_elapsed_timer_and_runs_each_operation_once(app, monkeypatch):
    ss, ui = setup(app, monkeypatch)
    real_import = app.import_replacement
    real_save = app.commit
    operations = []

    def import_once(*args, **kwargs):
        assert ui.open and "Step 1 of 3: Reading SmartPhrase" in ui.updates[-1][2]
        operations.append("parse")
        return real_import(*args, **kwargs)

    def save_once(*args, **kwargs):
        assert ui.open and "Step 2 of 3: Saving handoff" in ui.updates[-1][2]
        operations.append("save")
        return real_save(*args, **kwargs)

    def prepare_once(sheet):
        assert ui.open and "Step 3 of 3: Preparing PDF" in ui.updates[-1][2]
        assert sheet == ss["vault"]["rooms"]["P4102"]
        operations.append("pdf")
        return True

    monkeypatch.setattr(app, "import_replacement", import_once)
    monkeypatch.setattr(app, "commit", save_once)
    monkeypatch.setattr(app, "warm_handoff_pdf", prepare_once)
    store = Store(ss["vault"])

    app.create_handoff(store)

    assert operations == ["parse", "save", "pdf"]
    assert len(store.calls) == 1
    assert ui.events[0] == ("spinner", "Processing handoff", True)
    assert [value for _, value, _ in ui.updates] == [0.0, 1 / 3, 2 / 3, 1.0]
    assert "PDF ready" in ui.updates[-1][2]
    assert not any("Typical remaining" in text for _, _, text in ui.updates)
    assert not ui.open and ui.events[-2:] == [("cleared",), ("spinner_closed",)]
    assert ss["vault"] == store.vault
    assert ss["drafts"]["P4102"]["fields"]["Diagnoses"] == "SYNTHETIC_NEW_HANDOFF"
    assert ss["paste"] == ""
    assert len(ss[TIMING_KEY]["shared"]) == 1
    assert ss[TIMING_KEY]["session"] == []
    metadata = json.dumps(ss[TIMING_KEY])
    assert "P4102" not in metadata and "SYNTHETIC" not in metadata
    assert TIMING_KEY not in json.dumps(store.vault)


@pytest.mark.parametrize("source", ["", "unsupported source", "aaaaaaaa\nDiagnoses:\n1. Unclosed"])
def test_unusable_paste_stops_progress_and_preserves_previous_patient(app, monkeypatch, source):
    ss, ui = setup(app, monkeypatch)
    ss["paste"] = source
    before = {name: deepcopy(ss[name]) for name in ("vault", "drafts", "base_sheets")}
    store = Store(ss["vault"])

    app.create_handoff(store)

    assert store.calls == []
    assert all(ss[name] == value for name, value in before.items())
    assert ss["paste"] == source
    assert ss["notice"][0] == "error"
    assert len(ui.updates) == 1
    assert TIMING_KEY not in ss
    assert_closed_without_success(ui)


@pytest.mark.parametrize("failure", [ValueError("PRIVATE_PARSER_SENTINEL"), RuntimeError("PRIVATE_PARSER_SENTINEL")])
def test_parser_exception_clears_feedback_without_exposing_source_or_advancing(app, monkeypatch, failure):
    ss, ui = setup(app, monkeypatch)
    before = deepcopy(ss["vault"])

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(app, "import_replacement", fail)
    app.create_handoff(Store(before))

    assert ss["vault"] == before and ss["paste"] == NEW
    assert "PRIVATE_PARSER_SENTINEL" not in str(ui.events) + str(ss["notice"])
    assert len(ui.updates) == 1
    assert TIMING_KEY not in ss
    assert_closed_without_success(ui)


@pytest.mark.parametrize("failure", [StorageError("PRIVATE_WRITE_SENTINEL"),
                                     ConflictError("PRIVATE_WRITE_SENTINEL"),
                                     RuntimeError("PRIVATE_WRITE_SENTINEL")])
def test_save_failure_never_shows_complete_or_loses_old_patient_and_paste(app, monkeypatch, failure):
    ss, ui = setup(app, monkeypatch)
    before = {name: deepcopy(ss[name]) for name in ("vault", "drafts", "base_sheets")}
    store = Store(ss["vault"], failure=failure)

    app.create_handoff(store)

    assert len(store.calls) == 1
    assert all(ss[name] == value for name, value in before.items())
    assert ss["paste"] == NEW
    assert [value for _, value, _ in ui.updates] == [0.0, 1 / 3]
    assert "NOT confirmed" in ss["notice"][1]
    assert "PRIVATE_WRITE_SENTINEL" not in str(ui.events) + str(ss["notice"])
    assert TIMING_KEY not in ss
    assert_closed_without_success(ui)


def test_pdf_failure_keeps_confirmed_save_and_finishes_with_retry_caveat(app, monkeypatch):
    ss, ui = setup(app, monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_PDF_SENTINEL")

    monkeypatch.setattr(app, "session_pdf_cache", lambda: SimpleNamespace(prepare=fail))
    store = Store(ss["vault"])

    app.create_handoff(store)

    assert ss["vault"] == store.vault
    assert store.vault["rooms"]["P4102"]["fields"]["Diagnoses"] == "SYNTHETIC_NEW_HANDOFF"
    assert ss["paste"] == ""
    assert "PDF preparation will retry" in ss["notice"][1]
    assert "Processing finished. Handoff saved." in ui.updates[-1][2]
    assert "PDF preparation will retry" in ui.updates[-1][2]
    assert not any("PDF ready" in text for _, _, text in ui.updates)
    assert all(value < 1 for _, value, _ in ui.updates)
    assert not ui.open and ui.events[-2:] == [("cleared",), ("spinner_closed",)]
    assert "PRIVATE_PDF_SENTINEL" not in str(ui.events) + str(ss["notice"])
    assert TIMING_KEY not in ss


def test_partial_import_finishes_with_alerts_without_false_full_readiness(app, monkeypatch):
    ss, ui = setup(app, monkeypatch)
    ss["paste"] = NEW + "\nbbbbbbbb\nMedications:\nMALFORMED\nbbbbbbbb"

    app.create_handoff(Store(ss["vault"]))

    assert ss["drafts"]["P4102"]["fields"]["Diagnoses"] == "SYNTHETIC_NEW_HANDOFF"
    assert ss["drafts"]["P4102"]["medications"] == []
    assert ss["notice"][0] == "warning"
    assert "Handoff saved with alerts" in ui.updates[-1][2]
    assert all(value < 1 for _, value, _ in ui.updates)
    assert not ui.open
    assert TIMING_KEY not in ss


def test_precondition_guard_does_not_start_or_repeat_processing(app, monkeypatch):
    ss, ui = setup(app, monkeypatch)
    ss["vault"]["rooms"]["P4102"]["fields"]["Other"] = "SYNTHETIC_NEWER_EDIT"
    store = Store(ss["vault"])

    app.create_handoff(store)

    assert ui.events == []
    assert store.calls == [] and ss["paste"] == NEW
    assert "saved room changed" in ss["notice"][1]


def test_parser_readiness_failure_stops_first_step_without_replacing(app, monkeypatch):
    ss, ui = setup(app, monkeypatch)
    before = deepcopy(ss["vault"])
    monkeypatch.setattr(app, "respiratory_parser_ready", lambda: False)
    monkeypatch.setattr(app, "respiratory_fallback_ready", lambda: False)
    store = Store(before)

    app.create_handoff(store)

    assert ss["vault"] == before and ss["paste"] == NEW and store.calls == []
    assert len(ui.updates) == 1
    assert_closed_without_success(ui)


@pytest.mark.parametrize("facilities", ["missing", "broken"])
def test_absent_or_failed_ui_facilities_never_cancel_or_repeat_a_save(app, monkeypatch, facilities):
    ss, ui = setup(app, monkeypatch, visible=False)
    if facilities == "broken":
        def fail(*args, **kwargs):
            raise RuntimeError("Synthetic UI unavailable")
        app.st.spinner = fail
        app.st.progress = fail
    store = Store(ss["vault"])

    app.create_handoff(store)

    assert len(store.calls) == 1
    assert ss["vault"] == store.vault
    assert ss["drafts"]["P4102"]["fields"]["Diagnoses"] == "SYNTHETIC_NEW_HANDOFF"
    assert ss["paste"] == ""


def test_timing_estimates_use_real_successful_phases_and_update_only_at_steps():
    state, clock, first = {}, Clock(), FeedbackUI()
    with ProcessingFeedback(first, state, clock=clock) as feedback:
        clock.advance(4)
        feedback.step(1)
        clock.advance(5)
        feedback.step(2)
        clock.advance(3)
        feedback.finish(pdf_ready=True)
    assert state == {TIMING_KEY: {"session": [[4.0, 5.0, 3.0]], "shared": []}}
    assert not any("Typical remaining" in text for _, _, text in first.updates)

    second = FeedbackUI()
    with ProcessingFeedback(second, state, clock=clock) as feedback:
        assert "Typical remaining time: about 12 seconds" in second.updates[-1][2]
        assert "prior successful imports, updated at each step" in second.updates[-1][2]
        clock.advance(90)
        assert len(second.updates) == 1
        feedback.step(1)
        assert "Typical remaining time: about 8 seconds" in second.updates[-1][2]
        clock.advance(7)
        feedback.step(2)
        assert "Typical remaining time: about 3 seconds" in second.updates[-1][2]
        clock.advance(2)
        feedback.finish(pdf_ready=True)
    assert state[TIMING_KEY]["session"][-1] == [90.0, 7.0, 2.0]


def test_only_recent_successes_are_kept_and_storage_modes_do_not_share_estimates():
    state, clock = {}, Clock()
    for _ in range(MAX_SAMPLES + 2):
        with ProcessingFeedback(FeedbackUI(), state, clock=clock) as feedback:
            clock.advance(1)
            feedback.step(1)
            clock.advance(2)
            feedback.step(2)
            clock.advance(3)
            feedback.finish(pdf_ready=True)
    before = deepcopy(state)
    assert len(state[TIMING_KEY]["session"]) == MAX_SAMPLES
    shared = FeedbackUI()
    with ProcessingFeedback(shared, state, shared_storage=True, clock=clock):
        assert "Typical remaining" not in shared.updates[-1][2]
    assert state == before


def test_unexpected_exception_always_clears_spinner_and_does_not_learn_a_timing():
    state, ui = {}, FeedbackUI()

    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        with ProcessingFeedback(ui, state) as feedback:
            feedback.step(1)
            raise RuntimeError("Synthetic interruption")

    assert state == {}
    assert_closed_without_success(ui)
