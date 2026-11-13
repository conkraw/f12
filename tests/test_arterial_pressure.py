"""Synthetic arterial pressure import, recall, presentation and export checks."""
from copy import deepcopy
from datetime import datetime, timezone
import re

import fitz
import pytest

from arterial_pressure import parse_arterial_line, arterial_display_rows
from clinical_style import clinical_markup
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf, handoffs_html
from importing import import_sections
from models import new_sheet, new_vault, fields_with_medications, save_sheet_in, validate_sheet
from security import generate_key, seal_vault, open_vault
from vitals import parse_vitals, text_by_system

VITALS = """Heart Rate: [88-125] 102
BP: (88-116)/(42-70) 104/54
CVP (mean) Avg: 8 mmHg Min: 4 mmHg Max: 11 mmHg
Arterial Line BP Min: 80/40 Max: 112/65
Last Arterial BP: Arterial Line BP: 108/60
Arterial Line MAP (mmHg) Avg: 63 mmHg Min: 52 mmHg Max: 75 mmHg
Last Arterial MAP: Arterial Line MAP (mmHg): 72 mmHg"""
EXPECTED = (
    "Cuff: BP (88-116)/(42-70) 104/54\n"
    "ART BP: 80/40 to 112/65 [last 108/60]\n"
    "ART MAP: 52 to 75 mmHg [last 72]"
)


def block(text):
    return "eeeeeeee\nVITALS:\n" + text + "\neeeeeeee"


def sheet():
    result = import_sections(new_sheet("P4102"), block(VITALS), new_vault()["settings"])
    assert not result.errors and not result.skipped
    return result.sheet


@pytest.mark.parametrize("source,label,value", [
    ("Arterial Line BP Min: 80/40 Max: 112/65", "ART BP", "80/40 to 112/65"),
    ("Arterial Line BP: Min: 80 / 40 Max: 112 / 65", "ART BP", "80/40 to 112/65"),
    ("ART BP (mm Hg): Minimum: 80/40 Maximum: 112/65", "ART BP", "80/40 to 112/65 mmHg"),
    ("ABP Min: 80/40 mmHg Max: 112/65 mmHg", "ART BP", "80/40 to 112/65 mmHg"),
    ("arterial blood pressure Max: 112/65 Min: 80/40", "ART BP", "80/40 to 112/65"),
    ("Arterial Line MAP (mmHg) Avg: 63 mmHg Min: 52 mmHg Max: 75 mmHg", "ART MAP", "52 to 75 mmHg"),
    ("ART MAP (mmHg): Max: 75 Avg: N/A Min: 52", "ART MAP", "52 to 75 mmHg"),
    ("Arterial mean arterial pressure (kPa) Min: 7.2 Max: 10.5", "ART MAP", "7.2 to 10.5 kPa"),
    ("ART MAP Min: 0 Max: 120", "ART MAP", "0 to 120"),
    ("ART MAP (cm H₂O) Min: .5 Max: +10.0", "ART MAP", ".5 to +10.0 cmH2O"),
    ("ART BP: 80/40 to 112/65", "ART BP", "80/40 to 112/65"),
    ("ART MAP: 52 to 75 mmHg", "ART MAP", "52 to 75 mmHg"),
    ("Last Arterial BP: Arterial Line BP: 108/60", "Last ART BP", "108/60"),
    ("Last Arterial MAP: Arterial Line MAP (mmHg): 72 mmHg", "Last ART MAP", "72 mmHg"),
    ("Last ART MAP (mmHg): 72", "Last ART MAP", "72 mmHg"),
    ("Last ART BP: (!) 108 / 60", "Last ART BP", "(!) 108/60"),
    ("Arterial Line BP: (80-112)/(40-65) 108/60", "ART BP", "(80-112)/(40-65) 108/60"),
])
def test_supported_recorded_values(source, label, value):
    result = parse_vitals(source)
    assert not result.error and not result.issues
    assert result.rows == [{"label": label, "value": value, "section": "Cardiovascular", "include": True}]


