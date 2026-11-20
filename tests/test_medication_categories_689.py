"""Requested 6.89 medication placements, using synthetic orders only."""
from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from categories import (apply_category_rules, catalog, default_categories,
                        medication_blocks, placement, save_category,
                        set_category_rule, target_snapshot)
from exports import handoff_html, handoff_pdf, handoff_text
from fen_gi import effective_section
from medication_groups import FIXED_HANDOFF_GROUPS, group_for
from medications import DESTINATIONS, parse_medications
from models import fields_with_medications, new_sheet, new_vault, validate_vault
from security import generate_key, open_vault, seal_vault


CASES = [
    ("ocular lubricant (Artificial Tears) ophthalmic ointment", "Both Eyes", "eye_care_lubricants", "Neurologic", "Eye Care/Lubricants"),
    ("ocular lubricant (Refresh PF) ophthalmic solution 1 drop", "Both Eyes", "eye_care_lubricants", "Neurologic", "Eye Care/Lubricants"),
    ("amantadine (Symmetrel) solution 100 mg", "Per G Tube", "neurorecovery_neurostimulant", "Neurologic", "Neurorecovery/Neurostimulant"),
    ("The Very Finest Fish Oil liquid 2.5 mL", "Per G Tube", "neurorecovery_supplement", "Neurologic", "Neurorecovery Supplement"),
    ("ferrous sulfate solution 60 mg of iron", "Per G Tube", "iron_deficiency_anemia", "Hematology", "Iron Deficiency Anemia"),
    ("hydroxyurea (Hydrea) capsule", "Oral", "sickle_cell_anemia", "Hematology", "Sickle Cell Anemia"),
    ("pyridoxine (Vitamin B-6) tablet 100 mg", "Per G Tube", "antiepileptic_adjunct", "Neurologic", "Antiepileptic Adjunct"),
    ("naproxen (Naprosyn) tablet 250 mg", "Oral", "nsaids", "Neurologic", "NSAIDS"),
    ("ibuprofen (Motrin) suspension", "Oral", "nsaids", "Neurologic", "NSAIDS"),
    ("ketorolac (Toradol) injection", "Intravenous", "nsaids", "Neurologic", "NSAIDS"),
]


def order(name, route="Oral", marker=""):
    source = name + (" " + marker if marker else "") + "\tSYNTHETIC_DOSE\t" + route + "\tDaily\t\t\t"
    result = parse_medications(source)
    assert not result.error and len(result.rows) == 1
    return result.rows[0]


@pytest.mark.parametrize("name,route,group,section,label", CASES)
@pytest.mark.parametrize("prefix", ["", "[Held by provider] ", "And: [START ON 01/02/2027] "])
def test_requested_placements_apply_without_source_changes(name, route, group, section, label, prefix):
    row = order(prefix + name, route)
    before = deepcopy(row)
    assert group_for(row) == group
    assert placement(row)["name"] == label
    assert effective_section(row) == section
    emitted = [value["id"] for destination in DESTINATIONS
               for _, value in medication_blocks(destination, "", [row])
               if isinstance(value, dict)]
    assert emitted == [row["id"]]
    assert row == before


@pytest.mark.parametrize("name,route,group,section,label", CASES)
def test_stale_saved_rules_and_row_snapshots_cannot_override_requested_placement(name, route, group, section, label):
    row = order(name, route)
    row.update(section="Other Medications", group_mode="other", gi_mode="prokinetic",
               category_path=target_snapshot("group:fever", default_categories()))
    before = deepcopy(row)
    settings = set_category_rule(new_vault()["settings"], name, "system:Respiratory")
    settings_before = deepcopy(settings)
    assert placement(row)["name"] == label
    assert effective_section(row) == section
    mapped = apply_category_rules([row], settings)[0]
    assert placement(mapped)["name"] == label
    assert effective_section(mapped) == section
    for key in ("name", "dose", "route", "frequency", "last_rate", "rate_time", "include", "hidden"):
        assert mapped[key] == row[key]
    assert row == before and settings == settings_before


@pytest.mark.parametrize("visibility", ["ignored_section", "ignored_snapshot", "hidden", "excluded", "override_pull"])
def test_requested_categories_preserve_ignore_and_visibility_choices(visibility):
    row = order("amantadine SYNTHETIC_UNPRINTED")
    if visibility == "ignored_section":
        row["section"] = "Ignore"
    elif visibility == "ignored_snapshot":
        row["category_path"] = target_snapshot("system:Ignore", default_categories())
    elif visibility == "hidden":
        row["hidden"] = True
    elif visibility == "excluded":
        row["include"] = False
    else:
        row["name"] += " override pull"
    settings = set_category_rule(new_vault()["settings"], "amantadine", "system:Respiratory")
    mapped = apply_category_rules([row], settings)[0]
    sheet = dict(new_sheet("P4102"), medications=[mapped])
    assert "SYNTHETIC_UNPRINTED" not in handoff_text(sheet)
    assert "SYNTHETIC_UNPRINTED" not in handoff_html(sheet)


