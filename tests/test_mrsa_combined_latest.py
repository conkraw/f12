"""Both MRSA lab codes share one dated screen without changing saved results."""
from copy import deepcopy
from datetime import datetime
from io import BytesIO
import re
from zoneinfo import ZoneInfo

import fitz
from pypdf import PdfReader
import pytest

from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from importing import import_sections
from lab_windows import display_clock
from labs import result_cards
from models import fields_with_medications, new_sheet, new_vault, save_sheet_in
from mrsa import mrsa_screen_text
from security import generate_key, open_vault, seal_vault


NOW = datetime(2026, 11, 10, 12, tzinfo=ZoneInfo("America/New_York"))


def imported(source):
    text = "g" * 12 + "\nLABS:\n" + source + "\n" + "g" * 12
    result = import_sections(new_sheet("P4102"), text, new_vault()["settings"])
    assert not result.errors, result.errors
    return result.sheet


@pytest.mark.parametrize("source", [
    "MRSANPADM\tNot detected\t11/10/2026 08:30",
    "mrsanpadm\tNot detected\t11/10/2026 08:30",
    "MRSANPADM:\tNot detected\t11/10/2026 08:30",
    "mrsanpadm:\tNot detected\t11/10/2026 08:30",
    "MRSANPADM Not detected 11/10/2026 08:30",
    "mrsanpadm Not detected 11/10/2026 08:30",
    "MRSANPADM: Not detected 11/10/2026 08:30",
    "mrsanpadm:Not detected 11/10/2026 08:30",
])
def test_new_code_text_tab_colon_and_case_forms(source):
    sheet = imported(source)
    assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: Not detected [11/10/2026 08:30]"


@pytest.mark.parametrize("newest_code", ["MRSANPADM", "MRSADNA"])
@pytest.mark.parametrize("newest_value", ["Negative", "Not detected", "Pending"])
@pytest.mark.parametrize("newest_first", [True, False])
def test_either_newest_code_wins_by_collection_date_over_old_positive(newest_code, newest_value, newest_first):
    older_code = "MRSADNA" if newest_code == "MRSANPADM" else "MRSANPADM"
    old = older_code + "\tPositive\t11/09/2026 10:00"
    new = newest_code + "\t" + newest_value + "\t11/10/2026 09:00"
    source = "\n".join((new, old) if newest_first else (old, new))
    sheet = imported(source)
    assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: " + newest_value + " [11/10/2026 09:00]"


def test_same_day_complete_times_sort_across_codes_and_source_order():
    sheet = imported("MRSANPADM\tPositive\t11/10/2026 08:59\n"
                     "MRSADNA\tNot detected\t11/10/2026 09:01\n"
                     "MRSANPADM\tPending\t11/10/2026 0900")
    assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: Not detected [11/10/2026 09:01]"


@pytest.mark.parametrize("older,newer", [
    ("10/31/2026 23:59", "11/01/2026 00:01"),
    ("12/31/2025 23:59", "01/01/2026 00:01"),
    ("02/28/2024", "02/29/2024"),
    ("02/29/2024", "03/01/2024"),
])
def test_month_year_and_leap_day_boundaries_use_dates_not_text_sort(older, newer):
    sheet = imported("MRSANPADM\tPositive\t" + older + "\n"
                     "MRSADNA\tNegative\t" + newer)
    assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: Negative [" + newer + "]"


@pytest.mark.parametrize("first_code,first_date,second_code,second_date", [
    ("MRSANPADM", "11/10/2026", "MRSADNA", "11/10/2026"),
    ("MRSADNA", "11/10/2026", "MRSANPADM", "11/10/2026"),
    ("MRSANPADM", "11/10/2026", "MRSADNA", "11/10/2026 11:00"),
    ("MRSADNA", "11/10/2026 08:00", "MRSANPADM", "11/10/2026"),
])
def test_same_day_missing_times_preserve_source_order_across_codes(first_code, first_date, second_code, second_date):
    sheet = imported(first_code + "\tNegative\t" + first_date + "\n"
                     + second_code + "\tPositive\t" + second_date)
    assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: Negative [" + first_date + "]"


