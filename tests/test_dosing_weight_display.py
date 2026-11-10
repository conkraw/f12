"""Display-only order and missing-value regression tests for version 6.8."""
from copy import deepcopy
from io import BytesIO
import pytest
from pypdf import PdfReader
from demographics import demographic_weight_text
from models import new_sheet, new_vault, fields_with_medications, save_sheet_in, SCHEMA_VERSION
from importing import import_sections
from batching import available_handoffs
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_html, handoffs_pdf
from security import seal_vault, open_vault, generate_key
from test_callbacks import app, open_room


def nutrition(weight="12 kg", z="0.1", include=True):
    return {"weight": weight, "z_score": z, "include": include}


def sheet(dose="11 kg", z="0.1", room="P4102"):
    data = new_sheet(room)
    data["fields"]["Diagnoses"] = "Synthetic training example"
    data["nutrition"] = nutrition(z=z)
    data["dosing_weight"] = dose
    return data


@pytest.mark.parametrize("z", ["0.1", "-4.32", "0", "0.00", "+1.2"])
@pytest.mark.parametrize("dose", ["11 kg", ""])
def test_exact_order_and_missing_display(z, dose):
    data = nutrition(z=z)
    before = deepcopy(data)
    assert demographic_weight_text(data, dose) == f"Weight: 12 kg\nZ-score: {z}\nDosing weight: {dose or 'none'}"
    assert data == before


@pytest.mark.parametrize("dose", ["11 kg", ""])
def test_no_z_score_placeholder(dose):
    assert demographic_weight_text(nutrition(z=""), dose) == f"Weight: 12 kg\nDosing weight: {dose or 'none'}"


@pytest.mark.parametrize("data", [None, nutrition(include=False)])
@pytest.mark.parametrize("dose", ["11 kg", ""])
def test_absent_or_excluded_measured_weight_does_not_hide_dosing_line(data, dose):
    assert demographic_weight_text(data, dose) == "Dosing weight: " + (dose or "none")


@pytest.mark.parametrize("dose", ["11 kg", ""])
def test_all_single_room_exports_match_and_do_not_modify_record(dose):
    data = sheet(dose=dose)
    before = deepcopy(data)
    pdf = PdfReader(BytesIO(handoff_pdf(data)))
    for output in (handoff_text(data), handoff_html(data), "\n".join(p.extract_text() for p in pdf.pages)):
        assert output.index("Weight: 12 kg") < output.index("Z-score: 0.1") < output.index("Dosing weight: " + (dose or "none"))
        assert output.count("Dosing weight:") == 1
    assert data == before


def test_print_all_consistent_and_no_cross_room_reuse():
    first = sheet(dose="11 kg")
    second = sheet(dose="", room="P4104")
    pdf = PdfReader(BytesIO(handoffs_pdf([first, second])))
    assert len(pdf.pages) == 2
    for p in pdf.pages:
        text = p.extract_text()
        assert text.index("Weight: 12 kg") < text.index("Z-score: 0.1") < text.index("Dosing weight:")
    assert "Dosing weight: 11 kg" in pdf.pages[0].extract_text()
    assert "Dosing weight: none" not in pdf.pages[0].extract_text()
    assert "Dosing weight: none" in pdf.pages[1].extract_text()
    assert "Dosing weight: 11 kg" not in pdf.pages[1].extract_text()
    html = handoffs_html([first, second])
    assert html.count("Dosing weight: none") == html.count("Dosing weight: 11 kg") == 1


def test_missing_display_does_not_make_blank_room_printable():
    blank = new_sheet("P4102")
    assert fields_with_medications(blank)["Diagnoses"] == "Dosing weight: none"
    assert not available_handoffs(new_vault(), {"P4102": blank})
    saved = save_sheet_in(new_vault(), sheet())
    assert not available_handoffs(saved, {"P4102": blank})


def block(letter, text):
    return letter * 10 + "\n" + text + "\n" + letter * 10


@pytest.mark.parametrize("body", ["NUTRITION:", "NUTRITION:\nDosing Weight: none", "NUTRITION:\nWeight: 12 kg (Z= 0.1)"])
def test_new_nutrition_without_dose_clears_old_dose_and_prints_none(body):
    current = sheet()
    result = import_sections(current, block("i", body), new_vault()["settings"])
    assert not result.errors
    assert result.sheet["dosing_weight"] == ""
    assert fields_with_medications(result.sheet)["Diagnoses"].endswith("Dosing weight: none")
    assert current["dosing_weight"] == "11 kg"


def test_omitted_nutrition_preserves_saved_dose():
    current = sheet()
    result = import_sections(current, block("a", "Diagnoses:\n1. Changed synthetic example"), new_vault()["settings"])
    assert not result.errors
    assert result.sheet["dosing_weight"] == "11 kg"
    assert "Dosing weight: 11 kg" in fields_with_medications(result.sheet)["Diagnoses"]


def test_none_is_display_only_and_encrypted_archive_is_unchanged():
    current = sheet(dose="")
    saved = save_sheet_in(new_vault(), current)
    before = deepcopy(saved)
    key = generate_key()
    loaded = open_vault(seal_vault(saved, key), key)
    assert loaded == before and loaded["schema"] == SCHEMA_VERSION ==32
    assert loaded["rooms"]["P4102"]["dosing_weight"] == ""
    assert "Dosing weight: none" in handoff_text(loaded["rooms"]["P4102"])
    assert loaded == before


def test_clear_editor_dose_uses_none_without_touching_other_fields(app):
    open_room(app)
    app.st.session_state["drafts"]["P4102"] = sheet()
    before = deepcopy(app.st.session_state["drafts"]["P4102"])
    key = "test_dosing_clear"
    app.st.session_state[key] = ""
    app.demographic_change("P4102", "dosing_weight", key)
    updated = app.st.session_state["drafts"]["P4102"]
    assert updated["dosing_weight"] == ""
    assert {k:v for k,v in updated.items() if k != "dosing_weight"} == {k:v for k,v in before.items() if k != "dosing_weight"}
    assert fields_with_medications(updated)["Diagnoses"].endswith("Dosing weight: none")
