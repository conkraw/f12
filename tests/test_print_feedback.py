"""6.98 print preparation timer, readiness and guarded download regressions."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from models import new_sheet, new_vault, save_sheet_in
from print_feedback import PREPARATION_KEY, PrintFeedback, preparation_signature
from test_callbacks import app
from test_room_replacement import Store
from test_ui_smoke import equip


class FeedbackUI:
    def __init__(self):
        self.events = []
        self.open = False

    @contextmanager
    def spinner(self, text, *, show_time=False):
        self.open = True
        self.events.append(("spinner", text, show_time))
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


def seed(app, monkeypatch, count=2):
    sheets = []
    vault = new_vault()
    for room in ("P4102", "P4104")[:count]:
        sheet = new_sheet(room)
        sheet["fields"]["Diagnoses"] = "SYNTHETIC_PRINT_TIMER"
        vault = save_sheet_in(vault, sheet)
        sheets.append(vault["rooms"][room])
    ss = app.st.session_state
    ss.update(vault=vault, vault_sha="old-sha", drafts=deepcopy(vault["rooms"]),
              base_sheets=deepcopy(vault["rooms"]), page="Print all")
    ui = FeedbackUI()
    app.st.spinner = ui.spinner
    app.st.progress = ui.progress
    statuses = {sheet["room"]: app.display_room_save_status(sheet["room"], None) for sheet in sheets}
    signature = preparation_signature(sheets, 1, vault["reset_generation"], shared_storage=False)
    return ss, sheets, statuses, signature, ui


def test_feedback_uses_native_elapsed_timer_and_waits_for_final_verification():
    ui = FeedbackUI()
    clock = [0.0]
    with PrintFeedback(ui, 2, clock=lambda: clock[0]) as feedback:
        assert ui.open
        feedback.update(0, 2, "preparing")
        feedback.update(1, 2, "preparing")
        feedback.update(2, 2, "preparing")
        feedback.update(2, 2, "assembling")
        feedback.update(2, 2, "complete")
        assert all(value < 1 for _, value, _ in ui.updates)
        assert "Checking saved handoffs again" in ui.updates[-1][2]
        clock[0] = 4.25
        assert feedback.finish() == 4.25
    assert ui.events[0] == ("spinner", "Preparing print packet", True)
    assert ui.updates[-1][1] == 1
    assert not ui.open and ui.events[-2:] == [("cleared",), ("spinner_closed",)]


def test_feedback_failure_clears_without_claiming_readiness():
    ui = FeedbackUI()
    with pytest.raises(RuntimeError):
        with PrintFeedback(ui, 2) as feedback:
            feedback.update(1, 2, "preparing")
            raise RuntimeError("Synthetic failed preparation")
    assert all(value < 1 for _, value, _ in ui.updates)
    assert not ui.open and ui.events[-2:] == [("cleared",), ("spinner_closed",)]


def test_missing_feedback_methods_do_not_block_preparation():
    with PrintFeedback(SimpleNamespace(), 1) as feedback:
        feedback.update(1, 1, "preparing")
        feedback.finish()


def test_complete_preparation_is_counted_and_download_reuses_bodies_without_ui(app, monkeypatch):
    ss, sheets, statuses, signature, ui = seed(app, monkeypatch)
    app.prepare_print_packet(sheets, None, target_pages=1, save_statuses=statuses, signature=signature)
    assert ss[PREPARATION_KEY]["signature"] == signature
    assert ss[PREPARATION_KEY]["count"] == 2
    assert set(ss[PREPARATION_KEY]) == {"signature", "count", "seconds", "pages", "overflow",
                                        "goals_omitted", "compact_secondary"}
    assert ss[PREPARATION_KEY]["pages"] == 2
    assert ss[PREPARATION_KEY]["overflow"] == 0
    assert "P4102" not in json.dumps(ss[PREPARATION_KEY])
    assert "SYNTHETIC" not in json.dumps(ss[PREPARATION_KEY])
    assert PREPARATION_KEY not in json.dumps(ss["vault"])
    texts = [text for _, _, text in ui.updates]
    assert "Preparing handoffs: 0 of 2 ready" in texts
    assert "Preparing handoffs: 1 of 2 ready" in texts
    assert "Preparing handoffs: 2 of 2 ready" in texts
    assert "Combining 2 handoffs into one PDF" in texts
    assert ui.updates[-1][1] == 1
    cache = app.session_pdf_cache()
    assert cache.stats["builds"] == 2
    callback = app.handoff_download(sheets, None, target_pages=1, save_statuses=statuses)
    before = deepcopy(ui.events)
    # A download worker must use captured snapshots, never Streamlit state/UI.
    app.st.session_state = None
    assert callback().startswith(b"%PDF-")
    assert cache.stats["builds"] == 2
    assert ui.events == before


@pytest.mark.parametrize("change", ["before", "during", "cancelled", "error"])
def test_failed_guard_or_generation_never_leaves_ready_state(app, monkeypatch, change):
    ss, sheets, statuses, signature, ui = seed(app, monkeypatch)
    ss[PREPARATION_KEY] = {"signature": "OLD", "count": 1, "seconds": 1}
    store = Store(ss["vault"])
    real = app.cached_handoffs_pdf
    if change == "before":
        store.vault["rooms"]["P4102"]["fields"]["Diagnoses"] = "CHANGED_BEFORE_PREPARATION"
    else:
        def generate(*args, **kwargs):
            if change == "error":
                raise RuntimeError("Synthetic failure")
            result = real(*args, **kwargs)
            if change == "during":
                store.vault["rooms"]["P4102"]["fields"]["Diagnoses"] = "CHANGED_DURING_PREPARATION"
            else:
                app.download_revocation().set()
            return result
        monkeypatch.setattr(app, "cached_handoffs_pdf", generate)
    with pytest.raises((ValueError, RuntimeError)):
        app.prepare_print_packet(sheets, store, target_pages=1, save_statuses=statuses, signature=signature)
    assert PREPARATION_KEY not in ss
    assert all(value < 1 for _, value, _ in ui.updates)
    assert not ui.open


def test_prepared_download_still_checks_shared_edits_at_actual_click(app, monkeypatch):
    ss, sheets, statuses, signature, ui = seed(app, monkeypatch)
    store = Store(ss["vault"])
    app.prepare_print_packet(sheets, store, target_pages=1, save_statuses=statuses, signature=signature)
    callback = app.handoff_download(sheets, store, target_pages=1, save_statuses=statuses)
    store.vault["rooms"]["P4102"]["fields"]["Diagnoses"] = "CHANGED_AFTER_READY"
    with pytest.raises(ValueError, match="patient list changed"):
        callback()


@pytest.mark.parametrize("change", ["selection", "order", "target", "generation", "source", "saved_time", "storage"])
def test_readiness_signature_covers_packet_changes(change):
    a, b = new_sheet("P4102"), new_sheet("P4104")
    sheets, target, generation, shared = [a, b], 1, "generation", False
    old = preparation_signature(sheets, target, generation, shared_storage=shared)
    if change == "selection":
        sheets = [a]
    elif change == "order":
        sheets.reverse()
    elif change == "target":
        target = 2
    elif change == "generation":
        generation = "new-generation"
    elif change == "source":
        a["fields"]["Neurologic"] = "NEW SYNTHETIC NOTE"
    elif change == "saved_time":
        a["updated_at"] = "2026-11-21T14:30:00+00:00"
    else:
        shared = True
    assert preparation_signature(sheets, target, generation, shared_storage=shared) != old


def test_readiness_signature_tracks_exact_dynamic_lab_window(monkeypatch):
    from labs import parse_labs
    import print_feedback
    sheet = new_sheet("P4102")
    sheet["labs"] = parse_labs("LABS:\nComponent\tValue\tDate\nVANCOTROUGH\t12.4\t11/15/2026 07:00").data
    clock = [datetime(2026, 11, 16, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(print_feedback, "datetime", SimpleNamespace(now=lambda zone: clock[0]))
    before = preparation_signature([sheet], 1, "generation", shared_storage=False)
    clock[0] += timedelta(microseconds=1)
    after = preparation_signature([sheet], 1, "generation", shared_storage=False)
    assert before != after


def render(app, monkeypatch, *, click=False):
    equip(app, monkeypatch)
    events = []
    app.st.button = lambda label, **kw: click and kw.get("key") == "prepare_all_pdf"
    app.st.download_button = lambda label, data, **kw: None
    def download(label, data, *args, **kwargs):
        events.append(("download", kwargs["disabled"], data))
    app.st.download_button = download
    app.st.success = lambda text: events.append(("success", text))
    app.st.error = lambda text: events.append(("error", text))
    app.st.warning = lambda text: events.append(("warning", text))
    app.st.caption = lambda text: events.append(("caption", text))
    app.print_all_page(None)
    return events


def test_ui_requires_prepare_then_reuses_ready_marker_until_selection_changes(app, monkeypatch):
    ss, sheets, statuses, signature, ui = seed(app, monkeypatch)
    first = render(app, monkeypatch)
    assert next(item for item in first if item[0] == "download")[1] is True
    assert app.session_pdf_cache().stats["builds"] == 0
    prepared = render(app, monkeypatch, click=True)
    assert next(item for item in prepared if item[0] == "download")[1] is False
    assert any(item[0] == "success" and "2 handoffs prepared" in item[1] for item in prepared)
    cache = app.session_pdf_cache()
    assert cache.stats["builds"] == 2
    hits = cache.stats["hits"]
    again = render(app, monkeypatch)
    assert next(item for item in again if item[0] == "download")[1] is False
    assert cache.stats["hits"] == hits
    ss["print_rooms"] = ["P4102"]
    changed = render(app, monkeypatch)
    assert next(item for item in changed if item[0] == "download")[1] is True
    assert PREPARATION_KEY not in ss


def test_ui_failure_disables_download_and_preserves_saved_handoffs(app, monkeypatch):
    ss, sheets, statuses, signature, ui = seed(app, monkeypatch)
    before = deepcopy(ss["vault"])
    monkeypatch.setattr(app, "cached_handoffs_pdf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("FAIL")))
    events = render(app, monkeypatch, click=True)
    assert next(item for item in events if item[0] == "download")[1] is True
    assert any(item[0] == "error" and "not prepared" in item[1] for item in events)
    assert not any(item[0] == "success" for item in events)
    assert ss["vault"] == before and PREPARATION_KEY not in ss


def test_ready_ui_reports_overflow_and_print_only_goal_omission_without_refitting(app, monkeypatch):
    ss, sheets, statuses, signature, ui = seed(app, monkeypatch)
    calls = []
    def packet(*args, **kwargs):
        calls.append("prepare")
        for pages, omitted in ((1, True), (2, True)):
            kwargs["on_report"]({"page_count": pages, "target_met": pages == 1,
                                 "goals_omitted": omitted, "compact_secondary": True})
        kwargs["on_progress"](2, 2, "complete")
        return b"%PDF-SYNTHETIC_UI_TEST"
    monkeypatch.setattr(app, "cached_handoffs_pdf", packet)
    events = render(app, monkeypatch, click=True)
    assert any(kind == "warning" and "1 handoff exceeds the 1-page target" in text
               for kind, text, *unused in events)
    assert any(kind == "caption" and "omitted from 2 printed handoffs" in text
               and "Saved notes are kept" in text for kind, text, *unused in events)
    assert any(kind == "success" and "3 pages" in text for kind, text, *unused in events)
    assert ss[PREPARATION_KEY]["pages"] == 3
    assert ss[PREPARATION_KEY]["overflow"] == 1
    assert ss[PREPARATION_KEY]["goals_omitted"] == 2
    render(app, monkeypatch)
    assert calls == ["prepare"]


def test_optional_page_fit_explains_goals_and_secondary_compaction(app, monkeypatch):
    equip(app, monkeypatch)
    events = []
    app.st.caption = lambda text: events.append(("caption", text))
    app.st.warning = lambda text: events.append(("warning", text))
    report = {"page_count": 2, "target_met": False, "goals_omitted": True,
              "compact_secondary": True}
    cache = SimpleNamespace(prepare=lambda *a, **k: SimpleNamespace(report=report))
    monkeypatch.setattr(app, "session_pdf_cache", lambda: cache)
    app.render_print_fit([new_sheet("P4102")], 1)
    assert any("remaining clinical content" in text for kind, text in events if kind == "warning")
    assert any("Goals / Follow-up is omitted" in text for kind, text in events)
    assert any("Other Medications and Devices use compact" in text for kind, text in events)


def test_print_navigation_saves_without_invisible_pdf_warming(app, monkeypatch):
    ss, sheets, statuses, signature, ui = seed(app, monkeypatch)
    ss["current_room"] = "P4102"
    ss["room_choice"] = "P4102"
    ss["drafts"]["P4102"]["fields"]["Neurologic"] = "LATEST_SYNTHETIC_EDIT"
    ss["drafts"]["P4104"]["fields"]["Neurologic"] = "SECOND_SYNTHETIC_EDIT"
    calls = []
    monkeypatch.setattr(app, "warm_handoff_pdf", lambda sheet: calls.append(sheet["room"]))
    assert app.autosave_before_print_all(None)
    assert calls == []
    assert ss["vault"]["rooms"]["P4102"]["fields"]["Neurologic"] == "LATEST_SYNTHETIC_EDIT"
    assert ss["vault"]["rooms"]["P4104"]["fields"]["Neurologic"] == "SECOND_SYNTHETIC_EDIT"


def test_reset_removes_ready_marker_and_closes_prepared_cache(app, monkeypatch):
    ss, sheets, statuses, signature, ui = seed(app, monkeypatch)
    app.prepare_print_packet(sheets, None, target_pages=1, save_statuses=statuses, signature=signature)
    cache = app.session_pdf_cache()
    app.discard_all_handoff_state()
    assert PREPARATION_KEY not in ss and cache.closed
