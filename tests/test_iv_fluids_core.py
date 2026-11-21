"""Synthetic source, classification and display boundaries for IV fluids."""
from copy import deepcopy
from decimal import Decimal
import uuid

import pytest

from categories import (apply_category_rules, catalog, default_categories,
                        set_category_rule, target_snapshot, validate_settings)
from fen_gi import automatic_group, effective_section, fen_gi_body, group_for
from infusion_rates import parse_last_admin
from iv_fluids import is_iv_fluid, iv_fluid_entry, maintenance_annotation
from medications import parse_medications, upsert_rule
from models import new_sheet, new_vault


FLUID = "sodium acetate 75 mEq in dextrose 5 % and sodium chloride 0.45 % 1,000 mL infusion"
STAMP = "11/20/26 1400"


def row(name=FLUID, **changes):
    result = dict(id=uuid.uuid4().hex, name=name, dose="50 mL/hr", route="Intravenous",
                  frequency="Continuous", last_rate="50 mL/hr", rate_time=STAMP,
                  section="Other Medications", include=True, hidden=False,
                  custom_text="", warnings=[])
    result.update(parse_last_admin("50 mL/hr at " + STAMP))
    result.update(changes)
    return result


@pytest.mark.parametrize("name", [
    FLUID,
    "sodium acetate 38.5 mEq in dextrose 5 % and sodium chloride 0.45 % 500 mL infusion",
    "dextrose 5 % and sodium chloride 0.9 % infusion",
    "sodium chloride 0.9 % infusion", "sodium chloride 0.45 % infusion",
    "dextrose 10 % infusion", "D10 infusion", "D10W infusion", "D5NS infusion",
    "D5/0.9NS infusion", "D5/0.45NS infusion", "D5 1/2 NS infusion",
    "lactated ringers infusion", "Lactated Ringer's solution", "LR infusion",
    "Plasma-Lyte A infusion", "PlasmaLyte 148 infusion",
    "potassium chloride 20 mEq in dextrose 5 % and sodium chloride 0.45 % 1,000 mL infusion",
    "potassium chloride 40 mEq in sodium chloride 0.9 % 1,000 mL infusion",
    "potassium chloride 10 mEq in dextrose 5 % 500 mL infusion",
    "KCl 20 mEq in D5NS 500 mL infusion",
])
def test_complete_known_fluid_formulations_receive_requested_default(name):
    source = row(name)
    assert is_iv_fluid(source)
    assert automatic_group(source) == "iv_fluids"
    assert effective_section(source) == "FEN / GI"


@pytest.mark.parametrize("name", [
    "heparin 1 unit/mL in sodium chloride 0.9 %",
    "heparin infusion 100 units/mL in D5W 250 mL",
    "lidocaine (cardiac) PF (Xylocaine) 600 mg in dextrose 5 % 100 mL (6 mg/mL) infusion",
    "milrinone (Primacor) 30 mg in dextrose 5 % 100 mL (0.3 mg/mL) infusion",
    "nitroprusside (Nipride) 100 mg in sodium chloride 0.9 % 100 mL infusion",
    "[Held by provider] midazolam in NaCl 0.9 % (Versed) 100 mg/100 mL infusion",
    "levETIRAcetam in sodium chloride (Keppra) IVPB 1,000 mg",
    "sodium chloride 0.9 % with fentanyl infusion", "sodium chloride 0.9 % bolus",
    "sodium chloride 0.9 % flush", "sodium chloride 3 % infusion",
    "sodium chloride 3 % nebulizer solution 4 mL", "sodium chloride enteral solution 15 mEq",
    "sodium bicarbonate 8.4 % infusion", "potassium chloride 20 mEq infusion",
    "potassium chloride 20 mEq in sodium chloride 0.9 % 100 mL infusion",
    "potassium chloride 60 mEq in sodium chloride 0.9 % 1,000 mL infusion",
    "potassium chloride 20 mEq in dextrose 5 % and sodium chloride 0.45 % infusion",
    "potassium chloride 20 mEq in dextrose 5 % 1,000 mL repletion infusion",
    "potassium chloride 20 mEq in dextrose 5 % 1,000 mL IVPB",
    "sodium acetate 20 mEq infusion", "dextrose 50 % infusion",
    "pediatric parenteral nutrition", "fat emulsion 20 % infusion",
])
def test_drug_carriers_concentrated_products_and_nonfluids_do_not_match(name):
    assert not is_iv_fluid(row(name))


