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
                               nutrition_text, parenteral_kind, recorded_feed_matches)
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


@pytest.mark.parametrize("hours,daily,normalized,kcal,kcal_per_kg", [("20", "600", "120", "480", "96"), ("24", "720", "144", "576", "115.2"), ("", "", "144", "576", "115.2")])
def test_compact_diet_and_one_tube_feed_heading_with_correct_daily_totals(hours, daily, normalized, kcal, kcal_per_kg):
    data = diet([oral()], [enteral(hours=hours, daily_volume=daily, caloric_density="24 kcal/oz")])
    text = nutrition_text(data, dosing_weight="5 kg")
    duration = " (20 hr/day)" if hours == "20" else ""
    assert text == ("Diet: Regular\n-----\nTube feed:\nGT: Synthetic Formula A (24 kcal/oz) @ 30 mL/hr" + duration
                    + " | " + kcal + " kcal/day (" + kcal_per_kg + " kcal/kg/day) | " + normalized + " mL/kg/day")
    assert "24 hr/day" not in text and "Using dosing weight" not in text and "mL/day" not in text


def test_npo_medication_exception_is_diet_without_tube_feeding():
    assert nutrition_text(diet([oral("NPO except meds (NJ)")])) == "Diet: NPO except meds (NJ)"


@pytest.mark.parametrize("density,kcal,kcal_per_kg", [("24 kcal/oz", "480", "96"), ("0.8 kcal/mL", "480", "96"), ("800 kcal/L", "480", "96"), ("1.25 kcal/mL", "750", "150")])
def test_explicit_density_units_supply_daily_kcal(density, kcal, kcal_per_kg):
    text = nutrition_text(diet(enteral_rows=[enteral(caloric_density=density)]), dosing_weight="5 kg")
    assert " | " + kcal + " kcal/day (" + kcal_per_kg + " kcal/kg/day) | 120 mL/kg/day" in text


def test_measured_weight_is_not_used_as_dosing_weight_fallback():
    sheet = new_sheet("P4102")
    sheet["nutrition"] = dict(weight="5 kg", z_score="", include=True)
    text = nutrition_text(diet(enteral_rows=[enteral(caloric_density="24 kcal/oz")]), sheet=sheet)
    assert "480 kcal/day" in text and "mL/kg/day" not in text and "kcal/kg/day" not in text and "mL/day" not in text


@pytest.mark.parametrize("value", ["", "0 kg", "-2 kg", "8 lbs", "unknown", "5", "5 kg (estimated)"])
def test_missing_or_invalid_dosing_weight_omits_only_weight_normalization(value):
    text = nutrition_text(diet(enteral_rows=[enteral(caloric_density="24 kcal/oz")]), dosing_weight=value)
    assert "480 kcal/day" in text and "mL/kg/day" not in text and "kcal/kg/day" not in text


def test_grams_and_fractional_calories_round_to_one_decimal():
    kg, basis = dosing_weight_for_feeds("3200 g")
    assert kg == Decimal("3.2") and basis == "3200 g"
    text = nutrition_text(diet(enteral_rows=[enteral(rate="12.5 mL/hr", hours="18", daily_volume="225", caloric_density="1.23 kcal/mL")]), dosing_weight="3200 g")
    assert "(18 hr/day) | 276.8 kcal/day (86.5 kcal/kg/day) | 70.3 mL/kg/day" in text
    assert "Using dosing weight" not in text


def test_daily_and_weight_normalized_calories_round_independently():
    data = diet(enteral_rows=[enteral(rate="3.251 mL/hr", daily_volume="65.02", caloric_density="0.75 kcal/mL")])
    text = nutrition_text(data, dosing_weight="1.4 kg")
    assert "48.8 kcal/day (34.8 kcal/kg/day) | 46.4 mL/kg/day" in text
    assert "34.9 kcal/kg/day" not in text


def test_failed_weight_import_blocks_stale_dosing_weight_calculation():
    sheet = new_sheet("P4102")
    sheet["dosing_weight"] = "5 kg"
    sheet["import_warnings"]["i"] = []
    text = nutrition_text(diet(enteral_rows=[enteral(caloric_density="24 kcal/oz")]), sheet=sheet)
    assert "480 kcal/day" in text and "mL/kg/day" not in text and "kcal/kg/day" not in text


