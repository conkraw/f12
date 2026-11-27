"""Latest measured endocrine results in the lower Other labs display."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from lab_windows import (
    display_clock,
    laboratory_data,
    rows_for,
    window_help,
)
from labs import (
    canonical,
    display_component,
    is_numeric_endocrine,
    labs_text,
    panel_for,
    parse_labs,
    result_cards,
)
from models import fields_with_medications, new_sheet, new_vault, save_sheet_in
from security import generate_key, open_vault, seal_vault


NOW = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)
ALIASES = (
    ("TSH", "TSH", "TSH"),
    ("Thyroid stimulating hormone", "TSH", "TSH"),
    ("Thyroid-stimulating hormone", "TSH", "TSH"),
    ("FREET4", "FREET4", "Free T4"),
    ("FREE T4", "FREET4", "Free T4"),
    ("T4 FREE", "FREET4", "Free T4"),
    ("T4, FREE", "FREET4", "Free T4"),
    ("T4FREE", "FREET4", "Free T4"),
    ("FT4", "FREET4", "Free T4"),
    ("CORT", "CORTISOL", "Cortisol"),
    ("CORTISOL", "CORTISOL", "Cortisol"),
)


def parsed(source):
    result = parse_labs("Lab Results\nComponent\tValue\tDate\n" + source)
    assert not result.error, result.error
    return result.data


def handoff(source):
    sheet = new_sheet("P4102")
    sheet["labs"] = parsed(source)
    return sheet


def output(sheet, now=NOW):
    return labs_text(laboratory_data(sheet, now), include_id_panels=False)


@pytest.mark.parametrize("source,identity,label", ALIASES)
def test_supported_names_share_only_the_requested_identity(source, identity, label):
    assert canonical(source) == identity
    assert canonical("  " + source.lower().replace(" ", "  ") + "  ") == identity
    assert display_component(source) == label
    assert panel_for(source, "Hepatic") == "Other labs"


@pytest.mark.parametrize("source", [
    "T4", "TOTAL T4", "T4 TOTAL", "TT4", "ACTH", "CORTICOTROPIN",
    "TSH RECEPTOR ANTIBODY", "Free T4 index", "CORTISOL BINDING GLOBULIN",
])
def test_different_assays_are_not_normalized_as_requested_endocrine_tests(source):
    data = parsed(source + " 4.2 11/19/2026")
    assert data["rows"][0]["component"] == source
    assert canonical(source) not in {"TSH", "FREET4", "CORTISOL"}
    assert display_component(source) == source
    assert source + ": 4.2" in labs_text(data)


def test_example_values_flags_and_old_source_dates_remain_exact():
    sheet = handoff("TSH\t10.55\t11/19/2026\nFREET4\t2.10\t11/18/2026\nCORTISOL\t60.8 (H)\t10/21/2026")
    before = deepcopy(sheet)
    assert output(sheet) == (
        "Other labs\nTSH: 10.55 [11/19/2026]\nFree T4: 2.10 [11/18/2026]\n"
        "Cortisol: 60.8 (H) [10/21/2026]"
    )
    assert sheet == before


def test_prior_year_levels_are_not_limited_by_24_hours_or_current_admission():
    sheet = handoff("TSH\t1.74\t04/18/2025\nFREET4\t1.20\t04/18/2025\nCORT\t60.8 (H)\t10/21/2026")
    sheet["admission_date"] = "11/20/2026"
    with display_clock(NOW):
        fields = fields_with_medications(sheet)
    bottom = fields["Lab Results / Trends"]
    assert "TSH: 1.74 [04/18/2025]" in bottom
    assert "Free T4: 1.20 [04/18/2025]" in bottom
    assert "Cortisol: 60.8 (H) [10/21/2026]" in bottom
    for key, text in fields.items():
        if key != "Lab Results / Trends":
            assert "TSH:" not in text and "Free T4:" not in text and "Cortisol:" not in text


def test_latest_date_wins_across_aliases_regardless_of_paste_order():
    sheet = handoff("""TSH\t1.74\t04/18/2025
