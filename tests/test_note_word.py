"""Template preservation and safe insertion checks for Word note downloads."""
from collections import Counter
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest

import note_word
from note_word import NoteWordError, TEMPLATE_FILES, render_note_docx


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{" + NS["w"] + "}"


def package(data):
    with ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def tree(data):
    return ET.fromstring(package(data)["word/document.xml"])


def text(node):
    return "".join(item.text or "" for item in node.iter(W + "t"))


def section_table(root, label):
    for table in root.iter(W + "tbl"):
        paragraph = next(table.iter(W + "p"))
        if text(paragraph).strip() == label:
            return table
    raise AssertionError("Missing test section")


def sample_result():
    return {
        "medications": {"sections": {
            "Neurologic": {"Drips": ["Fentanyl at 2 mcg/kg/hr"], "Scheduled": ["Clobazam 100 mg Q12H"], "PRN": ["Fentanyl 20 mcg Q1H PRN"]},
            "Respiratory": {"Drips": [], "Scheduled": ["Albuterol 2.5 mg Q4H"], "PRN": []},
            "Cardiovascular": {"Drips": ["Milrinone at 0.5 mcg/kg/min"], "Scheduled": [], "PRN": []},
            "FEN / GI": {"Drips": [], "Scheduled": ["Pantoprazole 20 mg Q24H"], "PRN": []},
            "Hematology": {"Drips": [], "Scheduled": ["Ferrous sulfate 15 mg Daily"], "PRN": []},
            "Infectious Disease": {"Drips": [], "Scheduled": ["Ceftriaxone 500 mg Q24H"], "PRN": []},
            "Other Medications": {"Drips": [], "Scheduled": ["Unmapped example 1 mg Daily"], "PRN": []},
        }},
        "selected_plan_tokens": ["@ACKZATRISKFORGASTRICULCERS@", "@ACKZRHINOVIRUS@"],
        "phrase_style": "at",
    }


@pytest.mark.parametrize("note_type", ["progress", "attestation"])
def test_empty_generation_returns_the_original_template_unchanged(note_type):
    result = {"medications": {"sections": {}}, "selected_plan_tokens": []}
    assert render_note_docx(result, note_type=note_type) == TEMPLATE_FILES[note_type].read_bytes()


@pytest.mark.parametrize("note_type", ["progress", "attestation"])
def test_all_original_formatting_parts_paragraphs_and_table_properties_are_preserved(note_type):
    original_data = TEMPLATE_FILES[note_type].read_bytes()
    generated_data = render_note_docx(sample_result(), note_type=note_type)
    original_parts, generated_parts = package(original_data), package(generated_data)
    assert set(original_parts) == set(generated_parts)
    for name in original_parts:
        if name != "word/document.xml":
            assert original_parts[name] == generated_parts[name], name
    original, generated = tree(original_data), tree(generated_data)
    old_paragraphs = Counter(ET.tostring(p) for p in original.iter(W + "p"))
    body = list(original.find("w:body", NS))
    plan = section_table(original, "PLAN")
    for node in body[body.index(plan) + 1:]:
        if node.tag != W + "p" or any(child.tag != W + "pPr" for child in node):
            break
        # Only the original empty Plan placeholders may be filled or consumed.
        old_paragraphs.subtract([ET.tostring(node)])
    old_paragraphs += Counter()
    new_paragraphs = Counter(ET.tostring(p) for p in generated.iter(W + "p"))
    assert not (old_paragraphs - new_paragraphs)
    for tag in ("tblPr", "trPr", "tcPr", "sectPr"):
        assert [ET.tostring(node) for node in original.iter(W + tag)] == [ET.tostring(node) for node in generated.iter(W + tag)]
    size = generated.find(".//w:sectPr/w:pgSz", NS)
    assert size.get(W + "orient") == "landscape"


def test_medications_are_below_smartlists_and_inside_the_correct_original_cells():
    result = sample_result()
    before = deepcopy(result)
    document = tree(render_note_docx(result))
    body = document.find("w:body", NS)
    values = [text(child) for child in body]
    for token, medication in (
        ("{CKNEUROSMARTLIST:45213}", "Clobazam 100 mg Q12H"),
        ("{CKRESPLIST:45220}", "Albuterol 2.5 mg Q4H"),
        ("{CKCVLIST:45328}", "Milrinone at 0.5 mcg/kg/min"),
        ("{ACKFENGI:45365}", "Pantoprazole 20 mg Q24H"),
    ):
        assert values.index(token) < values.index(medication)
    heme = section_table(document, "HEMATOLOGY")
    infectious = section_table(document, "INFECTIOUS DISEASES")
    for section, medication in ((heme, "Ferrous sulfate 15 mg Daily"), (infectious, "Ceftriaxone 500 mg Q24H")):
        cell = next(cell for cell in section.iter(W + "tc") if "***" in text(cell))
        assert medication in text(cell)
        assert [text(p) for p in cell.iter(W + "p")][0] == "***"
    assert "Unmapped example 1 mg Daily" in text(document)
    assert text(document).count("***") == 3
    assert result == before


