"""Synthetic automatic paralytic import, output, cache, archive, and save checks."""
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
from prn_counts import COUNTED_MEDICATIONS, MEDICATIONS, confirm_review, empty_prn, prn_counts
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
        orders or [order("hydromorphone"), order("midazolam"),
                   order("vecuronium"), order("rocuronium")]))
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


def volume_event(drug, stamp, volume=1):
    result = event(drug, stamp, None, "volume")
    result["volume_ml"] = volume
    return result


def auto_sheet(room="P4102"):
    """Three vecuronium and two rocuronium records at NOW, without approval."""
    sheet = imported(room=room)
    data = empty_prn()
    data["events"] = [
        volume_event("vecuronium", "2026-11-21T06:59:00-05:00", 9),
        volume_event("vecuronium", "2026-11-21T07:00:00-05:00"),
        volume_event("vecuronium", "2026-11-21T23:59:00-05:00"),
        volume_event("vecuronium", "2026-11-22T04:00:00-05:00"),
        volume_event("vecuronium", "2026-11-22T04:01:00-05:00"),
        volume_event("vecuronium", "2026-11-22T07:01:00-05:00"),
        volume_event("rocuronium", "2026-11-22T03:30:00-05:00"),
        volume_event("rocuronium", "2026-11-22T03:55:00-05:00", 2),
        event("hydromorphone", "2026-11-22T03:00:00-05:00", 7),
        event("midazolam", "2026-11-22T03:00:00-05:00", 8),
    ]
    sheet["prn"] = data
    validate_sheet(sheet)
    return sheet


# Earlier HTML test helpers imported this name. Its data now has no review gate.
reviewed_sheet = auto_sheet


def text_from_pdf(data):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


def test_af_import_counts_only_paralytics_and_discards_source_names():
    body = ("TIME\tANALGESIA\tSEDATIVES\tPARALYTICS\n"
            "0100\tVolume (mL) Hydromorphone: 0.89 mL (11/22/26 0100 : CLINICIAN_SENTINEL, RN)\t"
            "Volume (mL) Midazolam: 1 mL (11/22/26 0100 : CLINICIAN_SENTINEL, RN)\t"
            "Volume (mL) Vecuronium: 0.5 mL (11/22/26 0100 : CLINICIAN_SENTINEL, RN)\n"
            "0141\t\t\tVolume (mL) Rocuronium: 2 mL (11/22/26 0141 : CLINICIAN_SENTINEL, RN)")
    sheet = imported(source(af=body))
    assert len(sheet["prn"]["events"]) == 2
    assert sheet["prn"]["reviewed"] == {}
    assert prn_counts(sheet, NOW) == {"vecuronium": 1, "rocuronium": 1}
    assert "CLINICIAN_SENTINEL" not in json.dumps(sheet)
    assert "SYNTHETIC_PROVIDER_SENTINEL" not in json.dumps(sheet)


def test_malformed_supported_af_clears_previous_counts_and_preserves_other_sections():
    before = auto_sheet()
    malformed = block("af", "PRN:\nVolume (mL) Vecuronium: 1 mL (missing date)")
    result = import_sections(before, malformed, new_vault()["settings"])
    assert result.errors and "af" in result.skipped
    assert result.sheet["prn"] is None
    assert result.sheet["medications"] == before["medications"]
    assert prn_counts(result.sheet, NOW) == {}


def test_ignored_sedative_or_analgesic_rows_do_not_block_paralytic_import():
    body = ("TIME\tANALGESIA\tSEDATIVES\tPARALYTICS\n"
            "0141\tVolume (mL) Hydromorphone: unknown (missing date)\t"
            "Volume (mL) Midazolam: 1 mL (missing date)\t"
            "Volume (mL) Vecuronium: 2 mL (11/22/26 0141 : SYNTHETIC_CLINICIAN, RN)")
    sheet = imported(source(af=body))
    assert prn_counts(sheet, NOW) == {"vecuronium": 1, "rocuronium": 0}
    assert "af" not in sheet["import_warnings"]


