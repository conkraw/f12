"""Preserve the supplied neurologic tables while filling their medication cells."""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import xml.etree.ElementTree as ET

import pytest

import note_word
from note_neuro import NEURO_TEMPLATE_FILES
from note_word import NoteWordError, TEMPLATE_FILES, render_note_docx
from test_note_word import (NS, W, medication_cell, package, sample_result, section_table,
                           text, tree, without_heading_keep_next, write_with_document)


HEADING = "NEUROLOGY"
SOURCE_HASHES = {
    "ct_patient": "93767ee5f0be91617cba0ad6c4401b8da0eb27724e7d084b4411821eefc5621e",
    "none": "ac1b2f194f3aa6ed2320a6675838e629bab4054c1e9584c6bde811b9d5860e19",
    "icp_monitoring": "ad04dd43268f7fa8794e4f28023595c2f2fee5b5cfabfa7fc93470a907ed348b",
    "intubated": "ab7ab0586ab4bf62b5e160304bb641570ebc6db60abc8874d026f94293730e19",
    "tbi": "d86c6b2eb18e015c4c5a11f48f16471babe90e4a40fd0e3312754bdc05955b50",
    "status_epilepticus": "fb2fa23388ebfae0c95e1d0935820ed1c3fe09f1c55a244d23792df223a9fb12",
    "extubated": "591879dcd18bd71995ebc4dc665c109237ba5104e576fe46ea6c224e71340159",
}


def neuro_result(variant):
    result = sample_result()
    result["neuro_variant"] = variant
    return result


def raw_table(data, *, normalize_pagination=False):
    document = package(data)["word/document.xml"]
    if normalize_pagination:
        document = without_heading_keep_next(document)
    root = note_word._parse_xml(document)
    return document, note_word._table(root, HEADING)


@pytest.mark.parametrize("variant", SOURCE_HASHES)
def test_packaged_neuro_templates_match_supplied_documents_with_approved_corrections(variant):
    assert sha256(NEURO_TEMPLATE_FILES[variant].read_bytes()).hexdigest() == SOURCE_HASHES[variant]


@pytest.mark.parametrize("variant", SOURCE_HASHES)
def test_selected_neuro_table_replaces_anchor_and_contains_each_medication_once(variant):
    result = neuro_result(variant)
    before = deepcopy(result)
    root = tree(render_note_docx(result))
    table = section_table(root, HEADING)
    body = list(root.find("w:body", NS))
    respiratory = next(p for p in body if p.tag == W + "p" and text(p) == "{CKRESPLIST:45220}")
    assert body.index(section_table(root, "OBJECTIVE")) < body.index(table) < body.index(respiratory)
    assert sum(text(p) == HEADING for p in root.iter(W + "p")) == 1
    assert "{CKNEUROSMARTLIST:45213}" not in text(root)
    cell = medication_cell(table)
    assert [text(p) for p in cell.iter(W + "p")] == [
        "Drips: Fentanyl at 2 mcg/kg/hr", "Scheduled: Clobazam 100 mg Q12H",
        "PRN: Fentanyl 20 mcg Q1H PRN",
    ]
    for values in result["medications"]["sections"]["Neurologic"].values():
        for value in values:
            assert text(root).count(value) == 1 and value in text(cell)
    assert "MEDICATIONS FOR REVIEW" not in text(root) and "MEDICATIONS IN REVIEW" not in text(root)
    assert text(root).count("***") == 1
    assert "with ***." in text(section_table(root, "ASSESSMENT"))
    assert result == before


@pytest.mark.parametrize("variant", SOURCE_HASHES)
def test_neuro_table_is_byte_identical_except_medications_and_heading_pagination(variant):
    original_data = NEURO_TEMPLATE_FILES[variant].read_bytes()
    source, original_table = raw_table(original_data, normalize_pagination=True)
    placeholder = note_word._medication_placeholder(original_table)
    generated_data = render_note_docx(neuro_result(variant))
    generated, inserted_table = raw_table(generated_data, normalize_pagination=True)
    inserted = generated[inserted_table.start:inserted_table.end]
    assert inserted.startswith(source[original_table.start:placeholder.start])
    assert inserted.endswith(source[placeholder.end:original_table.end])
    original_xml = section_table(tree(original_data), HEADING)
    inserted_xml = section_table(tree(generated_data), HEADING)
    for tag in ("tblPr", "tblGrid", "trPr", "tcPr"):
        assert [ET.tostring(node) for node in original_xml.iter(W + tag)] == [
            ET.tostring(node) for node in inserted_xml.iter(W + tag)]
    # This includes the approved device-site SmartList and the intentionally repeated
    # EEG/imaging SmartList in the supplied status-epilepticus document.
    source_paragraphs = Counter(text(p) for p in original_xml.iter(W + "p") if text(p) != "***")
    inserted_paragraphs = Counter(text(p) for p in inserted_xml.iter(W + "p"))
    assert not (source_paragraphs - inserted_paragraphs)
    assert NEURO_TEMPLATE_FILES[variant].read_bytes() == original_data


