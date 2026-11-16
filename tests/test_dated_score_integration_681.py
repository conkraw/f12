"""6.81 dated-score workflow regressions using synthetic source only."""
from copy import deepcopy
from datetime import datetime, timedelta
from html import unescape
from io import BytesIO
import json
import re

import pytest
from pypdf import PdfReader

from batching import available_handoffs
from exports import handoff_html, handoff_pdf, handoff_text
from importing import import_replacement, import_sections
from lab_windows import EASTERN, display_clock
from models import automatic_vitals, new_vault, save_sheet_in, validate_sheet
from pdf_cache import SessionPdfCache, cached_handoffs_pdf
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room


NOW = datetime(2026, 11, 16, 12, 0, tzinfo=EASTERN)
PC = "Pressure Control - Intermittent Mandatory Ventilation"
PS = "Pressure Support - Continuous Positive Airway Pressure"
STAFF = "SCORE_STAFF_SENTINEL"
K = ("Target Arousal Level:\nSBS Last 24 Hours: Target Arousal Level (SBS): "
     "SBS -2 (11/10/26 0743 : " + STAFF + ", DO)")
Y = ("CAPD: Cornell Assessment of Pediatric Delirium Score: "
     "12 (11/12/26 0937 : " + STAFF + ", RN)")
L = ("WAT Score:\nWAT-1 Total Score\nWAT-1 total score (0-12): "
     "4 (11/13/26 1109 : " + STAFF + ", RN)")


def block(letter, body):
    return letter * 24 + "\n" + body + "\n" + letter * 24


def phrase(*, mode=PC, delivery="Endotracheal tube", removed_ett=False,
           k=K, y=Y, l=L, vent_on="", diagnosis="SYNTHETIC_SCORE_EXAMPLE"):
    parts = [block("a", "Diagnoses:\n1. " + diagnosis)]
    c = "Invasive Ventilation:\nMode: " + ("Vent Mode: " + mode if mode else "")
    if mode:
        c += "\nRespiratory Rate: Resp Rate (Set): 20\nSet PEEP: PEEP (cm H2O): 5"
    if vent_on:
        c += "\nVentilator On: " + vent_on
    parts += [block("c", c), block("d", "Non-invasive Ventilation:\nO2 Delivery Method: " + delivery)]
    if removed_ett:
        parts.append(block("u", "Lines:\nEndotracheal Tube:\n[REMOVED] ETT 5 mm-Secured at (cm): 15 cm"))
    for letter, body in (("k", k), ("y", y), ("l", l)):
        if body is not None:
            parts.append(block(letter, body))
    return "\n".join(parts)


def imported(*, room="P4102", **kwargs):
    with display_clock(NOW):
        result = import_replacement(room, phrase(**kwargs), new_vault()["settings"])
    assert not result.errors, result.errors
    assert result.sheet is not None
    validate_sheet(result.sheet)
    assert STAFF not in json.dumps(result.sheet)
    assert STAFF not in json.dumps(result.notices + result.errors + result.diagnostics)
    return result.sheet


def neuro(sheet, when=NOW):
    with display_clock(when):
        return automatic_vitals(sheet)["Neurologic"]


def pdf_text(data):
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)


def compact(text):
    return re.sub(r"\s+", "", unescape(re.sub(r"<[^>]*>", "", text)))


def render(sheet, kind):
    with display_clock(NOW):
        if kind == "text":
            return handoff_text(sheet, NOW)
        if kind == "html":
            return handoff_html(sheet, NOW)
        return pdf_text(handoff_pdf(sheet, NOW))


@pytest.mark.parametrize("kind", ["text", "html", "pdf"])
@pytest.mark.parametrize("mode", [PC, PS])
def test_old_recorded_scores_render_once_with_source_date_only(kind, mode):
    sheet = imported(mode=mode)
    before = deepcopy(sheet)
    output = compact(render(sheet, kind))
    assert output.count("SBStarget:-2(11/10/26)") == 1
    assert output.count("CAPD:12(H)(11/12/26)") == 1
    assert output.count("WAT-1:4(11/13/26)") == 1
    assert STAFF not in output
    assert "0743" not in output and "0937" not in output and "1109" not in output
    assert "lastavailable" not in output
    assert sheet == before


@pytest.mark.parametrize("mode,delivery,removed_ett", [
    ("", "Nasal cannula", False),
    ("", "High flow nasal cannula", False),
    ("", "Nasal cannula", True),
    ("", "Endotracheal tube", False),
    ("", "Trach tube", False),
    ("Bilevel Non Invasive Ventilation", "Non-invasive ventilation", False),
    ("Continuous Positive Airway Pressure - Non Invasive Ventilation", "Non-invasive ventilation", False),
    ("Average Volume-Assured Pressure Support - Non Invasive Ventilation", "Non-invasive ventilation", False),
])
def test_only_sbs_requires_current_invasive_mode(mode, delivery, removed_ett):
    sheet = imported(mode=mode, delivery=delivery, removed_ett=removed_ett)
    output = neuro(sheet)
    assert "SBS" not in output
    assert "CAPD: 12 (H) (11/12/26)" in output
    assert "WAT-1: 4 (11/13/26)" in output


