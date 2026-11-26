"""Synthetic medication-note regressions. No source doses are calculated."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from categories import default_categories, target_snapshot
from medications import parse_medications
from models import new_sheet
from note_medications import build_note_medications


NOW = datetime(2026, 11, 25, 20, tzinfo=timezone.utc)


def order(name, dose="", route="Intravenous", frequency="Continuous", rate="", admin="", section="Neurologic"):
    source = "Medications:\n• " + "\t".join((name, dose, route, frequency, "", rate, admin))
    result = parse_medications(source)
    assert not result.error, result.issues
    row = result.rows[0]
    row["section"] = section
    return row


def summary(*rows):
    sheet = new_sheet("P4102")
    sheet["medications"] = list(rows)
    return build_note_medications(sheet, NOW)


def test_flat_main_group_uses_short_names_and_distinct_drip_scheduled_prn():
    result = summary(
        order("fentaNYL (PF) infusion syringe 100 mcg", "0.5-5 mcg/kg/hr", admin="2 mcg/kg/hr at 11/25/26 0800"),
        order("cloBAZam tablet 100 mg", "100 mg", "Oral", "q12h"),
        order("fentaNYL (PF) injection 20 mcg", "20 mcg", frequency="q1h PRN"),
    )
    assert result["sections"]["Neurologic"] == {
        "Drips": ["Fentanyl at 2 mcg/kg/hr"],
        "Scheduled": ["Clobazam 100 mg Q12H"],
        "PRN": ["Fentanyl 20 mcg Q1H PRN"],
    }
    assert "Antiepileptic" not in json.dumps(result["sections"])


def test_main_destination_comes_from_effective_category_snapshot():
    row = order("Example medication tablet 2 mg", "2 mg", "Oral", "Daily", section="Other Medications")
    row["category_path"] = target_snapshot("system:Respiratory", default_categories())
    result = summary(row)
    assert list(result["sections"]) == ["Respiratory"]
    assert result["entries"][0]["section"] == "Respiratory"


def test_custom_category_uses_main_section_without_custom_subheading():
    row = order("Example medication", "2 mg", "Oral", "Daily")
    row["category_path"] = dict(id="custom:example", name="Special subgroup", section="Cardiovascular",
                                parent_id="", parent_name="", order=100, parent_order=100)
    result = summary(row)
    assert "Cardiovascular" in result["sections"]
    assert "Special subgroup" not in json.dumps(result)


def test_legacy_main_section_override_is_preserved_when_automatic_group_was_disabled():
    row = order("Clobazam tablet 100 mg", "100 mg", "Oral", "q12h", section="Hematology")
    row["group_mode"] = "other"
    result = summary(row)
    assert list(result["sections"]) == ["Hematology"]


@pytest.mark.parametrize("name", ["Orencia", "Androderm", "Oralair"])
def test_drug_name_prefix_is_not_mistaken_for_an_order_connector(name):
    row = order(name + " tablet 1 mg", "1 mg", "Oral", "Daily")
    assert summary(row)["entries"][0]["name"] == name


def test_digit_in_drug_identity_is_not_removed_as_though_it_were_a_dose():
    row = order("Vitamin B-12 tablet 100 mcg", "100 mcg", "Oral", "Daily")
    text = summary(row)["entries"][0]["text"]
    assert "B-12" in text and text.count("100 mcg") == 1


@pytest.mark.parametrize("key,value", [("include", False), ("hidden", True), ("section", "Ignore")])
def test_excluded_rows_do_not_reappear(key, value):
    row = order("Example medication", "2 mg", "Oral", "Daily")
    row[key] = value
    assert summary(row)["entries"] == []


def test_override_pull_is_excluded_until_explicitly_restored():
    row = order("fentanyl ADS Override Pull", "20 mcg", frequency="q1h PRN")
    assert summary(row)["entries"] == []


def test_recorded_admin_rate_wins_without_weight_or_pump_conversion():
    row = order("Fentanyl 50 mcg/mL infusion", "0.5-5 mcg/kg/hr", rate="4 mL/hr", admin="2 mcg/kg/hr at 11/25/26 0800")
    sheet = new_sheet("P4102")
    sheet.update(medications=[row], dosing_weight="100 kg")
    before = deepcopy(sheet)
    result = build_note_medications(sheet, NOW)
    assert result["entries"][0]["text"] == "Fentanyl at 2 mcg/kg/hr"
    assert result["entries"][0]["rate_source"] == "last_admin"
    assert "4 mL/hr" not in result["entries"][0]["text"]
    assert sheet == before


def test_ordered_range_and_bag_strength_never_become_a_rate():
    row = order("Fentanyl 500 mcg in 50 mL infusion", "0.5-5 mcg/kg/hr")
    result = summary(row)
    assert result["sections"]["Neurologic"]["Drips"] == ["Fentanyl [rate not supplied]"]
    assert result["warnings"]


def test_numeric_recorded_pump_rate_is_kept_in_its_original_units():
    row = order("Norepinephrine 4 mg in 50 mL infusion", "0.01-1 mcg/kg/min", rate="1.25 mL/hr", section="Cardiovascular")
    result = summary(row)
    assert result["entries"][0]["text"] == "Norepinephrine at 1.25 mL/hr"
    assert result["entries"][0]["rate_source"] == "last_rate"


@pytest.mark.parametrize("admin,status", [("Stopped", "stopped"), ("Paused", "paused"), ("Held", "held")])
def test_nonrunning_drips_do_not_show_stale_rate_or_look_active(admin, status):
    row = order("Fentanyl infusion", "2 mcg/kg/hr", rate="3 mL/hr", admin=admin + " at 11/25/26 0800")
    result = summary(row)
    entry = result["entries"][0]
    assert not entry["active"] and entry["status"] == status
    assert " at " not in entry["text"]
    assert "[" + admin + "]" in entry["text"]


def test_source_held_label_wins_over_older_numeric_admin_rate():
    row = order("[Held by provider] Fentanyl infusion", "2 mcg/kg/hr", admin="3 mcg/kg/hr at 11/25/26 0800")
    entry = summary(row)["entries"][0]
    assert entry["text"] == "Fentanyl [Held]"
    assert not entry["active"]


@pytest.mark.parametrize("prefix,status", [
    ("[Paused]", "paused"), ("[Stopped]", "stopped"),
    ("Discontinued:", "discontinued"), ("Held by provider:", "held"),
    ("[Not given]", "not_given"),
])
def test_explicit_order_status_also_suppresses_stale_numeric_rates(prefix, status):
    row = order(prefix + " Fentanyl infusion", "2 mcg/kg/hr", admin="3 mcg/kg/hr at 11/25/26 0800")
    entry = summary(row)["entries"][0]
    assert entry["status"] == status and not entry["active"]
    assert " at " not in entry["text"] and "mcg/kg/hr" not in entry["text"]


def test_titrating_drip_does_not_promote_an_ordered_single_rate_without_a_recorded_rate():
    row = order("Norepinephrine infusion", "0.05 mcg/kg/min", section="Cardiovascular")
    entry = summary(row)["entries"][0]
    assert entry["text"] == "Norepinephrine [rate not supplied]"
    assert entry["rate_source"] == "unavailable"


def test_prn_wins_even_over_saved_infusion_display_choice():
    row = order("Fentanyl infusion syringe 20 mcg", "20 mcg", frequency="q1h PRN", rate="10 mL/hr")
    row["infusion_mode"] = "infusion"
    entry = summary(row)["entries"][0]
    assert entry["group"] == "PRN"
    assert entry["text"] == "Fentanyl 20 mcg Q1H PRN"


def test_weight_based_dose_stays_weight_based_without_calculation():
    row = order("Ceftriaxone syringe 500 mg", "50 mg/kg (Dosing Weight)", frequency="q24h", section="Infectious Disease")
    entry = summary(row)["entries"][0]
    assert entry["text"] == "Ceftriaxone 50 mg/kg Q24H"
    assert "500" not in entry["text"]


def test_routes_and_solution_concentrations_remain_for_local_medications():
    row = order("lidocaine 4 % cream", "", "Topical", "PRN")
    entry = summary(row)["entries"][0]
    assert entry["text"] == "Lidocaine 4 % cream PRN (Topical)"


def test_future_orders_are_labeled_and_not_diagnosis_triggers():
    row = order("[START ON 11/27/2026] Prednisolone oral solution 10 mg", "10 mg", "Oral", "q12h")
    entry = summary(row)["entries"][0]
    assert not entry["active"]
    assert entry["status"] == "future"
    assert "11/27/2026" in entry["text"]


def test_past_start_date_does_not_suppress_current_order():
    row = order("[START ON 11/20/2026] Prednisolone oral solution 10 mg", "10 mg", "Oral", "q12h")
    entry = summary(row)["entries"][0]
    assert entry["active"]
    assert entry["text"] == "Prednisolone 10 mg Q12H"


def test_superseded_pn_and_hidden_latest_pn_are_not_revived():
    first = order("[START ON 11/24/2026] Pediatric 2-in-1 PN", "20 mL/hr", section="FEN / GI")
    second = order("[START ON 11/25/2026] Pediatric 2-in-1 PN", "30 mL/hr", section="FEN / GI")
    result = summary(first, second)
    assert len(result["entries"]) == 1
    assert result["entries"][0]["id"] == second["id"]
    second["hidden"] = True
    assert summary(first, second)["entries"] == []


def test_custom_handoff_wording_is_kept_without_recalculation():
    row = order("Example medication", "2 mg", "Oral", "Daily")
    row["custom_text"] = "Example medication 3 mg Q12H per reviewed handoff"
    assert summary(row)["entries"][0]["text"] == row["custom_text"]


def test_payload_is_serializable_and_has_no_prn_counts_or_calculations():
    row = order("Vecuronium injection 1 mg", "1 mg", frequency="q1h PRN")
    row["_prn_count"] = {"count": 6}
    result = summary(row)
    encoded = json.dumps(result)
    assert "24 hours" not in encoded and "Calc:" not in encoded
