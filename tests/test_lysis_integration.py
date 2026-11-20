"""Synthetic G imports, Heme-only lysis output and export/cache integration."""
from copy import deepcopy
from datetime import datetime, timedelta
from html import unescape
from io import BytesIO
import re
from zoneinfo import ZoneInfo

import fitz
import pytest
from pypdf import PdfReader

from clinical_style import clinical_markup
from exports import (handoff_html, handoff_pdf, handoff_text, handoffs_html,
                     handoffs_pdf, pdf_content_signature)
from importing import import_replacement, import_sections
from lab_windows import display_clock, laboratory_data
from labs import result_cards
from models import fields_with_medications, new_vault, save_sheet_in, validate_sheet
from pdf_cache import SessionPdfCache


NOW = datetime(2026, 11, 20, 8, 0, tzinfo=ZoneInfo("America/New_York"))
RECENT_ROWS = ("HGBFREE\t15.4\t11/20/2026 01:00\n"
               "HGBFREE\t<6\t11/20/2026 07:00\n"
               "HGBFREE\t9.2\t11/20/2026 05:00\n"
               "LDH\t410 (H)\t11/20/2026 02:00\n"
               "LDH\t320 (H)\t11/20/2026 07:30\n"
               "LDH\t345 (H)\t11/20/2026 06:00\n"
               "URICACID\t2.7\t11/20/2026 06:30")


def block(letter, body):
    divider = letter * 16
    return divider + "\n" + body + "\n" + divider


def source(rows):
    return (block("a", "Diagnoses:\n1. Synthetic lysis layout example") + "\n" +
            block("g", "LABS:\nLab Results\nComponent\tValue\tDate\n" + rows))


def example(rows=RECENT_ROWS, room="P4102"):
    result = import_replacement(room, source(rows), new_vault()["settings"])
    assert not result.errors, result.errors
    assert result.sheet is not None
    result.sheet["fields"]["Hematology"] = "Heme note."
    validate_sheet(result.sheet)
    return result.sheet


def fields(sheet, now=NOW):
    with display_clock(now):
        return fields_with_medications(sheet)


def plain(value):
    if re.search(r"<(?:!doctype|html)\b", value, re.I):
        value = re.sub(r"<style.*?</style>|<script.*?</script>", "", value,
                       flags=re.S | re.I)
        value = unescape(re.sub(r"<[^>]+>", "", value))
    return re.sub(r"\s+", " ", value)


def pdf_text(data):
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)


def test_g_import_selects_latest_two_in_order_on_separate_heme_lines():
    sheet = example(RECENT_ROWS + "\nNA\t142\t11/20/2026 07:00\n"
                    "LACTATE\t2.1\t11/20/2026 07:00")
    before = deepcopy(sheet)
    output = fields(sheet)
    heme = output["Hematology"]
    assert "Lysis Labs:\nHGBFREE: 9.2 -> <6 [11/20/2026]\n" in heme
    assert "\nLDH: 345 (H) -> 320 (H) [11/20/2026]\n" in heme
    assert "\nUric acid: 2.7 [11/20/2026]" in heme
    assert "15.4" not in heme and "410" not in heme
    assert heme.index("Lysis Labs:") < heme.index("Heme note.")
    assert "Lactate: 2.1" in output["Cardiovascular"]
    assert "Lactate:" not in heme
    assert "NA: 142" in output["Lab Results / Trends"]
    for section, text in output.items():
        if section != "Hematology":
            assert all(label not in text for label in ("Lysis Labs:", "HGBFREE:", "LDH:", "Uric acid:"))
    assert sheet == before


def test_single_available_analyte_has_one_value_and_no_empty_labels():
    sheet = example("HGBFREE\t<5\t11/20/2026")
    output = fields(sheet)["Hematology"]
    assert "Lysis Labs:\nHGBFREE: <5 [11/20/2026]" in output
    assert " -> " not in output
    assert "LDH:" not in output and "Uric acid:" not in output
    assert "mg" not in output and "g/L" not in output


