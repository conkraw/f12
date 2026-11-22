"""Synthetic import, print, cache, archive, and callback PRN regressions."""
from copy import deepcopy
from datetime import datetime, timedelta
from io import BytesIO
import json
import re
from zoneinfo import ZoneInfo

import pytest
from pypdf import PdfReader

from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf
from importing import import_replacement, import_sections
from lab_windows import display_clock
from models import new_sheet, new_vault, save_sheet_in, upgrade_vault, validate_sheet
from pdf_cache import SessionPdfCache, cached_handoffs_pdf
from prn_counts import MEDICATIONS, confirm_review, empty_prn, prn_counts, validate_prn
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room


EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 22, 4, 0, tzinfo=EASTERN)
HEADER = "Medication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin"


def block(key, body):
    marker = key * 12
    return marker + "\n" + body + "\n" + marker


def order(drug, frequency="q1h PRN", dose="1 mg", rate=""):
    return "\t".join(["•", drug, dose, "Intravenous", frequency,
                       "SYNTHETIC_PROVIDER_SENTINEL", rate, ""])


def source(*, af=None, orders=None):
    text = block("a", "Diagnoses:\n1. Synthetic PRN print example")
    text += "\n" + block("b", "Medications:\n" + HEADER + "\n" + "\n".join(
        orders or [order("hydromorphone"), order("midazolam"), order("vecuronium")]))
    if af is not None:
        text += "\n" + block("af", af)
    return text


def imported(text=None, room="P4102"):
    result = import_replacement(room, text or source(), new_vault()["settings"])
    assert not result.errors, result.errors
    assert result.sheet is not None
    return result.sheet


def event(drug, stamp, count=1, source_kind="manual"):
    return {"medication": drug, "timestamp": stamp, "volume_ml": None,
            "dose_count": count, "source": source_kind}


def reviewed_sheet(room="P4102"):
    sheet = imported(room=room)
    data = empty_prn()
    data["events"] = [
        event("hydromorphone", "2026-11-21T06:59:00-05:00", 9),
        event("hydromorphone", "2026-11-21T07:00:00-05:00"),
        event("hydromorphone", "2026-11-21T23:59:00-05:00"),
        event("hydromorphone", "2026-11-22T04:00:00-05:00"),
        event("hydromorphone", "2026-11-22T04:01:00-05:00"),
        event("midazolam", "2026-11-22T03:55:00-05:00", 2),
        event("vecuronium", "2026-11-22T07:01:00-05:00"),
    ]
    sheet["prn"] = confirm_review(data, ["hydromorphone", "midazolam", "vecuronium"], NOW)
    validate_sheet(sheet)
    return sheet


def text_from_pdf(data):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


def test_af_import_keeps_sanitized_events_without_inventing_doses():
    body = ("TIME\tANALGESIA\tSEDATIVES\tPARALYTICS\n"
            "0100\tVolume (mL) Hydromorphone: 0.89 mL (11/22/26 0100 : CLINICIAN_SENTINEL, RN)\t \t \n"
            "0141\tVolume (mL) Hydromorphone: 1.05 mL (11/22/26 0141 : CLINICIAN_SENTINEL, RN)\t"
            "Volume (mL) Midazolam: 1 mL (11/22/26 0141 : CLINICIAN_SENTINEL, RN)\t")
    sheet = imported(source(af=body))
    assert len(sheet["prn"]["events"]) == 3
    assert prn_counts(sheet, NOW) == {}
    assert all(row["dose_count"] is None for row in sheet["prn"]["events"])
    assert "CLINICIAN_SENTINEL" not in json.dumps(sheet)
    assert "SYNTHETIC_PROVIDER_SENTINEL" not in json.dumps(sheet)


def test_malformed_af_clears_previous_counts_and_preserves_other_sections():
    before = reviewed_sheet()
    malformed = "afafafafafaf\nPRN:\nVolume (mL) Hydromorphone: 1 mL (missing date)\nafafafafafaf"
    result = import_sections(before, malformed, new_vault()["settings"])
    assert result.errors and "af" in result.skipped
    assert result.sheet["prn"] is None
    assert result.sheet["medications"] == before["medications"]
    assert prn_counts(result.sheet, NOW) == {}