@pytest.mark.parametrize("changes", [{"rate": "", "daily_volume": ""}, {"feeding_type": "", "daily_volume": ""}, {"feeding_type": "Bolus Feeds", "daily_volume": ""}])
def test_missing_rate_or_noncontinuous_schedule_does_not_receive_totals(changes):
    text = nutrition_text(diet(enteral_rows=[enteral(caloric_density="24 kcal/oz", **changes)]), dosing_weight="5 kg")
    assert "mL/kg/day" not in text and "kcal/day" not in text and "kcal/kg/day" not in text


@pytest.mark.parametrize("section", ["x", "ab"])
def test_conflicting_hours_are_not_replaced_with_24_hour_default(section):
    sheet = new_sheet("P4102")
    sheet["dosing_weight"] = "5 kg"
    sheet["import_warnings"][section] = [dict(code="nutrition_conflict", field="hours")]
    text = nutrition_text(diet(enteral_rows=[enteral(hours="", daily_volume="", caloric_density="24 kcal/oz")]), sheet=sheet)
    assert "mL/kg/day" not in text and "kcal/day" not in text and "kcal/kg/day" not in text
    assert "Review rate/hours" in text


def test_explicit_valid_duration_survives_another_rows_hours_warning():
    sheet = new_sheet("P4102")
    sheet["dosing_weight"] = "5 kg"
    sheet["import_warnings"]["ab"] = [dict(code="nutrition_conflict", field="hours")]
    text = nutrition_text(diet(enteral_rows=[enteral(hours="20", daily_volume="600", caloric_density="24 kcal/oz")]), sheet=sheet)
    assert "480 kcal/day (96 kcal/kg/day) | 120 mL/kg/day" in text


@pytest.mark.parametrize("supplied,answer", [("48 hours", "48 hours"), ("20 hours", "18 hours"), ("unknown", "unknown")])
def test_retained_source_blocks_default_after_duration_warning_is_removed(supplied, answer):
    from diet import parse_diet
    source = ("Infant tube feeding Pediatric Tube Feeding; Synthetic Formula A; Continuous Feeds; "
              "Gastrostomy tube; " + supplied + "; 30; ; No Additives; 24\n"
              "Comments: An instruction remains in the source.\n"
              "Question Answer Comment\nInfusion time (hours):\t" + answer)
    parsed = parse_diet(source, detailed=True)
    assert not parsed.error and parsed.data["enteral"][0]["hours"] == ""
    before = deepcopy(parsed.data)
    text = nutrition_text(parsed.data, dosing_weight="5 kg")
    assert "kcal/day" not in text and "mL/kg/day" not in text and "kcal/kg/day" not in text
    assert "Review rate/hours" in text and parsed.data == before
    parsed.data["enteral"][0]["hours"] = "24"
    assert "576 kcal/day (115.2 kcal/kg/day) | 144 mL/kg/day" in nutrition_text(parsed.data, dosing_weight="5 kg")


def test_retained_source_with_genuinely_absent_duration_uses_24_hour_default():
    from diet import parse_diet
    parsed = parse_diet("Infant tube feeding Pediatric Tube Feeding; Synthetic Formula A; Continuous Feeds; "
                        "Gastrostomy tube; ; 30; ; No Additives; 24", detailed=True)
    assert not parsed.error and parsed.data["enteral"][0]["hours"] == ""
    assert "576 kcal/day (115.2 kcal/kg/day) | 144 mL/kg/day" in nutrition_text(parsed.data, dosing_weight="5 kg")


@pytest.mark.parametrize("status,label", [("held", "[Held]"), ("future", "[Future order]")])
def test_held_and_future_orders_keep_status_without_totals(status, label):
    text = nutrition_text(diet(enteral_rows=[enteral(status=status, caloric_density="24 kcal/oz")]), dosing_weight="5 kg")
    assert label in text and "30 mL/hr" in text
    assert "mL/kg/day" not in text and "kcal/day" not in text and "kcal/kg/day" not in text


