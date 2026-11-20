"""Synthetic latest-ordered PN/lipid regressions. No patient data."""
from copy import deepcopy

import fitz
import pytest

from diet import parse_diet, validate_diet
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from fen_gi import fen_gi_body
from medications import parse_medications, validate_medication
from models import new_sheet, validate_sheet
from nutrition_display import nutrition_text
from pn_orders import (dietary_rows_for_display, medication_rows_for_display,
                       order_timestamp, parenteral_kind)


PN = "Pediatric 2-in-1 PN (Continuous)"
LIPID = "fat emulsion fish oil/plant based (SMOFlipid) 20 % 7 g 35 mL syringe"


def table_row(name=PN, dose="600 mL", rate="", admin="", route="Intravenous"):
    return "•\t" + "\t".join((name, dose, route, "Continuous PN", "Synthetic Provider", rate, admin))


def medications(*rows):
    result = parse_medications("Medications:\n" + "\n".join(rows))
    assert not result.error, result.issues
    return result.rows


def diet(*rows):
    result = parse_diet("Dietary Orders:\n" + "\n".join(rows), detailed=True)
    assert not result.error, result.issues
    validate_diet(result.data)
    return result.data


def pending_pair():
    return medications(
        table_row(dose="600 mL", rate="25 mL/hr at 11/19/26 2100", admin="New Bag at 11/19/26 2100"),
        "And", table_row(LIPID, "2 g/kg", "1.75 mL/hr at 11/19/26 2100", "7 g at 11/19/26 2100"),
        table_row(dose="720 mL"), "And", table_row(LIPID, "3 g/kg"))


def test_pending_new_bags_replace_prior_doses_and_do_not_inherit_prior_rates():
    rows = pending_pair()
    before = deepcopy(rows)
    selected = medication_rows_for_display(rows)
    assert [row["dose"] for row in selected] == ["720 mL", "3 g/kg"]
    assert all(row["last_rate"] == "" for row in selected)
    assert len(rows) == 4 and rows == before
    for row in rows:
        validate_medication(row)


def test_explicit_start_beats_reversed_table_order_and_dates_paired_lipids():
    rows = medications(
        table_row("[START ON 11/21/2026] " + PN, "720 mL"), "And", table_row(LIPID, "3 g/kg"),
        table_row("[START ON 11/20/2026] " + PN, "600 mL"), "And", table_row(LIPID, "2 g/kg"))
    assert [row["dose"] for row in medication_rows_for_display(rows)] == ["720 mL", "3 g/kg"]


def test_administration_and_pump_times_cannot_determine_order_recency():
    rows = medications(table_row(dose="600 mL", rate="25 mL/hr at 11/22/26 1100", admin="New Bag at 11/22/26 1100"),
                       table_row(dose="720 mL", rate="30 mL/hr at 11/20/26 1100", admin="New Bag at 11/20/26 1100"))
    assert medication_rows_for_display(rows) == rows[1:]
    rows[0]["rate_time"] = "12/31/2099 2359"
    rows[0]["last_admin_time"] = "12/31/2099 2359"
    assert medication_rows_for_display(rows) == rows[1:]


def test_lipid_brand_and_pn_formulation_changes_still_select_one_per_family():
    rows = medications(table_row(dose="600 mL"), table_row("SMOFlipid 20 % infusion", "2 g/kg"),
                       table_row("Pediatric 3-in-1 PN (Cyclic)", "800 mL"),
                       table_row("Intralipid 20 % infusion", "3 g/kg"))
    selected = medication_rows_for_display(rows)
    assert selected == rows[2:]