@pytest.mark.parametrize("changes", [
    {"route": "Per NG Tube"}, {"route": "Nebulization"}, {"route": ""},
    {"frequency": "Once"}, {"frequency": "Continuous PRN"},
    {"frequency": "as needed"}, {"infusion_mode": "other"},
])
def test_explicit_delivery_and_saved_infusion_override_are_required(changes):
    assert not is_iv_fluid(row(**changes))


def test_d50_existing_hypoglycemia_group_and_other_gi_override_are_preserved():
    assert automatic_group(row("dextrose 50 % infusion")) == "hypoglycemia"
    assert group_for(row(gi_mode="other")) == ""
    assert "Intravenous Fluids" not in fen_gi_body("", [row(gi_mode="other")], None)


@pytest.mark.parametrize("rate,weight,expected", [
    (50, "27 kg", "~3/4 maintenance"), (25, "8.2 kg", "~3/4 maintenance"),
    (45, "23.3 kg", "~71% maintenance"), (75, "66 kg", "~71% maintenance"),
    (40, "10 kg", "maintenance"), (60, "20 kg", "maintenance"),
    (67, "27 kg", "maintenance"), (106, "66 kg", "maintenance"),
    (20, "10 kg", "1/2 maintenance"), (10, "10 kg", "1/4 maintenance"),
    (50, "10 kg", "1 1/4 maintenance"),
    (Decimal("29.2"), "10 kg", "~3/4 maintenance"),
    (Decimal("29.19"), "10 kg", "~73% maintenance"),
    (30, "10000 g", "3/4 maintenance"),
])
def test_uncapped_hourly_reference_and_fraction_rounding(rate, weight, expected):
    assert maintenance_annotation(rate, weight) == expected


@pytest.mark.parametrize("rate,weight", [
    (1, "8.2 kg"), (2, "8.2 kg"), (0, "27 kg"), (-1, "27 kg"),
    (50, ""), (50, "27"), (50, "unknown"), (50, "0 kg"),
    (50, "27-30 kg"), ("50 mL/hr", "27 kg"), ("NaN", "27 kg"),
    ("Infinity", "27 kg"),
])
def test_unusable_weight_rate_and_low_volume_do_not_receive_comparison(rate, weight):
    assert maintenance_annotation(rate, weight) == ""


def test_new_bag_event_uses_explicit_last_rate_without_inventing_bag_rate():
    source = row(dose="", **parse_last_admin("New Bag at 11/20/26 1410"))
    before = deepcopy(source)
    text = iv_fluid_entry(source, {"dosing_weight": "27 kg"})
    assert "Last Rate: 50 mL/hr [11/20/26 1400] (~3/4 maintenance)" in text
    assert "Last Admin: Event without a rate [11/20/26 1410]" in text
    assert text.count("50 mL/hr") == 1
    assert source == before


def test_new_bag_event_at_same_recorded_rate_time_does_not_repeat_provenance():
    source = row(dose="", **parse_last_admin("New Bag at " + STAMP))
    text = iv_fluid_entry(source, {"dosing_weight": "27 kg"})
    assert "Last Rate: 50 mL/hr [" + STAMP + "] (~3/4 maintenance)" in text
    assert "Event without a rate" not in text
    assert text.count(STAMP) == 1


def test_primary_admin_rate_is_separate_from_dose_and_other_recorded_rate():
    source = row(dose="100 mL/hr", last_rate="45 mL/hr", rate_time="11/20/26 1200")
    text = iv_fluid_entry(source, {"dosing_weight": "27 kg"})
    assert "Last Admin rate: 50 mL/hr [11/20/26 1400] (~3/4 maintenance)" in text
    assert "Last Rate: 45 mL/hr [11/20/26 1200]" in text
    assert "100 mL/hr" not in text
    assert text.count("maintenance") == 1


def test_equal_rates_keep_distinct_timestamps_without_duplicate_values():
    text = iv_fluid_entry(row(rate_time="11/20/26 1200"), {"dosing_weight": "27 kg"})
    assert text.count("50 mL/hr") == 1
    assert "11/20/26 1200" in text and STAMP in text


@pytest.mark.parametrize("status", ["Stopped", "Paused", "Held", "Discontinued", "Not given", "Not administered"])
def test_nonrunning_events_show_status_without_stale_rate_comparison(status):
    source = row(**parse_last_admin(status + " at " + STAMP))
    text = iv_fluid_entry(source, {"dosing_weight": "27 kg"})
    assert status in text
    assert "maintenance" not in text
    assert "50 mL/hr" not in text
    assert source["last_rate"] == "50 mL/hr"