def test_conflicting_listed_total_blocks_all_derived_totals_without_printing_equation():
    text = nutrition_text(diet(enteral_rows=[enteral(daily_volume="720", caloric_density="24 kcal/oz")]), dosing_weight="5 kg")
    assert "30 mL/hr (20 hr/day)" in text and "Review rate/hours" in text
    assert "mL/day" not in text and "mL/kg/day" not in text and "kcal/day" not in text


def test_missing_rate_is_not_back_calculated_from_listed_total():
    text = nutrition_text(diet(enteral_rows=[enteral(rate="", caloric_density="24 kcal/oz")]), dosing_weight="5 kg")
    assert "GT: Synthetic Formula A (24 kcal/oz)" in text
    assert "UNK" not in text and "@" not in text and "30 mL/hr" not in text
    assert "mL/kg/day" not in text and "kcal/day" not in text and "kcal/kg/day" not in text


@pytest.mark.parametrize("formula", ["", "  ", "UNK", " unk ", "Unknown", " uNkNoWn "])
def test_unknown_formula_sentinels_are_omitted_without_losing_known_rate(formula):
    data = diet(enteral_rows=[enteral(formula=formula)])
    before = deepcopy(data)
    assert nutrition_text(data, dosing_weight="5 kg") == "Tube feed:\nGT: 30 mL/hr (20 hr/day) | 120 mL/kg/day"
    assert data == before


def test_missing_formula_preserves_explicit_density_and_calculable_totals():
    text = nutrition_text(diet(enteral_rows=[enteral(formula="", caloric_density="24 kcal/oz")]), dosing_weight="5 kg")
    assert text == ("Tube feed:\nGT: 30 mL/hr (24 kcal/oz) (20 hr/day)"
                    " | 480 kcal/day (96 kcal/kg/day) | 120 mL/kg/day")
    assert "@" not in text and "UNK" not in text


def test_formula_only_row_keeps_density_without_missing_rate_placeholder_or_totals():
    text = nutrition_text(diet(enteral_rows=[enteral(rate="", caloric_density="24 kcal/oz")]), dosing_weight="5 kg")
    assert text == "Tube feed:\nGT: Synthetic Formula A (24 kcal/oz) (20 hr/day)"
    assert "@" not in text and "UNK" not in text and "kcal/kg/day" not in text


@pytest.mark.parametrize("formula", ["", " ", "UNK", " unknown "])
def test_no_formula_or_rate_omits_entire_row_and_empty_heading(formula):
    data = diet(enteral_rows=[enteral(formula=formula, rate="", caloric_density="24 kcal/oz")])
    before = deepcopy(data)
    assert nutrition_text(data, dosing_weight="5 kg") == ""
    assert nutrition_text(data, dosing_weight="5 kg", rich=True) == ""
    assert data == before


@pytest.mark.parametrize("method", ["GT", "UNK", "PO"])
def test_empty_feed_rows_do_not_leave_route_or_heading_beside_other_nutrition(method):
    data = diet([oral("Regular")], [enteral(method=method, formula="", rate="")], [pn()])
    text = nutrition_text(data, dosing_weight="5 kg")
    assert text == "Diet: Regular\n-----\nTPN (diet order): Pediatric 2-in-1 PN (Continuous) @ 17 mL/hr"


@pytest.mark.parametrize("formula", ["Synthetic Unknown Formula", "Formula with unknown flavor"])
def test_real_formula_names_containing_unknown_are_preserved(formula):
    text = nutrition_text(diet(enteral_rows=[enteral(formula=formula, rate="", hours="", daily_volume="")]))
    assert text == "Tube feed:\nGT: " + formula


def test_unknown_route_does_not_insert_placeholder_for_known_feed_details():
    text = nutrition_text(diet(enteral_rows=[enteral(method="UNK", formula="")]), dosing_weight="5 kg")
    assert text == "Tube feed:\n30 mL/hr (20 hr/day) | 120 mL/kg/day"


@pytest.mark.parametrize("formula,density", [("Formula 1.5", ""), ("Ketogenic Formula 4:1", ""), ("Formula A", "24"), ("Formula A", "1.2 calories/mL")])
def test_calories_are_not_inferred_from_brand_numbers_or_unqualified_density(formula, density):
    text = nutrition_text(diet(enteral_rows=[enteral(formula=formula, caloric_density=density)]), dosing_weight="5 kg")
    assert "kcal/day" not in text and "kcal/kg/day" not in text and "120 mL/kg/day" in text


