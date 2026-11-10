"""Synthetic screening results retain polarity, dates, and archive identity."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from exports import handoff_html, handoff_text
from importing import import_sections
from lab_windows import display_clock
from labs import parse_labs, result_cards
from models import fields_with_medications, new_sheet, new_vault, validate_sheet
from mrsa import mrsa_screen_text


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=ZoneInfo("America/New_York"))


def imported(source: str, sheet: dict | None = None) -> dict:
    text = "g" * 12 + "\nLABS:\n" + source + "\n" + "g" * 12
    out = import_sections(sheet or new_sheet("P4102"), text, new_vault()["settings"])
    assert not out.errors, out.errors
    return out.sheet


@pytest.mark.parametrize("value", ["Negative", "Not detected", "Positive", "Detected", "Pending", "Positive (A)"])
@pytest.mark.parametrize("separator", ["\t", " "])
def test_exact_text_polarity_is_preserved(value, separator):
    sheet = imported(separator.join(("MRSADNA", value, "11/10/2026 08:30")))
    assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: " + value + " [11/10/2026 08:30]"


def test_exact_code_is_case_insensitive_and_allows_label_colon():
    sheet = imported("mrsadna:Not detected 11/10/2026")
    assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: Not detected [11/10/2026]"


def test_newest_negative_or_pending_does_not_reuse_older_positive():
    for value in ("Not detected", "Pending"):
        sheet = imported("MRSADNA\tPositive\t11/09/2026 10:00\n"
                         "MRSADNA\t" + value + "\t11/10/2026 09:00\n"
                         "MRSADNA\tPositive\t11/10/2026 08:00")
        assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: " + value + " [11/10/2026 09:00]"


def test_date_only_ties_follow_existing_epic_order_without_inventing_a_time():
    sheet = imported("MRSADNA\tNegative\t11/10/2026\nMRSADNA\tPositive\t11/10/2026")
    assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: Negative [11/10/2026]"


def test_screen_appears_once_in_demographics_with_original_date_and_not_lab_card():
    sheet = imported("MRSADNA\tNot detected\t11/10/2026\nNA\t140\t11/10/2026")
    sheet["fields"]["Demographics / Weight"] = "Manual demographic note"
    with display_clock(NOW):
        fields = fields_with_medications(sheet)
    assert fields["Demographics / Weight"] == "Manual demographic note\nMRSA Screen: Not detected [11/10/2026]"
    assert "MRSADNA" not in repr(result_cards(sheet["labs"]))
    text = handoff_text(sheet, printed_at=NOW)
    assert text.count("MRSA Screen:") == 1
    assert "Not detected [11/10/2026]" in text


def test_included_results_only_and_no_unprovided_negative():
    assert mrsa_screen_text(new_sheet("P4102"), NOW) == ""
    sheet = imported("MRSADNA\tNegative\t11/10/2026")
    sheet["labs"]["rows"][0]["include"] = False
    assert mrsa_screen_text(sheet, NOW) == ""
    other = imported("MRSA_OTHER\tPositive\t11/10/2026")
    assert mrsa_screen_text(other, NOW) == ""


def test_future_result_not_displayed_before_collection():
    sheet = imported("MRSADNA\tPositive\t11/10/2026 14:00\n"
                     "MRSADNA\tNegative\t11/09/2026")
    assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: Negative [11/09/2026]"


def test_failed_lab_import_does_not_present_retained_mrsa_as_refreshed():
    sheet = imported("MRSADNA\tNegative\t11/09/2026")
    text = "g" * 12 + "\nLABS:\nMRSADNA missing-date\n" + "g" * 12
    out = import_sections(sheet, text, new_vault()["settings"])
    assert out.errors
    assert out.sheet["labs"] == sheet["labs"]
    assert mrsa_screen_text(out.sheet, NOW) == ""


def test_successful_reimport_clears_absent_screen_without_changing_manual_notes():
    sheet = imported("MRSADNA\tNegative\t11/09/2026")
    sheet["fields"]["Demographics / Weight"] = "Manual note"
    sheet = imported("NA\t140\t11/10/2026", sheet)
    assert mrsa_screen_text(sheet, NOW) == ""
    assert sheet["fields"]["Demographics / Weight"] == "Manual note"
    validate_sheet(deepcopy(sheet))
    assert set(sheet) == set(new_sheet("P4102"))


def test_mrsa_markup_escapes_result_and_bolds_only_label():
    sheet = imported("MRSADNA\tNot detected <review>\t11/10/2026")
    markup = handoff_html(sheet, printed_at=NOW)
    assert "<b>MRSA Screen:</b> Not detected &lt;review&gt; [11/10/2026]" in markup
    assert "<b>Not detected" not in markup


def test_unparseable_text_analyte_keeps_existing_recovery_behavior():
    result = parse_labs("UNRECOGNIZED Not detected 11/10/2026")
    assert result.error