@pytest.mark.parametrize("source", [
    "Arterial Line BP: No data recorded", "Arterial Line MAP (mmHg): N/A",
    "Last Arterial BP: Arterial Line BP:", "Last Arterial MAP: Arterial Line MAP (mmHg): --",
    "ART BP:", "ART MAP (mmHg)", "Arterial Line BP None",
])
def test_missing_arterial_readings_do_not_relabel_cuff(source):
    result = parse_vitals("BP: 104/54\n" + source)
    assert not result.error
    assert text_by_system(result.rows)["Cardiovascular"] == "BP: 104/54"


@pytest.mark.parametrize("source", [
    "ART MAP Min: 75 Max: 52", "ART BP Min: bad Max: 112/65",
    "ART BP Min: 80/40 mmHg Max: 112/65 kPa",
    "ART MAP (mmHg) Min: 52 kPa Max: 75 kPa",
    "ART MAP Min: 52 Min: 53 Max: 75",
    "ART BP Min: 80/40 Min: 81/40 Max: 112/65",
    "Last ART MAP (kPa): Arterial Line MAP (mmHg): 72",
    "ART BP (mmHg) (kPa): 108/60",
])
def test_ambiguous_import_retains_previous_vitals_and_marks_review(source):
    original = sheet()
    before = deepcopy(original)
    result = import_sections(original, block(source), new_vault()["settings"])
    assert result.errors and "e" in result.skipped
    assert result.sheet["vitals"] == before["vitals"]
    assert "e" in result.sheet["import_warnings"]
    assert original == before


@pytest.mark.parametrize("source", [
    "ART MAP Avg: 63 mmHg", "ART MAP Min: 52 mmHg", "ART BP Max: 112/65",
    "ART MAP Avg: 63 mmHg Min: -- Max: 75 mmHg",
])
def test_partial_summary_never_invents_a_range(source):
    result = parse_vitals(source)
    assert not result.error
    rendered = text_by_system(result.rows)["Cardiovascular"]
    assert " to " not in rendered
    assert rendered == re.sub(r"^(ART (?:BP|MAP)) ", r"\1: ", source)


@pytest.mark.parametrize("text", ["BP: 104/54", "MAP: 72", "CVP (mean): 8 mmHg", "Arterial Line 01/01/26 Left Radial"])
def test_non_arterial_measurement_labels_are_not_interpreted(text):
    assert parse_arterial_line(text) is None


def test_order_units_latest_and_source_are_preserved():
    s = sheet()
    before = deepcopy(s)
    result = text_by_system(s["vitals"])["Cardiovascular"]
    assert EXPECTED in result
    assert result.index("Cuff:") < result.index("ART BP:") < result.index("ART MAP:") < result.index("CVP")
    assert "Avg:" not in result
    assert s == before


def test_reversed_source_order_still_groups_cuff_bp_map():
    result = parse_vitals("\n".join(reversed(VITALS.splitlines())))
    assert not result.error
    assert EXPECTED in text_by_system(result.rows)["Cardiovascular"]


def test_saved_old_first_colon_rows_render_without_changing_archive():
    rows = [{"label": line.split(":", 1)[0].strip(), "value": line.split(":", 1)[1].strip(),
             "section": "Cardiovascular", "include": True}
            for line in VITALS.splitlines() if not line.startswith("CVP")]
    before = deepcopy(rows)
    assert EXPECTED in text_by_system(rows)["Cardiovascular"]
    assert rows == before


def test_inclusion_and_explicit_section_override_are_respected():
    result = parse_vitals(VITALS)
    for row in result.rows:
        if "ART " in row["label"]:
            row["include"] = False
    assert "Cuff:" not in text_by_system(result.rows)["Cardiovascular"]
    assert "ART " not in text_by_system(result.rows)["Cardiovascular"]
    row = {"label": "ART MAP", "value": "72 mmHg", "section": "Other", "include": True}
    assert text_by_system([row]) == {"Other": "ART MAP: 72 mmHg"}


def test_latest_only_and_missing_cuff():
    result = parse_vitals("Last Arterial BP: Arterial Line BP: 108/60\nLast Arterial MAP: 72 mmHg")
    assert text_by_system(result.rows)["Cardiovascular"] == "ART BP: Last: 108/60\nART MAP: Last: 72 mmHg"
    assert "Cuff" not in text_by_system(result.rows)["Cardiovascular"]


