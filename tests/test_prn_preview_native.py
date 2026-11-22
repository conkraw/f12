"""Full Streamlit automatic paralytic import, preview, and save regressions."""
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
import json
import time

import pytest
from streamlit.testing.v1 import AppTest

import lab_windows
from security import hash_password
from error_store import APP_VERSION, validate_event
from prn_counts import prn_counts
from test_prn_integration import NOW, source


APP_PATH = Path(__file__).parents[1] / "app.py"
SYNTHETIC_IMPORT = source(af=(
    "TIME\tANALGESIA\tSEDATIVES\tPARALYTICS\n"
    "0141\tVolume (mL) Hydromorphone: 1.05 mL "
    "(11/22/26 0141 : SYNTHETIC_CLINICIAN, RN)\t"
    "Volume (mL) Midazolam: 1 mL (11/22/26 0141 : SYNTHETIC_CLINICIAN, RN)\t"
    "Volume (mL) Vecuronium: 2 mL (11/22/26 0141 : SYNTHETIC_CLINICIAN, RN)\n"
    "0230\t\t\tVolume (mL) Rocuronium: 1 mL (11/22/26 0230 : SYNTHETIC_CLINICIAN, RN)"))


@pytest.fixture
def native_app(monkeypatch):
    # AppTest runs on its own thread, so give the display clock a fixed default.
    monkeypatch.setattr(lab_windows, "_WINDOW_TIME", ContextVar("native_prn_clock", default=NOW))
    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.secrets["app"] = {"password_hash": hash_password("synthetic-preview-test-password")}
    now = time.monotonic()
    for key, value in dict(authenticated=True, last_activity=now,
                          login_at=now, patient_list_ready=True).items():
        at.session_state[key] = value
    at.run()
    assert not at.exception and not at.error
    at.selectbox(key="room_choice").select("P4102").run()
    assert not at.exception and not at.error
    return at


def import_source(at, text=SYNTHETIC_IMPORT):
    at.text_area(key="paste").set_value(text)
    next(button for button in at.button if button.label == "Replace room handoff").click().run()
    assert not at.exception, [item.message for item in at.exception]
    assert not at.error, [item.value for item in at.error]


def test_native_full_import_counts_paralytics_without_review_and_saves(native_app):
    at = native_app
    import_source(at)
    sheet = deepcopy(at.session_state["drafts"]["P4102"])
    assert len(sheet["prn"]["events"]) == 2
    assert {event["medication"] for event in sheet["prn"]["events"]} == {"vecuronium", "rocuronium"}
    assert sheet["prn"]["reviewed"] == {}
    assert prn_counts(sheet, NOW) == {"vecuronium": 1, "rocuronium": 1}
    assert at.session_state["vault"]["rooms"]["P4102"] == sheet
    assert at.session_state["paste"] == ""
    assert not any("PRN counts need review" in caption.value for caption in at.caption)
    assert not any("Confirm" in button.label and "PRN" in button.label for button in at.button)
    assert any(item.proto.label == "Download this handoff (PDF)" for item in at.get("download_button"))
    preview = next(item.proto.srcdoc for item in at.get("iframe") if "Synthetic PRN print example" in item.proto.srcdoc)
    assert preview.count('data-prn-count="') == 2
    assert preview.count(" × 1</span>") == 2

    next(button for button in at.button if button.label == "Save handoff").click().run()
    assert not at.exception and not at.error
    assert at.session_state["drafts"]["P4102"]["prn"] == sheet["prn"]
    assert at.session_state["vault"]["rooms"]["P4102"]["prn"] == sheet["prn"]


def test_native_medications_tab_has_no_prn_review_or_confirmation_controls(native_app):
    at = native_app
    import_source(at)
    at.session_state["handoff_tab"] = "Medications"
    at.run()
    assert not at.exception and not at.error
    assert any("Choose one destination per order" in caption.value for caption in at.caption)
    assert not any("PRN review" in item.label for item in at.selectbox)
    assert not any("Confirm" in button.label and "PRN" in button.label for button in at.button)
    assert not any("PRN counts" == item.label for item in at.expander)
    assert not at.data_editor
    assert not any("Verify actual administration" in caption.value for caption in at.caption)


def test_native_8am_import_keeps_overnight_counts_and_excludes_7am_entries(native_app, monkeypatch):
    at = native_app
    printed_at = NOW.replace(hour=8)
    monkeypatch.setattr(lab_windows, "_WINDOW_TIME", ContextVar("native_capped_prn_clock", default=printed_at))
    body = "\n".join(
        "Volume (mL) " + drug + ": 1 mL (" + stamp + " : SYNTHETIC_CLINICIAN, RN)"
        for drug in ("Vecuronium", "Rocuronium")
        for stamp in ("11/21/26 0700", "11/22/26 0141", "11/22/26 0659", "11/22/26 0700")
    )
    import_source(at, source(af=body))
    sheet = deepcopy(at.session_state["vault"]["rooms"]["P4102"])
    assert len(sheet["prn"]["events"]) == 8
    assert sheet["prn"]["reviewed"] == {}
    assert prn_counts(sheet, printed_at) == {"vecuronium": 3, "rocuronium": 3}
    preview = next(item.proto.srcdoc for item in at.get("iframe") if "Synthetic PRN print example" in item.proto.srcdoc)
    assert preview.count('data-prn-count="') == 2
    assert preview.count(" × 3</span>") == 2
    assert not any("Confirm" in button.label and "PRN" in button.label for button in at.button)
    next(button for button in at.button if button.label == "Save handoff").click().run()
    assert not at.exception and not at.error
    assert at.session_state["vault"]["rooms"]["P4102"]["prn"] == sheet["prn"]


def test_native_import_warning_is_recorded_without_blocking_preview_or_save(native_app):
    at = native_app
    malformed = source(af="Volume (mL) Vecuronium: 1 mL (missing date)")
    import_source(at, malformed)
    sheet = deepcopy(at.session_state["drafts"]["P4102"])
    assert sheet["fields"]["Diagnoses"] == "Synthetic PRN print example"
    assert sheet.get("prn") is None
    assert "af" in sheet["import_warnings"]
    assert at.session_state["vault"]["rooms"]["P4102"] == sheet
    assert at.session_state["paste"] == ""
    pending = at.session_state["pending_error_events"]
    assert len(pending) == 1
    record = next(iter(pending.values()))
    validate_event(record)
    assert record["app_version"] == APP_VERSION
    assert record["diagnostics"]
    assert "Synthetic PRN print example" not in json.dumps(record)
    assert "Vecuronium" not in json.dumps(record)
    assert any("Synthetic PRN print example" in item.proto.srcdoc for item in at.get("iframe"))

    next(button for button in at.button if button.label == "Save handoff").click().run()
    assert not at.exception and not at.error
    assert "af" in at.session_state["vault"]["rooms"]["P4102"]["import_warnings"]
