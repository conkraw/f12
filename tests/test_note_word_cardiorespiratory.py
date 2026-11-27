"""Source-preserving respiratory and cardiovascular Word section insertion."""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import xml.etree.ElementTree as ET

import pytest

import note_word
from note_cardiovascular import CV_TEMPLATE_FILES
from note_respiratory import RESP_TEMPLATE_FILES
from note_word import NoteWordError, TEMPLATE_FILES, render_note_docx
from test_note_word import (NS, W, CLINICAL_TABLES, SOURCE_HEADING_LABELS, medication_cell, package,
                           sample_result, section_table, text, tree, without_heading_keep_next,
                           write_with_document)


FAMILIES = {
    "resp": (RESP_TEMPLATE_FILES, "respiratory_variant", "Respiratory", "RESPIRATORY", "{CKRESPLIST:45220}"),
    "cv": (CV_TEMPLATE_FILES, "cardiovascular_variant", "Cardiovascular", "CARDIOVASCULAR", "{CKCVLIST:45328}"),
}
SOURCE_HASHES = {
    ("resp", "pc"): "1eac21e801d038b70acae417a2cba55dd62ab35c7b2e8ee1673cc392205d55c7",
    ("resp", "prvc"): "9a60d775087793f5b1991256ee847077dc39719a81147a1552979becd1735673",
    ("resp", "avaps"): "b343283ee0a60beccbc9218556ed66ff18c596f669fd305144d39e26091098dc",
    ("resp", "bpap"): "03e64c0001b63d6095ab505b99cf025003b8d341116a516f7915a14795107fe4",
    ("resp", "hfnc"): "e3c2ec07116cf7c527a5cc4fbc69772338d8e7b3c97608c38a47666869a88556",
    ("resp", "none"): "20fc38c18e146c22155916a6055126e6e27e7b14d770f39de3f02e6d000ffb0a",
    ("resp", "nava"): "26024ea69a1bfe835c45941d57a73d263c1a34ae47f4e6f16bc5acb72d013992",
    ("resp", "home_vent"): "6d4ef18384975305bb4f1f52a61f38ea63b17c39b3fd8df488d21a9173e7b759",
    ("cv", "art"): "f3d7503e58ab9fbb53696a586e2c393545d6ff5a2f9456a8225679f08ba56edf",
    ("cv", "art_cvl"): "f1f890b91bdf27b386cfd80009e621efa906ea6aa22bfdcd5281d76d1d0c33a8",
    ("cv", "art_cvl_ecls"): "4e5079643edc101d6a04324ee76f5397bda4e1bc13fc1adf28ae1d617f222375",
    ("cv", "art_cvl_pacemaker"): "20ef262a7105a0b7c1af0f48889b51a1028711867d6d6e3c2502b289869b1def",
    ("cv", "cvl"): "ce372dd8efbeb16b62ae43479c74f3f633e38fb8ec8f6140bb33135cef11410b",
    ("cv", "none"): "138c51aa2b9625b60ff25b3c8945c6de73b2f05bea54bf8434d66aee4fb1ef2a",
}
PAIRS = [
    ("pc", "art", False), ("prvc", "art_cvl", False), ("avaps", "cvl", False),
    ("bpap", "none", False), ("hfnc", "art_cvl_pacemaker", True),
    ("none", "art_cvl_ecls", False), ("nava", "art_cvl_ecls", True),
    ("home_vent", "none", False),
]


def section_result(family, variant):
    result = sample_result()
    _, key, section, _, _ = FAMILIES[family]
    result[key] = variant
    result["medications"]["sections"][section] = {
        "Drips": [f"Synthetic {section} infusion at 2 mcg/kg/hr"],
        "Scheduled": [f"Synthetic {section} medication 10 mg Q12H"],
        "PRN": [f"Synthetic {section} medication 2 mg Q6H PRN"],
    }
    return result


def raw_table(data, heading, *, normalize_pagination=False):
    document = package(data)["word/document.xml"]
    if normalize_pagination:
        document = without_heading_keep_next(document)
    return document, note_word._table(note_word._parse_xml(document), heading)


