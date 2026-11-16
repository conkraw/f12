"""Synthetic regressions for formulation-specific saline airway placement."""
from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from airway_clearance import is_sodium_chloride_3_percent_nebulizer
from categories import (BACKFILLED_BUILTIN_IDS, apply_category_rules, catalog,
                        default_categories, matching_target, medication_blocks,
                        placement, save_category, set_category_rule,
                        target_snapshot, validate_settings)
from exports import handoff_html, handoff_pdf, handoff_text
from fen_gi import effective_section
from medication_groups import group_for
from medications import DESTINATIONS, parse_medications, upsert_rule
from models import new_sheet, new_vault, validate_vault


TARGET = "group:airway_clearance"
LABEL = "Airway Clearance"


def order(name="sodium chloride 3 % nebulizer solution 3 mL", dose="3 mL",
          route="Nebulization", frequency="q12h", rules=None):
    parsed = parse_medications("\t".join([name, dose, route, frequency, "", "", ""]), rules)
    assert not parsed.error and len(parsed.rows) == 1
    return parsed.rows[0]


@pytest.mark.parametrize("name,route", [
    ("sodium chloride 3 % nebulizer solution 3 mL", "Nebulization"),
    ("sodium chloride 3 % nebulizer solution 4 mL", "Nebulization"),
    ("NaCl 3% inhalation solution", "Inhalation"),
    ("sodium chloride 3.0% solution", "Nebulization"),
    ("sodium chloride 3% nebuliser solution", ""),
    ("Or: [START ON 01/01/2026] sodium chloride 3% nebulizer solution", "Nebulization"),
    ("sodium chloride (HyperSal) 3 % nebulizer solution", "Nebulization"),
])
def test_qualifying_formulations(name, route):
    assert is_sodium_chloride_3_percent_nebulizer(dict(name=name, route=route))


@pytest.mark.parametrize("name,route", [
    ("sodium chloride enteral solution 17 mEq", "Per NJ Tube"),
    ("sodium chloride 0.9 % nebulizer solution 3 mL", "Nebulization"),
    ("sodium chloride 7 % nebulizer solution 4 mL", "Nebulization"),
    ("sodium chloride 0.3 % nebulizer solution", "Nebulization"),
    ("sodium chloride 13 % nebulizer solution", "Nebulization"),
    ("sodium chloride 3 % infusion", "Intravenous"),
    ("sodium chloride 3 % nebulizer solution", "Intravenous"),
    ("sodium chloride 3 % nebulizer solution", "Oral"),
    ("sodium chloride 3 % nasal spray", "Inhalation"),
    ("sodium chloride 3 % injection", "Nebulization"),
    ("sodium chloride 3 % solution", ""),
    ("sodium chloride 3 % with albuterol nebulizer solution", "Nebulization"),
    ("sodium chloride 3%-albuterol nebulizer solution", "Nebulization"),
    ("sodium chloride 3 % and sodium bicarbonate nebulizer solution", "Nebulization"),
    ("sodium chloride 3 % in dextrose 5 %", "Nebulization"),
    ("sodium chloride-like 3 % nebulizer solution", "Nebulization"),
    ("sodium acetate in sodium chloride 3 % solution", "Nebulization"),
    ("micafungin 1 mg/mL NaCl syringe 25 mg", "Intravenous"),
    ("cefepime in NaCl 0.9 % injection 700 mg", "Intravenous"),
])
def test_other_saline_orders_and_mixtures_are_not_captured(name, route):
    assert not is_sodium_chloride_3_percent_nebulizer(dict(name=name, route=route))


@pytest.mark.parametrize("volume", ["3", "4"])
def test_fixed_placement_wins_over_old_conflicting_assignments_once(volume):
    row = order(f"sodium chloride 3 % nebulizer solution {volume} mL", f"{volume} mL")
    row.update(section="FEN / GI", group_mode="other", gi_mode="bowel",
               category_path=target_snapshot("gi:prophylaxis", default_categories()))
    before = deepcopy(row)
    assert group_for(row) == "airway_clearance"
    assert effective_section(row) == "Respiratory"
    assert placement(row)["id"] == TARGET
    visible = [value["id"] for section in DESTINATIONS
               for kind, value in medication_blocks(section, "", [row]) if isinstance(value, dict)]
    assert visible == [row["id"]]
    sheet = dict(new_sheet("P4102"), medications=[row])
    for text in (handoff_text(sheet), handoff_html(sheet)):
        assert LABEL in text
        assert text.count(row["name"]) == 1
        assert "q12h" in text
    assert row == before