@pytest.mark.parametrize("changes", [{"hidden": True}, {"include": False}, {"section": "Ignore"}])
def test_hidden_latest_choice_never_restores_an_older_medication_or_diet_copy(changes):
    rows = medications(table_row(dose="600 mL"), table_row(dose="720 mL"))
    rows[1].update(changes)
    source = diet(PN + " at 25 mL/hr starting at 11/19 2100", PN + " at 30 mL/hr starting at 11/20 2100")
    assert medication_rows_for_display(rows, diet=source) == rows[1:]
    assert dietary_rows_for_display(source, rows) == []
    assert nutrition_text(source, medications=rows) == ""
    sheet = new_sheet("P4102")
    sheet.update(medications=rows, diet=source)
    assert PN not in handoff_text(sheet)


def test_held_new_order_keeps_its_status_and_discontinued_order_is_not_selected():
    rows = medications(table_row(dose="600 mL"), table_row("[Held by provider] " + PN, "720 mL"),
                       table_row("[DISCONTINUED] " + PN, "800 mL"))
    assert medication_rows_for_display(rows) == rows[1:2]
    assert "[Held by provider]" in medication_rows_for_display(rows)[0]["name"]
    assert medication_rows_for_display(rows[2:]) == []


@pytest.mark.parametrize("name", ["SMOFlipid 20 % infusion", "Intralipid 20 % infusion", "Omegaven 10 % infusion",
                                  "fish oil triglycerides (Omegaven) 10 % emulsion", "Clinolipid 20 % emulsion"])
def test_named_iv_lipid_products_are_recognized(name):
    assert parenteral_kind(name, "Intravenous") == "lipid"


@pytest.mark.parametrize("name", ["The Very Finest Fish Oil liquid 2.5 mL", "omega-3 fatty acids capsule",
                                  "fish oil oral liquid", "fat emulsion oral supplement"])
def test_enteral_fish_oil_is_not_an_iv_lipid_order(name):
    row = medications(table_row(name, "2.5 mL", route="Per G Tube"))[0]
    assert parenteral_kind(name, row["route"]) == ""
    assert medication_rows_for_display([row, *pending_pair()])[0] == row


def test_diet_keeps_dated_daily_bags_in_storage_and_selects_latest_start():
    source = diet(PN + " at 30 mL/hr starting at 11/20 2100", PN + " at 30 mL/hr starting at 11/19 2100")
    assert len(source["parenteral"]) == 2
    before = deepcopy(source)
    assert dietary_rows_for_display(source) == source["parenteral"][:1]
    assert nutrition_text(source).count(PN) == 1
    assert source == before


def test_new_dietary_rate_wins_without_merging_different_daily_bags():
    source = diet(PN + " at 30 mL/hr starting at 11/20 2100", PN + " at 25 mL/hr starting at 11/19 2100")
    assert "30 mL/hr" in nutrition_text(source)
    assert "25 mL/hr" not in nutrition_text(source)
    assert [row["rate"] for row in source["parenteral"]] == ["30 mL/hr", "25 mL/hr"]


def test_dietary_pn_and_lipid_are_selected_independently():
    source = diet(PN + " at 25 mL/hr starting at 11/19 2100",
                  "SMOFlipid 20 % infusion at 2 mL/hr starting at 11/19 2100",
                  PN + " at 30 mL/hr starting at 11/20 2100",
                  "Intralipid 20 % infusion at 3 mL/hr starting at 11/20 2100")
    text = nutrition_text(source)
    assert text.count(PN) == 1 and "30 mL/hr" in text
    assert "Intralipid" in text and "SMOFlipid" not in text


def test_detailed_order_timestamp_is_retained_and_used_ahead_of_start_date():
    source = diet("Start\tOrdered", "11/22/26 2100", PN + " at 30 mL/hr", "11/19/26 0900",
                  "11/21/26 2100", PN + " at 25 mL/hr", "11/20/26 1000")
    assert len(source["parenteral"]) == 2
    assert "Ordered: 11/20/26 1000" in source["parenteral"][1]["source"]
    text = nutrition_text(source)
    assert "25 mL/hr" in text and "30 mL/hr" not in text