def test_af_boundary_rejection_and_complete_replacement_clear_old_data():
    missing_close = source() + "\nafafafafafaf\nTIME\tANALGESIA\tSEDATIVES\tPARALYTICS\n"
    result = import_replacement("P4102", missing_close, new_vault()["settings"])
    assert result.sheet is not None and "af" in result.skipped
    assert result.sheet.get("prn") is None
    fresh = imported(source())
    assert fresh.get("prn") is None
    assert fresh["id"] != auto_sheet()["id"]
    repeated = source(af="PRN:\n") + "\n" + block("af", "PRN:\n")
    assert import_replacement("P4102", repeated, new_vault()["settings"]).sheet is None


@pytest.mark.parametrize("render", [
    lambda sheet: handoff_text(sheet, NOW),
    lambda sheet: re.sub(r"<[^>]+>", "", handoff_html(sheet, NOW)),
    lambda sheet: text_from_pdf(handoff_pdf(sheet, NOW)),
    lambda sheet: text_from_pdf(handoffs_pdf([sheet], NOW)),
], ids=["text", "html", "single_pdf", "combined_pdf"])
def test_automatic_counts_print_after_prn_without_event_dates(render):
    sheet = auto_sheet()
    before = deepcopy(sheet)
    output = render(sheet)
    assert "PRN × 3" in output and "PRN × 2" in output
    assert output.count("PRN ×") == 2
    assert "PRN × 7" not in output and "PRN × 8" not in output
    assert "2026-11-21T07:00" not in output
    assert "11/21/26 2359" not in output
    assert sheet == before


def test_infusion_does_not_suppress_prn_count_or_duplicate_it_across_orders():
    orders = [order("vecuronium infusion", "Continuous", "0.1 mg/kg/hr", "1 mL/hr"),
              order("vecuronium", dose="1 mg"), order("vecuronium", dose="2 mg"),
              order("rocuronium", "q6h")]
    sheet = imported(source(orders=orders))
    sheet["prn"] = auto_sheet()["prn"]
    output = handoff_text(sheet, NOW)
    assert output.count("PRN × 3") == 1
    assert "PRN × 2" not in output
    for line in output.splitlines():
        if "infusion" in line.casefold():
            assert "×" not in line


@pytest.mark.parametrize("drug", COUNTED_MEDICATIONS)
def test_each_paralytic_receives_its_count_without_review(drug):
    sheet = imported(source(orders=[order(drug)]))
    sheet["prn"] = empty_prn()
    sheet["prn"]["events"] = [volume_event(drug, "2026-11-22T03:00:00-05:00", 4)]
    output = handoff_text(sheet, NOW)
    assert "PRN × 1" in output
    assert "NEUROLOGIC" in output
    assert not sheet["prn"]["reviewed"]


@pytest.mark.parametrize("drug", [drug for drug in MEDICATIONS if drug not in COUNTED_MEDICATIONS])
def test_archived_sedative_and_analgesic_reviews_cannot_print_counts(drug):
    sheet = imported(source(orders=[order(drug)]))
    data = empty_prn()
    data["events"] = [event(drug, "2026-11-22T03:00:00-05:00", 4)]
    sheet["prn"] = confirm_review(data, [drug], NOW)
    validate_sheet(sheet)
    assert "PRN ×" not in handoff_text(sheet, NOW)


def test_hidden_orders_do_not_gain_neuro_counts():
    sheet = auto_sheet()
    for row in sheet["medications"]:
        row["hidden"] = True
    assert "PRN ×" not in handoff_text(sheet, NOW)


