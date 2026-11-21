"""Synthetic IV fluid grouping, weight boundaries and saved handoff output."""
from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from batching import available_handoffs
from exports import handoff_html, handoff_pdf, handoff_text
from importing import import_replacement, import_sections
from medications import upsert_rule
from models import fields_with_medications, new_vault, save_sheet_in, validate_sheet
from pdf_cache import SessionPdfCache
from security import generate_key, open_vault, seal_vault
from style_assert_helpers import without_style_tags
from test_callbacks import app, open_room


FLUID = "sodium acetate 75 mEq in dextrose 5 % and sodium chloride 0.45 % 1,000 mL infusion"
SALINE = "sodium chloride 0.9 % infusion"
HEADER = "Medication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin"


def block(letter, body):
    return letter * 12 + "\n" + body + "\n" + letter * 12


def order(name=FLUID, dose="", route="Intravenous", frequency="Continuous",
          rate="50 mL/hr at 11/20/26 0200", admin="New Bag at 11/20/26 0200"):
    return "\t".join(["\u2022", name, dose, route, frequency, "Synthetic provider", rate, admin])


def source(rows=None, weight="27 kg", measured_weight=None):
    text = block("a", "Diagnoses:\n1. Synthetic IV fluid example")
    text += "\n" + block("b", "Medications:\n" + HEADER + "\n" + "\n".join(rows or [order()]))
    if weight is not None:
        body = "NUTRITION:\n" + ("Weight: " + measured_weight + "\n" if measured_weight else "")
        body += "Dosing Weight:\nDosing Weight\nDosing\n" + (weight or "None")
        text += "\n" + block("i", body)
    return text


def imported(text, settings=None):
    result = import_replacement("P4102", text, settings or new_vault()["settings"])
    assert not result.errors, result.errors
    assert result.sheet is not None
    return result.sheet


def pdf_text(sheet):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(handoff_pdf(sheet))).pages)


@pytest.mark.parametrize("render", [handoff_text,
                                    lambda sheet: without_style_tags(handoff_html(sheet)),
                                    pdf_text], ids=["text", "html", "pdf"])
def test_import_groups_fluid_once_and_uses_documented_pump_rate_for_new_bag_event(render):
    sheet = imported(source())
    before = deepcopy(sheet)
    row = sheet["medications"][0]
    assert row["dose"] == ""
    assert row["last_rate"] == "50 mL/hr"
    assert row["last_admin_status"] == "no_rate"

    fields = fields_with_medications(sheet)
    text = render(sheet)

    assert "Intravenous Fluids" in fields["FEN / GI"]
    assert "~3/4 maintenance" in fields["FEN / GI"]
    assert "50 mL/hr" in fields["FEN / GI"]
    assert "11/20/26 0200" in fields["FEN / GI"]
    assert fields["FEN / GI"].count(FLUID) == 1
    assert FLUID not in fields["Other Medications"]
    assert text.count("Intravenous Fluids") == 1
    assert "~3/4 maintenance" in text and "50 mL/hr" in text
    assert sheet == before


@pytest.mark.parametrize("rate,weight,expected", [
    ("25", "8.2 kg", "~3/4 maintenance"),
    ("45", "23.3 kg", "~71% maintenance"),
    ("75", "66 kg", "~71% maintenance"),
    ("67", "27 kg", "maintenance"),
])
def test_each_fluid_compares_its_reported_rate_to_current_dosing_weight(rate, weight, expected):
    rows = [order(dose="100 mL/hr", rate=rate + " mL/hr at 11/20/26 1400",
                  admin=rate + " mL/hr at 11/20/26 1400")]
    sheet = imported(source(rows, weight))

    text = fields_with_medications(sheet)["FEN / GI"]

    assert expected in text
    assert rate + " mL/hr" in text
    assert "100 mL/hr" not in text
    assert sheet["medications"][0]["dose"] == "100 mL/hr"


@pytest.mark.parametrize("rate", ["1", "2"])
def test_low_rates_remain_visible_without_a_maintenance_comparison(rate):
    rows = [order(SALINE, dose=rate + " mL/hr", rate=rate + " mL/hr at 11/20/26 1800",
                  admin=rate + " mL/hr at 11/20/26 1800")]
    sheet = imported(source(rows, "8.2 kg"))

    for text in (fields_with_medications(sheet)["FEN / GI"], pdf_text(sheet)):
        assert "Intravenous Fluids" in text
        assert rate + " mL/hr" in text
        assert "maintenance" not in text.casefold()


