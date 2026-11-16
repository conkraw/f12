"""Synthetic per-dose display tests. No administration history is inferred."""
from copy import deepcopy
from decimal import Decimal

import pytest

from categories import default_categories, target_snapshot
from medication_doses import dose_per_kg_annotation, medication_weight
from medications import format_medication, parse_medications
from models import new_sheet


def order(name="furosemide (Lasix) injection 14 mg", dose="14 mg", frequency="q6h", route="Intravenous"):
    result = parse_medications("Medications:\n• " + "\t".join((name, dose, route, frequency, "", "", "")))
    assert not result.error
    return result.rows[0]


def handoff(dcw="10 kg", measured="12 kg", include=True):
    sheet = new_sheet("P4102")
    sheet["dosing_weight"] = dcw
    sheet["nutrition"] = None if measured is None else {"weight": measured, "z_score": "", "include": include}
    return sheet


def test_dcw_wins_and_both_source_objects_remain_unchanged():
    row, sheet = order(), handoff()
    before = deepcopy((row, sheet))
    assert dose_per_kg_annotation(row, sheet) == "1.4 mg/kg/dose (DCW 10 kg)"
    assert (row, sheet) == before


def test_current_measured_weight_is_labeled_when_dcw_missing():
    assert dose_per_kg_annotation(order(), handoff(dcw="", measured="14 kg")) == "1 mg/kg/dose (weight 14 kg)"


@pytest.mark.parametrize("dcw,measured,expected", [
    ("2500 g", "4 kg", "0.4 mg/kg/dose (DCW 2500 g)"),
    ("", "2500 g", "0.4 mg/kg/dose (weight 2500 g)"),
    ("10 KG", "12 kg", "0.1 mg/kg/dose (DCW 10 kg)"),
])
def test_metric_weight_units_and_case(dcw, measured, expected):
    assert dose_per_kg_annotation(order(dose="1 mg"), handoff(dcw, measured)) == expected


@pytest.mark.parametrize("dose", ["10 mg/kg (Dosing Weight)", "10 mg/kg", "1 mcg/kg", ".5 mcg/kg/dose", "1 mg (0.1 mg/kg)"])
def test_source_weight_based_dose_is_not_recomputed_or_duplicated(dose):
    row = order("chlorothiazide (Diuril) injection 97 mg", dose)
    before = deepcopy(row)
    assert dose_per_kg_annotation(row, handoff(dcw="10 kg")) == ""
    assert format_medication(row).count(dose) == 1
    assert row == before


@pytest.mark.parametrize("drug,unit,amount,expected", [
    ("fentanyl", "mcg", "12", "1.2 mcg/kg/dose"),
    ("midazolam", "mg", "1", "0.1 mg/kg/dose"),
    ("ketamine", "mg", "10", "1 mg/kg/dose"),
    ("morphine", "mg", "2", "0.2 mg/kg/dose"),
    ("hydromorphone", "mg", ".5", "0.05 mg/kg/dose"),
])
def test_automatic_sedative_prns_use_order_units(drug, unit, amount, expected):
    row = order(drug + " injection", amount + " " + unit, "q2h PRN")
    assert dose_per_kg_annotation(row, handoff()) == expected + " (DCW 10 kg)"


@pytest.mark.parametrize("unit", ["mcg", "ug", "µg", "μg", "MCG"])
def test_microgram_spellings_are_not_converted_to_milligrams(unit):
    row = order("fentanyl injection", "15 " + unit, "q2h PRN")
    assert dose_per_kg_annotation(row, handoff()) == "1.5 mcg/kg/dose (DCW 10 kg)"


def test_manual_sedative_prn_assignment_is_supported_even_when_renamed():
    row = order("clonidine suspension 15 mcg", "15 mcg", "q6h PRN", "Per G Tube")
    row["category_path"] = target_snapshot("group:sedative_prn", default_categories())
    row["category_path"]["name"] = "Rescue sedation"
    assert dose_per_kg_annotation(row, handoff()) == "1.5 mcg/kg/dose (DCW 10 kg)"


