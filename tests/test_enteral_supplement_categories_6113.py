"""Requested supplement headings, using source-shaped synthetic orders only."""
from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from categories import (add_missing_builtin_categories, apply_category_rules, catalog, default_categories,
                        medication_blocks, placement, save_category, set_category_rule, target_snapshot)
from exports import handoff_html, handoff_pdf, handoff_text
from fen_gi import FIXED_GI_GROUPS, automatic_group, effective_section, fixed_gi_group, group_for
from importing import import_sections
from medications import DESTINATIONS, parse_medications, upsert_rule
from models import fields_with_medications, new_sheet, new_vault, validate_vault
from security import generate_key, open_vault, seal_vault


CASES = [
    ("calcium carbonate (Tums) chewable tablet 500 mg", "Oral", "hypocalcemia", "Hypocalcemia"),
    ("sodium chloride enteral solution 6 mEq", "Per G Tube", "hyponatremia", "Hyponatremia"),
    ("zinc acetate oral solution 10 mg", "Per NJ Tube", "zinc_deficiency", "Zinc Deficiency"),
]
NEW_IDS = {"gi:" + group for group in FIXED_GI_GROUPS}


def order(name, route="Oral"):
    result = parse_medications("Medications:\n• " + "\t".join((name, "SYNTHETIC_DOSE", route or "Oral", "q12h", "", "", "")))
    assert not result.error and len(result.rows) == 1
    row = result.rows[0]
    row["route"] = route
    return row


@pytest.mark.parametrize("name,route,group,label", CASES)
@pytest.mark.parametrize("prefix", ["", "[Held by provider] ", "And: [START ON 01/02/2027] "])
def test_requested_headings_apply_once_without_changing_source_fields(name, route, group, label, prefix):
    row = order(prefix + name, route)
    before = deepcopy(row)
    assert fixed_gi_group(row) == automatic_group(row) == group_for(row) == group
    assert placement(row)["id"] == "gi:" + group
    assert placement(row)["name"] == label
    assert effective_section(row) == "FEN / GI"
    emitted = [value["id"] for section in DESTINATIONS
               for _, value in medication_blocks(section, "", [row]) if isinstance(value, dict)]
    assert emitted == [row["id"]]
    assert row == before


@pytest.mark.parametrize("route", ["Oral", "PO", "Enteral", "Per G Tube", "Per NG Tube", "Per NJ Tube",
                                   "Per OG Tube", "Per GJ Tube", "Per J Tube", "Per NG/OG Tube", "PEG", "PEG-J",
                                   "Gastrostomy tube", "Nasoenteric (post-pyloric) tube", "Per Feeding Tube"])
def test_recorded_enteral_routes_qualify_salts(route):
    assert fixed_gi_group(order("calcium carbonate", route)) == "hypocalcemia"
    assert fixed_gi_group(order("sodium chloride", route)) == "hyponatremia"


@pytest.mark.parametrize("name,group", [("calcium carbonate oral suspension", "hypocalcemia"),
                                       ("calcium carbonate chewable tablet", "hypocalcemia"),
                                       ("sodium chloride enteral solution", "hyponatremia"),
                                       ("NaCl oral solution", "hyponatremia"),
                                       ("zinc acetate", "zinc_deficiency")])
def test_unambiguous_enteral_form_and_requested_zinc_name_allow_missing_route(name, group):
    assert fixed_gi_group(order(name, "")) == group


