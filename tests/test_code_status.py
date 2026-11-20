"""Synthetic AE import, room replacement, storage and output regressions."""
from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from batching import available_handoffs
from code_status import code_status_text, parse_code_status, validate_code_status
from exports import handoff_html, handoff_pdf, handoff_text
from importing import import_replacement, import_sections
from import_review import diagnostic_text, review_summary
from models import fields_with_medications, new_sheet, new_vault, save_sheet_in, validate_sheet
from parser import parse_smartphrase
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room


def block(marker, body):
    divider = marker * 10
    return divider + "\n" + body + "\n" + divider


def source(value="Full Code"):
    return block("a", "Diagnoses:\n1. SYNTHETIC_TRAINING_EXAMPLE") + "\n" + block("ae", "Code Status:\n" + value)


def imported(value="Full Code"):
    result = import_replacement("P4102", source(value), new_vault()["settings"])
    assert result.sheet is not None, result.errors
    assert not result.errors, result.errors
    return result.sheet


@pytest.mark.parametrize("value", ["Full Code", "No Order", "DNR", "DNI", "DNR/DNI", "Limited Resuscitation"])
@pytest.mark.parametrize("separator", ["\n", " "])
def test_explicit_status_is_preserved_with_inline_or_next_line_value(value, separator):
    parsed = parse_code_status("Code Status:" + separator + value)
    assert not parsed.error
    assert parsed.value == value
    sheet = imported(value)
    assert sheet["code_status"] == value
    assert code_status_text(sheet) == "Code Status: " + value


@pytest.mark.parametrize("divider", ["ae" * 4, "AE" * 8, "ae" * 9 + "a"])
def test_ae_divider_variants_and_adjacent_ad_ac_blocks(divider):
    text = (block("ad", "System Readings\nECMO Mode: VV") + "\n"
            + divider + "\nCode Status: No Order\n" + divider + "\n"
            + block("ac", "Stool / bowel movement:\nNo data recorded"))
    parsed = parse_smartphrase(text)
    assert parsed.blocks["ae"] == "Code Status: No Order"
    assert {"ad", "ae", "ac"}.issubset(parsed.blocks)
    assert not parsed.invalid


def test_code_status_is_once_in_demographics_and_all_exports():
    sheet = imported("No Order")
    sheet["admission_date"] = "11/20/2026"
    sheet["fields"]["Demographics / Weight"] = "Manual demographic note"
    fields = fields_with_medications(sheet)
    assert fields["Demographics / Weight"] == "Admission: 11/20/2026\nManual demographic note\nCode Status: No Order"
    outputs = [handoff_text(sheet), handoff_html(sheet)]
    outputs.append("\n".join(page.extract_text() for page in PdfReader(BytesIO(handoff_pdf(sheet))).pages))
    for text in outputs:
        assert text.count("Code Status:") == 1
        assert "No Order" in text
        assert "Full Code" not in text


def test_code_status_label_only_is_bold_and_value_is_escaped():
    markup = handoff_html(imported("DNR/DNI <review>"))
    assert "<b>Code Status:</b> DNR/DNI &lt;review&gt;" in markup
    assert "<b>DNR/DNI" not in markup


def test_empty_heading_clears_an_old_value_without_inference():
    previous = imported()
    result = import_sections(previous, block("ae", "Code Status:"), new_vault()["settings"])
    assert not result.errors
    assert result.sheet["code_status"] == ""
    assert code_status_text(result.sheet) == ""
    assert previous["code_status"] == "Full Code"
    assert code_status_text(new_sheet("P4102")) == ""


@pytest.mark.parametrize("bad", [
    "aeaeaeae\nCode Status:\nFull Code",
    "aeaeaeae\nCode Status:\nFull Code\naeaeaeaeaeaeaebe",
    block("ae", "VITALS:\nFull Code"),
    block("ae", "Code Status:\nFull Code\nDNR"),
    block("ae", "Code Status: Full Code\nCode Status: DNR"),
])
def test_failed_status_import_clears_old_status_and_reports_review(bad):
    previous = imported("DNR")
    result = import_sections(previous, bad, new_vault()["settings"])
    assert result.errors
    assert result.sheet["code_status"] == ""
    assert code_status_text(result.sheet) == ""
    assert "cleared" in review_summary(result.sheet)
    assert "prior status was cleared" in diagnostic_text(result.sheet["import_warnings"]["ae"][0])
    assert previous["code_status"] == "DNR"


def test_bad_ae_does_not_discard_valid_new_diagnosis_or_carry_prior_data():
    text = block("a", "Diagnoses:\n1. NEW_SYNTHETIC_DIAGNOSIS") + "\naeaeaeae\nCode Status:\nDNR"
    result = import_replacement("P4102", text, new_vault()["settings"])
    assert result.sheet is not None
    assert result.sheet["fields"]["Diagnoses"] == "NEW_SYNTHETIC_DIAGNOSIS"
    assert code_status_text(result.sheet) == ""
    assert result.sheet["import_warnings"]["ae"][0]["action"] == "not_imported"


def test_multiple_ae_pairs_reject_the_document():
    result = import_replacement("P4102", source() + "\n" + block("ae", "Code Status:\nDNR"), new_vault()["settings"])
    assert result.sheet is None
    assert result.errors


def test_complete_new_paste_without_ae_clears_old_status_and_preserves_other_rooms(app):
    open_room(app)
    ss = app.st.session_state
    ss["paste"] = source("DNR")
    app.create_handoff(None)
    first_id = ss["drafts"]["P4102"]["id"]
    assert ss["drafts"]["P4102"]["code_status"] == "DNR"
    other = new_sheet("P4104")
    other["fields"]["Diagnoses"] = "OTHER_SYNTHETIC_ROOM"
    other["code_status"] = "No Order"
    ss["vault"] = save_sheet_in(ss["vault"], other)
    original_other = deepcopy(ss["vault"]["rooms"]["P4104"])
    ss["paste"] = block("a", "Diagnoses:\n1. NEW_SYNTHETIC_ROOM")
    app.create_handoff(None)
    current = ss["drafts"]["P4102"]
    assert current["id"] != first_id
    assert not current.get("code_status")
    assert code_status_text(current) == ""
    assert ss["vault"]["rooms"]["P4104"] == original_other


def test_optional_status_is_backward_compatible_and_survives_encryption():
    legacy = new_sheet("P4104")
    assert "code_status" not in legacy
    validate_sheet(legacy)
    current = imported("No Order")
    vault = save_sheet_in(save_sheet_in(new_vault(), legacy), current)
    key = generate_key()
    assert open_vault(seal_vault(vault, key), key) == vault


@pytest.mark.parametrize("value", [None, 1, {}, "Full Code\nDNR", "Full Code\tDNR", "x" * 301, "Full Code\x00"])
def test_invalid_saved_status_is_rejected(value):
    with pytest.raises(ValueError):
        validate_code_status(value)
    sheet = new_sheet("P4102")
    sheet["code_status"] = value
    with pytest.raises(ValueError):
        validate_sheet(sheet)


def test_code_status_only_handoff_is_available_to_print():
    result = import_replacement("P4102", block("ae", "Code Status:\nNo Order"), new_vault()["settings"])
    assert result.sheet is not None
    assert "P4102" in available_handoffs(new_vault(), {"P4102": result.sheet})
