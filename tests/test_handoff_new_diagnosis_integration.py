"""Deidentified A/G import-to-output checks for the v6.120 additions."""
from copy import deepcopy
from datetime import datetime
from html import unescape
from io import BytesIO
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from pypdf import PdfReader
import pytest

from exports import handoff_html, handoff_pdf, handoff_text
from importing import import_sections
from lab_windows import display_clock, laboratory_data
from labs import result_cards
from models import fields_with_medications, new_sheet, new_vault
from note_generator import generate_note
from note_word import render_note_docx
from parser import parse_smartphrase


NOW = datetime(2026, 11, 27, 12, tzinfo=ZoneInfo("America/New_York"))
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ENDOCRINE_ROWS = (
    ("TSH", "2.34", "03/12/2024"),
    ("FREET4", "1.41", "03/12/2024"),
    ("CORTISOL", "37.6 (H)", "08/22/2025"),
)


def block(key, body):
    return key * 16 + "\n" + body + "\n" + key * 16


def source(diagnoses, endocrine=ENDOCRINE_ROWS):
    # The repeated headers and intervening empty-result notices reproduce the
    # source structure. No full uploaded handoff is stored in this fixture.
    labs = "\n".join((
        "LABS:",
        "Lab Results", "Component\tValue\tDate", "HGB\t12.4\t11/26/2026",
        "Lab Results", "Component\tValue\tDate", "NA\t138\t11/26/2026",
        'No results found for: "SYNTHETIC_UNUSED_ASSAY"',
        "Lab Results", "Component\tValue\tDate", "ALT\t23\t11/25/2026",
        "Lab Results", "Component\tValue\tDate",
        *("\t".join(row) for row in endocrine),
    ))
    return block("a", "Diagnoses:\n" + "\n".join(
        f"{index}. {diagnosis}" for index, diagnosis in enumerate(diagnoses, 1)
    )) + "\n" + block("g", labs)


def imported(diagnoses, endocrine=ENDOCRINE_ROWS, settings=None):
    settings = settings or new_vault()["settings"]
    result = import_sections(new_sheet("P4102"), source(diagnoses, endocrine), settings)
    assert not result.errors, result.errors
    assert {"Diagnoses", "laboratory results"} <= set(result.imported)
    assert not ({"a", "g"} & set(result.sheet["import_warnings"]))
    return result.sheet


def word_paragraphs(payload):
    with ZipFile(BytesIO(payload)) as archive:
        doc = ET.fromstring(archive.read("word/document.xml"))
    return ["".join(run.text or "" for run in paragraph.iter(W + "t")).strip()
            for paragraph in doc.iter(W + "p")]


def plain_html(value):
    value = re.sub(r"<style.*?</style>|<script.*?</script>", "", value, flags=re.S | re.I)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value)))


@pytest.mark.parametrize("diagnoses", [
    ("Metachromatic leukodystrophy", "Metachromatic leukodystrophy, late infantile type"),
    ("Hypoplastic left heart syndrome", "Chylothorax"),
])
def test_full_parser_and_import_keep_a_diagnoses_and_late_repeated_g_tables(diagnoses):
    parsed = parse_smartphrase(source(diagnoses))
    assert not parsed.invalid and not parsed.diagnosis_error
    assert parsed.diagnoses == list(diagnoses)
    assert "CORTISOL\t37.6 (H)\t08/22/2025" in parsed.blocks["g"]
    sheet = imported(diagnoses)
    assert sheet["fields"]["Diagnoses"].splitlines() == list(diagnoses)
    actual = [(row["component"], row["value"], row["date"])
              for row in sheet["labs"]["rows"] if row["component"] in {"TSH", "FREET4", "CORTISOL"}]
    assert actual == list(ENDOCRINE_ROWS)
    assert all(row["include"] for row in sheet["labs"]["rows"])


@pytest.mark.parametrize("note_type", ["progress", "attestation"])
@pytest.mark.parametrize("diagnoses,tokens", [
    (("Metachromatic leukodystrophy", "Metachromatic leukodystrophy, late infantile type"),
     ("@ACKZMETACHROMATICLEUKODYSTROPHY@",)),
    (("Hypoplastic left heart syndrome", "Chylothorax"),
     ("@ACKZCHYLOUSEFFUSION@", "@ACKZHLHS@")),
])
def test_imported_diagnoses_populate_first_generated_text_and_word_once(diagnoses, tokens, note_type):
    sheet = imported(diagnoses)
    before = deepcopy(sheet)
    with display_clock(NOW):
        result = generate_note(sheet, note_type=note_type)
        paragraphs = word_paragraphs(render_note_docx(result, note_type=note_type))
    assert result["selected_plan_tokens"] == list(tokens)
    assert [line for line in result["text"].rsplit("\nPLAN\n", 1)[1].splitlines() if line.strip()] == list(tokens)
    assert [line for line in paragraphs[paragraphs.index("PLAN") + 1:] if line] == list(tokens)
    assert sheet == before