@pytest.mark.parametrize("family,variant", SOURCE_HASHES)
def test_packaged_assets_match_the_supplied_sources_with_the_approved_avaps_delimiter_correction(family, variant):
    paths = FAMILIES[family][0]
    assert sha256(paths[variant].read_bytes()).hexdigest() == SOURCE_HASHES[(family, variant)]


@pytest.mark.parametrize("family,variant", SOURCE_HASHES)
def test_every_selected_table_replaces_its_anchor_and_contains_each_medication_once(family, variant):
    _, _, section, heading, anchor = FAMILIES[family]
    result = section_result(family, variant)
    before = deepcopy(result)
    root = tree(render_note_docx(result))
    table = section_table(root, heading)
    cell = medication_cell(table)
    assert anchor not in text(root)
    assert sum(text(p) == heading for p in root.iter(W + "p")) == 1
    assert [text(p) for p in cell.iter(W + "p")] == [
        f"Drips: Synthetic {section} infusion at 2 mcg/kg/hr",
        f"Scheduled: Synthetic {section} medication 10 mg Q12H",
        f"PRN: Synthetic {section} medication 2 mg Q6H PRN",
    ]
    for values in result["medications"]["sections"][section].values():
        for value in values:
            assert text(root).count(value) == 1 and value in text(cell)
    assert "***" not in text(cell)
    assert "MEDICATIONS FOR REVIEW" not in text(root) and "MEDICATIONS IN REVIEW" not in text(root)
    assert "with ***." in text(section_table(root, "ASSESSMENT"))
    assert result == before


@pytest.mark.parametrize("family,variant", SOURCE_HASHES)
def test_each_source_table_is_byte_identical_except_medications_and_heading_pagination(family, variant):
    paths, _, _, heading, _ = FAMILIES[family]
    original_data = paths[variant].read_bytes()
    source, source_table = raw_table(original_data, heading, normalize_pagination=True)
    placeholder = note_word._medication_placeholder(source_table)
    output = render_note_docx(section_result(family, variant))
    generated, generated_table = raw_table(output, heading, normalize_pagination=True)
    inserted = generated[generated_table.start:generated_table.end]
    assert inserted.startswith(source[source_table.start:placeholder.start])
    assert inserted.endswith(source[placeholder.end:source_table.end])
    original_xml = section_table(tree(original_data), heading)
    inserted_xml = section_table(tree(output), heading)
    for tag in ("tblPr", "tblGrid", "trPr", "tcPr"):
        assert [ET.tostring(node) for node in original_xml.iter(W + tag)] == [
            ET.tostring(node) for node in inserted_xml.iter(W + tag)]
    original_text = Counter(text(p) for p in original_xml.iter(W + "p") if text(p) != "***")
    assert not (original_text - Counter(text(p) for p in inserted_xml.iter(W + "p")))
    assert paths[variant].read_bytes() == original_data


@pytest.mark.parametrize("family,variant", SOURCE_HASHES)
def test_empty_medications_clear_only_the_selected_medication_placeholder(family, variant):
    paths, key, _, heading, _ = FAMILIES[family]
    source, source_table = raw_table(paths[variant].read_bytes(), heading, normalize_pagination=True)
    placeholder = note_word._medication_placeholder(source_table)
    expected = (source[source_table.start:placeholder.start]
                + source[placeholder.start:placeholder.end].replace(b"***", b"")
                + source[placeholder.end:source_table.end])
    output = render_note_docx({key: variant, "selected_plan_tokens": []})
    generated, generated_table = raw_table(output, heading, normalize_pagination=True)
    assert generated[generated_table.start:generated_table.end] == expected
    root = tree(output)
    cell = medication_cell(section_table(root, heading))
    assert text(cell) == "" and cell.find("w:p", NS) is not None
    assert text(root).count("***") == 1
    assert "with ***." in text(section_table(root, "ASSESSMENT"))