@pytest.mark.parametrize("variant", SOURCE_HASHES)
def test_empty_neuro_medications_clear_only_the_designated_cell(variant):
    original_data = NEURO_TEMPLATE_FILES[variant].read_bytes()
    source, original_table = raw_table(original_data, normalize_pagination=True)
    placeholder = note_word._medication_placeholder(original_table)
    expected = (source[original_table.start:placeholder.start]
                + source[placeholder.start:placeholder.end].replace(b"***", b"")
                + source[placeholder.end:original_table.end])
    generated_data = render_note_docx({"neuro_variant": variant, "selected_plan_tokens": []})
    generated, inserted_table = raw_table(generated_data, normalize_pagination=True)
    assert generated[inserted_table.start:inserted_table.end] == expected
    root = tree(generated_data)
    cell = medication_cell(section_table(root, HEADING))
    assert text(cell) == "" and cell.find("w:p", NS) is not None
    assert text(root).count("***") == 1
    assert "with ***." in text(section_table(root, "ASSESSMENT"))


def test_progress_parts_and_unrelated_source_paragraphs_remain_unchanged():
    original_data = TEMPLATE_FILES["progress"].read_bytes()
    generated_data = render_note_docx(neuro_result("tbi"))
    original_parts, generated_parts = package(original_data), package(generated_data)
    assert set(original_parts) == set(generated_parts)
    for name in original_parts:
        if name != "word/document.xml":
            assert original_parts[name] == generated_parts[name], name
    original, generated = tree(original_data, normalize_heading_pagination=True), tree(generated_data, normalize_heading_pagination=True)
    preserved = Counter(ET.tostring(p) for p in original.iter(W + "p"))
    anchor = next(p for p in original.iter(W + "p") if text(p) == "{CKNEUROSMARTLIST:45213}")
    preserved.subtract([ET.tostring(anchor)])
    for label in ("HEMATOLOGY", "INFECTIOUS DISEASES"):
        cell = medication_cell(section_table(original, label))
        preserved.subtract([ET.tostring(next(cell.iter(W + "p")))])
    body = list(original.find("w:body", NS))
    plan = section_table(original, "PLAN")
    preserved.subtract([ET.tostring(next(plan.iter(W + "p")))])
    for node in body[body.index(plan) + 1:]:
        if node.tag != W + "p" or any(child.tag != W + "pPr" for child in node):
            break
        preserved.subtract([ET.tostring(node)])
    preserved += Counter()
    assert not (preserved - Counter(ET.tostring(p) for p in generated.iter(W + "p")))
    assert [ET.tostring(node) for node in original.iter(W + "sectPr")] == [
        ET.tostring(node) for node in generated.iter(W + "sectPr")]
    generated_body = list(generated.find("w:body", NS))
    index = generated_body.index(section_table(generated, HEADING))
    separator = generated_body[index - 1]
    assert separator.tag == W + "p" and text(separator) == ""
    assert ET.tostring(separator.find("w:pPr", NS)) == ET.tostring(anchor.find("w:pPr", NS))
    assert generated_body[index + 1].tag == W + "p" and text(generated_body[index + 1]) == ""


def test_selected_neuro_template_keeps_plan_heading_with_first_item_without_changing_its_visual_style():
    original = package(TEMPLATE_FILES["progress"].read_bytes())["word/document.xml"]
    original_root = note_word._parse_xml(original)
    original_header = note_word._paragraph(note_word._table(original_root, "PLAN"), "PLAN")
    original_paragraph = original[original_header.start:original_header.end]
    generated = package(render_note_docx(neuro_result("none")))["word/document.xml"]
    generated_root = note_word._parse_xml(generated)
    generated_header = note_word._paragraph(note_word._table(generated_root, "PLAN"), "PLAN")
    assert generated[generated_header.start:generated_header.end] == original_paragraph.replace(
        b"<w:pPr>", b"<w:pPr><w:keepNext/>", 1)
    empty = package(render_note_docx({"neuro_variant": "none", "selected_plan_tokens": []}))["word/document.xml"]
    empty_root = note_word._parse_xml(empty)
    empty_header = note_word._paragraph(note_word._table(empty_root, "PLAN"), "PLAN")
    assert empty[empty_header.start:empty_header.end] == original_paragraph


