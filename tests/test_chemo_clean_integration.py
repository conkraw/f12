"""End-to-end synthetic grouping and display-only label-cleanup coverage."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
from html import unescape
from io import BytesIO
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from pypdf import PdfReader
import pytest

from categories import apply_category_rules, medication_blocks, placement, save_category, set_category_rule
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_html, handoffs_pdf
from fen_gi import effective_section
from importing import import_sections
from lab_windows import display_clock
from medication_groups import group_for
from medications import DESTINATIONS, format_medication, match_name, parse_medications
from models import fields_with_medications, new_sheet, new_vault, save_sheet_in
from security import generate_key, open_vault, seal_vault


ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 11, 11, 12, tzinfo=ZoneInfo("America/New_York"))
CHEMO_BRANDS = ("Elspar", "Oncaspar", "Asparlas", "Erwinaze", "Rylaze", "Adriamycin")
BRAND_COUNTS = {name: 1 for name in CHEMO_BRANDS} | {
    "Decadron": 1, "Benadryl": 3, "Maxipime": 2,
    "Zofran": 1, "Neupogen": 1, "Zyloprim": 1,
}


def synthetic_sheet(settings=None):
    source = (ROOT / "examples" / "synthetic_chemotherapy_clean_labels.txt").read_text()
    with display_clock(NOW):
        result = import_sections(new_sheet("P4102"), source, settings or new_vault()["settings"])
    assert not result.errors, result.errors
    result.sheet["fields"]["Goals / Follow-up"] = "Synthetic display test. These are example values, not a treatment regimen."
    return result.sheet


def _rendered_text(kind, sheet):
    if kind == "text":
        return handoff_text(sheet, printed_at=NOW)
    if kind in ("html", "all_html"):
        markup = handoff_html(sheet, printed_at=NOW) if kind == "html" else handoffs_html([sheet], printed_at=NOW)
        markup = re.sub(r"<(?:style|script)\b[^>]*>.*?</(?:style|script)>", "", markup, flags=re.I | re.S)
        return unescape(re.sub(r"<[^>]+>", "", markup))
    data = handoff_pdf(sheet, printed_at=NOW) if kind == "pdf" else handoffs_pdf([sheet], printed_at=NOW)
    return re.sub(r"\s+", " ", "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages))


def test_mixed_source_import_retains_each_order_dose_route_frequency_and_wrappers():
    sheet = synthetic_sheet()
    rows = sheet["medications"]
    assert len(rows) == 15 and len({row["id"] for row in rows}) == 15
    assert [(row["dose"], row["route"], row["frequency"]) for row in rows] == [
        ("100 Units", "Intramuscular", "Once"),
        ("100 Units", "Intravenous", "Once"),
        ("100 Units", "Intravenous", "Once"),
        ("100 Units", "Intramuscular", "Once"),
        ("100 Units", "Intramuscular", "Once"),
        ("1 mg", "Intravenous", "Once"),
        ("1 mg", "Intravenous", "q6h"),
        ("5 mg", "Intravenous", "q6h PRN"),
        ("5 mg", "Oral", "q6h PRN"),
        ("10 mg", "Intravenous", "Once"),
        ("50 mg", "Intravenous", "q8h"),
        ("25 mg", "Intravenous", "q12h"),
        ("1 mg", "Intravenous", "q8h PRN"),
        ("10 mcg", "Subcutaneous", "Daily"),
        ("10 mg", "Oral", "Daily"),
    ]
    assert rows[1]["name"].startswith("And: pegaspargase")
    assert rows[5]["name"].startswith("And: [Held by provider] [START ON 11/12/2026]")
    assert rows[8]["name"].startswith("Or: diphenhydrAMINE")
    assert rows[9]["name"].startswith("And: diphenhydrAMINE")
    assert rows[10]["name"].startswith("[START ON 11/12/2026]")
    assert rows[11]["name"].startswith("Followed by: [START ON 11/13/2026]")


def test_chemotherapy_defaults_and_supportive_medication_groups_stay_separate():
    sheet = synthetic_sheet()
    before = deepcopy(sheet)
    rows = sheet["medications"]
    assert [placement(row)["id"] for row in rows[:6]] == ["group:chemotherapy"] * 6
    assert all(effective_section(row) == "Hematology" for row in rows[:6])
    assert placement(rows[6])["id"] == "group:airway_cerebral_steroid"
    assert effective_section(rows[6]) == "Respiratory"
    assert all(group_for(row) != "chemotherapy" for row in rows[6:])
    with display_clock(NOW):
        fields = fields_with_medications(sheet)
    assert "Chemotherapy" in fields["Hematology"]
    assert all(name in fields["Hematology"] for name in CHEMO_BRANDS)
    assert all(name not in fields["Hematology"] for name in ("Decadron", "Benadryl", "Maxipime", "Zofran", "Zyloprim"))
    emitted = [item["id"] for section in DESTINATIONS
               for _, item in medication_blocks(section, "", rows, sheet)
               if isinstance(item, dict) and "id" in item]
    assert Counter(emitted) == Counter(row["id"] for row in rows)
    assert sheet == before


@pytest.mark.parametrize("kind", ["text", "html", "all_html", "pdf", "all_pdf"])
def test_all_export_paths_keep_every_order_and_clean_only_requested_labels(kind):
    sheet = synthetic_sheet()
    before = deepcopy(sheet)
    output = _rendered_text(kind, sheet)
    for brand, count in BRAND_COUNTS.items():
        assert output.count(brand) == count, (kind, brand, output.count(brand))
    assert "Chemotherapy" in output
    assert "And:" not in output and "Or:" not in output
    assert "START ON" not in output and "Alternative order:" not in output
    assert "Held by provider" in output and "Followed by:" in output
    assert "MRSA Screen:" in output and "Not detected" in output
    assert "Day 2" in output
    assert sheet == before


@pytest.mark.parametrize("kind", ["text", "html", "pdf", "all_pdf"])
def test_detached_alternative_still_prints_without_alternative_label(kind):
    sheet = synthetic_sheet()
    sheet["medications"][7]["include"] = False
    before = deepcopy(sheet)
    output = _rendered_text(kind, sheet)
    assert output.count("Benadryl") == 2
    assert "Alternative order:" not in output and "Or:" not in output
    assert sheet["medications"][8]["name"].startswith("Or:")
    assert sheet == before


def test_explicit_user_category_override_wins_without_changing_source_amounts():
    settings = save_category(new_vault()["settings"], "User-selected medicines", "Infectious Disease", ident="custom:qa-override")
    settings = set_category_rule(settings, "doxorubicin", "custom:qa-override")
    sheet = synthetic_sheet(settings)
    row = next(row for row in sheet["medications"] if match_name(row["name"]).startswith("doxorubicin"))
    original = deepcopy(row)
    assert placement(row)["id"] == "custom:qa-override"
    assert effective_section(row) == "Infectious Disease"
    with display_clock(NOW):
        fields = fields_with_medications(sheet)
    assert "Adriamycin" in fields["Infectious Disease"] and "Adriamycin" not in fields["Hematology"]
    assert "[Held by provider]" in format_medication(row)
    assert "START ON" not in format_medication(row)
    assert (row["dose"], row["route"], row["frequency"]) == ("1 mg", "Intravenous", "Once")
    assert row == original


def test_incidental_chemo_name_does_not_move_an_unrelated_order():
    parsed = parse_medications("saline carrier for asparaginase infusion\t10 mL\tIntravenous\tOnce\t\t\t")
    assert not parsed.error, parsed.error
    rows = apply_category_rules(parsed.rows, new_vault()["settings"])
    assert group_for(rows[0]) != "chemotherapy"
    assert placement(rows[0])["id"] != "group:chemotherapy"


def test_encrypted_reload_keeps_original_connectors_future_schedule_and_amounts():
    sheet = synthetic_sheet()
    vault = save_sheet_in(new_vault(), sheet)
    before = deepcopy(vault)
    key = generate_key()
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == before
    output = handoff_text(restored["rooms"]["P4102"], printed_at=NOW)
    assert "START ON" not in output and "Followed by:" in output
    assert "[START ON 11/12/2026]" in restored["rooms"]["P4102"]["medications"][10]["name"]
    assert restored == before