def test_instructions_and_additives_stay_saved_but_do_not_print():
    data = diet(enteral_rows=[enteral(formula="Synthetic Milk <blend>", caloric_density="24 kcal/oz",
                                    additives="Fortifier powder", comments="Start at 10 mL/hr & advance per order.")])
    before = deepcopy(data)
    plain = nutrition_text(data, dosing_weight="5 kg")
    rich = nutrition_text(data, dosing_weight="5 kg", rich=True)
    assert "Synthetic Milk <blend> (24 kcal/oz)" in plain
    assert "Fortifier powder" not in plain and "Start at" not in plain
    assert "Instructions:" not in plain and "Additives:" not in plain
    assert "&lt;blend&gt;" in rich and "<blend>" not in rich
    assert data == before


def test_diet_only_pn_is_shown_without_tube_or_oral_inference():
    text = nutrition_text(diet(pn_rows=[pn()]))
    assert text == "TPN (diet order): Pediatric 2-in-1 PN (Continuous) @ 17 mL/hr"
    assert "Tube feed" not in text and "Diet:" not in text


def test_pn_listed_in_diet_and_medications_prints_once_with_medication_rate():
    data = diet([oral("NPO")], pn_rows=[pn(rate="11 mL/hr")])
    meds = [medication()]
    text = fen_gi_body("", meds, None, diet=data)
    assert text.count("Pediatric 2-in-1 PN") == 1
    assert "17 mL/hr" in text and "11 mL/hr" not in text
    assert "Diet: NPO" in text


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


def test_unique_compatible_route_uses_ordered_formula_once_even_when_recorded_formula_differs():
    data = diet(enteral_rows=[enteral(method="Post-pyloric", formula="Synthetic Milk")])
    feeds = recorded(formula="Synthetic Elemental Formula")
    before = deepcopy((data, feeds))
    text = nutrition_text(data, feeds, dosing_weight="5 kg")
    assert text.count("Tube feed:") == 1 and "Post-pyloric: Synthetic Milk" in text
    assert "Synthetic Elemental Formula" not in text and "Recorded formula" not in text
    assert (data, feeds) == before


def test_public_matching_uses_exact_formula_before_compatible_route():
    orders = [enteral(method="Post-pyloric", formula="Formula 1.0"), enteral(method="Post-pyloric", formula="Formula 1:0")]
    feeds = recorded("NJ", formula="Formula 1:0")["rows"] + recorded("ND", formula="Formula 1.0")["rows"]
    assert recorded_feed_matches(orders, feeds) == {0: 1, 1: 0}


def test_empty_current_feed_id_list_suppresses_old_recorded_feeds():
    data = diet([oral("NPO")])
    data["recorded_feed_ids"] = []
    assert nutrition_text(data, recorded()) == "Diet: NPO"


def test_only_current_feed_ids_can_appear_beside_orders():
    fresh, stale = recorded("NJ"), recorded("GT", formula="Old formula")
    data = diet([oral("Regular")])
    data["recorded_feed_ids"] = [fresh["rows"][0]["id"]]
    text = nutrition_text(data, {"rows": fresh["rows"] + stale["rows"]})
    assert "NJ: Synthetic Formula A" in text and "Old formula" not in text


def test_excluded_record_does_not_prevent_one_current_counterpart_from_matching():
    data = diet(enteral_rows=[enteral(method="NJ", formula="Ordered milk")])
    feeds = recorded(formula="Current formula")
    feeds["rows"] += recorded(formula="Old formula", include=False)["rows"]
    text = nutrition_text(data, feeds)
    assert text.count("NJ:") == 1 and "Ordered milk" in text
    assert "Current formula" not in text and "Old formula" not in text


def test_ambiguous_routes_remain_separate_without_guessed_identity():
    data = diet(enteral_rows=[enteral(method="Post-pyloric", formula="Ordered formula")])
    feeds = recorded("NJ", formula="Recorded A")
    feeds["rows"] += recorded("ND", formula="Recorded B")["rows"]
    text = nutrition_text(data, feeds)
    assert "Post-pyloric:" in text and "NJ:" in text and "ND:" in text
    assert text.count("Tube feed:") == 1