@pytest.mark.parametrize("flag", ["No", "Off", "False"])
def test_explicit_ventilator_off_suppresses_sbs_but_keeps_other_scores(flag):
    output = neuro(imported(vent_on=flag))
    assert "SBS" not in output
    assert "CAPD: 12 (H) (11/12/26)" in output
    assert "WAT-1: 4 (11/13/26)" in output


@pytest.mark.parametrize("reverse", [False, True])
def test_latest_dates_and_times_win_independently_of_score_and_source_order(reverse):
    krows = ["SBS -3 (11/11/26 1440 : " + STAFF + ", RN)",
             "SBS 1 (11/12/26 0905 : " + STAFF + ", RN)",
             "SBS -1 (11/12/26 0940 : " + STAFF + ", RN)"]
    yrows = ["CAPD: 28 (11/11/26 1440 : " + STAFF + ", RN)",
             "CAPD: 18 (11/12/26 0905 : " + STAFF + ", RN)",
             "CAPD: 3 (11/12/26 0940 : " + STAFF + ", RN)"]
    lrows = ["WAT-1: 8 (11/11/26 1440 : " + STAFF + ", RN)",
             "WAT-1: 5 (11/12/26 0905 : " + STAFF + ", RN)",
             "WAT-1: 1 (11/12/26 0940 : " + STAFF + ", RN)"]
    if reverse:
        krows.reverse()
        yrows.reverse()
        lrows.reverse()
    sheet = imported(k="SBS Last 24 Hours:\n" + "\n".join(krows),
                     y="\n".join(yrows), l="WAT Score:\n" + "\n".join(lrows))
    assert neuro(sheet).splitlines()[:3] == [
        "SBS: -1 (11/12/26)", "CAPD: 3 (11/12/26)", "WAT-1: 1 (11/12/26)",
    ]
    assert len(sheet["neuro_vitals"]["y"]) == 1
    assert len(sheet["neuro_vitals"]["l"]) == 1


def test_zero_scores_remain_recorded_values_with_dates():
    sheet = imported(k="SBS Last 24 Hours: SBS 0 (11/12/26 0900 : " + STAFF + ", RN)",
                     y="CAPD: 0 (11/12/26 0900 : " + STAFF + ", RN)",
                     l="WAT Score:\nWAT-1: 0 (11/12/26 0900 : " + STAFF + ", RN)")
    assert neuro(sheet).splitlines()[:3] == [
        "SBS: 0 (11/12/26)", "CAPD: 0 (11/12/26)", "WAT-1: 0 (11/12/26)",
    ]


def test_print_clock_does_not_replace_source_dates_or_expire_old_dated_scores():
    sheet = imported()
    expected = neuro(sheet)
    assert neuro(sheet, NOW + timedelta(days=10)) == expected
    assert "11/10/26" in expected and "11/12/26" in expected and "11/13/26" in expected
    assert "11/16/26" not in expected


@pytest.mark.parametrize("source,bad", [
    ("y", "CAPD: 3 (11/12/26 0900 : " + STAFF + ", RN)\nCAPD: 12 (11/12/26 0900 : " + STAFF + ", RN)"),
    ("l", "WAT Score:\nWAT-1: 3 (11/12/26 0900 : " + STAFF + ", RN)\nWAT-1: 8 (11/12/26 0900 : " + STAFF + ", RN)"),
    ("y", "CAPD: 3 (11/99/26 0900 : " + STAFF + ", RN)"),
    ("l", "WAT Score:\nWAT-1: 3 (11/99/26 0900 : " + STAFF + ", RN)"),
])
def test_failed_score_sections_do_not_store_staff_or_a_guessed_latest_value(source, bad):
    with display_clock(NOW):
        result = import_replacement("P4102", phrase(**{source: bad}), new_vault()["settings"])
    assert result.errors
    assert source in result.sheet["import_warnings"]
    assert any(item["section"] == source and item["code"] == "section_parse_failed"
               for item in result.diagnostics)
    assert not result.sheet["neuro_vitals"].get(source)
    assert STAFF not in json.dumps(result.sheet)
    assert STAFF not in json.dumps(result.errors + result.notices + result.diagnostics)


def test_scores_round_trip_encrypted_without_staff_and_keep_date_only_output():
    sheet = imported()
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == vault
    assert STAFF not in json.dumps(restored)
    assert neuro(restored["rooms"]["P4102"]) == neuro(sheet)