@pytest.mark.parametrize("prefix", ["[Held by provider]", "[Discontinued]"])
def test_order_status_prevents_comparison_despite_older_numeric_admin(prefix):
    text = iv_fluid_entry(row(prefix + " " + FLUID), {"dosing_weight": "27 kg"})
    assert prefix in text and "maintenance" not in text


@pytest.mark.parametrize("raw_rate", [
    "50 mL/hr then 80 mL/hr", "50-80 mL/hr",
    "50 mL/hr at 11/20/26 1200 and 80 mL/hr",
])
def test_parser_ambiguity_survives_sanitization_and_blocks_convenient_dose_fallback(raw_rate):
    source = "\t".join([FLUID, "50 mL/hr", "Intravenous", "Continuous", "", raw_rate, "New Bag"])
    result = parse_medications(source)
    assert not result.error
    text = iv_fluid_entry(result.rows[0], {"dosing_weight": "27 kg"})
    assert "maintenance" not in text
    assert "review" in text.casefold()


def test_ambiguous_last_admin_can_show_recorded_rate_but_has_no_comparison():
    source = row(**parse_last_admin("50-80 mL/hr at " + STAMP))
    text = iv_fluid_entry(source, {"dosing_weight": "27 kg"})
    assert "Last Admin: Unclear entry" in text
    assert "Last Rate: 50 mL/hr" in text
    assert "maintenance" not in text


@pytest.mark.parametrize("dose", ["1,000 mL", "40-60 mL/hr", "2 mL/kg/hr", ""])
def test_bag_quantity_range_or_weight_based_dose_never_becomes_an_hourly_rate(dose):
    source = row(dose=dose, last_rate="", rate_time="", **parse_last_admin("New Bag"))
    text = iv_fluid_entry(source, {"dosing_weight": "27 kg"})
    assert "maintenance" not in text
    assert "50 mL/hr" not in text


def test_failed_dosing_weight_section_blocks_old_value_and_supplied_override():
    context = new_sheet("P4102")
    context.update(dosing_weight="27 kg", import_warnings={"i": "Not updated"})
    assert "maintenance" not in iv_fluid_entry(row(), context)
    assert "maintenance" not in iv_fluid_entry(row(), context, dosing_weight="27 kg")
    assert "maintenance" not in fen_gi_body("", [row()], None, dosing_weight="27 kg", sheet=context)


def test_standalone_fen_gi_dosing_weight_reaches_fluid_renderer():
    source = row()
    before = deepcopy(source)
    text = fen_gi_body("", [source], None, dosing_weight="27 kg")
    assert "Intravenous Fluids" in text and "~3/4 maintenance" in text
    assert source == before
    assert "maintenance" not in fen_gi_body("", [source], None)


def test_custom_wording_remains_authoritative_and_is_html_escaped():
    source = row(custom_text="Use the checked fluid wording <review>")
    text = iv_fluid_entry(source, {"dosing_weight": "27 kg"}, rich=True)
    assert text == "<b>Use the checked fluid wording &lt;review&gt;</b>"
    assert "maintenance" not in text


def test_explicit_category_and_legacy_other_rules_override_new_default():
    settings = new_vault()["settings"]
    settings = set_category_rule(settings, FLUID, "system:Cardiovascular", match="exact")
    assigned = apply_category_rules([row()], settings)[0]
    assert effective_section(assigned) == "Cardiovascular"
    assert "Intravenous Fluids" not in fen_gi_body("", [assigned], None, dosing_weight="27 kg")
    legacy = new_vault()["settings"]
    legacy["medication_mappings"] = upsert_rule([], FLUID, "Other Medications", "exact")
    assigned = apply_category_rules([row()], legacy)[0]
    assert effective_section(assigned) == "Other Medications"


@pytest.mark.parametrize("changes", [{"include": False}, {"hidden": True}, {"section": "Ignore"},
                                      {"category_path": target_snapshot("system:Ignore", default_categories())}])
def test_saved_visibility_and_ignore_keep_fluid_out_of_output(changes):
    assert FLUID not in fen_gi_body("", [row(**changes)], None, dosing_weight="27 kg")


def test_old_category_catalog_backfills_fluid_without_changing_custom_names():
    settings = new_vault()["settings"]
    settings["medication_categories"] = [item for item in default_categories() if item["id"] != "gi:iv_fluids"]
    settings["medication_categories"][0]["name"] = "Saved heading"
    before = deepcopy(settings)
    validate_settings(settings)
    assert next(item for item in catalog(settings) if item["id"] == "gi:iv_fluids")["name"] == "Intravenous Fluids"
    assert settings == before
