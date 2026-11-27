"""Source-preserving insertion of the supplied age-specific FEN/GI tables."""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import xml.etree.ElementTree as ET

import pytest

import note_word
from note_fengi import FENGI_TEMPLATE_FILES
from note_word import NoteWordError, TEMPLATE_FILES, render_note_docx
from test_note_word import (NS, W, medication_cell, package, sample_result, section_table,
                           text, tree, without_heading_keep_next, write_with_document)


HEADING = "FLUIDS ELECTROLYTES NUTRITION/GASTROINTESTINAL"
VARIANTS = [
    ("under_2", "Head Circumference:", "@FLOWDATETIME(16)@", "@BMI@"),
    ("age_2_plus", "Body Mass Index:", "@BMI@", "@FLOWDATETIME(16)@"),
]
SOURCE_HASHES = {
    "under_2": "e2f50359dc62fdd9049268bf628ed672992f5702c2c687e01dd89871e7e1eb65",
    "age_2_plus": "c0f8c19e16f067fa4d3a8bfcc604ef23392eadab30e25cc23adcc23c9503e22d",
}


def age_result(variant):
    result = sample_result()
    result["fengi_variant"] = variant
    result["medications"]["sections"]["FEN / GI"] = {
        "Drips": ["Synthetic GI infusion at 20 mL/hr"],
        "Scheduled": ["Pantoprazole 20 mg Q24H", "Calcium carbonate 500 mg Q12H"],
        "PRN": ["Ondansetron 2 mg Q6H PRN"],
    }
    return result


def raw_table(data, heading=HEADING, *, normalize_pagination=False):
    document = package(data)["word/document.xml"]
    if normalize_pagination:
        document = without_heading_keep_next(document)
    root = note_word._parse_xml(document)
    table = note_word._table(root, heading)
    return document, table


def urine_output_row(table):
    return next(row for row in table.findall("w:tr", NS) if text(row).startswith("Urine Output:"))


@pytest.mark.parametrize("variant", SOURCE_HASHES)
def test_packaged_age_templates_are_exact_copies_of_the_supplied_documents(variant):
    assert sha256(FENGI_TEMPLATE_FILES[variant].read_bytes()).hexdigest() == SOURCE_HASHES[variant]


@pytest.mark.parametrize("variant,label,expected_token,excluded_token", VARIANTS)
def test_selected_age_table_replaces_generic_anchor_and_contains_its_medications(variant, label, expected_token, excluded_token):
    result = age_result(variant)
    before = deepcopy(result)
    root = tree(render_note_docx(result))
    table = section_table(root, HEADING)
    body = list(root.find("w:body", NS))
    assert body.index(table) < body.index(section_table(root, "HEMATOLOGY"))
    assert sum(text(p) == HEADING for p in root.iter(W + "p")) == 1
    assert "{ACKFENGI:45365}" not in text(root)
    assert label in text(table) and expected_token in text(table) and excluded_token not in text(table)
    cell = medication_cell(table)
    assert [text(p) for p in cell.iter(W + "p")] == [
        "Drips: Synthetic GI infusion at 20 mL/hr", "Scheduled: Pantoprazole 20 mg Q24H",
        "Calcium carbonate 500 mg Q12H", "PRN: Ondansetron 2 mg Q6H PRN",
    ]
    for values in result["medications"]["sections"]["FEN / GI"].values():
        for value in values:
            assert text(root).count(value) == 1
            assert value in text(cell)
    assert "MEDICATIONS FOR REVIEW" not in text(root) and "MEDICATIONS IN REVIEW" not in text(root)
    assert text(urine_output_row(table)) == "Urine Output:***"
    assert "with ***." in text(section_table(root, "ASSESSMENT"))
    assert text(root).count("***") == 2
    assert result == before


@pytest.mark.parametrize("variant", SOURCE_HASHES)
def test_transplanted_table_is_byte_identical_except_medications_and_heading_pagination(variant):
    source_data = FENGI_TEMPLATE_FILES[variant].read_bytes()
    source, original_table = raw_table(source_data, normalize_pagination=True)
    original_placeholder = note_word._medication_placeholder(original_table)
    generated_data = render_note_docx(age_result(variant))
    generated, inserted_table = raw_table(generated_data, normalize_pagination=True)
    inserted = generated[inserted_table.start:inserted_table.end]
    assert inserted.startswith(source[original_table.start:original_placeholder.start])
    assert inserted.endswith(source[original_placeholder.end:original_table.end])
    original_xml_table = section_table(tree(source_data), HEADING)
    inserted_xml_table = section_table(tree(generated_data), HEADING)
    for tag in ("tblPr", "tblGrid", "trPr", "tcPr"):
        assert [ET.tostring(node) for node in original_xml_table.iter(W + tag)] == [
            ET.tostring(node) for node in inserted_xml_table.iter(W + tag)]
    assert ET.tostring(urine_output_row(original_xml_table)) == ET.tostring(urine_output_row(inserted_xml_table))
    assert FENGI_TEMPLATE_FILES[variant].read_bytes() == source_data


