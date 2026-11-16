"""6.80 integration coverage using synthetic orders and weights only.

Exercise actual text, HTML, PDF, encrypted storage, and prepared-PDF paths.
No source examples, identifying data, network services, or prescribing rules.
"""
from copy import deepcopy
from datetime import datetime, timezone
from html import unescape
from io import BytesIO
import json
import re
import uuid

import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader

from categories import apply_category_rules, medication_blocks, set_category_rule
from exports import handoff_html, handoff_pdf, handoff_text
from fen_gi import effective_section
from import_review import diagnostic
from medication_doses import dose_per_kg_annotation
from medications import (destination_for, format_medication, parse_medications, remap,
                         rule_for_inline_mapping, suggested_key, upsert_rule, validate_medication)
from models import fields_with_medications, new_sheet, new_vault, save_sheet_in, validate_sheet
from pdf_cache import SessionPdfCache, cached_handoffs_pdf
from security import open_vault, seal_vault


NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def medication(name, dose, *, route="Intravenous", frequency="q6h", section="Other Medications"):
    row = {
        "id": uuid.uuid4().hex,
        "name": name,
        "dose": dose,
        "route": route,
        "frequency": frequency,
        "last_rate": "",
        "rate_time": "",
        "custom_text": "",
        "section": section,
        "include": True,
        "hidden": False,
        "warnings": [],
    }
    validate_medication(row)
    return row


def sheet_with(rows, *, room="P4102", dcw="10 kg", measured="12 kg"):
    sheet = new_sheet(room)
    sheet["fields"]["Diagnoses"] = "Synthetic medication display example"
    sheet["dosing_weight"] = dcw
    sheet["nutrition"] = ({"weight": measured, "z_score": "", "include": True}
                          if measured else None)
    sheet["medications"] = deepcopy(rows)
    validate_sheet(sheet)
    return sheet


def pdf_text(data):
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)


def compact(text):
    return re.sub(r"\s+", "", unescape(re.sub(r"<[^>]*>", "", text)))


def render(sheet, kind):
    if kind == "text":
        return handoff_text(sheet, NOW)
    if kind == "html":
        return handoff_html(sheet, NOW)
    return pdf_text(handoff_pdf(sheet, NOW))


@pytest.mark.parametrize("kind", ["text", "html", "pdf"])
def test_both_nebulizer_volumes_separate_from_enteral_sodium_in_actual_exports(kind):
    rules = upsert_rule([], "sodium chloride", "FEN / GI")
    block = (
        "Medications:\nMedication\tDose\tRoute\tFrequency\n"
        "sodium chloride 3 % nebulizer solution 3 mL\t3 mL\tNebulization\tq12h\n"
        "sodium chloride 3 % nebulizer solution 4 mL\t4 mL\tNebulization\tq8h\n"
        "sodium chloride enteral solution 6 mEq\t6 mEq\tPer G Tube\tq12h\n"
    )
    parsed = parse_medications(block, rules)
    assert not parsed.error
    assert len(parsed.rows) == 3
    sheet = sheet_with(apply_category_rules(parsed.rows, new_vault()["settings"]))
    before = deepcopy(sheet)
    fields = fields_with_medications(sheet)
    for volume in (3, 4):
        label = f"sodium chloride 3 % nebulizer solution {volume} mL"
        assert label in fields["Respiratory"]
        assert label not in fields["FEN / GI"]
    assert "Airway Clearance" in fields["Respiratory"]
    assert "sodium chloride enteral solution" in fields["FEN / GI"]
    assert "sodium chloride enteral solution" not in fields["Respiratory"]
    assert [effective_section(row) for row in sheet["medications"]] == [
        "Respiratory", "Respiratory", "FEN / GI",
    ]
    output = compact(render(sheet, kind))
    assert output.count("AirwayClearance") == 1
    for row in sheet["medications"]:
        assert output.count(compact(row["name"])) == 1
    assert sheet == before


