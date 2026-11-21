"""Synthetic checks for an independent, same-paste ventilator fallback."""
from copy import deepcopy
from html import unescape
from io import BytesIO
import json
import re

import pytest
from pypdf import PdfReader

import ventilation
from exports import handoff_html, handoff_pdf, handoff_text
from importing import import_replacement
from models import new_sheet, new_vault, save_sheet_in
from noninvasive import parse_respiratory
from security import generate_key, open_vault, seal_vault
from workspace_ui import alert_rows
from test_callbacks import app, open_room


PRVC = "Volume Targeted Pressure Control - Intermittent Mandatory Ventilation"
NAVA = "Neurally Adjusted Ventilatory Assist"
PS_CPAP = "Pressure Support - Continuous Positive Airway Pressure"
FALLBACK_NOTE = "Mode history unavailable. Showing first reported settings from this paste. Latest mode unconfirmed."
PRIVATE_EXCEPTION = "SYNTHETIC_PRIVATE_HISTORY_TRACE"
D_ETT = "Non-invasive Ventilation:\nO2 Delivery Method: Endotracheal tube\nFiO2 (%): 21 %"


def block(letter, text):
    marker = letter * 24
    return marker + "\n" + text.rstrip() + "\n" + marker + "\n"


def c_source(mode=PRVC, fio2="46 %", volume="90 mL", on=""):
    return f"""Invasive Ventilation:
Mode: Vent Mode: {mode}
Ventilator On: {on}
Respiratory Rate: Resp Rate (Set): 18
Set TV: Vt (Set, mL): {volume}
Set PEEP: PEEP (cm H2O): 5 cm H2O
FiO2: FiO2 set (%): {fio2}
Pressure Support: Pressure Support (cm H2O): 10 cm H20
NAVA Ventilator Settings:
NAVA Level: NAVA level: 2.5
Set PEEP: PEEP (cm H2O): 6 cm H2O
Set FIO2: FiO2 (%): 29 %
CPAP Trial Settings:
Pressure Support: Pressure Support (cm H2O): 8 cm H20
Set PEEP: PEEP (cm H2O): 7 cm H2O
FiO2: FiO2 set (%): 41 %
All Vent Modes:
Vent Mode: {PRVC} (11/20/26 0600 : SYNTHETIC_AUTHOR, RRT)
Vent Mode: {PRVC} (11/20/26 1800 : SYNTHETIC_AUTHOR, RRT)
Vent Mode: {NAVA} (11/20/26 1900 : SYNTHETIC_AUTHOR, RRT)
Vent Mode: {PS_CPAP} (11/20/26 1500 : SYNTHETIC_AUTHOR, RRT)
"""


def full_source(c=None, d=D_ETT):
    return (block("a", "Diagnoses:\n1. SYNTHETIC_NEW_RECORD")
            + block("c", c if c is not None else c_source()) + block("d", d))


