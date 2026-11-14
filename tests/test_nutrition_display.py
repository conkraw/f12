"""Synthetic nutrition display and source-reconciliation regressions."""
from copy import deepcopy
from decimal import Decimal
import re
import uuid

import fitz
import pytest

from feeds import parse_feeds
from fen_gi import fen_gi_body, automatic_group, effective_section
from models import new_sheet, fields_with_medications, validate_sheet
from nutrition_display import (dosing_weight_for_feeds, has_detailed_nutrition,
                               nutrition_text, parenteral_kind)
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf


def enteral(**changes):
    row = dict(id=uuid.uuid4().hex, source="Synthetic continuous tube order",
               method="GT", route="Gastrostomy tube", formula="Synthetic Formula A",
               feeding_type="Continuous Feeds", rate="30 mL/hr", hours="20",
               daily_volume="600", caloric_density="", additives="", comments="",
               status="active", include=True)
    row.update(changes)
    return row


def oral(text="Regular", **changes):
    row = dict(id=uuid.uuid4().hex, source="Synthetic oral order", text=text, include=True)
    row.update(changes)
    return row


def pn(**changes):
    row = dict(id=uuid.uuid4().hex, source="Synthetic PN order",
               name="Pediatric 2-in-1 PN (Continuous)", rate="17 mL/hr",
               status="active", include=True)
    row.update(changes)
    return row


def diet(rows=(), enteral_rows=(), pn_rows=()):
    return dict(rows=list(rows), enteral=list(enteral_rows), parenteral=list(pn_rows))


def medication(name="Pediatric 2-in-1 PN (Continuous)", **changes):
    row = dict(id=uuid.uuid4().hex, name=name, dose="17 mL/hr", route="Intravenous",
               frequency="Continuous", last_rate="17 mL/hr", rate_time="01/02/2026 1000",
               custom_text="", section="Other Medications", include=True, hidden=False,
               warnings=[])
    row.update(changes)
    return row


def recorded(method="NJ", formula="Synthetic Formula A", rate="30 mL", **changes):
    result = parse_feeds("Gastric Tube " + method + "-Tube Feeding: " + formula + "\n"
                         "Gastric Tube " + method + "-Continuous Tube Feeding Ordered Rate mL/hr (not calculated): " + rate)
    assert not result.error
    result.data["rows"][0].update(changes)
    return result.data


@pytest.mark.parametrize("hours,daily,normalized", [("20", "600", "120"), ("24", "720", "144")])
def test_oral_and_tube_feeds_coexist_with_explicit_daily_schedule(hours, daily, normalized):
    data = diet([oral()], [enteral(hours=hours, daily_volume=daily)])
    text = nutrition_text(data, dosing_weight="5 kg")
    assert "Oral: Regular" in text
    assert "Tube feeds (ordered, GT): Synthetic Formula A @ 30 mL/hr x " + hours + " hr/day = " + daily + " mL/day (" + normalized + " mL/kg/day)" in text
    assert text.count("Using dosing weight: 5 kg") == 1


def test_npo_medication_exception_does_not_create_tube_feed():
    text = nutrition_text(diet([oral("NPO except meds (NJ)")]))
    assert text == "Oral: NPO except meds (NJ)"
    assert "Tube feeds" not in text


def test_measured_weight_is_not_used_as_dosing_weight_fallback():
    sheet = new_sheet("P4102")
    sheet["nutrition"] = dict(weight="5 kg", z_score="", include=True)
    text = nutrition_text(diet(enteral_rows=[enteral()]), sheet=sheet)
    assert "600 mL/day" in text and "mL/kg/day" not in text
    assert "Using dosing weight" not in text


@pytest.mark.parametrize("value", ["", "0 kg", "-2 kg", "8 lbs", "unknown", "5", "5 kg (estimated)"])
def test_missing_or_invalid_dosing_weight_omits_only_normalization(value):
    text = nutrition_text(diet(enteral_rows=[enteral()]), dosing_weight=value)
    assert "600 mL/day" in text and "mL/kg/day" not in text


def test_grams_and_decimal_rounding_are_explicit():
    kg, basis = dosing_weight_for_feeds("3200 g")
    assert kg == Decimal("3.2") and basis == "3200 g"
    text = nutrition_text(diet(enteral_rows=[enteral(rate="12.5 mL/hr", hours="18", daily_volume="225")]), dosing_weight="3200 g")
    assert "225 mL/day (70.3 mL/kg/day)" in text
    assert "Using dosing weight: 3200 g" in text


def test_failed_weight_import_blocks_stale_dosing_weight_calculation():
    sheet = new_sheet("P4102")
    sheet["dosing_weight"] = "5 kg"
    sheet["import_warnings"]["i"] = []
    text = nutrition_text(diet(enteral_rows=[enteral()]), sheet=sheet)
    assert "600 mL/day" in text and "mL/kg/day" not in text


