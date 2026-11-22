"""PRN review validation and explicit form submission with synthetic events."""
from copy import deepcopy
from datetime import datetime
import sys
import types

import pytest

import prn_counts as core
from prn_ui import (prepare_prn_review, prn_editor_rows, prn_widget_token,
                    render_prn_editor)


NOW = datetime.fromisoformat("2026-11-22T04:00:00-05:00")


def event(drug="hydromorphone", stamp="2026-11-22T01:41:00-05:00", doses=None):
    return {"medication": drug, "timestamp": stamp, "volume_ml": 1.05,
            "dose_count": doses, "source": "volume"}


def data(*events):
    result = core.empty_prn()
    result["events"] = list(events)
    return result


def test_unresolved_source_needs_a_dose_decision():
    original = data(event())
    with pytest.raises(ValueError, match="Resolve every"):
        prepare_prn_review(original, "hydromorphone", prn_editor_rows(original, "hydromorphone"), as_of=NOW)
    assert original["events"][0]["dose_count"] is None
    assert original["reviewed"] == {}


def test_confirmed_doses_exclude_infusion_and_preserve_other_medication():
    original = data(event(), event(stamp="2026-11-22T02:00:00-05:00"),
                    event("midazolam", doses=1))
    original = core.confirm_review(original, ["midazolam"], as_of=NOW)
    before = deepcopy(original)
    rows = prn_editor_rows(original, "hydromorphone")
    rows[0]["dose_count"] = 1
    rows[1]["dose_count"] = 0
    reviewed = prepare_prn_review(original, "hydromorphone", rows, as_of=NOW)
    assert core.prn_counts({"prn": reviewed}, as_of=NOW) == {"hydromorphone": 1, "midazolam": 1}
    assert reviewed["reviewed"]["midazolam"] == before["reviewed"]["midazolam"]
    assert original == before


def test_manual_missing_administration_and_time_correction():
    original = data(event())
    rows = prn_editor_rows(original, "hydromorphone")
    rows[0].update(timestamp="2026-11-22 03:00", dose_count=1)
    rows.append({"timestamp": "2026-11-21 23:30", "dose_count": 2})
    reviewed = prepare_prn_review(original, "hydromorphone", rows, as_of=NOW)
    assert core.prn_counts({"prn": reviewed}, as_of=NOW) == {"hydromorphone": 3}
    assert reviewed["events"][0]["timestamp"] == "2026-11-22T03:00:00-05:00"
    assert reviewed["events"][1]["source"] == "manual"
    assert reviewed["events"][1]["volume_ml"] is None


def test_readonly_volume_cannot_be_changed_through_editor_payload():
    original = data(event())
    rows = prn_editor_rows(original, "hydromorphone")
    rows[0].update(dose_count=1, volume_ml=1000)
    reviewed = prepare_prn_review(original, "hydromorphone", rows, as_of=NOW)
    assert reviewed["events"][0]["volume_ml"] == 1.05


@pytest.mark.parametrize("value", [-1, 1.5, True, 101, float("inf"), "two"])
def test_invalid_counts_are_rejected(value):
    original = data(event())
    rows = prn_editor_rows(original, "hydromorphone")
    rows[0]["dose_count"] = value
    with pytest.raises(ValueError, match="whole number"):
        prepare_prn_review(original, "hydromorphone", rows, as_of=NOW)


def test_missing_time_is_rejected_and_new_blank_row_is_ignored():
    with pytest.raises(ValueError, match="date and time"):
        prepare_prn_review(data(), "morphine", [{"timestamp": "", "dose_count": 1}], as_of=NOW)
    reviewed = prepare_prn_review(data(), "morphine", [{"timestamp": "", "dose_count": None}], as_of=NOW)
    assert core.prn_counts({"prn": reviewed}, as_of=NOW) == {"morphine": 0}


def test_unknown_or_repeated_source_reference_is_rejected():
    original = data(event())
    rows = prn_editor_rows(original, "hydromorphone")
    rows[0]["dose_count"] = 1
    with pytest.raises(ValueError, match="reference"):
        prepare_prn_review(original, "hydromorphone", rows + rows, as_of=NOW)
    rows[0]["__row"] = 1
    with pytest.raises(ValueError, match="reference"):
        prepare_prn_review(original, "hydromorphone", rows, as_of=NOW)