def test_attestation_ignores_medications_and_preserves_every_exam_smartlist():
    result = sample_result()
    result["text"] = "Fentanyl SHOULD NOT APPEAR even if plain text contains medication lists"
    document = tree(render_note_docx(result, note_type="attestation"))
    output = text(document)
    assert "Fentanyl" not in output
    assert "MEDICATIONS FOR REVIEW" not in output
    assert "Clobazam" not in output and "Pantoprazole" not in output
    for token in ("{ACKNEUROEXAM:45450}", "{ACKRESPEXAM:45451}", "{ACKCVEXAM:45452}", "{ACKABDEXAM:45453}", "{CKCLININDICATIONS:45218}"):
        assert output.count(token) == 1
    assert "I personally examined the patient separately" in output
    assert "@ACKZATRISKFORGASTRICULCERS@" in output
    assert "@ACKZRHINOVIRUS@" in output


def test_special_characters_are_xml_escaped_without_changing_the_medication_text():
    value = 'Example A & B <comparison> 5 µg with "quoted" text'
    result = {"medications": {"sections": {"Neurologic": {"Scheduled": [value]}}}, "selected_plan_tokens": []}
    output = render_note_docx(result)
    assert value in text(tree(output))
    assert b"A &amp; B &lt;comparison&gt;" in package(output)["word/document.xml"]


def write_with_document(source_data, document, path):
    with ZipFile(BytesIO(source_data)) as original, ZipFile(path, "w") as updated:
        for info in original.infolist():
            updated.writestr(info, document if info.filename == "word/document.xml" else original.read(info.filename))


def test_anchor_split_across_word_runs_is_found_without_rewriting_those_runs(tmp_path, monkeypatch):
    original = TEMPLATE_FILES["progress"].read_bytes()
    source = package(original)["word/document.xml"]
    before = b"<w:t>{CKNEUROSMARTLIST:45213}</w:t>"
    split = b"<w:t>{CKNEURO</w:t></w:r><w:r><w:t>SMARTLIST:45213}</w:t>"
    assert before in source
    changed = source.replace(before, split, 1)
    path = tmp_path / "split_anchor.docx"
    write_with_document(original, changed, path)
    monkeypatch.setitem(TEMPLATE_FILES, "progress", path)
    output = render_note_docx(sample_result())
    assert split in package(output)["word/document.xml"]
    assert text(tree(output)).count("{CKNEUROSMARTLIST:45213}") == 1
    assert "Fentanyl at 2 mcg/kg/hr" in text(tree(output))


def test_large_medication_lists_use_wrapping_paragraphs_without_fixed_height_or_keep_chains():
    medications = [f"Synthetic medication {number} 10 mg Q12H with a deliberately long descriptive formulation" for number in range(120)]
    result = {"medications": {"sections": {"Hematology": {"Scheduled": medications}}}, "selected_plan_tokens": []}
    root = tree(render_note_docx(result))
    heme = section_table(root, "HEMATOLOGY")
    paragraphs = {text(p): p for p in heme.iter(W + "p")}
    assert all(item in paragraphs for item in medications)
    for item in medications:
        assert paragraphs[item].find("w:pPr/w:keepNext", NS).get(W + "val") == "0"
        assert paragraphs[item].find("w:pPr/w:keepLines", NS).get(W + "val") == "0"
    assert not root.findall('.//w:trHeight[@w:hRule="exact"]', NS)
    assert not root.findall(".//w:tcPr/w:noWrap", NS)


def test_dot_phrase_fallback_uses_only_selected_phrases_and_deduplicates():
    result = {"phrase_style": "dot", "suggestions": [
        {"phrase": "ACKZTBI", "selected": True},
        {"phrase": "ACKZTBI", "selected": True},
        {"phrase": "ACKZSEPSIS", "selected": False},
        {"phrase": "", "selected": True},
    ]}
    output = text(tree(render_note_docx(result, note_type="attestation")))
    assert output.count(".ACKZTBI") == 1
    assert "ACKZSEPSIS" not in output