def test_future_and_excluded_results_do_not_replace_the_latest_eligible_screen():
    sheet = imported("MRSANPADM\tPositive\t11/11/2026\n"
                     "MRSANPADM\tPending\t11/10/2026 10:00\n"
                     "MRSADNA\tNegative\t11/10/2026 09:00")
    sheet["labs"]["rows"][1]["include"] = False
    assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: Negative [11/10/2026 09:00]"
    sheet["labs"]["rows"][2]["include"] = False
    assert mrsa_screen_text(sheet, NOW) == ""


def test_both_source_codes_and_rows_remain_unchanged_and_are_not_duplicated_in_lab_cards():
    sheet = imported("MRSANPADM\tPending\t11/10/2026\n"
                     "MRSADNA\tPositive\t11/09/2026\n"
                     "NA\t140\t11/10/2026")
    sheet["fields"]["Demographics / Weight"] = "Synthetic demographic note"
    before = deepcopy(sheet)
    with display_clock(NOW):
        fields = fields_with_medications(sheet)
    assert fields["Demographics / Weight"] == "Synthetic demographic note\nMRSA Screen: Pending [11/10/2026]"
    cards = repr(result_cards(sheet["labs"]))
    assert "MRSANPADM" not in cards and "MRSADNA" not in cards
    assert "NA" in cards and "140" in cards
    assert sheet == before
    assert [row["component"] for row in sheet["labs"]["rows"]] == ["MRSANPADM", "MRSADNA", "NA"]


def test_encrypted_reload_preserves_both_rows_and_selects_newest_without_repasting():
    sheet = imported("MRSADNA\tPositive\t11/08/2026\n"
                     "MRSANPADM\tNegative\t11/09/2026")
    vault = save_sheet_in(new_vault(), sheet)
    before = deepcopy(vault)
    key = generate_key()
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == before
    assert mrsa_screen_text(restored["rooms"]["P4102"], NOW) == "MRSA Screen: Negative [11/09/2026]"
    assert restored == before


def test_html_text_and_pdfs_show_one_latest_screen_with_bold_label_and_regular_result():
    sheet = imported("MRSADNA\tPositive\t11/09/2026\n"
                     "MRSANPADM\tNegative\t11/10/2026")
    before = deepcopy(sheet)
    markup = handoff_html(sheet, printed_at=NOW)
    assert markup.count("<b>MRSA Screen:</b>") == 1
    assert "<b>MRSA Screen:</b> Negative [11/10/2026]" in markup
    assert "<b>Negative" not in markup
    text = handoff_text(sheet, printed_at=NOW)
    assert text.count("MRSA Screen:") == 1
    assert "MRSA Screen: Negative [11/10/2026]" in text
    for data in (handoff_pdf(sheet, printed_at=NOW), handoffs_pdf([sheet], printed_at=NOW)):
        extracted = re.sub(r"\s+", " ", "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages))
        assert extracted.count("MRSA Screen:") == 1
        assert "MRSA Screen: Negative [11/10/2026]" in extracted
        assert "Positive" not in extracted
        with fitz.open(stream=data, filetype="pdf") as document:
            spans = [span for page in document for block in page.get_text("dict")["blocks"] if "lines" in block
                     for line in block["lines"] for span in line["spans"]]
        label = next(span for span in spans if "MRSA Screen:" in span["text"])
        result = next(span for span in spans if "Negative" in span["text"])
        assert "Bold" in label["font"]
        assert "Bold" not in result["font"]
    assert sheet == before


def test_newest_source_text_is_escaped_in_html_without_losing_wording():
    sheet = imported("MRSADNA\tPositive\t11/09/2026\n"
                     "MRSANPADM\tNot detected <review>\t11/10/2026")
    markup = handoff_html(sheet, printed_at=NOW)
    assert "<b>MRSA Screen:</b> Not detected &lt;review&gt; [11/10/2026]" in markup


def test_unrelated_similarly_named_assay_is_not_used_as_the_screen():
    sheet = imported("MRSANPADM_OTHER\tPositive\t11/10/2026\n"
                     "MRSADNA\tNegative\t11/09/2026")
    assert mrsa_screen_text(sheet, NOW) == "MRSA Screen: Negative [11/09/2026]"