def test_genuinely_different_tubes_share_one_heading_but_remain_distinct():
    text = nutrition_text(diet(enteral_rows=[enteral()]), recorded(), dosing_weight="5 kg")
    assert "GT:" in text and "NJ:" in text and text.count("Tube feed:") == 1


def test_authoritative_order_does_not_borrow_a_different_recorded_rate():
    text = nutrition_text(diet(enteral_rows=[enteral(method="NJ", caloric_density="24 kcal/oz")]), recorded(rate="12 mL"), dosing_weight="5 kg")
    assert "30 mL/hr (20 hr/day) | 480 kcal/day (96 kcal/kg/day) | 120 mL/kg/day" in text
    assert "12 mL/hr" not in text and "Recorded rate" not in text


def test_order_missing_formula_and_rate_remains_editable_without_recorded_hybrid():
    data = diet(enteral_rows=[enteral(method="NJ", formula="", rate="", daily_volume="")])
    feeds = recorded(formula="Recorded formula 24 kcal/oz")
    before = deepcopy((data, feeds))
    text = nutrition_text(data, feeds, dosing_weight="5 kg")
    assert text == ""
    assert "Recorded formula" not in text and "30 mL/hr" not in text
    assert "mL/kg/day" not in text and "kcal/day" not in text and "kcal/kg/day" not in text
    assert (data, feeds) == before


def test_unmatched_formula_only_device_does_not_become_an_additional_feed():
    data = diet(enteral_rows=[enteral(method="NJ")])
    feeds = recorded("GT", rate="")
    before = deepcopy(feeds)
    text = nutrition_text(data, feeds)
    assert "NJ:" in text and "GT:" not in text and feeds == before


def test_excluded_diet_order_cannot_reappear_through_recorded_counterpart():
    data = diet(enteral_rows=[enteral(method="NJ", include=False)])
    assert not nutrition_text(data, recorded(formula="Different formula"), dosing_weight="5 kg")


def test_recorded_only_feed_uses_default24_with_explicit_density_and_same_heading():
    text = nutrition_text(diet(), recorded(formula="Synthetic Formula 24 kcal/oz"), dosing_weight="5 kg")
    assert text == "Tube feed:\nNJ: Synthetic Formula 24 kcal/oz @ 30 mL/hr | 576 kcal/day (115.2 kcal/kg/day) | 144 mL/kg/day"
    assert "24 hr/day" not in text


def test_recorded_formula_only_and_rate_only_rows_omit_unknown_fields():
    feeds = recorded(rate="")
    assert nutrition_text(diet(), feeds) == "Tube feed:\nNJ: Synthetic Formula A"
    feeds = recorded(formula="")
    assert nutrition_text(diet(), feeds, dosing_weight="5 kg") == "Tube feed:\nNJ: 30 mL/hr | 144 mL/kg/day"


def test_recorded_empty_feed_row_is_omitted_without_changing_source():
    feeds = recorded(formula="", rate="")
    feeds["rows"][0]["formula"] = "Unknown"
    before = deepcopy(feeds)
    assert nutrition_text(diet(), feeds, dosing_weight="5 kg") == ""
    assert feeds == before


def test_unknown_formula_sentinel_does_not_resolve_ambiguous_tubes():
    feeds = recorded("NJ")
    feeds["rows"][0]["formula"] = "UNK"
    feeds["rows"] += recorded("ND")["rows"]
    assert recorded_feed_matches([enteral(method="Post-pyloric", formula="UNK")], feeds["rows"]) == {}


@pytest.mark.parametrize("formula", ["Formula -24 kcal/oz", "Formula - 24 kcal/oz", "Formula 20-24 kcal/oz", "Formula 20 - 24 kcal/oz", "Formula 20 to 24 kcal/oz", "Formula <24 kcal/oz", "Formula 24 kcal/oz + water", "Mixed formula 24 kcal/oz", "Formula 24 kcal/oz and 1 kcal/mL", "Formula -24 kcal/oz; 1 kcal/mL", "Formula 4:1", "Formula 1.0", "Formula 0 kcal/mL", "Mix Formula A 1 kcal/mL with Formula B", "Formula A 1 kcal/mL plus Formula B", "Formula A 1 kcal/mL blended with Formula B", "Mix Formula A and Formula B 1 kcal/mL", "Formula A plus Formula B (24 kcal/oz)", "Formula A 1 kcal/mL followed by another ingredient"])
def test_recorded_density_is_not_taken_from_signed_ranged_mixed_or_missing_values(formula):
    text = nutrition_text(diet(), recorded(formula=formula), dosing_weight="5 kg")
    assert "kcal/day" not in text and "kcal/kg/day" not in text and "144 mL/kg/day" in text


