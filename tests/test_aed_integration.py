"""Synthetic G import, AED routing, export and clock-expiry integration checks."""
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
from security import generate_key, open_vault, seal_vault


EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 20, 8, 0, tzinfo=EASTERN)
RECENT_ROWS = ("PHENOBARB\t33.6\t11/20/2026 07:00\n"
               "PHENYTOIN\t1.9 (L)\t11/20/2026 06:30")
OLDER_ROWS = ("PHENOBARB\t33.6\t11/19/2026\n"
              "PHENYTOIN\t1.9 (L)\t11/19/2026")


def block(letter, body):
    divider = letter * 16
    return divider + "\n" + body + "\n" + divider


def source(rows):
    return (block("a", "Diagnoses:\n1. Synthetic training example") + "\n" +
            block("g", "LABS:\nLab Results\nComponent\tValue\tDate\n" + rows))


def example(rows=RECENT_ROWS, room="P4102"):
    result = import_replacement(room, source(rows), new_vault()["settings"])
    assert not result.errors, result.errors
    assert result.sheet is not None
    result.sheet["fields"]["Neurologic"] = "SYNTHETIC_NEURO_NOTES"
    validate_sheet(result.sheet)
    return result.sheet


def fields(sheet, now=NOW):
    with display_clock(now):
        return fields_with_medications(sheet)


def plain(value):
    value = re.sub(r"<style.*?</style>|<script.*?</script>", "", value,
                   flags=re.S | re.I)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", value)))


def pdf_text(data):
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)


def test_supplied_date_only_shape_falls_back_with_values_and_dates():
    sheet = example(OLDER_ROWS)
    before = deepcopy(sheet)
    output = fields(sheet)
    assert "AED Drug Levels:" not in output["Neurologic"]
    lower = output["Lab Results / Trends"]
    assert "AED Drug Levels" in lower
    assert "last checked" in lower.casefold()
    assert "Phenobarbital: 33.6" in lower
    assert "Phenytoin: 1.9 (L)" in lower
    assert "11/19/2026" in lower
    assert "mcg" not in lower and "µg" not in lower
    assert sheet == before


def test_timed_recent_import_moves_both_levels_to_neuro_before_notes():
    sheet = example()
    output = fields(sheet)
    neuro = output["Neurologic"]
    assert "AED Drug Levels:\nPhenobarbital: 33.6 [11/20/2026 07:00]" in neuro
    assert "Phenytoin: 1.9 (L) [11/20/2026 06:30]" in neuro
    assert neuro.index("AED Drug Levels:") < neuro.index("SYNTHETIC_NEURO_NOTES")
    assert "Phenobarbital" not in output["Lab Results / Trends"]
    assert "Phenytoin" not in output["Lab Results / Trends"]


def test_each_drug_routes_independently_without_showing_old_duplicates():
    sheet = example("PHENOBARB\t33.6\t11/20/2026 07:00\n"
                    "PHENOBARB\t41.2\t11/18/2026\n"
                    "PHENYTOIN\t1.9 (L)\t11/19/2026\n"
                    "PHENYTOIN\t7.4\t11/17/2026")
    output = fields(sheet)
    assert "Phenobarbital: 33.6" in output["Neurologic"]
    assert "Phenytoin" not in output["Neurologic"]
    assert "Phenytoin: 1.9 (L)" in output["Lab Results / Trends"]
    assert "Phenobarbital" not in output["Lab Results / Trends"]
    assert "41.2" not in "\n".join(output.values())
    assert "7.4" not in "\n".join(output.values())
    assert len(sheet["labs"]["rows"]) == 4


def test_recent_aliases_select_one_latest_value_and_keep_raw_source():
    sheet = example("PHENOBARB\t33.6\t11/20/2026 07:00\n"
                    "Phenobarbital\t35.8\t11/20/2026 07:30\n"
                    "PHENYTOIN\t1.9 (L)\t11/20/2026 06:30\n"
                    "Phenytoin, total\t2.8 (L)\t11/20/2026 07:00")
    before = deepcopy(sheet)
    output = fields(sheet)
    assert output["Neurologic"].count("Phenobarbital:") == 1
    assert output["Neurologic"].count("Phenytoin:") == 1
    assert "35.8" in output["Neurologic"] and "2.8 (L)" in output["Neurologic"]
    assert "33.6" not in output["Neurologic"] and "1.9" not in output["Neurologic"]
    assert sheet == before


@pytest.mark.parametrize("rows", [RECENT_ROWS, OLDER_ROWS])
@pytest.mark.parametrize("renderer", [
    lambda s: handoff_text(s, printed_at=NOW),
    lambda s: handoff_html(s, printed_at=NOW),
    lambda s: handoffs_html([s], printed_at=NOW),
    lambda s: pdf_text(handoff_pdf(s, printed_at=NOW)),
    lambda s: pdf_text(handoffs_pdf([s], printed_at=NOW)),
])
def test_all_export_formats_keep_one_level_with_source_value_flag_and_date(rows, renderer):
    sheet = example(rows)
    before = deepcopy(sheet)
    output = plain(renderer(sheet))
    assert output.count("Phenobarbital:") == 1
    assert output.count("Phenytoin:") == 1
    assert "Phenobarbital: 33.6" in output
    assert "Phenytoin: 1.9 (L)" in output
    if rows == OLDER_ROWS:
        assert "last checked" in output.casefold()
        assert re.search(r"11/19/(?:2026|26)", output)
    else:
        assert "AED Drug Levels:" in output
        assert "11/20/2026 07:00" in output
    assert sheet == before