@pytest.mark.parametrize("variant", SOURCE_HASHES)
def test_empty_age_table_clears_only_medication_stars_and_preserves_other_placeholders(variant):
    original_data = FENGI_TEMPLATE_FILES[variant].read_bytes()
    original, source_table = raw_table(original_data, normalize_pagination=True)
    placeholder = note_word._medication_placeholder(source_table)
    expected = (original[source_table.start:placeholder.start]
                + original[placeholder.start:placeholder.end].replace(b"***", b"")
                + original[placeholder.end:source_table.end])
    rendered = render_note_docx({"fengi_variant": variant, "selected_plan_tokens": []})
    generated, inserted_table = raw_table(rendered, normalize_pagination=True)
    assert generated[inserted_table.start:inserted_table.end] == expected
    root = tree(rendered)
    cell = medication_cell(section_table(root, HEADING))
    assert text(cell) == "" and cell.find("w:p", NS) is not None
    assert text(root).count("***") == 2
    assert "with ***." in text(section_table(root, "ASSESSMENT"))


@pytest.mark.parametrize("variant", SOURCE_HASHES)
def test_progress_resources_and_unrelated_paragraphs_remain_unchanged(variant):
    original_data = TEMPLATE_FILES["progress"].read_bytes()
    generated_data = render_note_docx(age_result(variant))
    original_parts, generated_parts = package(original_data), package(generated_data)
    assert set(original_parts) == set(generated_parts)
    for name in original_parts:
        if name != "word/document.xml":
            assert original_parts[name] == generated_parts[name], name
    original, generated = tree(original_data, normalize_heading_pagination=True), tree(generated_data, normalize_heading_pagination=True)
    preserved = Counter(ET.tostring(p) for p in original.iter(W + "p"))
    generic = next(p for p in original.iter(W + "p") if text(p) == "{ACKFENGI:45365}")
    preserved.subtract([ET.tostring(generic)])
    for label in ("HEMATOLOGY", "INFECTIOUS DISEASES"):
        cell = medication_cell(section_table(original, label))
        preserved.subtract([ET.tostring(next(cell.iter(W + "p")))])
    body = list(original.find("w:body", NS))
    plan = section_table(original, "PLAN")
    for node in body[body.index(plan) + 1:]:
        if node.tag != W + "p" or any(child.tag != W + "pPr" for child in node):
            break
        preserved.subtract([ET.tostring(node)])
    preserved += Counter()
    assert not (preserved - Counter(ET.tostring(p) for p in generated.iter(W + "p")))
    assert [ET.tostring(node) for node in original.iter(W + "sectPr")] == [
        ET.tostring(node) for node in generated.iter(W + "sectPr")]
    assert TEMPLATE_FILES["progress"].read_bytes() == original_data


def test_unknown_age_preserves_generic_anchor_and_flat_fen_medications_without_reading_new_assets(tmp_path, monkeypatch):
    result = age_result(None)
    expected = render_note_docx(result)
    for variant in FENGI_TEMPLATE_FILES:
        monkeypatch.setitem(FENGI_TEMPLATE_FILES, variant, tmp_path / "missing.docx")
    assert render_note_docx(result) == expected
    result.pop("fengi_variant")
    assert render_note_docx(result) == expected
    output = text(tree(expected))
    assert "{ACKFENGI:45365}" in output and HEADING not in output
    assert "Pantoprazole 20 mg Q24H" in output


@pytest.mark.parametrize("variant", ["under_2", "age_2_plus", "unrecognized"])
def test_attestation_ignores_age_variant_and_fen_medications_even_if_assets_are_unavailable(variant, tmp_path, monkeypatch):
    result = age_result(variant)
    expected = render_note_docx(sample_result(), note_type="attestation")
    for key in FENGI_TEMPLATE_FILES:
        monkeypatch.setitem(FENGI_TEMPLATE_FILES, key, tmp_path / "missing.docx")
    assert render_note_docx(result, note_type="attestation") == expected
    output = text(tree(expected))
    assert HEADING not in output and "Pantoprazole" not in output