@pytest.mark.parametrize("changes", [{"hours": "", "daily_volume": ""}, {"rate": "", "daily_volume": ""}, {"feeding_type": "", "daily_volume": ""}, {"feeding_type": "Bolus Feeds", "daily_volume": ""}])
def test_missing_schedule_or_rate_is_not_invented(changes):
    text = nutrition_text(diet(enteral_rows=[enteral(**changes)]), dosing_weight="5 kg")
    assert "mL/kg/day" not in text and " = " not in text
    assert "24 hr/day" not in text


@pytest.mark.parametrize("status,label", [("held", "[Held]"), ("future", "[Future order]")])
def test_held_and_future_orders_are_labelled_without_calculation(status, label):
    text = nutrition_text(diet(enteral_rows=[enteral(status=status)]), dosing_weight="5 kg")
    assert label in text and "30 mL/hr" in text
    assert "mL/kg/day" not in text and " = " not in text


def test_mismatched_listed_total_is_visible_and_blocks_normalization():
    text = nutrition_text(diet(enteral_rows=[enteral(daily_volume="720")]), dosing_weight="5 kg")
    assert "30 mL/hr x 20 hr/day = 600 mL/day" in text
    assert "Listed total: 720 mL/day. Review rate/hours." in text
    assert "mL/kg/day" not in text


def test_missing_rate_does_not_back_calculate_from_listed_total():
    text = nutrition_text(diet(enteral_rows=[enteral(rate="")]), dosing_weight="5 kg")
    assert "UNK rate" in text and "Listed total: 600 mL/day" in text
    assert "30 mL/hr" not in text and "mL/kg/day" not in text


def test_formula_fortifier_and_full_instructions_survive_rich_escape():
    data = diet(enteral_rows=[enteral(formula="Synthetic Milk <blend>", caloric_density="24 kcal/oz",
                                    additives="Fortifier powder", comments="Start at 10 mL/hr & advance per order.")])
    before = deepcopy(data)
    plain = nutrition_text(data, dosing_weight="5 kg")
    rich = nutrition_text(data, dosing_weight="5 kg", rich=True)
    assert "Synthetic Milk <blend> (24 kcal/oz)" in plain
    assert "Additives: Fortifier powder" in plain
    assert "Instructions: Start at 10 mL/hr & advance per order." in plain
    assert "&lt;blend&gt;" in rich and "&amp; advance" in rich and "<blend>" not in rich
    assert data == before


def test_diet_only_pn_is_shown_without_tube_or_oral_inference():
    text = nutrition_text(diet(pn_rows=[pn()]))
    assert text == "TPN (diet order): Pediatric 2-in-1 PN (Continuous) @ 17 mL/hr"
    assert "Tube feeds" not in text and "Oral:" not in text


def test_pn_listed_in_diet_and_medications_prints_once_with_medication_rate():
    data = diet([oral("NPO")], pn_rows=[pn(rate="11 mL/hr")])
    meds = [medication()]
    text = fen_gi_body("", meds, None, diet=data)
    assert text.count("Pediatric 2-in-1 PN") == 1
    assert "17 mL/hr" in text and "11 mL/hr" not in text
    assert "Oral: NPO" in text


@pytest.mark.parametrize("changes", [{"hidden": True}, {"include": False}, {"section": "Ignore"}])
def test_hidden_or_ignored_pn_is_not_restored_by_diet_fallback(changes):
    meds = [medication(**changes)]
    text = fen_gi_body("", meds, None, diet=diet(pn_rows=[pn()]))
    assert "Pediatric 2-in-1 PN" not in text and "17 mL/hr" not in text


def test_lipid_medication_does_not_suppress_distinct_diet_pn():
    meds = [medication("fat emulsion (SMOFlipid) 20 % infusion", dose="2 mL/hr", last_rate="2 mL/hr")]
    text = fen_gi_body("", meds, None, diet=diet(pn_rows=[pn()]))
    assert text.count("Pediatric 2-in-1 PN") == 1 and text.count("fat emulsion") == 1


@pytest.mark.parametrize("name", ["TPN", "PPN (Continuous)", "Adult 3-in-1 PN", "Parenteral nutrition infusion"])
def test_explicit_pn_names_group_in_fen_gi(name):
    row = medication(name)
    assert parenteral_kind(name) == "pn" and automatic_group(row) == "tpn"
    assert effective_section(row) == "FEN / GI"


@pytest.mark.parametrize("name", ["TPN", "Parenteral nutrition infusion"])
def test_uniquely_matching_generic_pn_suppresses_the_diet_duplicate(name):
    assert "diet order" not in nutrition_text(diet(pn_rows=[pn()]), medications=[medication(name)])


