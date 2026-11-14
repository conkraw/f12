"""Synthetic override-pull classification, restoration and output checks."""
from copy import deepcopy

import fitz
import pytest

from categories import apply_category_rules, placement, set_category_rule, target_snapshot, default_categories
from category_ui import local_target, targets
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_html, handoffs_pdf
from fen_gi import effective_section
from importing import import_sections
from medications import (destination_for, explicit_ignore_mapping, ignored, is_override_pull, parse_medications,
                         remap, rule_for_inline_mapping, set_visibility_rule,
                         upsert_rule, validate_medication, visible)
from models import fields_with_medications, new_sheet, new_vault, save_sheet_in, validate_sheet
from security import generate_key, open_vault, seal_vault

NAME = "midazolam 1 mg/mL injection - ADS Override Pull"


def imported(name=NAME, settings=None):
    settings = settings if settings is not None else new_vault()["settings"]
    source = "bbbbbbbb\nMedications:\n•\t" + name + "\nbbbbbbbb"
    result = import_sections(new_sheet("P4102"), source, settings)
    assert not result.errors
    return result.sheet


def resolved(sheet, settings):
    result = deepcopy(sheet)
    result["medications"] = apply_category_rules(
        remap(result["medications"], settings["medication_mappings"], settings["medication_visibility"]), settings)
    validate_sheet(result)
    return result


@pytest.mark.parametrize("label", ["ADS Override Pull", "override pull", "OVERRIDE PULL", "Override-Pull", "Override\u00a0Pull", "Override   Pull"])
def test_override_annotation_defaults_to_ignore(label):
    sheet = imported("fentanyl injection - " + label)
    row = sheet["medications"][0]
    assert is_override_pull(row["name"])
    assert row["section"] == "Ignore" and ignored(row) and not visible(row)
    assert placement(row)["section"] == effective_section(row) == "Ignore"
    assert local_target(row, new_vault()["settings"]) == "system:Ignore"
    assert "system:Ignore" in targets(new_vault()["settings"])
    assert row["include"] and not row["hidden"]
    assert all(row[k] == "" for k in ("dose", "route", "frequency"))
    assert "Override" not in "\n".join(fields_with_medications(sheet).values())


@pytest.mark.parametrize("name", ["override medication", "pull injection", "override pulling injection", "normal pullulan tablet"])
def test_unrelated_words_are_not_override_pull(name):
    assert not is_override_pull(name)


@pytest.mark.parametrize("name,target", [
    ("bupivacaine injection - ADS Override Pull", "group:epidural"),
    ("dexamethasone injection - ADS Override Pull", "group:airway_cerebral_steroid"),
    ("ondansetron injection - ADS Override Pull", "gi:antiemetic"),
    ("albuterol inhaler - ADS Override Pull", "group:beta_agonist"),
])
def test_broad_system_category_and_automatic_grouping_do_not_revive(name, target):
    settings = new_vault()["settings"]
    drug = name.split()[0]
    settings["medication_mappings"] = upsert_rule([], drug, "Neurologic")
    settings = set_category_rule(settings, drug, target)
    settings["medication_visibility"] = set_visibility_rule([], drug, False, "prefix")
    sheet = imported(name, settings)
    row = sheet["medications"][0]
    assert row["section"] == effective_section(row) == "Ignore"
    assert not visible(row)
    assert name not in handoff_text(sheet)


def test_ordinary_order_of_same_drug_stays_visible():
    source = ("bbbbbbbb\nMedications:\n•\t" + NAME +
              "\n•\tmidazolam injection 1 mg\t1 mg\tIntravenous\tq1h PRN\nbbbbbbbb")
    result = import_sections(new_sheet("P4102"), source, new_vault()["settings"])
    assert not result.errors and len(result.sheet["medications"]) == 2
    override, ordinary = result.sheet["medications"]
    assert not visible(override) and visible(ordinary)
    text = handoff_text(result.sheet)
    assert "Override Pull" not in text and "midazolam injection 1 mg" in text


def test_override_rows_with_complete_columns_are_ignored_without_source_changes():
    name = "Synthetic medication Override Pull annotation"
    row = parse_medications("Medications:\n•\t" + name + "\t2 mg\tIntravenous\tOnce").rows[0]
    assert row["name"] == name and row["dose"] == "2 mg"
    assert row["route"] == "Intravenous" and row["frequency"] == "Once"
    assert ignored(row)


def test_exact_category_reassignment_restores_and_persists():
    sheet = imported()
    before = deepcopy(sheet)
    settings = set_category_rule(new_vault()["settings"], NAME, "system:Neurologic", "exact")
    restored = resolved(sheet, settings)
    row = restored["medications"][0]
    assert row["override_pull_restored"] and visible(row)
    assert effective_section(row) == "Neurologic"
    assert NAME in fields_with_medications(restored)["Neurologic"]
    assert sheet == before
    vault = new_vault()
    vault["settings"] = settings
    vault = save_sheet_in(vault, restored)
    key = generate_key()
    loaded = open_vault(seal_vault(vault, key), key)
    saved = loaded["rooms"]["P4102"]
    assert visible(saved["medications"][0])
    assert NAME in handoff_text(saved)
    assert visible(imported(NAME, settings)["medications"][0])