def test_recent_heading_is_bold_in_neuro_html_and_pdf():
    sheet = example()
    assert clinical_markup("AED Drug Levels:\nPhenobarbital: 33.6").startswith("<b>AED Drug Levels:</b>")
    html = handoff_html(sheet, printed_at=NOW)
    assert "<b>AED Drug Levels:</b>" in html
    doc = fitz.open(stream=handoff_pdf(sheet, printed_at=NOW), filetype="pdf")
    spans = [span for page in doc for item in page.get_text("dict")["blocks"]
             if "lines" in item for line in item["lines"] for span in line["spans"]]
    headings = [span for span in spans if "AED Drug Levels:" in span["text"]]
    assert len(headings) == 1 and "Bold" in headings[0]["font"]
    assert headings[0]["size"] <= 8


def test_mixed_results_have_correct_printed_regions_without_overflow():
    sheet = example("PHENOBARB\t33.6\t11/20/2026 07:00\n"
                    "PHENYTOIN\t1.9 (L)\t11/18/2026 12:00")
    doc = fitz.open(stream=handoff_pdf(sheet, printed_at=NOW), filetype="pdf")
    assert len(doc) == 1
    page = doc[0]
    neuro = page.search_for("Phenobarbital:")[0]
    lower = page.search_for("Phenytoin:")[0]
    notes = page.search_for("SYNTHETIC_NEURO_NOTES")[0]
    assert neuro.y0 < notes.y0 < lower.y0
    spans = [span for block in page.get_text("dict")["blocks"]
             if "lines" in block for line in block["lines"] for span in line["spans"]]
    assert all(0 <= s["bbox"][0] < s["bbox"][2] <= 792 for s in spans)
    assert all(0 <= s["bbox"][1] < s["bbox"][3] <= 612 for s in spans)


def test_result_moves_to_labs_when_24h_passes_and_cache_is_rebuilt():
    sheet = example("PHENOBARB\t33.6\t11/19/2026 08:00")
    before = deepcopy(sheet)
    expired = NOW + timedelta(seconds=1)
    at_boundary = fields(sheet, NOW)
    after_boundary = fields(sheet, expired)
    assert "Phenobarbital: 33.6" in at_boundary["Neurologic"]
    assert "Phenobarbital" not in at_boundary["Lab Results / Trends"]
    assert "Phenobarbital" not in after_boundary["Neurologic"]
    assert "Phenobarbital: 33.6" in after_boundary["Lab Results / Trends"]
    assert pdf_content_signature(sheet, printed_at=NOW) != pdf_content_signature(sheet, printed_at=expired)
    cache = SessionPdfCache()
    first = cache.prepare(sheet, NOW)
    second = cache.prepare(sheet, expired)
    assert first.signature != second.signature
    assert cache.stats["builds"] == 2
    cache.close()
    assert sheet == before


def test_batch_exports_keep_rooms_and_drug_values_separate():
    first = example()
    second = example("PHENOBARB\t29.4\t11/18/2026\n"
                     "PHENYTOIN\t13.7\t11/18/2026", "P4104")
    doc = PdfReader(BytesIO(handoffs_pdf([first, second], printed_at=NOW)))
    assert len(doc.pages) == 2
    first_text, second_text = [plain(p.extract_text()) for p in doc.pages]
    assert "33.6" in first_text and "1.9 (L)" in first_text
    assert "29.4" not in first_text and "13.7" not in first_text
    assert "29.4" in second_text and "13.7" in second_text
    assert "33.6" not in second_text and "1.9 (L)" not in second_text
    html = plain(handoffs_html([first, second], printed_at=NOW))
    assert html.count("Phenobarbital:") == 2 and html.count("Phenytoin:") == 2


def test_latest_older_levels_form_one_lower_card_with_individual_dates():
    sheet = example("PHENOBARB\t33.6\t11/19/2026\n"
                    "PHENYTOIN\t1.9 (L)\t11/18/2026 12:00")
    with display_clock(NOW):
        cards = result_cards(laboratory_data(sheet), include_id_panels=False)
    aed = [card for card in cards if card["title"].startswith("AED Drug Levels")]
    assert len(aed) == 1
    assert len(aed[0]["rows"]) == 2
    assert {row["date"] for row in aed[0]["rows"].values()} == {"11/19/2026", "11/18/2026 12:00"}


def test_failed_g_import_does_not_make_retained_levels_current_or_print_them():
    original = example()
    result = import_sections(original, block("g", "LABS:\nunreadable row"), new_vault()["settings"])
    assert result.errors and result.sheet is not None
    assert "g" in result.sheet["import_warnings"]
    output = fields(result.sheet)
    assert "Phenobarbital" not in output["Neurologic"] + output["Lab Results / Trends"]
    assert "Phenytoin" not in output["Neurologic"] + output["Lab Results / Trends"]
    assert result.sheet["labs"]["rows"] == original["labs"]["rows"]


def test_new_complete_room_without_g_has_no_previous_aed_levels():
    old = example()
    fresh = import_replacement("P4102", block("a", "Diagnoses:\n1. NEW_SYNTHETIC_PATIENT"),
                               new_vault()["settings"])
    assert fresh.sheet is not None
    assert fresh.sheet["id"] != old["id"]
    assert not fresh.sheet["labs"]["rows"]
    assert "AED Drug Levels" not in "\n".join(fields(fresh.sheet).values())


def test_existing_laboratory_rows_round_trip_without_new_archive_fields():
    sheet = example(OLDER_ROWS)
    vault = save_sheet_in(new_vault(), sheet)
    before = deepcopy(vault)
    key = generate_key()
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == before
    assert fields(restored["rooms"]["P4102"]) == fields(sheet)