def test_pdf_cache_refreshes_for_new_events_and_automatic_7am_rollover():
    sheet = auto_sheet()
    cache = SessionPdfCache()
    try:
        first = cache.prepare(sheet, NOW)
        same = cache.prepare(sheet, NOW + timedelta(seconds=30))
        later = cache.prepare(sheet, NOW + timedelta(minutes=1))
        next_day = cache.prepare(sheet, NOW.replace(hour=7))
        next_event = cache.prepare(sheet, NOW.replace(hour=7, minute=1))
        assert first.signature == same.signature
        assert len({first.signature, later.signature, next_day.signature, next_event.signature}) == 4
        assert "PRN × 3" in text_from_pdf(first.data)
        assert "PRN × 4" in text_from_pdf(later.data)
        assert text_from_pdf(next_day.data).count("PRN × 0") == 2
        assert "PRN × 1" in text_from_pdf(next_event.data)
        packet = cached_handoffs_pdf([sheet, auto_sheet("P4104")], cache, NOW)
        assert text_from_pdf(packet).count("PRN × 3") == 2
    finally:
        cache.close()


def test_existing_archive_and_unreviewed_events_roundtrip_encrypted():
    before = new_vault()
    before["schema"] = 34
    before["rooms"]["P4102"] = new_sheet("P4102")
    snapshot = deepcopy(before)
    upgraded = upgrade_vault(before)
    assert before == snapshot
    assert upgraded["schema"] == 34
    assert upgraded["rooms"] == before["rooms"]
    vault = save_sheet_in(upgraded, auto_sheet())
    key = generate_key()
    payload = seal_vault(vault, key)
    reopened = open_vault(payload, key)
    assert reopened == vault
    assert b"vecuronium" not in payload
    assert prn_counts(reopened["rooms"]["P4102"], NOW) == {"vecuronium": 3, "rocuronium": 2}
    assert reopened["rooms"]["P4102"]["prn"]["reviewed"] == {}


def test_mapping_sync_accepts_existing_schema_and_preserves_prn_records():
    from mapping_sync import candidate_for, decrypt_archive, mapping_bundle
    vault = save_sheet_in(new_vault(), auto_sheet())
    key = generate_key()
    restored = decrypt_archive(seal_vault(vault, key), key)
    assert restored == vault
    other_settings = deepcopy(new_vault()["settings"])
    other_settings["medication_mappings"] = [{"name": "fentanyl", "destination": "Neurologic", "match": "prefix"}]
    changed = candidate_for(restored, mapping_bundle(other_settings))
    assert changed["rooms"] == vault["rooms"]
    assert changed["schema"] == 34


def test_import_saves_automatic_counts_and_revokes_previous_download(app):
    open_room(app)
    ss = app.st.session_state
    prior_download = app.download_revocation()
    ss["paste"] = source(af="Volume (mL) Vecuronium: 2 mL (11/22/26 0141 : SYNTHETIC_CLINICIAN, RN)")
    with display_clock(NOW):
        app.create_handoff()
    saved = ss["vault"]["rooms"]["P4102"]
    assert saved["prn"] == ss["drafts"]["P4102"]["prn"]
    assert prior_download.is_set()
    assert saved["prn"]["reviewed"] == {}
    assert prn_counts(saved, NOW) == {"vecuronium": 1, "rocuronium": 0}
    assert ss["paste"] == ""


def test_new_import_removes_old_counts_without_affecting_other_rooms(app):
    open_room(app, "P4104")
    other = auto_sheet("P4104")
    app.set_editor("P4104", other)
    app.save_room(None)
    other_saved = deepcopy(app.st.session_state["vault"]["rooms"]["P4104"])
    open_room(app)
    app.set_editor("P4102", auto_sheet())
    app.save_room(None)
    app.st.session_state["paste"] = source()
    with display_clock(NOW):
        app.create_handoff()
    saved = app.st.session_state["vault"]["rooms"]["P4102"]
    assert saved.get("prn") is None and prn_counts(saved, NOW) == {}
    assert app.st.session_state["vault"]["rooms"]["P4104"] == other_saved


def test_repeated_source_rows_are_counted_once_after_import():
    row = "Volume (mL) Vecuronium: 2 mL (11/22/26 0141 : SYNTHETIC_CLINICIAN, RN)"
    sheet = imported(source(af=row + "\n" + row))
    assert len(sheet["prn"]["events"]) == 1
    assert prn_counts(sheet, NOW) == {"vecuronium": 1, "rocuronium": 0}