@pytest.mark.parametrize("kind", ["text", "html", "pdf"])
def test_source_weight_based_order_survives_rounded_absolute_discrepancy(kind):
    row = medication("chlorothiazide (Diuril) injection 95 mg", "10 mg/kg (Dosing Weight)",
                     frequency="q12h")
    sheet = sheet_with([row])
    before = deepcopy(sheet)
    assert dose_per_kg_annotation(row, sheet) == ""
    output = compact(render(sheet, kind))
    assert "95mg" in output
    # Existing handoff cleanup hides the literal '(Dosing Weight)' qualifier.
    # Its source dose and numerical mg/kg value must still remain unchanged.
    assert "Dose:10mg/kg" in output
    assert "9.5mg/kg" not in output
    assert "Calc:" not in output
    assert sheet == before
    assert sheet["medications"][0]["dose"] == "10 mg/kg (Dosing Weight)"


@pytest.mark.parametrize("kind", ["text", "html", "pdf"])
def test_sedative_and_both_diuretic_dose_annotations_reach_all_exports(kind):
    rows = [
        medication("midazolam injection 2 mg", "2 mg", frequency="q2h PRN"),
        medication("fentanyl injection 20 mcg", "20 mcg", frequency="q2h PRN"),
        medication("furosemide injection 14 mg", "14 mg"),
        medication("chlorothiazide suspension 80 mg", "80 mg", route="Per G Tube", frequency="q12h"),
    ]
    sheet = sheet_with(rows)
    before = deepcopy(sheet)
    output = compact(render(sheet, kind))
    for expected in ("0.2 mg/kg/dose", "2 mcg/kg/dose", "1.4 mg/kg/dose", "8 mg/kg/dose"):
        assert compact("Calc: " + expected + " (DCW 10 kg)") in output
    assert output.count("Calc:") == 4
    for row in rows:
        assert compact(row["name"]) in output
    assert sheet == before


def test_transient_annotations_never_mutate_rows_or_enter_encrypted_archive():
    rows = [
        medication("midazolam injection", "2 mg", frequency="q2h PRN"),
        medication("furosemide injection", "14 mg"),
    ]
    sheet = sheet_with(rows)
    before = deepcopy(sheet)
    blocks = medication_blocks("Neurologic", "", sheet["medications"], sheet)
    emitted = [item for kind, item in blocks if kind == "medication"]
    assert len(emitted) == 1
    assert "0.2 mg/kg/dose (DCW 10 kg)" in format_medication(emitted[0])
    assert "0.2 mg/kg/dose (DCW 10 kg)" in format_medication(sheet["medications"][0], sheet)
    assert "1.4 mg/kg/dose (DCW 10 kg)" in handoff_text(sheet, NOW)
    assert sheet == before
    assert all(not any(key.startswith("_") for key in row) for row in sheet["medications"])
    vault = save_sheet_in(new_vault(), sheet)
    key = Fernet.generate_key().decode()
    restored = open_vault(seal_vault(vault, key), key)
    assert restored["rooms"]["P4102"] == vault["rooms"]["P4102"]
    assert "_dose_per_kg" not in json.dumps(restored)
    assert "Calc:" not in json.dumps(restored)
    assert "1.4 mg/kg/dose (DCW 10 kg)" in handoff_text(restored["rooms"]["P4102"], NOW)


def test_manual_sedative_prn_category_receives_calculation_in_display():
    row = medication("clonidine suspension 15 mcg", "15 mcg", route="Per G Tube", frequency="q6h PRN")
    settings = set_category_rule(new_vault()["settings"], row["name"], "group:sedative_prn",
                                 "exact", row["route"], row["frequency"])
    sheet = sheet_with(apply_category_rules([row], settings))
    fields = fields_with_medications(sheet)
    assert "Calc: 1.5 mcg/kg/dose (DCW 10 kg)" in fields["Neurologic"]
    assert "clonidine" not in fields["Cardiovascular"]