@pytest.mark.parametrize("edit", ["score", "date", "airway"])
def test_print_all_rebuilds_only_changed_room_for_score_date_or_airway_edit(edit):
    first, second = imported(), imported(room="P4104")
    other_before = deepcopy(second)
    cache = SessionPdfCache()
    cached_handoffs_pdf([first, second], cache, NOW)
    cached_handoffs_pdf([first, second], cache, NOW + timedelta(minutes=1))
    assert cache.stats["builds"] == 2
    if edit == "score":
        first["neuro_vitals"]["y"][0]["value"] = "5 (11/12/26)"
    elif edit == "date":
        first["neuro_vitals"]["y"][0]["value"] = "12 (11/13/26)"
    else:
        nc = imported(mode="", delivery="Nasal cannula", removed_ett=True)
        for name in ("ventilation", "noninvasive", "sbs_vent_mode", "devices"):
            if name in nc:
                first[name] = deepcopy(nc[name])
            else:
                first.pop(name, None)
    validate_sheet(first)
    output = compact(pdf_text(cached_handoffs_pdf([first, second], cache, NOW + timedelta(minutes=2))))
    assert cache.stats["builds"] == 3
    assert second == other_before
    if edit == "score":
        assert output.count("CAPD:5(11/12/26)") == 1
        assert output.count("CAPD:12(H)(11/12/26)") == 1
    elif edit == "date":
        assert output.count("CAPD:12(H)(11/13/26)") == 1
        assert output.count("CAPD:12(H)(11/12/26)") == 1
    else:
        assert output.count("SBStarget:-2(11/10/26)") == 1
        assert output.count("CAPD:12(H)(11/12/26)") == 2
        assert output.count("WAT-1:4(11/13/26)") == 2


def test_complete_replacement_clears_old_scores_and_leaves_other_room_unchanged():
    first, second = imported(), imported(room="P4104")
    vault = save_sheet_in(save_sheet_in(new_vault(), first), second)
    other_before = deepcopy(vault["rooms"]["P4104"])
    with display_clock(NOW):
        replacement = import_replacement("P4102", phrase(
            mode="", delivery="Nasal cannula", k="Target Arousal Level:\nSBS Last 24 Hours:",
            y="CAPD:", l="WAT Score:", diagnosis="SYNTHETIC_NEW_ROOM_OCCUPANT"), vault["settings"])
    assert not replacement.errors
    assert replacement.sheet["id"] != first["id"]
    vault = save_sheet_in(vault, replacement.sheet)
    ready = available_handoffs(vault, {})
    assert vault["rooms"]["P4104"] == other_before
    assert "SBS" not in neuro(ready["P4102"])
    assert "WAT" not in neuro(ready["P4102"])
    assert "12 (H)" not in neuro(ready["P4102"])
    assert "11/10/26" not in neuro(ready["P4102"])
    assert neuro(ready["P4104"]) == neuro(second)


@pytest.mark.parametrize("delivery", ["Nasal cannula", "High flow nasal cannula", "Simple mask", "CPAP/Bi-PAP mask"])
def test_pressure_support_with_explicit_nasal_or_mask_delivery_does_not_authorize_sbs(delivery):
    sheet = imported(mode=PS, delivery=delivery)
    assert not sheet["sbs_vent_mode"]
    assert "SBS" not in neuro(sheet)
    assert "CAPD: 12 (H) (11/12/26)" in neuro(sheet)
    assert "WAT-1: 4 (11/13/26)" in neuro(sheet)


def failed_score_reimport(sheet, source):
    heading = "CAPD: " if source == "y" else "WAT Score:\nWAT-1: "
    with display_clock(NOW):
        result = import_sections(sheet, block(source, heading + "unreadable recorded total"),
                                 new_vault()["settings"])
    assert result.errors
    assert source in result.sheet["import_warnings"]
    assert result.sheet["neuro_vitals"][source] == sheet["neuro_vitals"][source]
    return result.sheet


@pytest.mark.parametrize("source,label", [("y", "CAPD"), ("l", "WAT-1")])
def test_app_score_edit_removes_staff_and_time_and_recovers_failed_source(app, source, label):
    open_room(app)
    ss = app.st.session_state
    sheet = failed_score_reimport(imported(), source)
    ss["drafts"]["P4102"] = sheet
    assert (label + ": 12" if source == "y" else label + ": 4") not in neuro(sheet)
    key = "neuro_" + sheet["id"] + "_" + source + "_0"
    ss[key] = label + ": 0 (11/14/26 1311 : " + STAFF + ", RN)"
    app.neuro_row_change("P4102", source, 0, "value", key)
    edited = ss["drafts"]["P4102"]
    assert edited["neuro_vitals"][source][0]["value"] == "0 (11/14/26)"
    assert ss[key] == "0 (11/14/26)"
    assert source not in edited["import_warnings"]
    assert label + ": 0 (11/14/26)" in neuro(edited)
    assert STAFF not in json.dumps(edited)