@pytest.mark.parametrize("weight", [None, ""])
def test_missing_dosing_weight_does_not_use_measured_weight_or_medication_dose(weight):
    sheet = imported(source(weight=weight, measured_weight="16 kg"))
    assert not sheet["dosing_weight"]

    for text in (fields_with_medications(sheet)["FEN / GI"], pdf_text(sheet)):
        assert "50 mL/hr" in text and "Intravenous Fluids" in text
        assert "maintenance" not in text.casefold()


def test_failed_weight_update_hides_comparison_using_retained_old_dosing_weight():
    old = imported(source())
    result = import_sections(old, block("i", "NUTRITION:\nDosing Weight: unparseable"), new_vault()["settings"])
    assert result.errors and "i" in result.skipped
    assert result.sheet["dosing_weight"] == "27 kg"

    for text in (fields_with_medications(result.sheet)["FEN / GI"],
                 without_style_tags(handoff_html(result.sheet)), pdf_text(result.sheet)):
        assert "Intravenous Fluids" in text and "50 mL/hr" in text
        assert "maintenance" not in text.casefold()


def test_complete_room_replacement_drops_previous_weight_before_computing_new_fluid():
    first = imported(source())
    second = imported(source(weight=None))

    assert first["id"] != second["id"]
    assert "~3/4 maintenance" in fields_with_medications(first)["FEN / GI"]
    assert "maintenance" not in fields_with_medications(second)["FEN / GI"].casefold()


def test_saved_encrypted_handoff_retains_fluid_output_and_original_fields():
    sheet = imported(source())
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()

    encrypted = seal_vault(vault, key)
    saved = open_vault(encrypted, key)["rooms"]["P4102"]

    assert FLUID.encode() not in encrypted
    assert saved["medications"] == sheet["medications"]
    assert saved["dosing_weight"] == "27 kg"
    assert "~3/4 maintenance" in fields_with_medications(saved)["FEN / GI"]
    assert "~3/4 maintenance" in pdf_text(saved)
    assert list(available_handoffs(new_vault(), {"P4102": saved})) == ["P4102"]


def test_dosing_weight_edits_refresh_fluid_text_and_prepared_pdf():
    sheet = imported(source())
    cache = SessionPdfCache()
    try:
        first = cache.prepare(sheet)
        changed = deepcopy(sheet)
        changed["dosing_weight"] = "15 kg"
        validate_sheet(changed)
        second = cache.prepare(changed)
    finally:
        cache.close()

    assert first.signature != second.signature
    first_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(first.data)).pages)
    second_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(second.data)).pages)
    assert "~3/4 maintenance" in first_text and "~3/4 maintenance" not in second_text
    assert "~3/4 maintenance" not in fields_with_medications(changed)["FEN / GI"]
    assert "maintenance" in fields_with_medications(changed)["FEN / GI"]
    assert sheet["dosing_weight"] == "27 kg"


@pytest.mark.parametrize("status", ["Stopped", "Paused", "Held", "Discontinued"])
def test_non_running_events_preserve_status_and_withhold_maintenance(status):
    rows = [order(dose="50 mL/hr", admin=status + " at 11/20/26 1500")]
    sheet = imported(source(rows))

    for text in (fields_with_medications(sheet)["FEN / GI"], pdf_text(sheet)):
        assert "Intravenous Fluids" in text
        assert status in text
        assert "maintenance" not in text.casefold()


def test_drug_infusions_keep_their_system_and_do_not_receive_fluid_maintenance():
    settings = new_vault()["settings"]
    settings["medication_mappings"] = upsert_rule([], "fentanyl", "Neurologic")
    rows = [order(), order("fentaNYL infusion 125 mcg/25 mL NS infusion (neo/ped)",
                           dose="0.5 mcg/kg/hr", rate="5 mL/hr at 11/20/26 1400",
                           admin="0.5 mcg/kg/hr at 11/20/26 1400")]
    sheet = imported(source(rows), settings)

    fields = fields_with_medications(sheet)

    assert "fentaNYL" not in fields["FEN / GI"]
    assert "fentaNYL" in fields["Neurologic"]
    assert "maintenance" not in fields["Neurologic"].casefold()
    assert sum(field.count("~3/4 maintenance") for field in fields.values()) == 1


def test_inline_include_control_excludes_fluid_without_erasing_source_values(app):
    open_room(app)
    ss = app.st.session_state
    ss["paste"] = source()
    app.create_handoff()
    row = ss["drafts"]["P4102"]["medications"][0]
    row["include"] = False
    app.save_room(None)

    saved = ss["vault"]["rooms"]["P4102"]

    assert saved["medications"][0]["name"] == FLUID
    assert "~3/4 maintenance" not in handoff_text(saved)
    assert FLUID not in handoff_text(saved)