def test_af_boundary_rejection_and_complete_replacement_clear_old_data():
    missing_close = source() + "\nafafafafafaf\nTIME\tANALGESIA\tSEDATIVES\tPARALYTICS\n"
    result = import_replacement("P4102", missing_close, new_vault()["settings"])
    assert result.sheet is not None and "af" in result.skipped
    assert result.sheet.get("prn") is None
    fresh = imported(source())
    assert fresh.get("prn") is None
    assert fresh["id"] != reviewed_sheet()["id"]
    repeated = source(af="PRN:\n") + "\n" + block("af", "PRN:\n")
    assert import_replacement("P4102", repeated, new_vault()["settings"]).sheet is None


@pytest.mark.parametrize("render", [
    lambda sheet: handoff_text(sheet, NOW),
    lambda sheet: re.sub(r"<[^>]+>", "", handoff_html(sheet, NOW)),
    lambda sheet: text_from_pdf(handoff_pdf(sheet, NOW)),
    lambda sheet: text_from_pdf(handoffs_pdf([sheet], NOW)),
], ids=["text", "html", "single_pdf", "combined_pdf"])
def test_verified_counts_print_after_prn_without_event_dates(render):
    sheet = reviewed_sheet()
    before = deepcopy(sheet)
    output = render(sheet)
    assert "PRN × 3" in output
    assert "PRN × 2" in output
    assert "PRN × 0" in output
    assert "2026-11-21T07:00" not in output
    assert "11/21/26 2359" not in output
    assert sheet == before


def test_counts_do_not_annotate_infusions_or_repeat_for_multiple_drug_orders():
    orders = [order("hydromorphone infusion", "Continuous", "0.1 mg/kg/hr", "1 mL/hr"),
              order("hydromorphone", dose="1 mg"), order("hydromorphone", dose="2 mg"),
              order("midazolam", "q6h")]
    sheet = imported(source(orders=orders))
    sheet["prn"] = reviewed_sheet()["prn"]
    output = handoff_text(sheet, NOW)
    assert output.count("PRN × 3") == 1
    assert "PRN × 2" not in output
    for line in output.splitlines():
        if "infusion" in line.casefold():
            assert "×" not in line


@pytest.mark.parametrize("drug", MEDICATIONS)
def test_every_requested_drug_receives_its_neuro_count(drug):
    sheet = imported(source(orders=[order(drug)]))
    data = empty_prn()
    data["events"] = [event(drug, "2026-11-22T03:00:00-05:00", 4)]
    sheet["prn"] = confirm_review(data, [drug], NOW)
    output = handoff_text(sheet, NOW)
    assert "PRN × 4" in output
    assert "NEUROLOGIC" in output


def test_hidden_or_remapped_orders_do_not_gain_neuro_counts():
    sheet = reviewed_sheet()
    for row in sheet["medications"]:
        row["hidden"] = True
    assert "PRN ×" not in handoff_text(sheet, NOW)


def test_pdf_cache_refreshes_for_new_events_and_7am_rollover():
    sheet = reviewed_sheet()
    cache = SessionPdfCache()
    try:
        first = cache.prepare(sheet, NOW)
        same = cache.prepare(sheet, NOW + timedelta(seconds=30))
        later = cache.prepare(sheet, NOW + timedelta(minutes=1))
        next_day = cache.prepare(sheet, NOW.replace(hour=7))
        assert first.signature == same.signature
        assert first.signature != later.signature != next_day.signature
        assert "PRN × 3" in text_from_pdf(first.data)
        assert "PRN × 4" in text_from_pdf(later.data)
        assert "PRN ×" not in text_from_pdf(next_day.data)
        packet = cached_handoffs_pdf([sheet, reviewed_sheet("P4104")], cache, NOW)
        assert text_from_pdf(packet).count("PRN × 3") == 2
    finally:
        cache.close()