def test_start_only_column_never_assigns_next_start_as_previous_ordered_time():
    source = diet("Start", "11/19/26 2100", PN + " at 10 mL/hr",
                  "11/20/26 2100", PN + " at 12 mL/hr")
    assert all("Ordered:" not in row["source"] for row in source["parenteral"])
    assert "Start: 11/20/26 2100" in source["parenteral"][1]["source"]
    text = nutrition_text(source)
    assert "12 mL/hr" in text and "10 mL/hr" not in text


def test_missing_ordered_cell_does_not_assign_an_ambiguous_time_to_old_bag():
    source = diet("Start\tOrdered", "11/19/26 2100", PN + " at 10 mL/hr",
                  "11/20/26 2100", PN + " at 12 mL/hr")
    assert "Ordered: 11/20/26 2100" not in source["parenteral"][0]["source"]
    assert "Unassigned table time: 11/20/26 2100" in source["parenteral"][0]["source"]
    text = nutrition_text(source)
    assert "12 mL/hr" in text and "10 mL/hr" not in text


@pytest.mark.parametrize("changes", [{}, {"hidden": True}, {"include": False}, {"section": "Ignore"}])
def test_same_day_date_only_medication_cannot_be_overridden_by_timed_diet_copy(changes):
    rows = medications(table_row("[START ON 11/20/2026] " + PN, "640 mL"))
    rows[0].update(changes)
    source = diet(PN + " at 30 mL/hr starting at 11/20 2100")
    sheet = new_sheet("P4102")
    sheet.update(medications=rows, diet=source)
    assert medication_rows_for_display(rows, sheet) == rows
    assert dietary_rows_for_display(source, rows, sheet) == []
    output = handoff_text(sheet)
    assert "30 mL/hr" not in output
    assert ("640 mL" in output) == (not changes)
    if changes:
        assert PN not in output


@pytest.mark.parametrize("med_time,diet_wins", [("2000", True), ("2200", False)])
def test_explicit_times_on_both_same_day_sources_still_establish_latest(med_time, diet_wins):
    rows = medications(table_row("[START ON 11/20/2026 " + med_time + "] " + PN, "640 mL"))
    source = diet(PN + " at 30 mL/hr starting at 11/20 2100")
    assert bool(dietary_rows_for_display(source, rows)) == diet_wins
    assert bool(medication_rows_for_display(rows, diet=source)) != diet_wins


def test_unknown_same_day_medication_time_uses_source_sequence_without_assuming_midnight():
    rows = medications(table_row("[START ON 11/20/2026 2100] " + PN, "600 mL"),
                       table_row("[START ON 11/20/2026] " + PN, "720 mL"))
    assert medication_rows_for_display(rows) == rows[1:]


def test_new_undated_bag_uses_source_fallback_when_old_bag_has_a_date():
    rows = medications(table_row("[START ON 11/19/2026] " + PN, "600 mL"),
                       table_row(dose="720 mL"))
    assert medication_rows_for_display(rows) == rows[1:]


def test_dated_newer_diet_order_supersedes_explicitly_older_medication_order():
    rows = medications(table_row("[START ON 11/19/2026] " + PN, "600 mL"))
    source = diet("Pediatric 3-in-1 PN (Cyclic) at 30 mL/hr starting at 11/20 2100")
    sheet = new_sheet("P4102")
    sheet.update(medications=rows, diet=source)
    assert medication_rows_for_display(rows, sheet) == []
    assert dietary_rows_for_display(source, rows, sheet) == source["parenteral"]
    standalone = fen_gi_body("", rows, None, diet=source)
    assert "Pediatric 3-in-1 PN" in standalone and "600 mL" not in standalone


def test_older_diet_product_does_not_survive_a_newer_medication_product():
    rows = medications(table_row("[START ON 11/20/2026] " + PN, "720 mL"))
    source = diet("Pediatric 3-in-1 PN (Cyclic) at 25 mL/hr starting at 11/19 2100")
    assert medication_rows_for_display(rows, diet=source) == rows
    assert dietary_rows_for_display(source, rows) == []