@pytest.mark.parametrize("change,expected", [
    ("dose", "2 mg/kg/dose (DCW 10 kg)"),
    ("dosing_weight", "0.7 mg/kg/dose (DCW 20 kg)"),
    ("weight_warning", ""),
])
def test_cached_pdf_reuses_unchanged_rooms_and_rebuilds_changed_medication_basis(change, expected):
    row = medication("furosemide injection", "14 mg")
    sheets = [sheet_with([row]), sheet_with([row], room="P4104")]
    cache = SessionPdfCache()
    first = [cache.prepare(sheet, NOW) for sheet in sheets]
    assert cache.stats["builds"] == 2
    cached_handoffs_pdf(sheets, cache, NOW)
    assert cache.stats["builds"] == 2
    if change == "dose":
        sheets[0]["medications"][0]["dose"] = "20 mg"
    elif change == "dosing_weight":
        sheets[0]["dosing_weight"] = "20 kg"
    else:
        sheets[0]["import_warnings"]["i"] = [diagnostic("i", "section_parse_failed", action="not_imported")]
    cached_handoffs_pdf(sheets, cache, NOW)
    changed = cache.prepare(sheets[0], NOW)
    unchanged = cache.prepare(sheets[1], NOW)
    assert cache.stats["builds"] == 3
    assert changed.signature != first[0].signature
    assert unchanged is first[1]
    text = compact(pdf_text(changed.data))
    assert "1.4mg/kg/dose" not in text
    if expected:
        assert compact("Calc: " + expected) in text
    else:
        assert "Calc:" not in text


@pytest.mark.parametrize("kind", ["text", "html", "pdf"])
@pytest.mark.parametrize("basis", ["missing", "failed_import"])
def test_missing_or_failed_weight_withholds_derived_value_but_preserves_orders(kind, basis):
    sheet = sheet_with([
        medication("furosemide injection 14 mg", "14 mg"),
        medication("chlorothiazide injection 95 mg", "10 mg/kg (Dosing Weight)", frequency="q12h"),
    ])
    if basis == "missing":
        sheet["dosing_weight"] = ""
        sheet["nutrition"] = None
    else:
        sheet["import_warnings"]["i"] = [diagnostic("i", "section_parse_failed", action="not_imported")]
    output = compact(render(sheet, kind))
    assert "furosemideinjection14mg" in output
    assert "Dose:10mg/kg" in output
    assert "Calc:" not in output
    assert sheet["medications"][1]["dose"] == "10 mg/kg (Dosing Weight)"


@pytest.mark.parametrize("kind", ["text", "html", "pdf"])
def test_custom_handoff_wording_remains_authoritative(kind):
    row = medication("furosemide injection 14 mg", "14 mg")
    row["custom_text"] = "Synthetic custom diuretic instruction"
    sheet = sheet_with([row])
    before = deepcopy(sheet)
    output = compact(render(sheet, kind))
    assert output.count("Syntheticcustomdiureticinstruction") == 1
    assert "Calc:" not in output
    assert "furosemideinjection" not in output
    assert sheet == before


@pytest.mark.parametrize("kind", ["text", "html", "pdf"])
def test_measured_weight_fallback_is_identified_separately(kind):
    sheet = sheet_with([medication("furosemide injection 12 mg", "12 mg")], dcw="", measured="12 kg")
    output = compact(render(sheet, kind))
    assert "Calc:1mg/kg/dose(weight12kg)" in output
    assert "DCW12kg" not in output


@pytest.mark.parametrize("identity", ["sodium chloride", "NaCl"])
def test_inline_mapping_suggestion_keeps_concentration_and_nebulizer_form(identity):
    first = f"{identity} 3 % nebulizer solution 3 mL"
    second = f"{identity} 3 % nebulizer solution 4 mL"
    expected = identity.lower() + " 3 % nebulizer solution"
    assert suggested_key(first) == suggested_key(second) == expected
    old_rules = upsert_rule([], identity, "Respiratory")
    assert rule_for_inline_mapping(first, old_rules) == (expected, "prefix")
    assert suggested_key(f"{identity} enteral solution 6 mEq") != expected
    assert suggested_key("sodium acetate 40 mEq infusion") == "sodium acetate"
    assert suggested_key("potassium chloride solution 4 mEq") == "potassium chloride solution"