def test_form_cannot_confirm_previous_day_after_seven_am():
    old_start, _ = core.prn_window(NOW)
    with pytest.raises(ValueError, match="day changed"):
        prepare_prn_review(data(), "fentanyl", [], expected_window=old_start.isoformat(),
                           as_of=datetime.fromisoformat("2026-11-22T07:00:00-05:00"))


def test_unchanged_repeated_dst_hour_preserves_explicit_offset():
    first_fold = event(stamp="2026-11-01T01:30:00-04:00", doses=1)
    second_fold = event(stamp="2026-11-01T01:30:00-05:00", doses=1)
    original = data(first_fold, second_fold)
    now = datetime.fromisoformat("2026-11-01T04:00:00-05:00")
    reviewed = prepare_prn_review(original, "hydromorphone", prn_editor_rows(original, "hydromorphone"), as_of=now)
    assert [row["timestamp"] for row in reviewed["events"]] == [first_fold["timestamp"], second_fold["timestamp"]]
    assert core.prn_counts({"prn": reviewed}, as_of=now) == {"hydromorphone": 2}


def test_future_unresolved_record_does_not_turn_into_a_count_later():
    original = data(event(stamp="2026-11-22T05:00:00-05:00"))
    reviewed = prepare_prn_review(original, "hydromorphone", prn_editor_rows(original, "hydromorphone"), as_of=NOW)
    assert core.prn_counts({"prn": reviewed}, as_of=NOW) == {"hydromorphone": 0}
    assert core.prn_counts({"prn": reviewed}, as_of=datetime.fromisoformat("2026-11-22T05:01:00-05:00")) == {}


def test_widget_identity_changes_with_patient_day_and_source():
    sheet = {"id": "a" * 32, "prn": data(event())}
    start, _ = core.prn_window(NOW)
    token = prn_widget_token(sheet, start)
    changed = deepcopy(sheet)
    changed["prn"]["events"][0]["dose_count"] = 1
    assert prn_widget_token(changed, start) != token
    assert prn_widget_token(dict(sheet, id="b" * 32), start) != token
    next_start, _ = core.prn_window(datetime.fromisoformat("2026-11-22T08:00:00-05:00"))
    assert prn_widget_token(sheet, next_start) != token


class Context:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def stub_ui(monkeypatch, submitted=False):
    stub = types.ModuleType("streamlit")
    stub.messages, stub.errors, stub.reruns = [], [], []
    stub.expander = lambda *args, **kwargs: Context()
    stub.form = lambda *args, **kwargs: Context()
    stub.caption = stub.messages.append
    stub.error = stub.errors.append
    stub.selectbox = lambda _label, choices, **kwargs: choices[0]
    stub.data_editor = lambda frame, **kwargs: frame.assign(dose_count=1)
    stub.form_submit_button = lambda *args, **kwargs: submitted
    stub.rerun = lambda: stub.reruns.append(True)
    stub.column_config = types.SimpleNamespace(TextColumn=lambda *args, **kwargs: None,
                                               NumberColumn=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "streamlit", stub)
    real_window = core.prn_window
    monkeypatch.setattr(core, "prn_window", lambda as_of=None: real_window(as_of or NOW))
    return stub


def test_form_does_not_apply_unsubmitted_edits(monkeypatch):
    stub = stub_ui(monkeypatch)
    updates = []
    sheet = {"id": "a" * 32, "prn": data(event())}
    render_prn_editor(sheet, updates.append)
    assert not updates and not stub.errors and not stub.reruns
    assert sheet["prn"]["events"][0]["dose_count"] is None


def test_form_applies_confirmed_medication_once(monkeypatch):
    stub = stub_ui(monkeypatch, submitted=True)
    updates = []
    render_prn_editor({"id": "a" * 32, "prn": data(event())}, updates.append)
    assert len(updates) == 1 and len(stub.reruns) == 1 and not stub.errors
    assert core.prn_counts({"prn": updates[0]}, as_of=NOW) == {"hydromorphone": 1}


def test_callback_rejection_keeps_form_and_reports_error(monkeypatch):
    stub = stub_ui(monkeypatch, submitted=True)
    def reject(_candidate):
        raise ValueError("The room changed. Reopen the review.")
    render_prn_editor({"id": "a" * 32, "prn": data(event())}, reject)
    assert stub.errors == ["The room changed. Reopen the review."]
    assert not stub.reruns