@pytest.mark.parametrize("fengi_variant", ["under_2", "age_2_plus"])
def test_neuro_and_fengi_tables_coexist_with_medications_in_their_own_cells(fengi_variant):
    result = neuro_result("tbi")
    result["fengi_variant"] = fengi_variant
    root = tree(render_note_docx(result))
    body = list(root.find("w:body", NS))
    neuro = section_table(root, HEADING)
    fengi = section_table(root, "FLUIDS ELECTROLYTES NUTRITION/GASTROINTESTINAL")
    assert body.index(neuro) < body.index(fengi) < body.index(section_table(root, "HEMATOLOGY"))
    assert "Clobazam 100 mg Q12H" in text(medication_cell(neuro))
    assert "Pantoprazole 20 mg Q24H" in text(medication_cell(fengi))
    assert "Pantoprazole" not in text(neuro) and "Clobazam" not in text(fengi)
    assert "{CKNEUROSMARTLIST:45213}" not in text(root) and "{ACKFENGI:45365}" not in text(root)
    assert "Urine Output:***" in text(fengi)
    assert "with ***." in text(section_table(root, "ASSESSMENT"))
    assert "{ICPMONITORSITE:45483}" in text(neuro)
    assert "{???}" not in text(neuro)


def test_missing_or_none_neuro_variant_preserves_legacy_generic_behavior_without_loading_assets(tmp_path, monkeypatch):
    result = neuro_result(None)
    expected = render_note_docx(result)
    for variant in NEURO_TEMPLATE_FILES:
        monkeypatch.setitem(NEURO_TEMPLATE_FILES, variant, tmp_path / "missing.docx")
    assert render_note_docx(result) == expected
    result.pop("neuro_variant")
    assert render_note_docx(result) == expected
    output = text(tree(expected))
    assert "{CKNEUROSMARTLIST:45213}" in output and HEADING not in output
    assert output.count("Clobazam 100 mg Q12H") == 1


@pytest.mark.parametrize("variant", [*SOURCE_HASHES, "unrecognized"])
def test_attestation_ignores_neuro_variants_and_unavailable_neuro_assets(variant, tmp_path, monkeypatch):
    expected = render_note_docx(sample_result(), note_type="attestation")
    for key in NEURO_TEMPLATE_FILES:
        monkeypatch.setitem(NEURO_TEMPLATE_FILES, key, tmp_path / "missing.docx")
    assert render_note_docx(neuro_result(variant), note_type="attestation") == expected
    output = text(tree(expected))
    assert HEADING not in output and "Clobazam" not in output and "Fentanyl" not in output
    assert "{ACKNEUROEXAM:45450}" in output


@pytest.mark.parametrize("variant", ["", "unrecognized", []])
def test_invalid_selected_neuro_variant_fails_clearly(variant):
    with pytest.raises(NoteWordError, match="selected neurologic Word template is invalid"):
        render_note_docx({"neuro_variant": variant})


def test_missing_selected_neuro_asset_cannot_silently_drop_the_section(tmp_path, monkeypatch):
    monkeypatch.setitem(NEURO_TEMPLATE_FILES, "none", tmp_path / "missing.docx")
    with pytest.raises(NoteWordError, match="neurologic Word template is missing or invalid"):
        render_note_docx({"neuro_variant": "none"})