@pytest.fixture
def broken_history(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError(PRIVATE_EXCEPTION)

    monkeypatch.setattr(ventilation, "_history_context", fail)


def assert_first_snapshot(data):
    assert data["mode"] == PRVC
    assert data["values"]["FiO2 set (%)"] == "46 %"
    assert data["values"]["PEEP (cm H2O)"] == "5 cm H2O"
    assert data["values"]["Vt (Set, mL)"] == "90 mL"
    assert "NAVA level" not in data["values"]
    assert data["mode_history"] == {
        "reported_at": "", "other_modes": [], "latest_confirmed": False,
        "notes": [FALLBACK_NOTE],
    }
    text = ventilation.format_ventilation(data)
    assert text.splitlines()[0] == "Mode: PRVC-IMV"
    assert "Mode: NAVA" not in text and "Mode: PS-CPAP" not in text
    assert "FiO2: 29 %" not in text and "FiO2: 41 %" not in text and "FiO2: 21 %" not in text
    assert FALLBACK_NOTE in text


def test_healthy_history_still_selects_latest_mode_without_fallback():
    result = parse_respiratory(c_source(), D_ETT)
    assert not result.error
    assert result.history_fallback is False
    assert result.invasive["mode"] == NAVA
    assert result.invasive["values"]["FiO2 (%)"] == "29 %"
    assert result.invasive["mode_history"]["reported_at"] == "2026-11-20T19:00"
    assert result.invasive["mode_history"]["latest_confirmed"] is True
    assert result.source_fields["mode"] == NAVA
    assert FALLBACK_NOTE not in result.issues


def test_history_exception_automatically_uses_independent_first_snapshot(broken_history, capsys, caplog):
    result = parse_respiratory(c_source(), D_ETT)
    assert not result.error, result.error
    assert result.history_fallback is True
    assert result.devices == []
    assert result.source_fields["mode"] == PRVC
    assert result.source_fields["fio2_set"] == "46 %"
    assert_first_snapshot(result.invasive)
    assert FALLBACK_NOTE in result.issues
    captured = capsys.readouterr()
    assert PRIVATE_EXCEPTION not in repr(result) + captured.out + captured.err + caplog.text


def test_forced_fallback_bypasses_history_failure_through_full_import_and_sbs(broken_history):
    result = import_replacement("P4102", full_source(), new_vault()["settings"], respiratory_first_reported=True)
    assert not result.errors, result.errors
    assert result.sheet is not None
    assert_first_snapshot(result.sheet["ventilation"])
    assert result.sheet["sbs_vent_mode"] == PRVC
    assert result.sheet["fields"]["Diagnoses"] == "SYNTHETIC_NEW_RECORD"
    assert FALLBACK_NOTE in result.notices


def test_automatic_fallback_import_uses_returned_source_fields_for_sbs(broken_history):
    result = import_replacement("P4102", full_source(), new_vault()["settings"])
    assert not result.errors, result.errors
    assert result.sheet is not None
    assert result.sheet["sbs_vent_mode"] == PRVC
    assert_first_snapshot(result.sheet["ventilation"])
    assert "respiratory support" in result.imported


class MemoryStore:
    def __init__(self, vault):
        self.vault = deepcopy(vault)
        self.writes = []

    def save(self, candidate, sha):
        self.writes.append(deepcopy(candidate))
        self.vault = deepcopy(candidate)
        return "synthetic-saved-sha"


def test_app_fallback_replaces_only_selected_room_with_new_paste_and_warning(app, broken_history):
    ss = app.st.session_state
    old = new_sheet("P4102")
    old["fields"]["Respiratory"] = "SYNTHETIC_OLD_MANUAL_NOTE"
    old["ventilation"] = {"mode": "Pressure Control", "values": {"FiO2 set (%)": "99 %", "PEEP (cm H2O)": "19"}}
    other = new_sheet("P4104")
    other["fields"]["Diagnoses"] = "SYNTHETIC_OTHER_ROOM"
    ss["vault"] = save_sheet_in(save_sheet_in(new_vault(), old), other)
    other_before = deepcopy(ss["vault"]["rooms"]["P4104"])
    settings_before = deepcopy(ss["vault"]["settings"])
    store = MemoryStore(ss["vault"])
    open_room(app)
    old_id = ss["drafts"]["P4102"]["id"]
    ss[app.edit_key(ss["drafts"]["P4102"], "Respiratory")] = "SYNTHETIC_OLD_UNSAVED_NOTE"
    ss["paste"] = full_source()
    assert app.respiratory_parser_ready() is False
    assert app.respiratory_fallback_ready() is True

    app.create_handoff(store)

    assert len(store.writes) == 1
    assert store.vault == ss["vault"]
    assert ss["paste"] == ""
    saved = ss["vault"]["rooms"]["P4102"]
    assert saved == ss["drafts"]["P4102"]
    assert saved["id"] != old_id
    assert saved["fields"]["Respiratory"] == ""
    assert_first_snapshot(saved["ventilation"])
    assert saved["sbs_vent_mode"] == PRVC
    assert "SYNTHETIC_OLD_" not in json.dumps(saved)
    assert ss["vault"]["rooms"]["P4104"] == other_before
    assert ss["vault"]["settings"] == settings_before
    assert not ss["import_result"]["errors"]
    assert FALLBACK_NOTE in ss["import_result"]["notices"]
    assert ss["notice"][0] == "warning"


def test_blank_first_settings_are_not_filled_from_other_modes_or_d_block(broken_history):
    result = parse_respiratory(c_source(fio2="", volume=""), D_ETT)
    assert not result.error
    assert result.invasive["mode"] == PRVC
    values = result.invasive["values"]
    assert "FiO2 set (%)" not in values and "FiO2 (%)" not in values
    assert "Vt (Set, mL)" not in values
    assert "NAVA level" not in values
    assert values["PEEP (cm H2O)"] == "5 cm H2O"


@pytest.mark.parametrize("forced", [False, True])
def test_fallback_cannot_bypass_conflicting_d_block_fields(broken_history, forced):
    result = parse_respiratory(c_source(), D_ETT + "\nFiO2 (%): 88 %", first_reported_only=forced)
    assert result.error
    assert result.invasive is None
    assert result.devices == []


def test_fallback_cannot_choose_between_conflicting_first_settings(broken_history):
    text = c_source().replace("FiO2: FiO2 set (%): 46 %", "FiO2: FiO2 set (%): 46 %\nFiO2 set (%): 88 %", 1)
    result = parse_respiratory(text, D_ETT)
    assert result.error
    assert result.invasive is None
    assert result.devices == []


def test_ventilator_off_does_not_become_invasive_support_in_fallback(broken_history):
    text = c_source(on="Off")
    parsed = parse_respiratory(text, D_ETT)
    assert parsed.error
    assert parsed.invasive is None
    assert parsed.devices == []
    result = import_replacement("P4102", full_source(text), new_vault()["settings"])
    assert result.errors
    assert result.sheet["ventilation"] is None
    assert result.sheet.get("sbs_vent_mode", "") == ""


def test_explicit_niv_snapshot_is_not_recast_as_invasive_when_history_fails(broken_history):
    mode = "Bilevel Non Invasive Ventilation"
    d_source = """Non-invasive Ventilation:
O2 Delivery Method: CPAP/Bi-PAP mask
Total Inspiratory Pressure (cm H2O): 14 cmH20
Expiratory Positive Airway Pressure (EPAP) (cmH20): 7 cmH20
FiO2 (%): 35 %
"""
    result = parse_respiratory(c_source(mode=mode), d_source)
    assert result.error
    assert result.invasive is None
    assert result.devices == []
    assert result.history_fallback is False


@pytest.mark.parametrize("delivery", ["HHFNC", "CPAP", "BiPAP"])
def test_noninvasive_delivery_aliases_cannot_enable_an_invasive_fallback(broken_history, delivery):
    d_source = "Non-invasive Ventilation:\nO2 Delivery Method: " + delivery + "\nFiO2 (%): 35 %"
    result = parse_respiratory(c_source(), d_source)
    assert result.error
    assert result.invasive is None
    assert result.devices == []


def test_fallback_warning_survives_saved_outputs_and_encrypted_reload(broken_history):
    result = import_replacement("P4102", full_source(), new_vault()["settings"])
    assert not result.errors
    sheet = result.sheet
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    sealed = seal_vault(vault, key)
    assert FALLBACK_NOTE.encode() not in sealed
    restored = open_vault(sealed, key)
    assert restored == vault
    saved = restored["rooms"]["P4102"]
    assert_first_snapshot(saved["ventilation"])
    assert ("warning", FALLBACK_NOTE) in alert_rows(saved, {})
    html = unescape(re.sub(r"<[^>]*>", "", handoff_html(saved)))
    pdf = PdfReader(BytesIO(handoff_pdf(saved)))
    pdf_text = re.sub(r"\s+", " ", " ".join(page.extract_text() for page in pdf.pages))
    for text in (handoff_text(saved), html, pdf_text):
        assert FALLBACK_NOTE in text
        assert "Mode: PRVC-IMV" in text
        assert "Mode: NAVA" not in text and "Mode: PS-CPAP" not in text
        assert "SYNTHETIC_AUTHOR" not in text and PRIVATE_EXCEPTION not in text
    assert ventilation.VENTILATION_HISTORY_FALLBACK_NOTE == FALLBACK_NOTE

