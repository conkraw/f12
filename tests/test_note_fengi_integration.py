"""Age-selected FEN/GI content and medication placement in generated notes."""
from copy import deepcopy
from io import BytesIO
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest

from anthropometrics import empty_anthropometrics
from medications import parse_medications
from models import new_sheet
from note_generator import generate_note
from note_word import render_note_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
FENGI_TITLE = "FLUIDS ELECTROLYTES NUTRITION/GASTROINTESTINAL"


def example(age):
    sheet = new_sheet("P4102")
    sheet["anthropometrics"] = dict(empty_anthropometrics(), age=age)
    rows = (
        ("sodium chloride 0.9 % infusion", "5 mL/hr", "Intravenous", "Continuous"),
        ("Pantoprazole", "20 mg", "Intravenous", "q24h"),
        ("Ondansetron", "2 mg", "Intravenous", "q8h PRN"),
        ("Clobazam", "100 mg", "Oral", "q12h"),
        ("Ferrous sulfate", "15 mg", "Oral", "Daily"),
        ("Ceftriaxone", "500 mg", "Intravenous", "q24h"),
    )
    parsed = parse_medications("Medications:\n" + "\n".join(
        "• " + "\t".join((*row, "", "", "")) for row in rows
    ))
    assert not parsed.error
    sheet["medications"] = parsed.rows
    return sheet


def word_tree(result, note_type="progress"):
    with ZipFile(BytesIO(render_note_docx(result, note_type=note_type))) as archive:
        return ET.fromstring(archive.read("word/document.xml"))


def text(node):
    return "".join(part.text or "" for part in node.iter(W + "t"))


def table(root, title):
    return next(item for item in root.iter(W + "tbl")
                if text(next(item.iter(W + "p"))) == title)


def medication_cell(section):
    rows = section.findall(W + "tr")
    for index, row in enumerate(rows[:-1]):
        if text(row).strip() == "MEDICATIONS":
            return rows[index + 1].find(W + "tc")
    raise AssertionError("Medication cell is missing")


@pytest.mark.parametrize("age,variant,present,absent", [
    ("18 m.o.", "under_2", "Head Circumference:", "Body Mass Index:"),
    ("1 year 11 months", "under_2", "Head Circumference:", "Body Mass Index:"),
    ("2 y.o.", "age_2_plus", "Body Mass Index:", "Head Circumference:"),
    ("24 months", "age_2_plus", "Body Mass Index:", "Head Circumference:"),
    ("15 years", "age_2_plus", "Body Mass Index:", "Head Circumference:"),
])
def test_age_selected_section_precedes_hematology_with_its_medications_inside(age, variant, present, absent):
    sheet = example(age)
    before = deepcopy(sheet)
    result = generate_note(sheet)
    assert result["fengi_variant"] == variant
    assert "{ACKFENGI:45365}" not in result["text"]
    assert FENGI_TITLE in result["text"]
    plain_section = result["text"].split(FENGI_TITLE, 1)[1].split("HEMATOLOGY", 1)[0]
    assert present in plain_section and absent not in plain_section
    document = word_tree(result)
    section = table(document, FENGI_TITLE)
    titles = [text(next(item.iter(W + "p"))) for item in document.find(W + "body").findall(W + "tbl")]
    assert titles[titles.index(FENGI_TITLE) + 1] == "HEMATOLOGY"
    assert present in text(section) and absent not in text(section)
    assert "{ACKFENGI:45365}" not in text(document)
    cell = medication_cell(section)
    med_lines = [text(paragraph) for paragraph in cell.iter(W + "p")]
    for group in ("Drips", "Scheduled", "PRN"):
        values = result["medications"]["sections"]["FEN / GI"][group]
        assert values
        for index, value in enumerate(values):
            expected_line = group + ": " + value if index == 0 else value
            assert expected_line in med_lines and plain_section.count(value) == 1
            assert text(document).count(value) == 1
    for other_medication in ("Clobazam", "Ferrous sulfate", "Ceftriaxone"):
        assert other_medication not in text(section)
    assert "***" not in text(cell)
    assert text(section).count("***") == plain_section.count("***") == 1
    assert "Urine Output:" in text(section)
    assert text(document).count("***") == result["text"].count("***") == 2
    for token in ("@DIETORDERPRINTGROUP@", "@IOBRIEFMR@", "{ACKFENGIDRAINS:45361}",
                  "{ACKABDEXAM:45453}", "{ACKFENGIIMAGING:45362}", "{ACKFENGILABS:45363}"):
        assert text(section).count(token) == plain_section.count(token) == 1
    assert "MEDICATIONS FOR REVIEW" not in text(document)
    assert sheet == before


@pytest.mark.parametrize("age", ["18 months", "24 months"])
def test_empty_age_selected_section_keeps_other_placeholders_and_has_an_empty_medication_cell(age):
    sheet = example(age)
    sheet["medications"] = []
    result = generate_note(sheet)
    section = table(word_tree(result), FENGI_TITLE)
    cell = medication_cell(section)
    assert text(cell).strip() == ""
    assert cell.find(W + "p") is not None
    assert text(section).count("***") == 1
    assert "MEDICATIONS\nABDOMINAL IMAGING INTERPRETATION" in result["text"]


@pytest.mark.parametrize("age", ["", "unknown", "104 weeks"])
def test_unresolved_age_keeps_generic_fengi_and_does_not_guess(age):
    result = generate_note(example(age))
    assert result["fengi_variant"] is None
    assert any("age" in warning.lower() and "FEN/GI" in warning for warning in result["warnings"])
    assert "{ACKFENGI:45365}" in result["text"]
    assert FENGI_TITLE not in result["text"]
    assert "Pantoprazole 20 mg Q24H" in result["text"]
    document = word_tree(result)
    assert "{ACKFENGI:45365}" in text(document)
    assert FENGI_TITLE not in text(document)


@pytest.mark.parametrize("age", ["", "18 months", "2 years"])
def test_attestation_stays_free_of_the_progress_fengi_table_and_medications(age):
    result = generate_note(example(age), note_type="attestation")
    assert result["fengi_variant"] is None
    assert not any("FEN/GI" in warning for warning in result["warnings"])
    output = text(word_tree(result, "attestation"))
    for absent in (FENGI_TITLE, "Pantoprazole", "Drips:", "Scheduled:", "PRN:"):
        assert absent not in result["text"] and absent not in output
    assert output.count("***") == 1
