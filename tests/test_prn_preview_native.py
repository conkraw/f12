"""Full Streamlit import, preview, and save regression with synthetic PRN data."""
from copy import deepcopy
from pathlib import Path
import time

import pytest
from streamlit.testing.v1 import AppTest

from security import hash_password
from test_prn_integration import source


APP_PATH = Path(__file__).parents[1] / "app.py"
SYNTHETIC_IMPORT = source(af=(
    "TIME\tANALGESIA\tSEDATIVES\tPARALYTICS\n"
    "0141\tVolume (mL) Hydromorphone: 1.05 mL "
    "(11/22/26 0141 : SYNTHETIC_CLINICIAN, RN)\t\t\n"))


@pytest.fixture
def native_app():
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


def test_native_full_import_with_prns_renders_preview_and_saves(native_app):
    at = native_app
    at.text_area(key="paste").set_value(SYNTHETIC_IMPORT)
    next(button for button in at.button if button.label == "Replace room handoff").click().run()
    assert not at.exception
    assert not at.error, [item.value for item in at.error]
    sheet = deepcopy(at.session_state["drafts"]["P4102"])
    assert len(sheet["prn"]["events"]) == 1
    assert sheet["prn"]["events"][0]["dose_count"] is None
    assert at.session_state["vault"]["rooms"]["P4102"] == sheet
    assert at.session_state["paste"] == ""
    assert any("Some PRN counts need review" in caption.value for caption in at.caption)
    assert any(item.proto.label == "Download this handoff (PDF)" for item in at.get("download_button"))
    assert any("Synthetic PRN print example" in item.proto.srcdoc for item in at.get("iframe"))

    next(button for button in at.button if button.label == "Save handoff").click().run()
    assert not at.exception and not at.error
    assert at.session_state["drafts"]["P4102"]["prn"] == sheet["prn"]
    assert at.session_state["vault"]["rooms"]["P4102"]["prn"] == sheet["prn"]
