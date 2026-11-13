"""Montelukast is a display group only. All tests use synthetic source values."""
from copy import deepcopy
import pytest
from categories import apply_category_rules, catalog, default_categories, medication_blocks, placement
from exports import handoff_html, handoff_text
from fen_gi import effective_section
from medication_groups import automatic_group, group_for
from medications import DESTINATIONS, parse_medications
from models import new_vault, new_sheet, validate_vault
from security import generate_key, open_vault, seal_vault

TARGET = "group:leukotriene_receptor_antagonist"
LABEL = "Leukotriene receptor antagonist"


def order(name):
    parsed = parse_medications(name + "\tSYNTHETIC_DOSE\tOral\tNightly\t\t\t")
    assert not parsed.error and len(parsed.rows) == 1
    return parsed.rows[0]


@pytest.mark.parametrize("name", ["montelukast", "montelukast sodium", "montelukast (SINGULAIR) chewable tablet",
                                   "Singulair oral granules", "MONTELUKAST 5 mg", "Or: [START ON 11/14/2026] montelukast"])
def test_default_group_and_single_resp_placement_preserve_source(name):
    row = order(name)
    before = deepcopy(row)
    assert automatic_group(row) == "leukotriene_receptor_antagonist"
    assert effective_section(row) == "Respiratory"
    assert placement(row)["id"] == TARGET
    assert placement(row)["name"] == LABEL
    emitted = [v["id"] for section in DESTINATIONS for _, v in medication_blocks(section, "", [row]) if isinstance(v, dict)]
    assert emitted == [row["id"]]
    assert row == before


@pytest.mark.parametrize("name", ["montelukastX", "montelukast-like compound", "synthetic for montelukast", "zafirlukast", "zileuton"])
def test_nonmatches_are_not_accidentally_added(name):
    assert group_for(order(name)) != "leukotriene_receptor_antagonist"


def test_saved_catalog_backfills_new_group_without_rewriting_patient():
    value = new_vault()
    value["settings"]["medication_categories"] = [c for c in default_categories() if c["id"] != TARGET]
    sheet = new_sheet("P4102")
    sheet["medications"] = [order("montelukast SYNTHETIC_MONTE")]
    value["rooms"]["P4102"] = sheet
    before = deepcopy(value)
    validate_vault(value)
    assert TARGET in {c["id"] for c in catalog(value["settings"])}
    key = generate_key()
    assert open_vault(seal_vault(value, key), key) == before
    for text in (handoff_text(sheet), handoff_html(sheet)):
        assert LABEL in text
        assert text.count("SYNTHETIC_MONTE") == 1
        assert "SYNTHETIC_DOSE" in text
    assert value == before


def test_hidden_orders_stay_hidden_and_admin_category_is_available():
    value = new_vault()
    assert TARGET in {c["id"] for c in catalog(value["settings"])}
    row = order("montelukast SYNTHETIC_MONTE")
    row["hidden"] = True
    sheet = new_sheet("P4102")
    sheet["medications"] = apply_category_rules([row], value["settings"])
    assert "SYNTHETIC_MONTE" not in handoff_text(sheet)


def test_explicit_existing_choice_remains_authoritative_but_new_target_can_be_selected():
    from categories import set_category_rule
    row = order("montelukast SYNTHETIC_MONTE")
    row["group_mode"] = "allergy_immunology"
    assert group_for(row) == "allergy_immunology"
    settings = set_category_rule(new_vault()["settings"], "montelukast", TARGET)
    updated = apply_category_rules([row], settings)[0]
    assert placement(updated)["id"] == TARGET
    assert updated["dose"] == row["dose"]