def test_missing_latest_leaves_only_recorded_ranges():
    result = parse_vitals("\n".join(l for l in VITALS.splitlines() if not l.startswith("Last ")))
    text = text_by_system(result.rows)["Cardiovascular"]
    assert "ART BP: 80/40 to 112/65" in text
    assert "ART MAP: 52 to 75 mmHg" in text
    assert "[last " not in text


def test_conflicting_latest_values_are_not_arbitrarily_selected():
    result = parse_vitals(VITALS + "\nLast ART BP: 110/62")
    text = text_by_system(result.rows)["Cardiovascular"]
    assert "ART BP: 80/40 to 112/65\nLast ART BP: 108/60\nLast ART BP: 110/62" in text
    assert "ART BP: 80/40 to 112/65 [last" not in text


def test_incompatible_latest_units_stay_explicit_and_separate():
    result = parse_vitals("ART MAP Min: 52 mmHg Max: 75 mmHg\nLast ART MAP: 9.6 kPa")
    assert text_by_system(result.rows)["Cardiovascular"] == "ART MAP: 52 to 75 mmHg\nLast ART MAP: 9.6 kPa"


def test_hidden_latest_is_not_shown_and_hidden_range_does_not_survive():
    result = parse_vitals(VITALS)
    for r in result.rows:
        if r["label"] == "Last ART MAP":
            r["include"] = False
    text = text_by_system(result.rows)["Cardiovascular"]
    assert "ART MAP: 52 to 75 mmHg" in text and "last 72" not in text
    for r in result.rows:
        if r["label"] == "ART BP":
            r["include"] = False
    assert "ART BP: Last: 108/60" in text_by_system(result.rows)["Cardiovascular"]


def test_render_is_idempotent_and_clinical_labels_bold():
    rows = parse_vitals(VITALS).rows
    display = arterial_display_rows(rows)
    assert arterial_display_rows(display) == display
    markup = clinical_markup(EXPECTED)
    assert all("<b>" + label + ":</b>" in markup for label in ("Cuff", "ART BP", "ART MAP"))


def test_reimport_clears_arterial_values_when_no_longer_supplied():
    result = import_sections(sheet(), block("BP: 106/58"), new_vault()["settings"])
    assert not result.errors
    assert fields_with_medications(result.sheet)["Cardiovascular"] == "BP: 106/58"


def test_encrypted_roundtrip_preserves_patients_and_schema():
    s = sheet()
    validate_sheet(s)
    vault = save_sheet_in(new_vault(), s)
    key = generate_key()
    reopened = open_vault(seal_vault(vault, key), key)
    assert reopened == vault and reopened["schema"] == 34
    assert EXPECTED in text_by_system(reopened["rooms"][s["room"]]["vitals"])["Cardiovascular"]


def test_text_html_pdf_and_print_all():
    s = sheet()
    before = deepcopy(s)
    t = datetime(2026, 11, 13, 12, 10, tzinfo=timezone.utc)
    assert EXPECTED in handoff_text(s, t)
    html = handoff_html(s, t)
    assert "<b>Cuff:</b> BP (88-116)/(42-70) 104/54" in html
    assert "<b>ART BP:</b> 80/40 to 112/65 [last 108/60]" in html
    assert "<b>ART MAP:</b> 52 to 75 mmHg [last 72]" in html
    other = deepcopy(s)
    other["room"] = "P4104"
    assert handoffs_html([s, other], t).count("<b>ART MAP:</b>") == 2
    for data, pages in ((handoff_pdf(s, t), 1), (handoffs_pdf([s, other], t), 2)):
        with fitz.open(stream=data, filetype="pdf") as document:
            assert len(document) == pages
            for page in document:
                text = re.sub(r"\s+", " ", page.get_text())
                for line in EXPECTED.splitlines():
                    assert line in text
                assert page.search_for("Cuff:")[0].y0 < page.search_for("ART BP:")[0].y0 < page.search_for("ART MAP:")[0].y0
    assert s == before