def test_custom_child_of_sedative_prn_category_is_supported():
    row = order("Example sedative injection", "1 mg", "As needed")
    placement = dict(target_snapshot("group:sedative_prn", default_categories()),
                     id="custom:rescue", parent_id="group:sedative_prn", parent_name="PRN", name="Rescue")
    assert dose_per_kg_annotation(row, handoff(), placement) == "0.1 mg/kg/dose (DCW 10 kg)"


def test_group_name_alone_does_not_invent_a_sedative_category():
    row = order("Example medication injection", "1 mg", "PRN")
    placement = dict(target_snapshot("group:fever", default_categories()), name="PRN")
    assert dose_per_kg_annotation(row, handoff(), placement) == ""


def test_source_prn_frequency_is_required_for_sedative_group():
    row = order("midazolam injection", "1 mg", "q6h")
    row["category_path"] = target_snapshot("group:sedative_prn", default_categories())
    assert dose_per_kg_annotation(row, handoff()) == ""


def test_explicit_move_out_of_sedative_group_is_respected():
    row = order("midazolam injection", "1 mg", "q6h PRN")
    row["category_path"] = target_snapshot("group:antiepileptic", default_categories())
    assert dose_per_kg_annotation(row, handoff()) == ""


@pytest.mark.parametrize("name", ["chlorothiazide suspension", "furosemide injection", "Diuril suspension", "Lasix injection"])
def test_requested_diuretics_use_per_dose_display_in_any_category(name):
    row = order(name, "20 mg")
    row["category_path"] = target_snapshot("system:Cardiovascular", default_categories())
    assert dose_per_kg_annotation(row, handoff()) == "2 mg/kg/dose (DCW 10 kg)"


@pytest.mark.parametrize("name", ["hydrochlorothiazide tablet", "bumetanide injection", "spironolactone suspension", "chlorothiazide-like example", "furosemidex example"])
def test_no_extension_to_other_drugs_or_similar_names(name):
    assert dose_per_kg_annotation(order(name, "10 mg"), handoff()) == ""


@pytest.mark.parametrize("dose", [
    "", "5 mL", "10 mg/mL", "10 mg/hr", "1 mcg/kg/min", "1 mg/kg/hr", "20 mg/day",
    "10 mg per day", "5-10 mg", "5–10 mg", "5 mg or 10 mg", "10 mg (estimated)",
    "1e-3 mg", "NaN mg", "Infinity mg", "-1 mg", "0 mg", ">1 mg", "1,2 mg",
    "1 mg/mL 5 mL", "1 mg + 2 mg", "1 mg at 12:00", "1 mg (Dosing Weight)",
])
def test_ambiguous_amounts_rates_ranges_and_annotations_are_not_divided(dose):
    row = order()
    row["dose"] = dose
    assert dose_per_kg_annotation(row, handoff()) == ""


@pytest.mark.parametrize("frequency", ["Continuous", "Continuous PRN", "Titrate", "Titration", "Titratable"])
def test_infusion_bag_amount_does_not_become_a_per_dose_value(frequency):
    row = order("furosemide infusion 50 mg", "50 mg", frequency)
    assert dose_per_kg_annotation(row, handoff()) == ""


def test_explicit_infusion_choice_blocks_per_dose_annotation():
    row = order()
    row["infusion_mode"] = "infusion"
    assert dose_per_kg_annotation(row, handoff()) == ""


def test_intermittent_last_rate_is_not_used_as_the_dose():
    row = order()
    row["last_rate"] = "500 mL/hr"
    assert dose_per_kg_annotation(row, handoff()) == "1.4 mg/kg/dose (DCW 10 kg)"


def test_product_amount_never_supplies_a_missing_dose_column():
    row = order("furosemide 10 mg/mL injection 20 mg", "")
    assert dose_per_kg_annotation(row, handoff()) == ""