@pytest.mark.parametrize("source", ["y", "l"])
def test_app_invalid_dated_score_edit_keeps_previous_value_and_warning(app, source):
    open_room(app)
    ss = app.st.session_state
    sheet = failed_score_reimport(imported(), source)
    ss["drafts"]["P4102"] = sheet
    before = deepcopy(sheet)
    key = "neuro_" + sheet["id"] + "_" + source + "_0"
    ss[key] = "99 (11/14/26 1311 : " + STAFF + ", RN)"
    app.neuro_row_change("P4102", source, 0, "value", key)
    assert ss["drafts"]["P4102"] == before
    assert ss[key] == before["neuro_vitals"][source][0]["value"]
    assert ss["notice"][0] == "error"
    assert STAFF not in json.dumps(ss["notice"])


@pytest.mark.parametrize("source,label", [("y", "CAPD"), ("l", "WAT-1")])
def test_pending_score_edit_snapshot_normalizes_metadata_and_recovers_failed_source(app, source, label):
    open_room(app)
    ss = app.st.session_state
    sheet = failed_score_reimport(imported(), source)
    ss["drafts"]["P4102"] = sheet
    before = deepcopy(sheet)
    key = "neuro_" + sheet["id"] + "_" + source + "_0"
    ss[key] = label + ": 0 (11/14/26 1311 : " + STAFF + ", RN)"
    snapshot = app.editor_snapshot("P4102")
    assert snapshot["neuro_vitals"][source][0]["value"] == "0 (11/14/26)"
    assert source not in snapshot["import_warnings"]
    assert label + ": 0 (11/14/26)" in neuro(snapshot)
    assert STAFF not in json.dumps(snapshot)
    assert ss["drafts"]["P4102"] == before


@pytest.mark.parametrize("source", ["y", "l"])
def test_invalid_pending_score_edit_cannot_partially_change_or_save_a_room(app, source):
    open_room(app)
    ss = app.st.session_state
    sheet = imported()
    ss["drafts"]["P4102"] = sheet
    before = deepcopy(sheet)
    key = "neuro_" + sheet["id"] + "_" + source + "_0"
    ss[key] = "3 (11/99/26 1311 : " + STAFF + ", RN)"
    with pytest.raises(ValueError) as raised:
        app.editor_snapshot("P4102")
    assert STAFF not in str(raised.value)
    assert ss["drafts"]["P4102"] == before
    assert "P4102" not in ss["vault"]["rooms"]


@pytest.mark.parametrize("mode,expected", [(PC, "SBS: -1 (11/14/26)"), ("", "")])
def test_app_add_accepts_date_only_sbs_but_still_requires_invasive_mode(app, mode, expected):
    open_room(app)
    ss = app.st.session_state
    ss["drafts"]["P4102"] = imported(mode=mode, delivery="Endotracheal tube" if mode else "Nasal cannula")
    ss["score_entry"], ss["date_entry"] = "-1", "11/14/26"
    app.sbs_add_reading("P4102", "score_entry", "date_entry")
    sheet = ss["drafts"]["P4102"]
    assert sheet["sbs_observations"]["readings"][-1]["recorded_at"] == "11/14/26"
    assert ss["score_entry"] == ss["date_entry"] == ""
    if expected:
        assert expected in neuro(sheet)
    else:
        assert "SBS" not in neuro(sheet)


def test_app_add_never_relabels_a_dated_target_as_a_measured_sbs(app):
    open_room(app)
    ss = app.st.session_state
    ss["drafts"]["P4102"] = imported()
    ss["score_entry"], ss["date_entry"] = "-1", "11/09/26"
    app.sbs_add_reading("P4102", "score_entry", "date_entry")
    output = neuro(ss["drafts"]["P4102"])
    assert "SBS: -2" not in output
    assert "SBS target: -2 (11/10/26)" in output or "SBS: -1 (11/09/26)" in output


def test_app_import_saves_sanitized_scores_and_clears_source_paste(app):
    open_room(app)
    ss = app.st.session_state
    ss["paste"] = phrase()
    with display_clock(NOW):
        app.create_handoff()
    assert ss["paste"] == ""
    assert STAFF not in json.dumps(ss["vault"])
    assert STAFF not in json.dumps(ss["drafts"])
    assert STAFF not in json.dumps(ss["import_result"])
    assert "SBS target: -2 (11/10/26)" in neuro(ss["vault"]["rooms"]["P4102"])