@pytest.mark.parametrize("diet_name,med_name", [
    ("Pediatric 3-in-1 PN (Cyclic)", "Pediatric 2-in-1 PN (Continuous)"),
    ("Pediatric 2-in-1 PN (Cyclic)", "Pediatric 2-in-1 PN (Continuous)"),
    ("Adult 2-in-1 PN (Continuous)", "Pediatric 2-in-1 PN (Continuous)"),
    ("Intralipid 20 % infusion", "SMOFlipid 20 % infusion"),
    ("Pediatric 2-in-1 PN (Continuous)", "PPN (Continuous)"),
])
def test_distinct_pn_products_and_schedules_are_not_suppressed(diet_name, med_name):
    data = diet(pn_rows=[pn(name=diet_name)])
    assert diet_name in nutrition_text(data, medications=[medication(med_name)])


def test_generic_pn_does_not_choose_between_multiple_medication_products():
    data = diet(pn_rows=[pn(name="TPN")])
    meds = [medication(), medication("Pediatric 3-in-1 PN (Cyclic)")]
    assert "TPN (diet order): TPN" in nutrition_text(data, medications=meds)


def test_generic_medication_does_not_hide_two_distinct_dietary_pn_products():
    data = diet(pn_rows=[pn(), pn(name="Pediatric 3-in-1 PN (Cyclic)")])
    text = nutrition_text(data, medications=[medication("TPN")])
    assert "Pediatric 2-in-1 PN" in text and "Pediatric 3-in-1 PN" in text


def test_same_lipid_product_with_generic_wrapper_is_deduplicated():
    data = diet(pn_rows=[pn(name="SMOFlipid 20 % infusion")])
    assert not nutrition_text(data, medications=[medication("fat emulsion (SMOFlipid) 20 % infusion")])


def test_hidden_matching_pn_does_not_hide_a_distinct_diet_product():
    data = diet(pn_rows=[pn(), pn(name="Pediatric 3-in-1 PN (Cyclic)")])
    text = nutrition_text(data, medications=[medication(hidden=True)])
    assert "Pediatric 2-in-1 PN" not in text and "Pediatric 3-in-1 PN" in text


def test_specific_manual_medication_destination_is_preserved():
    sheet = new_sheet("P4102")
    sheet["diet"] = diet(pn_rows=[pn()])
    sheet["medications"] = [medication(gi_mode="other", section="Cardiovascular")]
    fields = fields_with_medications(sheet)
    assert "Pediatric 2-in-1 PN" in fields["Cardiovascular"]
    assert "Pediatric 2-in-1 PN" not in fields["FEN / GI"]


def test_unique_matching_record_deduplicates_without_display_time_route_inference():
    data = diet(enteral_rows=[enteral(method="Post-pyloric", route="Nasoenteric (post-pyloric) tube")])
    text = nutrition_text(data, recorded(), dosing_weight="5 kg")
    assert "ordered, Post-pyloric" in text and "recorded," not in text
    assert text.count("Synthetic Formula A") == 1


def test_empty_current_feed_id_list_suppresses_older_recorded_feeds():
    data = diet([oral("NPO")])
    data["recorded_feed_ids"] = []
    assert nutrition_text(data, recorded()) == "Oral: NPO"


def test_only_current_feed_ids_can_appear_beside_orders():
    fresh, stale = recorded("NJ"), recorded("GT", formula="Old formula")
    data = diet([oral("Regular")])
    data["recorded_feed_ids"] = [fresh["rows"][0]["id"]]
    feeds = {"rows": fresh["rows"] + stale["rows"]}
    text = nutrition_text(data, feeds)
    assert "recorded, NJ" in text and "Old formula" not in text


def test_hidden_record_cannot_refine_postpyloric_to_nj():
    data = diet(enteral_rows=[enteral(method="Post-pyloric", route="Nasoenteric (post-pyloric) tube")])
    text = nutrition_text(data, recorded(include=False), dosing_weight="5 kg")
    assert "ordered, Post-pyloric" in text and "NJ" not in text


def test_ambiguous_matching_routes_do_not_refine_or_collapse_devices():
    data = diet(enteral_rows=[enteral(method="Post-pyloric", route="Nasoenteric (post-pyloric) tube")])
    feeds = recorded()
    feeds["rows"] += recorded("ND")["rows"]
    text = nutrition_text(data, feeds)
    assert "ordered, Post-pyloric" in text
    assert "recorded, NJ" in text and "recorded, ND" in text


def test_unmatched_recorded_route_stays_separate():
    text = nutrition_text(diet(enteral_rows=[enteral()]), recorded())
    assert "ordered, GT" in text and "recorded, NJ" in text