@pytest.mark.parametrize("dcw", ["0 kg", "-10 kg", "NaN kg", "1e1 kg", "unknown", "10", "10 lb", "10 kg (estimate)", "1-2 kg", None])
def test_invalid_dcw_does_not_silently_use_another_weight(dcw):
    sheet = handoff()
    sheet["dosing_weight"] = dcw
    assert dose_per_kg_annotation(order(), sheet) == ""


@pytest.mark.parametrize("measured", [None, "", "0 kg", "-10 kg", "12 lb", "estimated 10 kg", "10"])
def test_missing_or_invalid_measured_weight_is_not_invented(measured):
    assert dose_per_kg_annotation(order(), handoff(dcw="", measured=measured)) == ""


def test_excluded_measured_weight_is_not_used():
    assert dose_per_kg_annotation(order(), handoff(dcw="", include=False)) == ""


def test_excluded_measured_weight_does_not_disable_valid_dcw():
    assert dose_per_kg_annotation(order(), handoff(include=False)) == "1.4 mg/kg/dose (DCW 10 kg)"


def test_i_block_warning_blocks_both_weights_but_other_warnings_do_not():
    sheet = handoff()
    sheet["import_warnings"]["i"] = [{"action": "not_imported"}]
    assert dose_per_kg_annotation(order(), sheet) == ""
    sheet["dosing_weight"] = ""
    assert dose_per_kg_annotation(order(), sheet) == ""
    sheet["import_warnings"] = {"t": [{"action": "not_imported"}]}
    assert dose_per_kg_annotation(order(dose="12 mg"), sheet) == "1 mg/kg/dose (weight 12 kg)"


def test_io_and_free_text_weights_are_never_fallbacks():
    sheet = handoff(dcw="", measured=None)
    sheet["current_shift"] = {"weight_kg": "10"}
    sheet["intake_output"] = {"weight_kg": "10"}
    sheet["fields"]["Demographics / Weight"] = "Weight 10 kg"
    assert dose_per_kg_annotation(order(), sheet) == ""


def test_custom_handoff_text_is_authoritative():
    row = order()
    row["custom_text"] = "Clinician-written dose text"
    assert dose_per_kg_annotation(row, handoff()) == ""


@pytest.mark.parametrize("change", [{"include": False}, {"hidden": True}, {"section": "Ignore"}])
def test_excluded_orders_do_not_get_annotations(change):
    row = order()
    row.update(change)
    assert dose_per_kg_annotation(row, handoff()) == ""


@pytest.mark.parametrize("dose,weight,expected", [
    ("14 mg", "10 kg", "1.4"),
    ("1 mg", "6 kg", "0.167"),
    ("1 mg", "300 kg", "0.00333"),
    ("0.000001 mg", "100 kg", "0.00000001"),
    ("999.9 mg", "100 kg", "10"),
])
def test_compact_rounding_retains_small_positive_values(dose, weight, expected):
    annotation = dose_per_kg_annotation(order(dose=dose), handoff(dcw=weight))
    assert annotation == expected + " mg/kg/dose (DCW " + weight + ")"
    assert Decimal(annotation.split()[0]) > 0


@pytest.mark.parametrize("dose", ["2 mg/dose", "2 mg per dose"])
def test_explicit_per_dose_amounts_are_supported(dose):
    assert dose_per_kg_annotation(order(dose=dose), handoff()) == "0.2 mg/kg/dose (DCW 10 kg)"


def test_weight_api_reports_basis_for_editor_and_none_for_no_sheet():
    assert medication_weight(handoff()) == (Decimal("10"), "DCW 10 kg")
    assert medication_weight(handoff(dcw="")) == (Decimal("12"), "weight 12 kg")
    assert medication_weight(None) == (None, "")
    assert dose_per_kg_annotation(order(), None) == ""