@pytest.mark.parametrize("rows", [
    "NA\t142\t11/20/2026 07:00",
    "HGBFREE\t18.2\t11/18/2026\nLDH\t410\t11/18/2026\nURICACID\t4.2\t11/18/2026",
    "HGBFREE\tPending\t11/20/2026 07:00\nLDH\t410\t11/20/2026 09:00",
])
def test_missing_or_unusable_values_leave_no_heading_or_lower_duplicates(rows):
    sheet = example(rows)
    output = fields(sheet)
    all_fields = "\n".join(output.values())
    assert "Lysis Labs:" not in all_fields
    assert "HGBFREE:" not in all_fields and "LDH:" not in all_fields
    assert "Uric acid:" not in all_fields
    assert "Lysis Labs:" not in handoff_text(sheet, printed_at=NOW)
    assert "Lysis Labs:" not in handoff_html(sheet, printed_at=NOW)


def test_prior_day_date_only_uses_the_existing_lactate_overlap_window():
    sheet = example("HGBFREE\t<5\t11/19/2026\n"
                    "HGBFREE\t21.4\t11/18/2026\n"
                    "LACTATE\t1.6\t11/19/2026")
    before = deepcopy(sheet)
    output = fields(sheet)
    assert "HGBFREE: <5 [11/19/2026]" in output["Hematology"]
    assert "Lactate: 1.6 [11/19/2026]" in output["Cardiovascular"]
    assert "21.4" not in "\n".join(output.values())
    assert "00:00" not in output["Hematology"]
    assert sheet == before


def test_lysis_aliases_are_consumed_by_lower_lab_routes_without_mutating_rows():
    sheet = example("HGBFREE\t<5\t11/20/2026 07:00\n"
                    "LDH\t325\t11/20/2026 06:00\n"
                    "Uric acid\t2.7\t11/20/2026 06:30\n"
                    "NA\t142\t11/20/2026 07:00")
    before = deepcopy(sheet)
    with display_clock(NOW):
        lower = laboratory_data(sheet)
        cards = result_cards(sheet["labs"], include_id_panels=False)
    assert [row["component"] for row in lower["rows"]] == ["NA"]
    displayed_components = {key for card in cards for key in card["rows"]}
    assert displayed_components == {"NA"}
    assert "Uric acid: 2.7" in fields(sheet)["Hematology"]
    assert sheet == before


@pytest.mark.parametrize("renderer", [
    lambda s: handoff_text(s, printed_at=NOW),
    lambda s: handoff_html(s, printed_at=NOW),
    lambda s: handoffs_html([s], printed_at=NOW),
    lambda s: pdf_text(handoff_pdf(s, printed_at=NOW)),
    lambda s: pdf_text(handoffs_pdf([s], printed_at=NOW)),
], ids=["text", "html", "batch_html", "pdf", "batch_pdf"])
def test_all_exports_keep_one_lysis_block_and_preserve_values_flags_dates(renderer):
    sheet = example()
    before = deepcopy(sheet)
    output = plain(renderer(sheet))
    assert output.count("Lysis Labs:") == 1
    for label in ("HGBFREE:", "LDH:", "Uric acid:"):
        assert output.count(label) == 1
    assert "HGBFREE: 9.2 -> <6 [11/20/2026]" in output
    assert "LDH: 345 (H) -> 320 (H) [11/20/2026]" in output
    assert "Uric acid: 2.7 [11/20/2026]" in output
    assert "15.4" not in output and "410 (H)" not in output
    assert sheet == before