def test_existing_archive_and_confirmed_events_roundtrip_encrypted():
    before = new_vault()
    before["schema"] = 34
    before["rooms"]["P4102"] = new_sheet("P4102")
    snapshot = deepcopy(before)
    upgraded = upgrade_vault(before)
    assert before == snapshot
    assert upgraded["schema"] == 34
    assert upgraded["rooms"] == before["rooms"]
    vault = save_sheet_in(upgraded, reviewed_sheet())
    key = generate_key()
    payload = seal_vault(vault, key)
    reopened = open_vault(payload, key)
    assert reopened == vault
    assert b"hydromorphone" not in payload
    assert prn_counts(reopened["rooms"]["P4102"], NOW)["hydromorphone"] == 3


def test_mapping_sync_accepts_existing_schema_and_preserves_prn_records():
    from mapping_sync import candidate_for, decrypt_archive, mapping_bundle
    vault = save_sheet_in(new_vault(), reviewed_sheet())
    key = generate_key()
    restored = decrypt_archive(seal_vault(vault, key), key)
    assert restored == vault
    other_settings = deepcopy(new_vault()["settings"])
    other_settings["medication_mappings"] = [{"name": "fentanyl", "destination": "Neurologic", "match": "prefix"}]
    changed = candidate_for(restored, mapping_bundle(other_settings))
    assert changed["rooms"] == vault["rooms"]
    assert changed["schema"] == 34


def test_review_callback_saves_and_revokes_previous_download(app):
    open_room(app)
    ss = app.st.session_state
    original = imported()
    app.set_editor("P4102", original)
    prior_download = app.download_revocation()
    with display_clock(NOW):
        app.apply_prn_review("P4102", original["id"], reviewed_sheet()["prn"], expected_prn=None)
    saved = ss["vault"]["rooms"]["P4102"]
    assert saved["prn"] == ss["drafts"]["P4102"]["prn"]
    assert prior_download.is_set()
    assert prn_counts(saved, NOW)["hydromorphone"] == 3


def test_review_callback_rejects_replaced_room_and_changed_same_sheet_source(app):
    open_room(app)
    ss = app.st.session_state
    old = ss["drafts"]["P4102"]
    replacement = imported()
    app.set_editor("P4102", replacement)
    with pytest.raises(ValueError, match="handoff changed"):
        app.apply_prn_review("P4102", old["id"], reviewed_sheet()["prn"], expected_prn=None)
    ss["drafts"]["P4102"]["prn"] = empty_prn()
    snapshot = deepcopy(ss["drafts"]["P4102"])
    with pytest.raises(ValueError, match="PRN records changed"):
        app.apply_prn_review("P4102", replacement["id"], reviewed_sheet()["prn"], expected_prn=None)
    assert ss["drafts"]["P4102"] == snapshot


def test_manual_review_can_resolve_a_failed_af_import(app):
    open_room(app)
    result = import_replacement("P4102", source(af="Volume (mL) Hydromorphone: 1 mL (missing date)"),
                                new_vault()["settings"])
    assert "af" in result.sheet["import_warnings"]
    app.set_editor("P4102", result.sheet)
    with display_clock(NOW):
        app.apply_prn_review("P4102", result.sheet["id"], reviewed_sheet()["prn"], expected_prn=None)
    saved = app.st.session_state["vault"]["rooms"]["P4102"]
    assert "af" not in saved["import_warnings"]
    assert prn_counts(saved, NOW)["hydromorphone"] == 3


def test_duplicate_charting_and_added_manual_dose_cannot_double_count():
    data = empty_prn()
    first = event("hydromorphone", "2026-11-22T03:00:00-05:00", 1, "volume")
    first["volume_ml"] = 1.2
    data["events"] = [first, event("hydromorphone", first["timestamp"], 1)]
    with pytest.raises(ValueError, match="same administration time"):
        confirm_review(data, ["hydromorphone"], NOW)
    data["events"][0]["dose_count"] = 0
    data["events"][1]["dose_count"] = 2
    validate_prn(data)
    verified = confirm_review(data, ["hydromorphone"], NOW)
    assert prn_counts({"prn": verified}, NOW) == {"hydromorphone": 2}