@pytest.mark.parametrize("populated", [False, True])
def test_split_medication_placeholder_is_removed_without_changing_other_neuro_fields(tmp_path, monkeypatch, populated):
    original_data = NEURO_TEMPLATE_FILES["tbi"].read_bytes()
    source, table = raw_table(original_data)
    placeholder = note_word._medication_placeholder(table)
    split = source[placeholder.start:placeholder.end].replace(
        b"<w:t>***</w:t>", b"<w:t>*</w:t></w:r><w:r><w:t>**</w:t>")
    assert split != source[placeholder.start:placeholder.end]
    changed = source[:placeholder.start] + split + source[placeholder.end:]
    path = tmp_path / "split_neuro_medication_placeholder.docx"
    write_with_document(original_data, changed, path)
    monkeypatch.setitem(NEURO_TEMPLATE_FILES, "tbi", path)
    result = neuro_result("tbi") if populated else {"neuro_variant": "tbi"}
    root = tree(render_note_docx(result))
    table = section_table(root, HEADING)
    assert "*" not in text(medication_cell(table))
    assert "{ICPMONITORSITE:45483}" in text(table)
    assert "{???}" not in text(table)
    assert "{ACKNGCSE:45310}" in text(table)
    assert "{ACKNEUROEXAM:45450}" in text(table)


def test_generic_anchor_split_across_runs_is_replaced_with_the_selected_table(tmp_path, monkeypatch):
    original = TEMPLATE_FILES["progress"].read_bytes()
    source = package(original)["word/document.xml"]
    changed = source.replace(b"<w:t>{CKNEUROSMARTLIST:45213}</w:t>",
                             b"<w:t>{CKNEURO</w:t></w:r><w:r><w:t>SMARTLIST:45213}</w:t>")
    assert changed != source
    path = tmp_path / "split_neuro_anchor.docx"
    write_with_document(original, changed, path)
    monkeypatch.setitem(TEMPLATE_FILES, "progress", path)
    root = tree(render_note_docx(neuro_result("none")))
    assert "{CKNEUROSMARTLIST:45213}" not in text(root)
    assert "Clobazam 100 mg Q12H" in text(medication_cell(section_table(root, HEADING)))


def test_missing_medication_heading_cannot_consume_a_different_neuro_placeholder(tmp_path, monkeypatch):
    original = NEURO_TEMPLATE_FILES["tbi"].read_bytes()
    source = package(original)["word/document.xml"].replace(b">MEDICATIONS<", b">MISSING LABEL<")
    path = tmp_path / "missing_neuro_medication_label.docx"
    write_with_document(original, source, path)
    monkeypatch.setitem(NEURO_TEMPLATE_FILES, "tbi", path)
    with pytest.raises(NoteWordError, match="unique required medication cell"):
        render_note_docx(neuro_result("tbi"))


@pytest.mark.parametrize("insertion", [
    b'<w:hyperlink r:id="rIdMissing"><w:r><w:t>Linked content</w:t></w:r></w:hyperlink>',
    b'<w:pPr><w:pStyle w:val="UnmergedStyle"/></w:pPr>',
])
def test_neuro_sources_with_unsupported_resources_fail_instead_of_losing_formatting(tmp_path, monkeypatch, insertion):
    original = NEURO_TEMPLATE_FILES["none"].read_bytes()
    source, table = raw_table(original)
    placeholder = note_word._medication_placeholder(table)
    changed = source[:placeholder.open_end] + insertion + source[placeholder.open_end:]
    path = tmp_path / "unsupported_neuro_resource.docx"
    write_with_document(original, changed, path)
    monkeypatch.setitem(NEURO_TEMPLATE_FILES, "none", path)
    with pytest.raises(NoteWordError, match="neurologic Word template requires unsupported Word resources"):
        render_note_docx(neuro_result("none"))


def test_large_neuro_medication_list_can_wrap_inside_its_own_table_and_escapes_source_text():
    values = [f"Synthetic neurologic medication {number} 10 mg Q12H with a long descriptive formulation" for number in range(80)]
    values.append('Example A & B <comparison> 5 µg with "quoted" text')
    result = {"neuro_variant": "status_epilepticus", "medications": {"sections": {"Neurologic": {"Scheduled": values}}}}
    output = render_note_docx(result)
    root = tree(output)
    table = section_table(root, HEADING)
    cell = medication_cell(table)
    paragraphs = {text(p).removeprefix("Scheduled: "): p for p in cell.iter(W + "p")}
    for value in values:
        assert text(root).count(value) == 1
        assert paragraphs[value].find("w:pPr/w:keepNext", NS).get(W + "val") == "0"
        assert paragraphs[value].find("w:pPr/w:keepLines", NS).get(W + "val") == "0"
    assert b"A &amp; B &lt;comparison&gt;" in package(output)["word/document.xml"]
    assert not table.findall('.//w:trHeight[@w:hRule="exact"]', NS)
    assert not table.findall(".//w:tcPr/w:noWrap", NS)
    assert text(table).count("{ACKNIMAGES:45359}") == 2