def test_heading_and_labels_are_bold_and_print_in_heme_before_notes():
    sheet = example()
    html = handoff_html(sheet, printed_at=NOW)
    for label in ("Lysis Labs:", "HGBFREE:", "LDH:", "Uric acid:"):
        assert "<b>" + label + "</b>" in clinical_markup(label)
        assert "<b>" + label + "</b>" in html
    doc = fitz.open(stream=handoff_pdf(sheet, printed_at=NOW), filetype="pdf")
    assert len(doc) == 1
    page = doc[0]
    heme = page.search_for("HEME")[0]
    id_header = page.search_for("ID")[0]
    notes = page.search_for("Heme note.")[0]
    positions = [page.search_for(label)[0] for label in ("Lysis Labs:", "HGBFREE:", "LDH:", "Uric acid:")]
    assert notes.x0 < heme.x0 < id_header.x0
    assert all(abs(position.x0 - notes.x0) < 1 for position in positions)
    assert positions[0].y0 < positions[1].y0 < positions[2].y0 < positions[3].y0 < notes.y0
    spans = [span for item in page.get_text("dict")["blocks"] if "lines" in item
             for line in item["lines"] for span in line["spans"]]
    heading = [span for span in spans if "Lysis Labs:" in span["text"]]
    assert len(heading) == 1 and "Bold" in heading[0]["font"]
    assert heading[0]["size"] <= 8
    assert all(0 <= span["bbox"][0] < span["bbox"][2] <= 792 for span in spans)
    assert all(0 <= span["bbox"][1] < span["bbox"][3] <= 612 for span in spans)


def test_aging_uses_current_clock_and_invalidates_cached_pdf_without_changing_rows():
    sheet = example("HGBFREE\t7.3\t11/19/2026 08:00")
    before = deepcopy(sheet)
    expired = NOW + timedelta(seconds=1)
    assert "HGBFREE: 7.3" in fields(sheet, NOW)["Hematology"]
    assert "Lysis Labs:" not in "\n".join(fields(sheet, expired).values())
    assert pdf_content_signature(sheet, printed_at=NOW) != pdf_content_signature(sheet, printed_at=expired)
    cache = SessionPdfCache()
    try:
        first = cache.prepare(sheet, NOW)
        second = cache.prepare(sheet, expired)
        assert first.signature != second.signature
        assert cache.stats["builds"] == 2
    finally:
        cache.close()
    assert sheet == before


def test_failed_g_import_suppresses_lysis_output_but_retains_source_rows():
    original = example()
    result = import_sections(original, block("g", "LABS:\nunreadable row"), new_vault()["settings"])
    assert result.errors and result.sheet is not None
    assert "g" in result.sheet["import_warnings"]
    assert "Lysis Labs:" not in "\n".join(fields(result.sheet).values())
    assert "HGBFREE:" not in handoff_text(result.sheet, printed_at=NOW)
    assert result.sheet["labs"]["rows"] == original["labs"]["rows"]


def test_room_replacement_without_g_clears_lysis_only_for_the_replaced_room():
    first = example()
    other = example("LDH\t284\t11/20/2026 07:00", room="P4104")
    vault = save_sheet_in(save_sheet_in(new_vault(), first), other)
    stored_other = deepcopy(vault["rooms"]["P4104"])
    fresh = import_replacement("P4102", block("a", "Diagnoses:\n1. NEW_SYNTHETIC_PATIENT"),
                               vault["settings"])
    assert fresh.sheet is not None and fresh.sheet["id"] != first["id"]
    vault = save_sheet_in(vault, fresh.sheet)
    assert not vault["rooms"]["P4102"]["labs"]["rows"]
    assert "Lysis Labs:" not in "\n".join(fields(vault["rooms"]["P4102"]).values())
    assert vault["rooms"]["P4104"] == stored_other
    assert "LDH: 284" in fields(other)["Hematology"]


def test_batch_exports_keep_room_results_separate():
    first = example()
    second = example("HGBFREE\t<4\t11/20/2026 07:00\nLDH\t284\t11/20/2026 06:00", room="P4104")
    pages = PdfReader(BytesIO(handoffs_pdf([first, second], printed_at=NOW))).pages
    assert len(pages) == 2
    first_text, second_text = [plain(page.extract_text()) for page in pages]
    assert "HGBFREE: 9.2 -> <6" in first_text and "LDH: 345 (H) -> 320 (H)" in first_text
    assert "HGBFREE: <4" not in first_text and "LDH: 284" not in first_text
    assert "HGBFREE: <4" in second_text and "LDH: 284" in second_text
    assert "9.2" not in second_text and "345" not in second_text
    assert plain(handoffs_html([first, second], printed_at=NOW)).count("Lysis Labs:") == 2