@pytest.mark.parametrize("identity", ["sodium chloride", "NaCl"])
def test_generic_legacy_respiratory_rule_cannot_sweep_other_saline_orders_on_parse_or_remap(identity):
    rules = upsert_rule([], identity, "Respiratory")
    specs = [
        (f"{identity} 3 % nebulizer solution 3 mL", "3 mL", "Nebulization", "q12h"),
        (f"{identity} 3 % nebulizer solution 4 mL", "4 mL", "Nebulization", "q8h"),
        (f"{identity} enteral solution 6 mEq", "6 mEq", "Per G Tube", "q12h"),
        (f"{identity} 0.9 % nebulizer solution 3 mL", "3 mL", "Nebulization", "q8h"),
        (f"{identity} 3 % injection 20 mL", "20 mL", "Intravenous", "Once"),
    ]
    block = "Medication\tDose\tRoute\tFrequency\n" + "\n".join("\t".join(spec) for spec in specs)
    parsed = parse_medications(block, rules)
    assert not parsed.error
    expected = ["Respiratory", "Respiratory", "Other Medications", "Other Medications", "Other Medications"]
    assert [row["section"] for row in parsed.rows] == expected
    # Simulate retained rows that the older generic mapping had placed in Respiratory.
    old_rows = [dict(row, section="Respiratory") for row in parsed.rows]
    before = deepcopy(old_rows)
    updated = remap(old_rows, rules)
    assert [row["section"] for row in updated] == expected
    assert old_rows == before
    for row in updated:
        assert destination_for(row["name"], rules, row["route"]) == row["section"]


@pytest.mark.parametrize("identity", ["sodium chloride", "NaCl"])
def test_explicit_exact_and_formulation_specific_saline_rules_still_work(identity):
    enteral = medication(f"{identity} enteral solution 6 mEq", "6 mEq", route="Per G Tube")
    isotonic = medication(f"{identity} 0.9 % nebulizer solution 3 mL", "3 mL", route="Nebulization")
    generic = upsert_rule([], identity, "Respiratory")
    exact = upsert_rule(generic, enteral["name"], "Respiratory", "exact")
    specific = upsert_rule(generic, identity + " 0.9 % nebulizer solution", "Respiratory")
    assert destination_for(enteral["name"], exact, enteral["route"]) == "Respiratory"
    assert destination_for(isotonic["name"], specific, isotonic["route"]) == "Respiratory"
    assert remap([enteral], exact)[0]["section"] == "Respiratory"
    assert remap([isotonic], specific)[0]["section"] == "Respiratory"
    # The safeguard only narrows the mistaken generic Respiratory assignment.
    fen_rule = upsert_rule([], identity, "FEN / GI")
    assert destination_for(enteral["name"], fen_rule, enteral["route"]) == "FEN / GI"


@pytest.mark.parametrize("identity", ["sodium chloride", "NaCl"])
def test_generic_category_assignment_to_airway_clearance_does_not_sweep_other_saline(identity):
    rows = [
        medication(f"{identity} 3 % nebulizer solution 4 mL", "4 mL", route="Nebulization"),
        medication(f"{identity} enteral solution 6 mEq", "6 mEq", route="Per G Tube", section="FEN / GI"),
    ]
    settings = set_category_rule(new_vault()["settings"], identity, "group:airway_clearance")
    mapped = apply_category_rules(rows, settings)
    assert [effective_section(row) for row in mapped] == ["Respiratory", "FEN / GI"]
    explicit = set_category_rule(settings, rows[1]["name"], "group:airway_clearance",
                                 "exact", rows[1]["route"], rows[1]["frequency"])
    assert effective_section(apply_category_rules([rows[1]], explicit)[0]) == "Respiratory"
