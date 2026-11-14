"""Synthetic AVAPS import, editor, encrypted recall and export checks."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import re

import fitz
import pytest

from batching import available_handoffs
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_html, handoffs_pdf
from importing import import_sections
from models import (new_sheet, new_vault, save_sheet_in, validate_sheet,
                    fields_with_medications, respiratory_text, SCHEMA_VERSION)
from security import generate_key, open_vault, seal_vault
from ventilation import LABELS, format_ventilation
from test_callbacks import app, open_room
from test_ui_smoke import equip


C = """Invasive Ventilation:
Mode: Vent Mode: Average Volume-Assured Pressure Support
Respiratory Rate:
Set PIP:
Observed PIP: No data recorded
Set TV:
Observed TV: No data recorded
Set PEEP:
Inspiratory Time:
FiO2:
Pressure Support:
Home Ventilator Settings:
Pmin:
Pmax:
Timin:
Timax:
Average Volume-Assured Pressure Support Settings:
AVAPS Respiratory Rate: AVAPS rate (cm H2O/min): 3
AVAPS Target TV: Vt Set/Target ml: 130
Observed AVAPS TV: Vt (observed, mL): 145 mL
PS Max: Pressure Support Max (cm H2O): 24 cm H2O
PS Min: Pressure Support Min (cm H2O): 9 cm H2O"""
D = """Non-invasive Ventilation:
O2 Delivery Method: Trach tube, Other (Comment) (home vent)
FiO2 (%): 35 %"""
E = """VITALS:
Resp: [20-40] 28
FiO2 (%): [30 %-35 %] 35 %
SpO2 Avg: 96 % Min: 94 % Max: 99 %
Last SPO2: SpO2: 97 %
NIRS Range: No data recorded
Last NIRS:"""
EXPECTED = """Mode: AVAPS
AVAPS rate: 3 cm H2O/min
Target TV: 130 mL
Observed TV: 145 mL
PS Min: 9 cm H2O
PS Max: 24 cm H2O"""
NEW_LABELS = (
    "AVAPS rate (cm H2O/min)", "AVAPS Respiratory Rate", "Vt Set/Target ml",
    "Pressure Support Min (cm H2O)", "Pressure Support Max (cm H2O)",
    "AVAPS Observed TV (mL)",
)


def block(letter, body):
    return letter * 24 + "\n" + body + "\n" + letter * 24


def imported(c=C, d=D, extra="", old=None, room="P4102"):
    source = block("c", c) + "\n" + block("d", d) + "\n" + extra
    result = import_sections(old or new_sheet(room), source, new_vault()["settings"])
    assert not result.errors and not result.skipped, result.errors
    return result.sheet


def test_exact_source_structure_uses_avaps_fields_and_keeps_fio2_in_vitals():
    sheet = imported(extra=block("e", E) + "\n" + block("z", "No results found for this or any previous visit from the past 365 days."))
    assert format_ventilation(sheet["ventilation"]) == EXPECTED
    assert not sheet["noninvasive"]
    assert "FiO2" not in format_ventilation(sheet["ventilation"])
    assert "FiO2" in fields_with_medications(sheet)["Respiratory"]
    assert "35 %" in fields_with_medications(sheet)["Respiratory"]
    assert "NIRS" not in fields_with_medications(sheet)["Neurologic"]
    assert sheet["ecg"] is None
    assert "Vent Settings\n" + EXPECTED == respiratory_text(sheet)


def test_source_settings_roundtrip_and_old_archives_stay_valid():
    old = new_vault()
    old["rooms"]["P4104"] = new_sheet("P4104")
    key = generate_key()
    assert open_vault(seal_vault(old, key), key) == old
    sheet = imported()
    sheet["fields"]["Respiratory"] = "Synthetic separate respiratory note"
    before = deepcopy(sheet)
    vault = save_sheet_in(old, sheet)
    token = seal_vault(vault, key)
    loaded = open_vault(token, key)
    assert loaded == vault and loaded["schema"] == SCHEMA_VERSION == 34
    assert format_ventilation(loaded["rooms"]["P4102"]["ventilation"]) == EXPECTED
    assert sheet == before and "AVAPS rate" not in token.decode()
    assert "P4102" in available_handoffs(loaded, {})


@pytest.mark.parametrize("label", NEW_LABELS)
def test_every_appended_field_supports_edit_pending_capture_and_save(app, label):
    open_room(app)
    sheet = imported()
    app.set_editor("P4102", sheet)
    ss = app.st.session_state
    key = "vent_" + sheet["id"] + "_" + str(LABELS.index(label))
    ss[key] = "7"
    app.ventilation_change("P4102", label, key)
    assert ss["drafts"]["P4102"]["ventilation"]["values"][label] == "7"
    ss[key] = "8"
    snapshot = app.editor_snapshot("P4102")
    validate_sheet(snapshot)
    assert snapshot["ventilation"]["values"][label] == "8"
    vault = save_sheet_in(new_vault(), snapshot)
    encryption_key = generate_key()
    assert open_vault(seal_vault(vault, encryption_key), encryption_key) == vault


def test_avaps_to_pc_clears_previous_settings_and_keeps_notes():
    sheet = imported()
    sheet["fields"]["Respiratory"] = "Synthetic note"
    pc = "Invasive Ventilation:\nMode: Vent Mode: Pressure Control\nSet PIP: PIP Set (cm H2O): 19 cm H2O\nObserved TV: Vt (observed, mL): 70 mL"
    updated = imported(pc, "Non-invasive Ventilation:", old=sheet)
    text = fields_with_medications(updated)["Respiratory"]
    assert "Mode: PC" in text and "Set PIP: 19 cm H2O" in text
    assert "Observed TV: 70 mL" in text and "Synthetic note" in text
    assert "AVAPS" not in text and "Target TV" not in text and "PS Min" not in text
    assert not set(NEW_LABELS) & set(updated["ventilation"]["values"])


def test_conflicting_avaps_field_skips_support_but_accepts_other_sections():
    original = imported()
    before = deepcopy(original)
    source = block("c", C + "\nPS Min: Pressure Support Min (cm H2O): 14 cm H2O") + "\n" + block("e", E)
    result = import_sections(original, source, new_vault()["settings"])
    assert result.errors and result.skipped == ["cd"]
    assert result.sheet["ventilation"] == before["ventilation"]
    assert "cd" in result.sheet["import_warnings"] and result.sheet["vitals"]
    assert original == before


def test_print_preview_and_single_batch_outputs_use_same_values():
    sheet = imported()
    other = imported(C.replace("130", "170").replace("145", "190"), room="P4104")
    before = deepcopy((sheet, other))
    printed = datetime(2026, 11, 14, 3, tzinfo=timezone.utc)
    expected_lines = EXPECTED.splitlines()
    assert all(line in handoff_text(sheet, printed) for line in expected_lines)
    assert all(line in handoff_html(sheet, printed) for line in expected_lines)
    assert "Target TV: 170 mL" in handoffs_html([sheet, other], printed)
    with fitz.open(stream=handoff_pdf(sheet, printed), filetype="pdf") as document:
        text = re.sub(r"\s+", " ", document[0].get_text())
        assert all(line in text for line in expected_lines)
    with fitz.open(stream=handoffs_pdf([sheet, other], printed), filetype="pdf") as document:
        assert len(document) == 2
        first = re.sub(r"\s+", " ", document[0].get_text())
        second = re.sub(r"\s+", " ", document[1].get_text())
        assert "Target TV: 130 mL" in first and "Target TV: 170 mL" not in first
        assert "Target TV: 170 mL" in second and "Target TV: 130 mL" not in second
    assert (sheet, other) == before


def test_full_editor_render_exposes_each_avaps_field_and_can_download(app, monkeypatch):
    open_room(app)
    app.set_editor("P4102", imported())
    downloads = equip(app, monkeypatch)
    app.handoff_page(None)
    sheet = app.st.session_state["drafts"]["P4102"]
    for label in NEW_LABELS:
        assert "vent_" + sheet["id"] + "_" + str(LABELS.index(label)) in app.st.session_state
    assert any(isinstance(data, bytes) and data.startswith(b"%PDF") for _, data in downloads)
