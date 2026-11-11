"""Synthetic alternative-order placement without changing saved order data."""
from copy import deepcopy

import pytest

from categories import (default_categories, medication_blocks, save_category,
                        target_snapshot)
from exports import handoff_text
from infusions import infusion_entry
from medications import DESTINATIONS, format_medication, parse_medications
from models import new_sheet


def order(name, section="Neurologic", category=None, group="other"):
    parsed = parse_medications(name + "\t1 mg\tIntravenous\tq4h PRN\t\t\t")
    assert not parsed.error, parsed.error
    row = parsed.rows[0]
    row.update(section=section, group_mode=group)
    if category is not None:
        row["category_path"] = category
    return row


def emitted(section, rows):
    return [value for kind, value in medication_blocks(section, "", rows)
            if kind in ("medication", "infusion")]


def test_same_bucket_or_chain_stays_in_source_order_under_neuro_sort():
    rows = [order("Zulu source"), order("Or: Alpha alternative"),
            order("Or: Beta alternative"), order("Middle independent")]
    before = deepcopy(rows)
    rendered = emitted("Neurologic", rows)
    assert [row["name"] for row in rendered] == [
        "Middle independent", "Zulu source", "Or: Alpha alternative", "Or: Beta alternative"]
    assert all("_display_name" not in row for row in rendered)
    assert len({row["id"] for row in rendered}) == len(rows)
    assert rows == before


def test_same_prn_group_keeps_morphine_before_its_alternative():
    rows = [order("morphine injection", group="auto"),
            order("Or: hydromorphone injection", group="auto")]
    assert [row["name"] for row in emitted("Neurologic", rows)] == [row["name"] for row in rows]


@pytest.mark.parametrize("section", ["Respiratory", "Cardiovascular", "FEN / GI"])
def test_other_sections_keep_source_order_and_attached_or(section):
    rows = [order("Zulu source", section), order("Or: Alpha alternative", section)]
    result = emitted(section, rows)
    assert [row["id"] for row in result] == [row["id"] for row in rows]
    assert all("_display_name" not in row for row in result)


@pytest.mark.parametrize("visibility", [dict(hidden=True), dict(include=False)])
def test_hidden_predecessor_detaches_first_visible_alternative_only(visibility):
    rows = [order("Hidden source"), order("Or: Zulu alternative"),
            order("Or: Alpha next alternative"), order("Middle independent")]
    rows[0].update(visibility)
    before = deepcopy(rows)
    rendered = emitted("Neurologic", rows)
    assert [row["name"] for row in rendered] == [
        "Middle independent", "Or: Zulu alternative", "Or: Alpha next alternative"]
    assert rendered[1]["_display_name"] == "Alternative order: Zulu alternative"
    assert "Hidden source" not in rendered[1]["_display_name"]
    assert "_display_name" not in rendered[2]
    assert rows == before


def test_hidden_middle_order_breaks_an_alternative_chain():
    rows = [order("Zulu source"), order("Or: Hidden alternative"),
            order("Or: Alpha alternative")]
    rows[1]["hidden"] = True
    rendered = emitted("Neurologic", rows)
    last = next(row for row in rendered if row["id"] == rows[2]["id"])
    assert last["name"] == "Or: Alpha alternative"
    assert last["_display_name"] == "Alternative order: Alpha alternative"


def test_separate_systems_keep_assignments_and_detach_alternative():
    rows = [order("Zulu source", "Respiratory"), order("Or: Alpha alternative", "Neurologic")]
    before = deepcopy(rows)
    original, = emitted("Respiratory", rows)
    alternative, = emitted("Neurologic", rows)
    assert original["id"] == rows[0]["id"] and "_display_name" not in original
    assert alternative["id"] == rows[1]["id"]
    assert alternative["_display_name"] == "Alternative order: Alpha alternative"
    all_rendered = [row for section in DESTINATIONS for row in emitted(section, rows)]
    assert sorted(row["id"] for row in all_rendered) == sorted(row["id"] for row in rows)
    assert rows == before