def test_exact_ignore_rule_still_excludes_requested_drug():
    row = order("hydroxyurea SYNTHETIC_UNPRINTED")
    settings = set_category_rule(new_vault()["settings"], row["name"], "system:Ignore", match="exact")
    mapped = apply_category_rules([row], settings)[0]
    assert placement(mapped)["section"] == "Ignore"


@pytest.mark.parametrize("name,route", [
    ("fat emulsion fish oil/plant based (SMOFlipid) 20 % 7 g 35 mL syringe", "Intravenous"),
    ("SMOFlipid 20 % infusion", "Intravenous"),
    ("fish oil triglycerides (Omegaven) infusion", "Intravenous"),
    ("The Very Finest Fish Oil", "Intravenous"),
    ("ketorolac ophthalmic solution", "Both Eyes"),
    ("diclofenac gel", "Topical"),
    ("ibuprofen gel", "Topical"),
    ("ketorolac", "Right Eye"),
    ("ketorolac ophthalmic solution", "Nasal"),
    ("Sprix", "Both Eyes"),
    ("amantadineX", "Oral"),
    ("pyridoxine-like product", "Oral"),
    ("synthetic product with fish oil", "Oral"),
    ("aspirin", "Oral"),
    ("acetaminophen", "Oral"),
])
def test_similar_names_and_local_formulations_do_not_enter_new_fixed_groups(name, route):
    row = order(name, route)
    assert group_for(row) not in FIXED_HANDOFF_GROUPS
    if "SMOFlipid" in name:
        assert placement(row)["id"] == "gi:tpn"
        assert effective_section(row) == "FEN / GI"
    if name == "aspirin":
        assert group_for(row) == "antiplatelet"
    if name == "acetaminophen":
        assert group_for(row) == "fever"


@pytest.mark.parametrize("name,route", [
    ("ketorolac nasal spray", "Nasal"),
    ("ketorolac tromethamine (Sprix)", "Intranasal"),
    ("Sprix nasal spray", "Each Nostril"),
    ("SPRIX", "Nasal"),
])
def test_intranasal_ketorolac_remains_a_systemic_nsaid(name, route):
    row = order(name, route)
    before = deepcopy(row)
    assert group_for(row) == "nsaids"
    assert placement(row)["name"] == "NSAIDS"
    assert effective_section(row) == "Neurologic"
    assert row == before


def test_all_headings_export_once_and_do_not_add_diagnoses():
    rows = [order(name, route, f"SYNTHETIC_CLASS_{i:02d}") for i, (name, route, *_rest) in enumerate(CASES)]
    sheet = dict(new_sheet("P4102"), medications=rows)
    sheet["fields"]["Diagnoses"] = "SYNTHETIC_EXISTING_DIAGNOSIS"
    before = deepcopy(sheet)
    fields = fields_with_medications(sheet)
    for name, route, group, section, label in CASES:
        assert label in fields[section]
    assert fields["Diagnoses"] == fields_with_medications(dict(sheet, medications=[]))["Diagnoses"]
    outputs = [handoff_text(sheet), handoff_html(sheet),
               "\n".join(page.extract_text() for page in PdfReader(BytesIO(handoff_pdf(sheet))).pages)]
    for output in outputs:
        compact = "".join(output.split())
        for i in range(len(CASES)):
            assert compact.count(f"SYNTHETIC_CLASS_{i:02d}") == 1
        for label in {case[-1] for case in CASES}:
            assert "".join(label.split()) in compact
    assert sheet == before


def test_old_schema34_catalog_backfills_and_roundtrips_without_mutation():
    new_ids = {"group:" + group for group in FIXED_HANDOFF_GROUPS}
    vault = new_vault()
    vault["settings"]["medication_categories"] = [c for c in default_categories() if c["id"] not in new_ids]
    vault["rooms"]["P4102"] = dict(new_sheet("P4102"), medications=[order("hydroxyurea")])
    before = deepcopy(vault)
    validate_vault(vault)
    assert new_ids.issubset({c["id"] for c in catalog(vault["settings"])})
    key = generate_key()
    assert open_vault(seal_vault(vault, key), key) == before
    assert vault == before


def test_renamed_saved_category_does_not_absorb_fixed_heading():
    target = "group:neurorecovery_neurostimulant"
    settings = save_category(new_vault()["settings"], "Prior custom title", "Neurologic", ident=target)
    settings = set_category_rule(settings, "synthetic unrelated product", target)
    rows = apply_category_rules([order("amantadine"), order("synthetic unrelated product")], settings)
    headings = [value for kind, value in medication_blocks("Neurologic", "", rows) if kind == "heading"]
    assert set(headings) == {"Neurorecovery/Neurostimulant", "Prior custom title"}