def test_hidden_newest_diet_order_does_not_restore_an_older_bag():
    source = diet(PN + " at 30 mL/hr starting at 11/20 2100", PN + " at 25 mL/hr starting at 11/19 2100")
    source["parenteral"][0]["include"] = False
    assert nutrition_text(source) == ""


def test_failed_diet_import_does_not_suppress_current_medication_order():
    rows = medications(table_row("[START ON 11/19/2026] " + PN))
    source = diet(PN + " at 30 mL/hr starting at 11/20 2100")
    sheet = new_sheet("P4102")
    sheet.update(medications=rows, diet=source)
    sheet["import_warnings"] = {"ab": [{"action": "diet_hidden"}]}
    assert medication_rows_for_display(rows, sheet) == rows
    assert dietary_rows_for_display(source, rows, sheet) == []


def test_year_boundary_uses_explicit_source_year_without_server_clock():
    rows = medications(table_row("[START ON 12/31/2026] " + PN))
    source = diet(PN + " at 30 mL/hr starting at 01/01 2100")
    assert medication_rows_for_display(rows, diet=source) == []
    assert dietary_rows_for_display(source, rows) == source["parenteral"]
    assert order_timestamp({"name": "[START ON 02/30/2026] " + PN}) is None


def test_unrelated_scheduled_medication_does_not_supply_the_nutrition_year():
    rows = medications(table_row("[START ON 06/01/2099] filgrastim injection", "10 mcg"))
    source = diet(PN + " at 30 mL/hr starting at 01/01 2100", PN + " at 25 mL/hr starting at 12/31 2100")
    sheet = new_sheet("P4102")
    sheet.update(medications=rows, diet=source, admission_date="12/30/2026")
    selected = dietary_rows_for_display(source, rows, sheet)
    assert selected == source["parenteral"][:1]


def test_non_pn_orders_and_multiple_scheduled_steps_are_unchanged():
    rows = medications(table_row("[START ON 11/20/2026] methylprednisolone injection 10 mg", "10 mg"),
                       table_row("[START ON 11/21/2026] methylprednisolone injection 5 mg", "5 mg"))
    assert medication_rows_for_display(rows) == rows


def test_full_exports_show_latest_pair_once_and_preserve_editor_rows():
    sheet = new_sheet("P4102")
    sheet["medications"] = pending_pair()
    sheet["diet"] = diet(PN + " at 30 mL/hr starting at 11/20 2100", PN + " at 25 mL/hr starting at 11/19 2100")
    before = deepcopy(sheet)
    validate_sheet(sheet)
    pdf = fitz.open(stream=handoff_pdf(sheet), filetype="pdf")
    batch = fitz.open(stream=handoffs_pdf([sheet]), filetype="pdf")
    outputs = [handoff_text(sheet), handoff_html(sheet),
               "\n".join(page.get_text() for page in pdf), "\n".join(page.get_text() for page in batch)]
    for output in outputs:
        assert output.count(PN) == 1 and output.count("SMOFlipid") == 1
        assert "720 mL" in output and "3 g/kg" in output
        assert "600 mL" not in output and "2 g/kg" not in output
        assert "25 mL/hr" not in output and "1.75 mL/hr" not in output
    assert sheet == before and len(sheet["medications"]) == 4


def test_full_export_uses_only_a_dated_newer_diet_order():
    sheet = new_sheet("P4102")
    sheet["medications"] = medications(table_row("[START ON 11/19/2026] " + PN, "600 mL"))
    sheet["diet"] = diet("Pediatric 3-in-1 PN (Cyclic) at 30 mL/hr starting at 11/20 2100")
    output = handoff_text(sheet)
    assert "Pediatric 3-in-1 PN" in output and "30 mL/hr" in output
    assert "Pediatric 2-in-1 PN" not in output and "600 mL" not in output