def test_separate_root_categories_detach_without_moving_either_order():
    defaults = default_categories()
    rows = [order("Zulu source", category=target_snapshot("group:fever", defaults)),
            order("Or: Alpha alternative", category=target_snapshot("group:sedative_prn", defaults))]
    before = deepcopy(rows)
    alternative = next(row for row in emitted("Neurologic", rows) if row["id"] == rows[1]["id"])
    assert alternative["_display_name"] == "Alternative order: Alpha alternative"
    assert alternative["category_path"] == rows[1]["category_path"]
    assert rows == before


def test_root_and_subcategory_are_distinct_emitted_buckets():
    settings = save_category({}, "Synthetic parent", "Neurologic", ident="custom:alternative_parent")
    settings = save_category(settings, "Synthetic child", "Neurologic",
                             parent="custom:alternative_parent", ident="custom:alternative_child")
    items = settings["medication_categories"]
    rows = [order("Zulu source", category=target_snapshot("custom:alternative_parent", items)),
            order("Or: Alpha alternative", category=target_snapshot("custom:alternative_child", items))]
    rendered = emitted("Neurologic", rows)
    assert rendered[1]["_display_name"] == "Alternative order: Alpha alternative"
    rows[0]["category_path"] = deepcopy(rows[1]["category_path"])
    same_bucket = emitted("Neurologic", rows)
    assert [row["id"] for row in same_bucket] == [row["id"] for row in rows]
    assert all("_display_name" not in row for row in same_bucket)


def test_distinct_epidural_display_roots_do_not_make_a_false_or_link():
    path = target_snapshot("group:epidural", default_categories())
    path["name"] = "Regional infusions"
    rows = [order("Zulu source", category=path), order("Or: bupivacaine")]
    alternative = next(row for row in emitted("Neurologic", rows) if row["id"] == rows[1]["id"])
    assert alternative["_display_name"] == "Alternative order: bupivacaine"


def test_orphan_alternative_gets_display_copy_without_mutating_source_name():
    rows = [order("Or: [START ON 11/12/2026] Synthetic alternative")]
    before = deepcopy(rows)
    rendered, = emitted("Neurologic", rows)
    assert rendered is not rows[0]
    assert rendered["_display_name"] == "Alternative order: [START ON 11/12/2026] Synthetic alternative"
    assert rows == before and "_display_name" not in rows[0]


def test_independent_same_name_orders_keep_existing_stable_source_order():
    rows = [order("Synthetic product 2"), order("Synthetic product 1")]
    assert [row["id"] for row in emitted("Neurologic", rows)] == [row["id"] for row in rows]


def test_legacy_labs_alternative_keeps_source_context_with_clean_handoff_label():
    rows = [order("Synthetic source"), order("Or: Synthetic lab order", "Labs")]
    before = deepcopy(rows)
    alternative, = emitted("Labs", rows)
    assert alternative["_display_name"] == "Alternative order: Synthetic lab order"
    sheet = new_sheet("P4102")
    sheet["medications"] = rows
    output = handoff_text(sheet)
    assert "Synthetic lab order" in output
    assert "Alternative order: Synthetic lab order" not in output
    assert "Or: Synthetic lab order" not in output
    assert rows == before


def test_detached_infusion_label_does_not_change_rate_selection():
    row = order("Or: norepinephrine", "Cardiovascular")
    row.update(dose="0.03 mcg/kg/min", frequency="Continuous")
    before = deepcopy(row)
    rendered, = emitted("Cardiovascular", [row])
    for output in (format_medication(rendered), infusion_entry(rendered)):
        assert output.startswith("norepinephrine")
        assert "Alternative order: " not in output
        assert "Last Admin rate: UNK" in output
        assert "Dose: 0.03" not in output
    assert row == before and row["name"] == "Or: norepinephrine"