@pytest.mark.parametrize("respiratory,cardiovascular,pacemaker", PAIRS)
def test_all_four_selected_systems_keep_their_order_separate_tables_and_own_medications(respiratory, cardiovascular, pacemaker):
    result = sample_result()
    result.update(neuro_variant="intubated", respiratory_variant=respiratory,
                  cardiovascular_variant=cardiovascular, cardiovascular_include_pacemaker=pacemaker,
                  fengi_variant="age_2_plus")
    output = render_note_docx(result)
    root = tree(output)
    body = list(root.find("w:body", NS))
    headings = ["NEUROLOGY", "RESPIRATORY", "CARDIOVASCULAR",
                "FLUIDS ELECTROLYTES NUTRITION/GASTROINTESTINAL", "HEMATOLOGY"]
    positions = [body.index(section_table(root, heading)) for heading in headings]
    assert positions == sorted(positions)
    for index, heading in enumerate(headings[:-1]):
        separator = body[positions[index] + 1]
        assert separator.tag == W + "p" and text(separator) == "", heading
    for section, heading in zip(("Neurologic", "Respiratory", "Cardiovascular", "FEN / GI"), headings):
        cell = medication_cell(section_table(root, heading))
        for values in result["medications"]["sections"][section].values():
            for value in values:
                assert text(root).count(value) == 1 and value in text(cell)
    for anchor in ("{CKNEUROSMARTLIST:45213}", "{CKRESPLIST:45220}", "{CKCVLIST:45328}", "{ACKFENGI:45365}"):
        assert anchor not in text(root)
    assert "Urine Output:***" in text(root) and "with ***." in text(root)
    original_parts, generated_parts = package(TEMPLATE_FILES["progress"].read_bytes()), package(output)
    assert set(original_parts) == set(generated_parts)
    for name in original_parts:
        if name != "word/document.xml":
            assert generated_parts[name] == original_parts[name], name


@pytest.mark.parametrize("populated", [False, True])
def test_ecls_and_pacemaker_share_one_cv_table_and_copy_the_two_pacemaker_rows_exactly(populated):
    result = section_result("cv", "art_cvl_ecls") if populated else {"cardiovascular_variant": "art_cvl_ecls"}
    result["cardiovascular_include_pacemaker"] = True
    before = deepcopy(result)
    output = render_note_docx(result)
    root = tree(output)
    table = section_table(root, "CARDIOVASCULAR")
    rows = table.findall("w:tr", NS)
    labels = [text(row).strip() for row in rows]
    assert labels.count("EXTRACORPOREAL LIFE SUPPORT") == labels.count("PACEMAKER") == labels.count("MEDICATIONS") == 1
    pacer_index = labels.index("PACEMAKER")
    assert labels[pacer_index + 1] == "{ACKCVPACEMAKER:45347}"
    assert labels[pacer_index + 2] == "MEDICATIONS"
    assert labels.index("EXTRACORPOREAL LIFE SUPPORT") < pacer_index
    assert "@FLOW24(1120100493)@" in text(table)
    source, source_table = raw_table(CV_TEMPLATE_FILES["art_cvl_pacemaker"].read_bytes(), "CARDIOVASCULAR", normalize_pagination=True)
    source_rows = [node for node in source_table.children if node.name == note_word._W + "tr"]
    index = next(index for index, row in enumerate(source_rows) if note_word._text(row).strip() == "PACEMAKER")
    exact_rows = source[source_rows[index].start:source_rows[index + 1].end]
    document = without_heading_keep_next(package(output)["word/document.xml"])
    assert document.count(exact_rows) == 1
    assert "***" not in text(medication_cell(table))
    if populated:
        assert text(root).count("Synthetic Cardiovascular infusion at 2 mcg/kg/hr") == 1
    assert result == before