def test_exact_restore_visibility_is_remembered_and_removal_reverts_to_ignore():
    sheet = imported()
    settings = new_vault()["settings"]
    settings["medication_visibility"] = set_visibility_rule([], NAME, False)
    restored = resolved(sheet, settings)
    assert visible(restored["medications"][0]) and NAME in handoff_text(restored)
    assert visible(imported(NAME, settings)["medications"][0])
    reverted = resolved(restored, new_vault()["settings"])
    assert ignored(reverted["medications"][0])


def test_exact_system_rule_restores_only_override_formulation():
    rules = upsert_rule([], NAME, "Cardiovascular", "exact")
    settings = new_vault()["settings"]
    settings["medication_mappings"] = rules
    row = imported(NAME, settings)["medications"][0]
    assert visible(row) and effective_section(row) == "Cardiovascular"
    assert destination_for(NAME, rules) == "Cardiovascular"
    assert destination_for("midazolam 2 mg/mL injection - ADS Override Pull", rules) == "Ignore"
    assert rule_for_inline_mapping(NAME, rules)[1] == "exact"


def test_ignore_category_is_explicit_and_reversible():
    sheet = imported()
    settings = set_category_rule(new_vault()["settings"], NAME, "system:Neurologic", "exact")
    sheet = resolved(sheet, settings)
    settings = set_category_rule(settings, NAME, "system:Ignore", "exact")
    sheet = resolved(sheet, settings)
    assert ignored(sheet["medications"][0])
    settings = set_category_rule(settings, NAME, "system:Other Medications", "exact")
    sheet = resolved(sheet, settings)
    assert visible(sheet["medications"][0])
    assert NAME in fields_with_medications(sheet)["Other Medications"]


@pytest.mark.parametrize("flag,value", [("hidden", True), ("include", False)])
def test_reassignment_respects_separate_hide_and_include_choices(flag, value):
    sheet = imported()
    sheet["medications"][0][flag] = value
    settings = set_category_rule(new_vault()["settings"], NAME, "system:Neurologic", "exact")
    rows = apply_category_rules(sheet["medications"], settings)
    assert rows[0][flag] == value and not visible(rows[0])


def test_saved_legacy_override_snapshot_is_ignored_without_reimport_or_mutation():
    sheet = imported("bupivacaine injection - ADS Override Pull")
    row = sheet["medications"][0]
    row.pop("override_pull_restored")
    row["section"] = "Neurologic"
    row["category_path"] = target_snapshot("group:epidural", default_categories())
    before = deepcopy(sheet)
    assert ignored(row) and effective_section(row) == placement(row)["section"] == "Ignore"
    assert "bupivacaine" not in handoff_text(sheet)
    assert sheet == before


def test_all_output_forms_exclude_ignored_override_entries():
    sheet = imported()
    for text in (handoff_text(sheet), handoff_html(sheet), handoffs_html([sheet])):
        assert "Override Pull" not in text and "midazolam" not in text
    for data in (handoff_pdf(sheet), handoffs_pdf([sheet])):
        with fitz.open(stream=data, filetype="pdf") as pdf:
            text = "\n".join(page.get_text() for page in pdf)
        assert "Override Pull" not in text and "midazolam" not in text


def test_restoration_flag_requires_boolean():
    row = imported()["medications"][0]
    row["override_pull_restored"] = "true"
    with pytest.raises(ValueError):
        validate_medication(row)


def test_explicit_ignore_mapping_distinguishes_default_and_broad_legacy_rules():
    assert not explicit_ignore_mapping(NAME, [])
    rules = upsert_rule([], "midazolam", "Ignore")
    assert explicit_ignore_mapping(NAME, rules)
    assert explicit_ignore_mapping("midazolam injection 1 mg", rules)
    assert not explicit_ignore_mapping("fentanyl injection", rules)
    rules = upsert_rule(rules, NAME, "Neurologic", "exact")
    assert not explicit_ignore_mapping(NAME, rules)
    assert explicit_ignore_mapping("midazolam injection 1 mg", rules)
    rules = upsert_rule(rules, NAME, "Ignore", "exact")
    assert explicit_ignore_mapping(NAME, rules)


def test_explicit_ignore_mapping_uses_same_specificity_as_destination_rules():
    rules = upsert_rule([], "midazolam", "Neurologic")
    rules = upsert_rule(rules, "midazolam 1 mg/mL", "Ignore")
    assert explicit_ignore_mapping(NAME, rules)
    assert not explicit_ignore_mapping("midazolam 2 mg/mL injection", rules)
    assert explicit_ignore_mapping("[Held by provider] " + NAME, rules)