@pytest.mark.parametrize("note_type", ["progress", "attestation"])
@pytest.mark.parametrize("tokens", [["@ACKZTBI@"], ["@ACKZTBI@", "@ACKZRHINOVIRUS@", "@ACKZATRISKFORGASTRICULCERS@"]])
def test_selected_plan_tokens_consume_empty_tail_placeholders_without_blank_paragraphs(note_type, tokens):
    document = tree(render_note_docx({"selected_plan_tokens": tokens}, note_type=note_type))
    body = list(document.find("w:body", NS))
    plan = section_table(document, "PLAN")
    tail = body[body.index(plan) + 1:]
    assert [text(node) for node in tail if node.tag == W + "p"] == tokens
    assert tail[-1].tag == W + "sectPr"


def test_empty_plan_paragraph_with_a_bookmark_is_never_consumed(tmp_path, monkeypatch):
    original = TEMPLATE_FILES["progress"].read_bytes()
    source = package(original)["word/document.xml"]
    root = note_word._parse_xml(source)
    plan = note_word._table(root, "PLAN")
    placeholder = note_word._empty_plan_placeholders(root, plan)[0]
    bookmark = b'<w:bookmarkStart w:id="101" w:name="PreserveThis"/><w:bookmarkEnd w:id="101"/>'
    protected = source[placeholder.start:placeholder.close_start] + bookmark + source[placeholder.close_start:placeholder.end]
    changed = source[:placeholder.start] + protected + source[placeholder.end:]
    path = tmp_path / "bookmarked_plan.docx"
    write_with_document(original, changed, path)
    monkeypatch.setitem(TEMPLATE_FILES, "progress", path)
    output = render_note_docx({"selected_plan_tokens": ["@ACKZTBI@"]})
    assert protected in package(output)["word/document.xml"]


@pytest.mark.parametrize("empty_xml", [b"<w:p/>", b"<w:p></w:p>"])
def test_plan_placeholder_supports_both_empty_xml_paragraph_forms(tmp_path, monkeypatch, empty_xml):
    original = TEMPLATE_FILES["progress"].read_bytes()
    source = package(original)["word/document.xml"]
    root = note_word._parse_xml(source)
    plan = note_word._table(root, "PLAN")
    placeholder = note_word._empty_plan_placeholders(root, plan)[0]
    changed = source[:placeholder.start] + empty_xml + source[placeholder.end:]
    path = tmp_path / "empty_plan_forms.docx"
    write_with_document(original, changed, path)
    monkeypatch.setitem(TEMPLATE_FILES, "progress", path)
    document = tree(render_note_docx({"selected_plan_tokens": ["@ACKZTBI@"]}))
    body = list(document.find("w:body", NS))
    plan_table = section_table(document, "PLAN")
    tail = body[body.index(plan_table) + 1:]
    assert [text(node) for node in tail if node.tag == W + "p"] == ["@ACKZTBI@"]
    assert tail[-1].tag == W + "sectPr"


def test_missing_template_fails_with_a_clear_static_message(tmp_path, monkeypatch):
    monkeypatch.setitem(TEMPLATE_FILES, "progress", tmp_path / "missing.docx")
    with pytest.raises(NoteWordError, match="template is missing or unavailable"):
        render_note_docx(sample_result())


def test_missing_required_anchor_fails_instead_of_silently_dropping_medications(tmp_path, monkeypatch):
    original = TEMPLATE_FILES["progress"].read_bytes()
    changed = package(original)["word/document.xml"].replace(b"{CKNEUROSMARTLIST:45213}", b"REMOVEDANCHOR")
    path = tmp_path / "missing_anchor.docx"
    write_with_document(original, changed, path)
    monkeypatch.setitem(TEMPLATE_FILES, "progress", path)
    with pytest.raises(NoteWordError, match="required note placeholder"):
        render_note_docx(sample_result())


@pytest.mark.parametrize("token", ["@ACKZTBI@\nEXAM", "<w:t>INJECTED</w:t>", "@UNFINISHED"])
def test_invalid_plan_tokens_cannot_add_unreviewed_text(token):
    with pytest.raises(NoteWordError, match="valid Epic phrase token"):
        render_note_docx({"selected_plan_tokens": [token]}, note_type="attestation")