def test_numeric_formula_punctuation_does_not_merge_different_products():
    data = diet(enteral_rows=[enteral(method="NJ", formula="Synthetic Formula 1.0")])
    text = nutrition_text(data, recorded(formula="Synthetic Formula 1:0"))
    assert "ordered, NJ" in text and "recorded, NJ" in text
    assert "Synthetic Formula 1.0" in text and "Synthetic Formula 1:0" in text


def test_missing_order_formula_preserves_the_matching_recorded_formula():
    data = diet(enteral_rows=[enteral(method="NJ", formula="")])
    text = nutrition_text(data, recorded())
    assert "UNK formula" in text and "Recorded formula: Synthetic Formula A" in text


def test_unmatched_formula_only_device_does_not_become_an_additional_feed():
    data = diet(enteral_rows=[enteral(method="NJ")])
    feeds = recorded("GT", rate="")
    before = deepcopy(feeds)
    text = nutrition_text(data, feeds)
    assert "ordered, NJ" in text and "recorded, GT" not in text
    assert feeds == before


def test_legacy_formula_only_device_remains_visible_without_detailed_order():
    feeds = recorded("GT", rate="")
    text = fen_gi_body("", [], None, feeds=feeds)
    assert "Feeding Method: GT" in text and "Synthetic Formula A @ UNK" in text


def test_conflicting_recorded_rate_does_not_replace_ordered_calculation():
    data = diet(enteral_rows=[enteral(method="NJ")])
    text = nutrition_text(data, recorded(rate="12 mL"), dosing_weight="5 kg")
    assert "30 mL/hr x 20 hr/day = 600 mL/day (120 mL/kg/day)" in text
    assert "Recorded rate: 12 mL/hr" in text
    assert "240 mL/day" not in text


def test_recorded_rate_does_not_supply_a_missing_ordered_rate():
    data = diet(enteral_rows=[enteral(method="NJ", rate="", daily_volume="")])
    text = nutrition_text(data, recorded(), dosing_weight="5 kg")
    assert "UNK rate" in text and "Recorded rate: 30 mL/hr" in text
    assert "mL/kg/day" not in text


def test_excluded_diet_row_does_not_reappear_through_matching_record():
    data = diet(enteral_rows=[enteral(method="NJ", include=False)])
    text = nutrition_text(data, recorded(), dosing_weight="5 kg")
    assert not text


def test_legacy_diet_and_feeds_rendering_is_unchanged():
    old = dict(rows=[oral("Peds Regular")])
    assert not has_detailed_nutrition(old)
    assert nutrition_text(old) == ""
    text = fen_gi_body("", [], None, diet=old, feeds=recorded())
    assert text == "Diet: Peds Regular\n-----\nFeeds:\nFeeding Method: NJ\nSynthetic Formula A @ 30 mL/hr"


def test_failed_recorded_feeds_do_not_override_valid_dietary_order():
    data = diet(enteral_rows=[enteral(method="Post-pyloric")])
    text = fen_gi_body("", [], None, diet=data, feeds=recorded(), feeds_failed=True, dosing_weight="5 kg")
    assert "ordered, Post-pyloric" in text and "120 mL/kg/day" in text
    assert "Recorded feeds: Not updated. Review needed." in text


def test_plain_rich_and_pdf_exports_use_same_ordered_volume_and_preserve_sheet():
    sheet = new_sheet("P4102")
    sheet["dosing_weight"] = "5 kg"
    sheet["diet"] = diet([oral()], [enteral()], [pn()])
    sheet["medications"] = [medication()]
    before = deepcopy(sheet)
    validate_sheet(sheet)
    expected = "600 mL/day (120 mL/kg/day)"
    for text in (handoff_text(sheet), handoff_html(sheet)):
        assert expected in text and text.count("Pediatric 2-in-1 PN") == 1
    with fitz.open(stream=handoff_pdf(sheet), filetype="pdf") as doc:
        text = re.sub(r"\s+", " ", " ".join(page.get_text() for page in doc))
        assert expected in text and text.count("Pediatric 2-in-1 PN") == 1
    second = deepcopy(sheet)
    second["id"] = uuid.uuid4().hex
    second["room"] = "P4104"
    second["dosing_weight"] = "10 kg"
    with fitz.open(stream=handoffs_pdf([sheet, second]), filetype="pdf") as doc:
        assert len(doc) == 2
        first = re.sub(r"\s+", " ", doc[0].get_text())
        second = re.sub(r"\s+", " ", doc[1].get_text())
        assert "120 mL/kg/day" in first and "60 mL/kg/day" in second
        assert "120 mL/kg/day" not in second
    assert sheet == before