def test_recorded_formula_ending_parenthetical_density_can_supply_calories():
    text = nutrition_text(diet(), recorded(formula="Synthetic Formula (24 kcal/oz)"), dosing_weight="5 kg")
    assert "576 kcal/day (115.2 kcal/kg/day) | 144 mL/kg/day" in text


def test_oral_formula_feeding_uses_diet_heading_without_tube_label():
    text = nutrition_text(diet([oral("Regular")], [enteral(method="PO", route="Oral", caloric_density="24 kcal/oz")]), dosing_weight="5 kg")
    assert text.startswith("Diet: Regular\nPO:") and "Tube feed:" not in text


def test_legacy_diet_still_uses_separate_legacy_path():
    old = dict(rows=[oral("Peds Regular")])
    assert not has_detailed_nutrition(old) and nutrition_text(old) == ""


def test_extreme_recorded_rate_or_density_cannot_crash_or_create_derived_values():
    huge_rate = "9" * 70 + " mL/hr"
    feed = recorded()
    feed["rows"][0]["rate"] = huge_rate
    text = nutrition_text(diet(), feed, dosing_weight="5 kg")
    assert huge_rate in text and "mL/kg/day" not in text
    text = nutrition_text(diet(enteral_rows=[enteral(caloric_density="9" * 100 + " kcal/mL")]), dosing_weight="5 kg")
    assert "kcal/day" not in text and "kcal/kg/day" not in text and "120 mL/kg/day" in text


def test_extremely_small_or_long_dosing_weight_never_crashes_exports():
    sheet = new_sheet("P4102")
    sheet["diet"] = diet(enteral_rows=[enteral(rate="99999999999999999999 mL/hr", hours="", daily_volume="", caloric_density="99999999999999999999 kcal/mL")])
    sheet["dosing_weight"] = "0.000000000000000001 kg"
    text = handoff_text(sheet)
    assert "kcal/day" in text and "mL/kg/day" in text
    assert handoff_pdf(sheet).startswith(b"%PDF")
    sheet["dosing_weight"] = "0." + "0" * 50 + "1 kg"
    assert "mL/kg/day" not in handoff_text(sheet)


def test_cross_export_compact_output_keeps_calories_and_weight_volume_once():
    sheet = new_sheet("P4102")
    sheet["dosing_weight"] = "5 kg"
    sheet["diet"] = diet([oral()], [enteral(caloric_density="24 kcal/oz", comments="Do not print instructions", additives="Do not print additives")], [pn()])
    sheet["medications"] = [medication()]
    before = deepcopy(sheet)
    validate_sheet(sheet)
    expected = "480 kcal/day (96 kcal/kg/day) | 120 mL/kg/day"
    for text in (handoff_text(sheet), handoff_html(sheet)):
        assert expected in text and text.count("Pediatric 2-in-1 PN") == 1
        for unwanted in ("Do not print", "Using dosing weight", "Instructions:", "Additives:", "mL/day", "Recorded rate:"):
            assert unwanted not in text
    with fitz.open(stream=handoff_pdf(sheet), filetype="pdf") as document:
        text = re.sub(r"\s+", " ", " ".join(page.get_text() for page in document))
        assert expected in text and text.count("Pediatric 2-in-1 PN") == 1
    second = deepcopy(sheet)
    second["id"] = uuid.uuid4().hex
    second["room"] = "P4104"
    second["dosing_weight"] = "10 kg"
    with fitz.open(stream=handoffs_pdf([sheet, second]), filetype="pdf") as document:
        assert len(document) == 2
        first = re.sub(r"\s+", " ", document[0].get_text())
        later = re.sub(r"\s+", " ", document[1].get_text())
        assert "120 mL/kg/day" in first and "60 mL/kg/day" in later
        assert "120 mL/kg/day" not in later
    assert sheet == before