def test_category_apply_overrides_broad_gi_rule_for_neb_but_preserves_enteral():
    settings = set_category_rule(new_vault()["settings"], "sodium chloride", "gi:prophylaxis")
    rows = [order(), order("sodium chloride enteral solution 17 mEq", "17 mEq", "Per NJ Tube")]
    before = deepcopy(rows)
    applied = apply_category_rules(rows, settings)
    assert placement(applied[0])["id"] == TARGET
    assert placement(applied[1])["id"] == "gi:prophylaxis"
    assert effective_section(applied[1]) == "FEN / GI"
    for original, updated in zip(rows, applied):
        for field in ("name", "dose", "route", "frequency", "last_rate", "include", "hidden"):
            assert updated[field] == original[field]
    assert rows == before


@pytest.mark.parametrize("target", ["system:Respiratory", TARGET, "group:beta_agonist"])
def test_broad_saline_airway_category_does_not_capture_other_orders(target):
    settings = set_category_rule(new_vault()["settings"], "sodium chloride", target)
    enteral = order("sodium chloride enteral solution 17 mEq", "17 mEq", "Per NJ Tube")
    assert matching_target(enteral, settings) == ""
    applied = apply_category_rules([enteral, order()], settings)
    assert effective_section(applied[0]) == "Other Medications"
    assert placement(applied[1])["id"] == TARGET
    settings = set_category_rule(settings, enteral["name"], "gi:prophylaxis", "exact", enteral["route"])
    assert placement(apply_category_rules([enteral], settings)[0])["id"] == "gi:prophylaxis"


def test_specific_non_target_respiratory_mapping_is_preserved():
    row = order("sodium chloride 7 % nebulizer solution 4 mL", "4 mL")
    settings = set_category_rule(new_vault()["settings"], "sodium chloride", TARGET)
    settings = set_category_rule(settings, row["name"], TARGET, "exact", row["route"])
    assert matching_target(row, settings) == TARGET
    assert placement(apply_category_rules([row], settings)[0])["id"] == TARGET


@pytest.mark.parametrize("category_rule", [False, True])
def test_settings_aware_repair_of_saved_generic_resp_destination(category_rule):
    settings = new_vault()["settings"]
    row = order("sodium chloride enteral solution 17 mEq", "17 mEq", "Per NJ Tube")
    row["section"] = "Respiratory"
    if category_rule:
        settings = set_category_rule(settings, "sodium chloride", TARGET)
        row["category_path"] = target_snapshot(TARGET, default_categories())
    else:
        settings["medication_mappings"] = upsert_rule([], "sodium chloride", "Respiratory")
    before = deepcopy(row)
    repaired = apply_category_rules([row], settings)[0]
    assert effective_section(repaired) == "Other Medications"
    assert row == before
    settings["medication_mappings"] = upsert_rule(settings["medication_mappings"], "sodium chloride enteral", "FEN / GI")
    assert effective_section(apply_category_rules([row], settings)[0]) == "FEN / GI"


def test_no_settings_evidence_does_not_guess_saved_non_target_placement():
    row = order("sodium chloride enteral solution 17 mEq", "17 mEq", "Per NJ Tube")
    row["section"] = "Respiratory"
    assert effective_section(row) == "Respiratory"
    assert effective_section(apply_category_rules([row], new_vault()["settings"])[0]) == "Respiratory"


@pytest.mark.parametrize("change", [dict(hidden=True), dict(include=False), dict(section="Ignore")])
def test_hidden_excluded_and_ignored_nebulizers_stay_absent(change):
    row = order()
    row.update(change)
    settings = set_category_rule(new_vault()["settings"], "sodium chloride", "gi:prophylaxis")
    sheet = dict(new_sheet("P4102"), medications=apply_category_rules([row], settings))
    assert row["name"] not in handoff_text(sheet)