FT4\t1.20\t04/18/2025
CORTISOL\t32.4\t10/01/2026
Thyroid stimulating hormone\t10.55\t11/19/2026
FREE T4\t2.10\t11/18/2026
CORT\t60.8 (H)\t10/21/2026
T4 FREE\t1.80\t09/11/2026""")
    text = output(sheet)
    for expected in ("TSH: 10.55 [11/19/2026]", "Free T4: 2.10 [11/18/2026]", "Cortisol: 60.8 (H) [10/21/2026]"):
        assert text.count(expected) == 1
    for old in ("1.74", "1.20", "32.4", "1.80"):
        assert old not in text
    assert len(sheet["labs"]["rows"]) == 7


def test_time_order_is_used_across_aliases_when_all_same_day_actual_rows_have_times():
    sheet = handoff("FT4\t1.10\t11/19/2026 0800\nFREE T4\t1.80\t11/19/2026 14:30\nFREET4\t1.30\t11/19/2026 11:00")
    assert output(sheet) == "Other labs\nFree T4: 1.80 [11/19/2026 14:30]"


def test_date_only_same_day_rows_keep_epic_source_order_without_invented_times():
    sheet = handoff("CORT\t60.8 (H)\t11/19/2026\nCORTISOL\t52.1\t11/19/2026 18:00")
    assert output(sheet) == "Other labs\nCortisol: 60.8 (H) [11/19/2026]"


def test_equal_timestamps_keep_source_order_without_combining_values():
    sheet = handoff("FREE T4\t1.20\t11/19/2026 0800\nFT4\t1.30\t11/19/2026 0800")
    assert output(sheet) == "Other labs\nFree T4: 1.20 [11/19/2026 0800]"


@pytest.mark.parametrize("status", [
    "Pending", "Canceled", "Cancelled", "Hemolyzed", "Haemolysed", "Rejected",
    "Invalid", "UNK", "Unknown", "No result", "Insufficient sample", "See comment", "--",
    "2.1 pending", "2.1 canceled", "2.1 invalid",
])
def test_newer_unusable_result_does_not_hide_the_last_actual_level(status):
    sheet = handoff("TSH\t" + status + "\t11/20/2026\nThyroid stimulating hormone\t1.74\t04/18/2025")
    before = deepcopy(sheet)
    assert output(sheet) == "Other labs\nTSH: 1.74 [04/18/2025]"
    assert labs_text(sheet["labs"]) == "Other labs\nTSH: 1.74 [04/18/2025]"
    assert sheet == before


@pytest.mark.parametrize("status", ["Pending", "Canceled", "Unknown", "Insufficient sample", "--"])
def test_only_unusable_results_do_not_invent_a_level(status):
    sheet = handoff("FREET4\t" + status + "\t11/19/2026")
    assert output(sheet) == ""
    assert result_cards(sheet["labs"]) == []
    assert sheet["labs"]["rows"][0]["value"] == status


def test_pending_date_only_record_does_not_disrupt_order_of_timed_actual_rows():
    sheet = handoff("FT4\tPending\t11/19/2026\nFREET4\t1.1\t11/19/2026 0800\nT4 FREE\t1.8\t11/19/2026 1400")
    assert output(sheet) == "Other labs\nFree T4: 1.8 [11/19/2026 1400]"
    assert labs_text(sheet["labs"]) == "Other labs\nFree T4: 1.8 [11/19/2026 1400]"


@pytest.mark.parametrize("source,identity,label", ALIASES)
def test_space_separated_known_status_rows_are_retained_without_loosening_assay_names(source, identity, label):
    data = parsed(source + " Pending 11/20/2026\n" + source + " 1.20 11/19/2026")
    assert len(data["rows"]) == 2
    assert canonical(data["rows"][0]["component"]) == identity
    assert data["rows"][0]["value"] == "Pending"
    assert labs_text(data) == "Other labs\n" + label + ": 1.20 [11/19/2026]"


@pytest.mark.parametrize("value", [
    "10.55", "60.8 (H)", "0.00", "<0.010 (L)", ">60.8 (H)",
    "1.20 ng/dL", "1.20 ng/dL (H)", "1.20 (H) ng/dL", "60.8 µg/dL (H)",
    "1.74 mIU/L", "1.74 (L) mIU/L", "2.10*",
])
def test_numeric_values_flags_and_supplied_units_are_preserved_without_calculation(value):
    sheet = handoff("FREET4\t" + value + "\t11/19/2026")
    assert is_numeric_endocrine(value)
    assert output(sheet) == "Other labs\nFree T4: " + value + " [11/19/2026]"
    assert rows_for(sheet, "FREET4", NOW)[0]["value"] == value


def test_excluded_latest_row_falls_back_to_prior_included_alias_and_all_excluded_is_blank():
    sheet = handoff("CORT\t60.8 (H)\t11/19/2026\nCORTISOL\t32.4\t10/01/2026")
    sheet["labs"]["rows"][0]["include"] = False
    assert output(sheet) == "Other labs\nCortisol: 32.4 [10/01/2026]"
    sheet["labs"]["rows"][1]["include"] = False
    assert output(sheet) == "" and labs_text(sheet["labs"]) == ""


@pytest.mark.parametrize("date", ["11/21/2026", "11/20/2026 14:00"])
def test_future_result_does_not_replace_an_actual_past_result(date):
    sheet = handoff("TSH\t9.9\t" + date + "\nTSH\t1.74\t04/18/2025")
    assert output(sheet) == "Other labs\nTSH: 1.74 [04/18/2025]"
    assert len(sheet["labs"]["rows"]) == 2


def test_same_day_date_only_result_is_kept_without_guessing_collection_time():
    sheet = handoff("TSH\t10.55\t11/20/2026")
    assert output(sheet) == "Other labs\nTSH: 10.55 [11/20/2026]"


def test_failed_lab_import_does_not_represent_retained_endocrine_data_as_current():
    sheet = handoff("TSH\t1.74\t04/18/2025\nFREET4\t1.20\t04/18/2025")
    sheet["import_warnings"]["g"] = [{"action": "not_updated", "code": "section_parse_failed"}]
    before = deepcopy(sheet)
    assert output(sheet) == ""
    assert sheet == before


@pytest.mark.parametrize("panel", ["Hepatic", "Inflammatory", "Thyroid panel", "Endocrine"])
def test_legacy_source_panel_is_rerouted_only_for_display(panel):
    sheet = handoff("TSH\t1.74\t04/18/2025\nFT4\t1.20\t04/18/2025")
    for row in sheet["labs"]["rows"]:
        row["panel"] = panel
    before = deepcopy(sheet)
    cards = result_cards(sheet["labs"])
    assert len(cards) == 1 and cards[0]["title"] == "Other labs | latest"
    assert output(sheet).startswith("Other labs\n")
    assert sheet == before


def test_existing_saved_labs_show_normalized_latest_results_without_reimport():
    sheet = handoff("FT4\t1.20\t04/18/2025\nFREE T4\t2.10\t11/18/2026\nCORT\t60.8 (H)\t10/21/2026")
    for row in sheet["labs"]["rows"]:
        row["panel"] = "Historical custom panel"
    vault = save_sheet_in(new_vault(), sheet)
    before = deepcopy(vault)
    key = generate_key()
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == before
    text = output(restored["rooms"]["P4102"])
    assert text.count("Free T4:") == text.count("Cortisol:") == 1
    assert "Free T4: 2.10 [11/18/2026]" in text
    assert "Cortisol: 60.8 (H) [10/21/2026]" in text
    assert restored == before


def test_other_analytes_keep_existing_values_panels_and_status_behavior():
    sheet = handoff("""Hepatic:
AST\t21\t11/19/2026
Other labs:
TOTAL T4\t8.2\t11/19/2026
ACTH\tPending\t11/20/2026
ACTH\t20.1\t11/19/2026
TSH\t1.74\t04/18/2025""")
    before = deepcopy(sheet)
    text = output(sheet)
    assert "Hepatic\nAST: 21 [11/19/2026]" in text
    assert "TOTAL T4: 8.2 [11/19/2026]" in text
    assert "ACTH: Pending [11/20/2026]" in text
    assert "ACTH: 20.1" not in text
    assert "TSH: 1.74 [04/18/2025]" in text
    assert sheet == before


def test_window_help_explains_latest_actual_without_new_warning_flow():
    text = window_help(new_sheet("P4102"), NOW)
    assert "TSH, free T4 and cortisol: latest included actual level from all supplied dates in Other labs." in text
    assert "Pending or unusable endocrine entries do not replace a prior measured level." in text