@pytest.mark.parametrize("variant", ["", "unrecognized", []])
def test_invalid_selected_age_variant_fails_clearly(variant):
    with pytest.raises(NoteWordError, match="selected age-specific FEN/GI Word template is invalid"):
        render_note_docx({"fengi_variant": variant})


def test_missing_selected_age_template_fails_instead_of_dropping_the_section(tmp_path, monkeypatch):
    monkeypatch.setitem(FENGI_TEMPLATE_FILES, "under_2", tmp_path / "missing.docx")
    with pytest.raises(NoteWordError, match="age-specific FEN/GI Word template is missing or invalid"):
        render_note_docx({"fengi_variant": "under_2"})


@pytest.mark.parametrize("populated", [False, True])
def test_split_medication_placeholder_is_replaced_without_touching_urine_output(tmp_path, monkeypatch, populated):
    original_data = FENGI_TEMPLATE_FILES["under_2"].read_bytes()
    original, table = raw_table(original_data)
    placeholder = note_word._medication_placeholder(table)
    split = original[placeholder.start:placeholder.end].replace(
        b"<w:t>***</w:t>", b"<w:t>*</w:t></w:r><w:r><w:t>**</w:t>")
    assert split != original[placeholder.start:placeholder.end]
    changed = original[:placeholder.start] + split + original[placeholder.end:]
    path = tmp_path / "split_fengi_placeholder.docx"
    write_with_document(original_data, changed, path)
    monkeypatch.setitem(FENGI_TEMPLATE_FILES, "under_2", path)
    result = age_result("under_2") if populated else {"fengi_variant": "under_2"}
    root = tree(render_note_docx(result))
    table = section_table(root, HEADING)
    assert "*" not in text(medication_cell(table))
    assert text(urine_output_row(table)) == "Urine Output:***"


def test_missing_medication_label_cannot_consume_the_urine_output_placeholder(tmp_path, monkeypatch):
    original = FENGI_TEMPLATE_FILES["under_2"].read_bytes()
    source = package(original)["word/document.xml"].replace(b">MEDICATIONS<", b">MISSING LABEL<")
    path = tmp_path / "missing_fengi_medication_label.docx"
    write_with_document(original, source, path)
    monkeypatch.setitem(FENGI_TEMPLATE_FILES, "under_2", path)
    with pytest.raises(NoteWordError, match="unique required medication cell"):
        render_note_docx(age_result("under_2"))


@pytest.mark.parametrize("insertion", [
    b'<w:hyperlink r:id="rIdMissing"><w:r><w:t>Linked content</w:t></w:r></w:hyperlink>',
    b'<w:pPr><w:pStyle w:val="UnmergedStyle"/></w:pPr>',
])
def test_unavailable_source_relationships_or_named_styles_cannot_be_silently_transplanted(tmp_path, monkeypatch, insertion):
    original = FENGI_TEMPLATE_FILES["under_2"].read_bytes()
    source, table = raw_table(original)
    placeholder = note_word._medication_placeholder(table)
    changed = source[:placeholder.open_end] + insertion + source[placeholder.open_end:]
    path = tmp_path / "unsupported_fengi_resource.docx"
    write_with_document(original, changed, path)
    monkeypatch.setitem(FENGI_TEMPLATE_FILES, "under_2", path)
    with pytest.raises(NoteWordError, match="requires unsupported Word resources"):
        render_note_docx(age_result("under_2"))


def test_large_fen_medication_list_remains_inside_its_original_table_with_wrapping_paragraphs():
    medications = [f"Synthetic FEN medication {number} 10 mg Q12H with a long descriptive formulation" for number in range(80)]
    result = {"fengi_variant": "age_2_plus", "medications": {"sections": {"FEN / GI": {"Scheduled": medications}}}}
    root = tree(render_note_docx(result))
    table = section_table(root, HEADING)
    cell = medication_cell(table)
    paragraphs = {text(p).removeprefix("Scheduled: "): p for p in cell.iter(W + "p")}
    for value in medications:
        assert text(root).count(value) == 1
        assert paragraphs[value].find("w:pPr/w:keepNext", NS).get(W + "val") == "0"
        assert paragraphs[value].find("w:pPr/w:keepLines", NS).get(W + "val") == "0"
    assert not table.findall('.//w:trHeight[@w:hRule="exact"]', NS)
    assert not table.findall(".//w:tcPr/w:noWrap", NS)