def test_clinical_heading_rows_keep_the_following_row_without_changing_visual_formatting():
    result = sample_result()
    result.update(neuro_variant="intubated", respiratory_variant="pc", cardiovascular_variant="art_cvl_ecls",
                  cardiovascular_include_pacemaker=True, fengi_variant="age_2_plus")
    root = tree(render_note_docx(result))
    checked = set()
    for table in root.iter(W + "tbl"):
        if text(next(table.iter(W + "p"))).strip() not in CLINICAL_TABLES:
            continue
        for row in table.findall("w:tr", NS)[:-1]:
            cells = row.findall("w:tc", NS)
            visible = [p for p in row.iter(W + "p") if text(p).strip()]
            if len(cells) != 1 or len(visible) != 1 or text(visible[0]).strip() not in SOURCE_HEADING_LABELS:
                continue
            keep = visible[0].find("w:pPr/w:keepNext", NS)
            assert keep is not None and keep.get(W + "val") in (None, "1", "true", "on")
            checked.add(text(visible[0]).strip())
    assert {"DETAILED REVIEW", "PERTINENT LABORATORY DATA", "MEDICATIONS",
            "ELECTROCARDIOGRAPHIC INTERPRETATION", "PACEMAKER"} <= checked


@pytest.mark.parametrize("first_group", ["Drips", "Scheduled", "PRN"])
def test_inline_group_labels_keep_the_first_medication_in_the_same_paragraph_without_keep_chains(first_group):
    values = [f"Synthetic layout medication {index} with a long recorded order description" for index in range(60)]
    result = {"cardiovascular_variant": "art_cvl_ecls", "cardiovascular_include_pacemaker": True,
              "medications": {"sections": {"Cardiovascular": {first_group: values}}}}
    if first_group != "PRN":
        result["medications"]["sections"]["Cardiovascular"]["PRN"] = ["Additional PRN medication"]
    root = tree(render_note_docx(result))
    table = section_table(root, "CARDIOVASCULAR")
    cell = medication_cell(table)
    paragraphs = cell.findall("w:p", NS)
    assert text(paragraphs[0]) == first_group + ": " + values[0]
    runs = paragraphs[0].findall("w:r", NS)
    assert len(runs) == 2 and text(runs[0]) == first_group + ": " and text(runs[1]) == values[0]
    assert runs[0].find("w:rPr/w:b", NS) is not None
    assert runs[1].find("w:rPr/w:b", NS) is None
    assert not paragraphs[0].findall(".//w:br", NS)
    assert not cell.findall(".//w:tbl", NS)
    for value in values:
        assert text(root).count(value) == 1
    for paragraph in paragraphs:
        assert paragraph.find("w:pPr/w:keepNext", NS).get(W + "val") == "0"
        assert paragraph.find("w:pPr/w:keepLines", NS).get(W + "val") == "0"


@pytest.mark.parametrize("flag", [False, True])
def test_pacemaker_template_is_never_given_duplicate_pacemaker_rows(flag):
    result = section_result("cv", "art_cvl_pacemaker")
    result["cardiovascular_include_pacemaker"] = flag
    output = render_note_docx(result)
    assert text(tree(output)).count("{ACKCVPACEMAKER:45347}") == 1


def test_ecls_without_pacemaker_never_reads_the_pacemaker_asset(tmp_path, monkeypatch):
    result = section_result("cv", "art_cvl_ecls")
    expected = render_note_docx(result)
    monkeypatch.setitem(CV_TEMPLATE_FILES, "art_cvl_pacemaker", tmp_path / "missing.docx")
    assert render_note_docx(result) == expected
    assert "{ACKCVPACEMAKER:45347}" not in text(tree(expected))
    result["cardiovascular_include_pacemaker"] = True
    with pytest.raises(NoteWordError, match="cardiovascular Word template is missing or invalid"):
        render_note_docx(result)


@pytest.mark.parametrize("correction,error", [
    ((b">PACEMAKER<", b">MISSING LABEL<"), "missing unique required pacemaker rows"),
    ((b'<w:gridCol w:w="3351"/>', b'<w:gridCol w:w="3352"/>'), "incompatible table grid"),
])
def test_invalid_pacemaker_row_source_fails_clearly(tmp_path, monkeypatch, correction, error):
    original = CV_TEMPLATE_FILES["art_cvl_pacemaker"].read_bytes()
    document = package(original)["word/document.xml"]
    changed = document.replace(*correction, 1)
    assert changed != document
    path = tmp_path / "invalid_pacemaker_rows.docx"
    write_with_document(original, changed, path)
    monkeypatch.setitem(CV_TEMPLATE_FILES, "art_cvl_pacemaker", path)
    with pytest.raises(NoteWordError, match=error):
        render_note_docx({"cardiovascular_variant": "art_cvl_ecls", "cardiovascular_include_pacemaker": True})