@pytest.mark.parametrize("name,route", [
    ("calcium carbonate", ""), ("sodium chloride solution", ""),
    ("calcium carbonate", "Intravenous"), ("calcium carbonate oral suspension", "Intravenous"),
    ("calcium gluconate injection", "Intravenous"), ("calcium chloride injection", "Intravenous"),
    ("calcium acetate capsule", "Oral"), ("calcium carbonate-vitamin D tablet", "Oral"),
    ("calcium carbonate / vitamin D tablet", "Oral"),
    ("sodium chloride 0.9 % infusion", "Intravenous"), ("sodium chloride 0.9 % flush", "Intracatheter"),
    ("sodium chloride 3 % nebulizer solution", "Nebulization"),
    ("sodium chloride 3 % nebulizer solution", "Oral"),
    ("sodium chloride enteral solution", "Nebulization"),
    ("sodium chloride nasal spray", "Nasal"), ("sodium chloride IV solution", ""),
    ("sodium chloride", "Endotracheal tube"),
    ("zinc acetate injection", ""), ("zinc acetate", "Intravenous"),
    ("zinc acetate cream", "Topical"), ("zinc acetate IVPB", ""),
    ("zinc acetate in sodium chloride 0.9 %", ""), ("zinc sulfate", "Oral"),
    ("synthetic product with zinc acetate", "Oral"),
    ("sodium chloridex", "Oral"), ("calcium carbonate-like compound", "Oral"),
])
def test_nonenteral_other_salts_mixtures_and_substrings_are_not_recategorized(name, route):
    assert fixed_gi_group(order(name, route)) == ""


@pytest.mark.parametrize("name,route,group,label", CASES)
def test_saved_rules_and_snapshots_keep_definitions_but_use_requested_heading(name, route, group, label):
    row = order(name, route)
    row.update(section="Respiratory", group_mode="anticholinergic", gi_mode="other",
               category_path=target_snapshot("group:fever", default_categories()))
    original = deepcopy(row)
    settings = set_category_rule(new_vault()["settings"], name, "system:Respiratory")
    settings["medication_mappings"] = upsert_rule([], name, "Respiratory")
    before = deepcopy(settings)
    assert placement(row)["name"] == label and effective_section(row) == "FEN / GI"
    mapped = apply_category_rules([row], settings)[0]
    assert placement(mapped)["id"] == "gi:" + group
    assert mapped["section"] == "FEN / GI"
    assert {key: value for key, value in mapped.items() if key not in {"section", "category_path"}} == {
        key: value for key, value in row.items() if key not in {"section", "category_path"}}
    assert row == original and settings == before


@pytest.mark.parametrize("name,route,group,label", CASES)
@pytest.mark.parametrize("visibility", ["ignored_section", "ignored_snapshot", "hidden", "excluded", "override_pull"])
def test_requested_heading_preserves_visibility_choices(name, route, group, label, visibility):
    row = order(name + " SYNTHETIC_UNPRINTED", route)
    if visibility == "ignored_section":
        row["section"] = "Ignore"
    elif visibility == "ignored_snapshot":
        row["category_path"] = target_snapshot("system:Ignore", default_categories())
    elif visibility == "hidden":
        row["hidden"] = True
    elif visibility == "excluded":
        row["include"] = False
    else:
        row["name"] += " ADS Override Pull"
    settings = set_category_rule(new_vault()["settings"], name, "system:Respiratory")
    mapped = apply_category_rules([row], settings)[0]
    sheet = dict(new_sheet("P4102"), medications=[mapped])
    assert "SYNTHETIC_UNPRINTED" not in handoff_text(sheet)
    assert "SYNTHETIC_UNPRINTED" not in handoff_html(sheet)


@pytest.mark.parametrize("name,route,group,label", CASES)
def test_explicit_ignore_mapping_still_wins(name, route, group, label):
    row = order(name, route)
    settings = set_category_rule(new_vault()["settings"], name, "system:Ignore", match="exact")
    assert placement(apply_category_rules([row], settings)[0])["section"] == "Ignore"


def test_new_categories_backfill_without_rewriting_saved_catalog_or_rules():
    vault = new_vault()
    vault["settings"]["medication_categories"] = [item for item in default_categories() if item["id"] not in NEW_IDS]
    vault["settings"]["medication_categories"].append(dict(id="custom:existing_calcium", name="Hypocalcemia",
                                                          section="FEN / GI", parent="", order=105))
    before = deepcopy(vault)
    available = {item["id"]: item for item in catalog(vault["settings"])}
    assert NEW_IDS <= available.keys()
    assert available["gi:hypocalcemia"]["name"] == "Hypocalcemia (default)"
    validate_vault(vault)
    key = generate_key()
    assert open_vault(seal_vault(vault, key), key) == before
    upgraded = add_missing_builtin_categories(vault["settings"])
    assert NEW_IDS <= {item["id"] for item in upgraded["medication_categories"]}
    assert vault == before