def test_custom_a_destination_still_drives_new_plan_suggestions_without_mutation():
    settings = new_vault()["settings"]
    settings["diagnoses_destination"] = "Cardiovascular"
    sheet = imported(("HLHS", "Chylous pleural effusion"), settings=settings)
    assert sheet["fields"]["Diagnoses"] == ""
    assert sheet["fields"]["Cardiovascular"] == "HLHS\nChylous pleural effusion"
    before = deepcopy(sheet)
    with display_clock(NOW):
        note = generate_note(sheet, settings=settings)
    assert note["selected_plan_tokens"] == ["@ACKZCHYLOUSEFFUSION@", "@ACKZHLHS@"]
    assert sheet == before


@pytest.mark.parametrize("diagnosis", [
    "HLHS: No", "Chylothorax: None", "Trisomy 21: No",
    "Not currently diagnosed with HLHS", "No currently diagnosed trisomy 21",
])
def test_imported_explicit_negation_does_not_add_a_new_diagnosis_plan(diagnosis):
    sheet = imported((diagnosis,))
    with display_clock(NOW):
        note = generate_note(sheet, note_type="attestation")
    assert note["selected_plan_tokens"] == []


def test_old_endocrine_results_remain_in_lower_other_labs_with_exact_source_dates():
    sheet = imported(("Synthetic training example",))
    before = deepcopy(sheet)
    with display_clock(NOW):
        fields = fields_with_medications(sheet)
        cards = result_cards(laboratory_data(sheet), include_id_panels=False)
    lower = fields["Lab Results / Trends"]
    assert "Other labs" in lower
    for _, value, date in ENDOCRINE_ROWS:
        assert value in lower and date in lower
    other = next(card for card in cards if card["title"].startswith("Other labs"))
    assert {"TSH", "FREET4", "CORTISOL"} <= set(other["rows"])
    assert sheet == before


@pytest.mark.parametrize("kind", ["text", "html", "pdf"])
def test_full_handoff_exports_show_each_old_endocrine_result_once_in_other_labs(kind):
    sheet = imported(("Synthetic training example",))
    before = deepcopy(sheet)
    if kind == "text":
        output = handoff_text(sheet, printed_at=NOW)
    elif kind == "html":
        output = plain_html(handoff_html(sheet, printed_at=NOW))
    else:
        payload = handoff_pdf(sheet, printed_at=NOW)
        output = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(payload)).pages)
    output = re.sub(r"\s+", " ", output)
    other_start = output.index("Other labs")
    for label, value, full_date, short_date in (
        ("TSH", "2.34", "03/12/2024", "03/12/24"),
        ("Free T4", "1.41", "03/12/2024", "03/12/24"),
        ("Cortisol", "37.6 (H)", "08/22/2025", "08/22/25"),
    ):
        assert output.count(label + ":") == 1
        assert output.index(label + ":") > other_start
        assert label + ": " + value in output
        assert (full_date if kind == "text" else short_date) in output[other_start:]
    assert "FREET4:" not in output and "CORTISOL:" not in output
    assert sheet == before


def test_imported_aliases_use_latest_measured_time_and_preserve_older_source_rows():
    rows = (
        ("TSH", "1.91", "01/10/2023"),
        ("thyroid stimulating hormone", "3.72", "01/12/2023 13:30"),
        ("TSH", "3.11", "01/12/2023 09:15"),
        ("TSH", "Pending", "11/26/2026"),
        ("FT4", "1.18", "05/20/2024"),
        ("FREET4", "1.08", "05/18/2024"),
        ("CORT", "28.4 (H)", "08/22/2025"),
        ("CORTISOL", "19.2", "08/20/2025"),
    )
    sheet = imported(("Synthetic training example",), rows)
    before = deepcopy(sheet)
    with display_clock(NOW):
        lower = fields_with_medications(sheet)["Lab Results / Trends"]
    assert "TSH: 3.72 [01/12/2023 13:30]" in lower
    assert "Free T4: 1.18 [05/20/2024]" in lower
    assert "Cortisol: 28.4 (H) [08/22/2025]" in lower
    assert all(lower.count(label + ":") == 1 for label in ("TSH", "Free T4", "Cortisol"))
    for value in ("1.91", "3.11", "Pending", "1.08", "19.2"):
        assert value not in lower
    assert [(row["component"], row["value"], row["date"])
            for row in sheet["labs"]["rows"][-len(rows):]] == list(rows)
    assert sheet == before