def test_approved_avaps_delimiter_correction_retains_the_supplied_heading_and_identifier():
    root = tree(render_note_docx({"respiratory_variant": "avaps"}))
    table = section_table(root, "RESPIRATORY")
    row = next(row for row in table.findall("w:tr", NS) if text(row).startswith("PS Min:"))
    assert text(row) == "PS Min:@FLOW24(3040000087)@"
    assert "INVASIVE MECHANICAL VENTILATOR SETTINGS" in text(table)


def test_legacy_missing_or_none_variants_preserve_generic_behavior_without_reading_new_assets(tmp_path, monkeypatch):
    result = sample_result()
    result.update(respiratory_variant=None, cardiovascular_variant=None, cardiovascular_include_pacemaker=True)
    expected = render_note_docx(result)
    for paths, _, _, _, _ in FAMILIES.values():
        for variant in paths:
            monkeypatch.setitem(paths, variant, tmp_path / "missing.docx")
    assert render_note_docx(result) == expected
    result.pop("respiratory_variant")
    result.pop("cardiovascular_variant")
    assert render_note_docx(result) == expected
    assert "{CKRESPLIST:45220}" in text(tree(expected)) and "{CKCVLIST:45328}" in text(tree(expected))


@pytest.mark.parametrize("metadata", [
    {"respiratory_variant": "nava", "cardiovascular_variant": "art_cvl_ecls", "cardiovascular_include_pacemaker": True},
    {"respiratory_variant": [], "cardiovascular_variant": "invalid", "cardiovascular_include_pacemaker": True},
])
def test_attestation_ignores_the_new_metadata_medications_and_unavailable_assets(metadata, tmp_path, monkeypatch):
    expected = render_note_docx(sample_result(), note_type="attestation")
    for paths, _, _, _, _ in FAMILIES.values():
        for variant in paths:
            monkeypatch.setitem(paths, variant, tmp_path / "missing.docx")
    result = sample_result()
    result.update(metadata)
    assert render_note_docx(result, note_type="attestation") == expected


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("variant", ["", "invalid", []])
def test_invalid_selected_variants_fail_clearly(family, variant):
    _, key, _, _, _ = FAMILIES[family]
    with pytest.raises(NoteWordError, match="selected .* Word template is invalid"):
        render_note_docx({key: variant})


@pytest.mark.parametrize("family", FAMILIES)
def test_missing_selected_assets_cannot_silently_drop_sections(family, tmp_path, monkeypatch):
    paths, key, _, _, _ = FAMILIES[family]
    monkeypatch.setitem(paths, "none", tmp_path / "missing.docx")
    with pytest.raises(NoteWordError, match="Word template is missing or invalid"):
        render_note_docx({key: "none"})


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("populated", [False, True])
def test_split_medication_placeholder_is_removed_without_changing_other_fields(family, populated, tmp_path, monkeypatch):
    paths, key, _, heading, _ = FAMILIES[family]
    original = paths["none"].read_bytes()
    document, table = raw_table(original, heading)
    placeholder = note_word._medication_placeholder(table)
    split = document[placeholder.start:placeholder.end].replace(
        b"<w:t>***</w:t>", b"<w:t>*</w:t></w:r><w:r><w:t>**</w:t>")
    assert split != document[placeholder.start:placeholder.end]
    changed = document[:placeholder.start] + split + document[placeholder.end:]
    path = tmp_path / "split_medication_placeholder.docx"
    write_with_document(original, changed, path)
    monkeypatch.setitem(paths, "none", path)
    result = section_result(family, "none") if populated else {key: "none"}
    root = tree(render_note_docx(result))
    assert "*" not in text(medication_cell(section_table(root, heading)))
    assert "with ***." in text(section_table(root, "ASSESSMENT"))