def test_fixed_heading_does_not_merge_with_a_renamed_saved_category():
    settings = save_category(new_vault()["settings"], "Saved calcium category", "FEN / GI", ident="gi:hypocalcemia")
    settings = set_category_rule(settings, "Synthetic companion", "gi:hypocalcemia")
    rows = apply_category_rules([order(CASES[0][0]), order("Synthetic companion")], settings)
    blocks = medication_blocks("FEN / GI", "", rows)
    assert {value for kind, value in blocks if kind == "heading"} == {"Hypocalcemia", "Saved calcium category"}
    assert sum(isinstance(value, dict) for _, value in blocks) == 2


def test_import_and_all_handoff_exports_keep_enteral_salts_separate_from_iv_and_nebulized_saline():
    rows = [order(name, route) for name, route, _, _ in CASES]
    rows += [order("sodium chloride 3 % nebulizer solution 3 mL", "Nebulization"),
             order("sodium chloride 0.9 % infusion", "Intravenous"),
             order("calcium gluconate injection", "Intravenous")]
    rows[-2]["frequency"] = "Continuous"
    sheet = dict(new_sheet("P4102"), medications=rows)
    sheet["fields"]["Diagnoses"] = "SYNTHETIC_EXISTING_DIAGNOSIS"
    before = deepcopy(sheet)
    fields = fields_with_medications(sheet)
    for name, route, group, label in CASES:
        assert label in fields["FEN / GI"] and name in fields["FEN / GI"]
    assert "Airway Clearance" in fields["Respiratory"]
    assert "sodium chloride 3 % nebulizer solution" not in fields["FEN / GI"]
    assert placement(rows[-2])["id"] == "gi:iv_fluids"
    assert placement(rows[-1])["id"] not in NEW_IDS
    for output in (handoff_text(sheet), handoff_html(sheet),
                   "\n".join(page.extract_text() for page in PdfReader(BytesIO(handoff_pdf(sheet))).pages)):
        output = " ".join(output.split())
        for name, _, _, label in CASES:
            assert label in output and output.count(name) == 1
        assert "SYNTHETIC_DOSE" in output
    assert sheet == before
    source = "bbbbbbbbbbbb\nMedications:\n" + "\n".join(
        "• " + "\t".join((name, "SYNTHETIC_DOSE", route, "q12h", "", "", ""))
        for name, route, _, _ in CASES) + "\nBBBBBBBBBBBB"
    imported = import_sections(new_sheet("P4102"), source, new_vault()["settings"])
    assert not imported.errors
    assert {placement(row)["id"] for row in imported.sheet["medications"]} == NEW_IDS


@pytest.mark.parametrize("note_type", ["progress", "attestation"])
def test_fixed_category_note_plans_are_unique_without_zinc_phrase_or_medication_subheadings(note_type):
    from note_generator import generate_note
    rows = [order(name, route) for name, route, _, _ in CASES]
    rows.append(order("calcium carbonate oral suspension", "Per G Tube"))
    mapped = apply_category_rules(rows, new_vault()["settings"])
    assert {row["category_path"]["id"] for row in mapped} == NEW_IDS
    sheet = dict(new_sheet("P4102"), medications=mapped)
    before = deepcopy(sheet)
    result = generate_note(sheet, note_type=note_type)
    assert result["selected_plan_tokens"].count("@ACKZHYPOCALCEMIA@") == 1
    assert result["selected_plan_tokens"].count("@ACKZHYPONATREMIA@") == 1
    assert not any("ZINC" in token for token in result["selected_plan_tokens"])
    assert not any(item["id"] == "zinc_deficiency" for item in result["suggestions"])
    assert all(label not in result["text"] for label in ("Hypocalcemia", "Hyponatremia", "Zinc Deficiency"))
    assert sheet == before