def test_old_ignore_snapshot_stays_ignored_during_broad_rule_repair():
    row = order("sodium chloride enteral solution 17 mEq", "17 mEq", "Per NJ Tube")
    row.update(section="Respiratory", category_path=target_snapshot("system:Ignore", default_categories()))
    settings = set_category_rule(new_vault()["settings"], "sodium chloride", TARGET)
    assert effective_section(apply_category_rules([row], settings)[0]) == "Ignore"


def test_exact_category_choice_restores_previously_ignored_nebulizer():
    row = order()
    row.update(section="Ignore", category_path=target_snapshot("system:Ignore", default_categories()))
    settings = set_category_rule(new_vault()["settings"], row["name"], TARGET,
                                 "exact", row["route"], row["frequency"])
    restored = apply_category_rules([row], settings)[0]
    assert effective_section(restored) == "Respiratory"
    assert placement(restored)["id"] == TARGET
    assert row["name"] in handoff_text(dict(new_sheet("P4102"), medications=[restored]))


def test_old_catalog_preserves_custom_airway_clearance_and_shares_heading():
    settings = new_vault()["settings"]
    settings["medication_categories"] = [c for c in default_categories() if c["id"] != TARGET]
    custom = dict(id="custom:airway_existing", name=LABEL, section="Respiratory", parent="", order=100)
    settings["medication_categories"].append(custom)
    original = deepcopy(settings)
    validate_settings(settings)
    expanded = catalog(settings)
    assert next(c for c in expanded if c["id"] == custom["id"]) == custom
    assert next(c for c in expanded if c["id"] == TARGET)["name"] == LABEL + " (default)"
    assert settings == original
    settings = set_category_rule(settings, "dornase alfa", custom["id"])
    rows = apply_category_rules([order(), order("dornase alfa nebulizer solution", "2 mg")], settings)
    blocks = medication_blocks("Respiratory", "", rows)
    assert [value for kind, value in blocks if kind == "heading"] == [LABEL]
    assert len([value for kind, value in blocks if isinstance(value, dict)]) == 2


def test_renamed_builtin_does_not_absorb_fixed_airway_heading():
    settings = save_category(new_vault()["settings"], "Custom respiratory group", "Respiratory", ident=TARGET)
    settings = set_category_rule(settings, "dornase alfa", TARGET)
    rows = apply_category_rules([order(), order("dornase alfa nebulizer solution", "2 mg")], settings)
    headings = [value for kind, value in medication_blocks("Respiratory", "", rows) if kind == "heading"]
    assert set(headings) == {LABEL, "Custom respiratory group"}


def test_full_legacy_catalog_keeps_250_slots_plus_reserved_additions():
    value = new_vault()
    old = [c for c in default_categories() if c["id"] not in BACKFILLED_BUILTIN_IDS]
    old.extend(dict(id=f"custom:legacy_{i}", name=f"Legacy {i}", section="Neurologic", parent="", order=100)
               for i in range(250 - len(old)))
    value["settings"]["medication_categories"] = old
    before = deepcopy(value)
    validate_vault(value)
    assert len(catalog(value["settings"])) == 250 + len(BACKFILLED_BUILTIN_IDS)
    assert value == before


def test_pdf_includes_both_nebulizer_volumes_once_under_requested_heading():
    rows = [order(), order("sodium chloride 3 % nebulizer solution 4 mL", "4 mL", frequency="q8h")]
    sheet = dict(new_sheet("P4102"), medications=rows)
    before = deepcopy(sheet)
    text = " ".join("\n".join(page.extract_text() for page in PdfReader(BytesIO(handoff_pdf(sheet))).pages).split())
    assert LABEL in text
    assert text.count("sodium chloride 3 % nebulizer solution 3 mL") == 1
    assert text.count("sodium chloride 3 % nebulizer solution 4 mL") == 1
    assert sheet == before
