"""Handoff-selected neurologic tables in the preview and actual Word note."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest

from devices import parse_devices
from note_generator import generate_note
from note_neuro import NEURO_TEMPLATE_FILES
from note_word import render_note_docx
from test_note_generator import order, sheet_with
from vitals import parse_vitals


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
VARIANTS = (
    ("tbi", "ACKNTBI", "GLASGOW COMA SCALE"),
    ("icp_monitoring", "ACKNICPMONITORING", "INTRACRANIAL PRESSURE MONITORING"),
    ("status_epilepticus", "ACKNSTATUSEPI", "PERTINENT ELECTROENCEPHALOGRAM DATA"),
    ("ct_patient", "ACKNCTPATIENT", "CEREBRAL OXIMETRY MONITORING"),
    ("intubated", "ACKNINTUBATED", "SBS Score:"),
    ("extubated", "ACKNEXTUBATED", "CAPD:"),
    ("none", "ACKNNONE", "PHYSICAL EXAMINATION"),
)


def example(variant):
    sheet = sheet_with(
        order("Fentanyl infusion", "2 mcg/kg/hr", frequency="Continuous"),
        order("Clobazam", "100 mg", route="Oral"),
        order("Fentanyl injection", "20 mcg", frequency="q1h PRN"),
        order("Pantoprazole", "20 mg", section="FEN / GI"),
    )
    sheet["anthropometrics"] = {"age": "24 months"}
    if variant == "tbi":
        sheet["fields"]["Diagnoses"] = "Traumatic brain injury"
    elif variant == "status_epilepticus":
        sheet["fields"]["Diagnoses"] = "Refractory status epilepticus"
    elif variant == "icp_monitoring":
        result = parse_devices(
            "Intracranial Pressure/Ventriculostomy Ventricular drainage catheter with ICP microsensor-Drain Status: Clamped", "v")
        assert not result.error
        sheet["neuro_devices"] = result.data
    elif variant == "ct_patient":
        result = parse_vitals("NIRS Range: rSO2 Cerebral % Avg: 62.8 % Min: 60 % Max: 68 %\nLast NIRS: rSO2 Cerebral %: 66 %")
        assert not result.error
        sheet["vitals"] = result.rows
    elif variant == "intubated":
        sheet["ventilation"] = {"mode": "PRVC", "values": {}}
    elif variant == "extubated":
        sheet["fields"]["Respiratory"] = "Extubated to HFNC today."
        sheet["noninvasive"] = [{"device": "HFNC", "values": {}}]
    return sheet


def tree(payload):
    with ZipFile(BytesIO(payload)) as archive:
        return ET.fromstring(archive.read("word/document.xml"))


def text(node):
    return "".join(part.text or "" for part in node.iter(W + "t"))


def section(root, title):
    return next(item for item in root.iter(W + "tbl")
                if text(next(item.iter(W + "p"))) == title)


def medication_cell(table):
    rows = table.findall(W + "tr")
    index = next(index for index, row in enumerate(rows) if text(row).strip() == "MEDICATIONS")
    return rows[index + 1].find(W + "tc")


@pytest.mark.parametrize("variant,phrase,distinctive", VARIANTS)
def test_all_seven_selected_sections_have_neuro_medications_once_in_the_correct_cell(variant, phrase, distinctive):
    sheet = example(variant)
    before = deepcopy(sheet)
    result = generate_note(sheet)
    assert result["neuro_variant"] == variant
    assert result["neuro_phrase"] == phrase
    assert result["neuro_reason"]
    assert result["neuro_label"]
    plain = result["text"].split("NEUROLOGY", 1)[1].split("{CKRESPLIST:45220}", 1)[0]
    root = tree(render_note_docx(result))
    neuro = section(root, "NEUROLOGY")
    cell = medication_cell(neuro)
    assert "{CKNEUROSMARTLIST:45213}" not in result["text"] + text(root)
    assert "{ACKNEUROEXAM:45450}" in plain and "{ACKNEUROEXAM:45450}" in text(neuro)
    assert distinctive in plain and distinctive in text(neuro)
    assert "Pantoprazole" not in plain + text(neuro)
    assert "***" not in plain + text(cell)
    assert "MEDICATIONS FOR REVIEW" not in plain + text(neuro)
    assert "MEDICATIONS IN REVIEW" not in plain + text(neuro)
    if variant in ("tbi", "icp_monitoring"):
        assert plain.count("{ICPMONITORSITE:45483}") == text(neuro).count("{ICPMONITORSITE:45483}") == 1
        assert "{???}" not in plain + text(neuro)
    for group in ("Drips", "Scheduled", "PRN"):
        assert group + ":" in plain and group + ":" in text(cell)
        for medication in result["medications"]["sections"]["Neurologic"][group]:
            assert result["text"].count(medication) == text(root).count(medication) == 1
            assert medication in plain and medication in text(cell)
    paragraphs = [text(p) for p in root.iter(W + "p")]
    assert paragraphs.index("OBJECTIVE") < paragraphs.index("NEUROLOGY") < paragraphs.index("{CKRESPLIST:45220}")
    assert result["fengi_variant"] == "age_2_plus"
    assert "Body Mass Index:" in text(root)
    assert text(root).count("***") == result["text"].count("***") == 2
    assert sheet == before


@pytest.mark.parametrize("variant,phrase,distinctive", VARIANTS)
def test_empty_neuro_medication_cell_removes_its_placeholder_without_removing_exam_or_monitoring(variant, phrase, distinctive):
    sheet = example(variant)
    sheet["medications"] = []
    result = generate_note(sheet)
    assert result["neuro_variant"] == variant
    root = tree(render_note_docx(result))
    neuro = section(root, "NEUROLOGY")
    cell = medication_cell(neuro)
    assert text(cell).strip() == "" and cell.find(W + "p") is not None
    assert "{ACKNEUROEXAM:45450}" in text(neuro)
    assert distinctive in text(neuro)
    assert "***" not in text(neuro)
    if variant in ("tbi", "icp_monitoring"):
        assert "{ICPMONITORSITE:45483}" in text(neuro)
        assert "{???}" not in text(neuro)
    if variant == "status_epilepticus":
        assert text(neuro).count("{ACKNIMAGES:45359}") == 2


def test_plan_edits_do_not_change_the_section_selected_from_the_handoff():
    sheet = example("intubated")
    result = generate_note(sheet, selected_ids=["tbi", "status_epilepticus"])
    assert result["neuro_variant"] == "intubated"
    assert "@ACKZTBI@" in result["text"] and "@ACKZSTATUSEPILEPTICUS@" in result["text"]
    assert "GLASGOW COMA SCALE" not in result["text"]


def test_custom_diagnosis_destination_can_select_the_neuro_section():
    sheet = example("none")
    sheet["fields"]["Other"] = "Traumatic brain injury"
    result = generate_note(sheet, settings={"diagnoses_destination": "Other"})
    assert result["neuro_variant"] == "tbi"


def test_recorded_current_icp_readings_select_monitoring_without_a_device_inventory():
    from observations import parse_neuro

    sheet = example("none")
    parsed = parse_neuro("ICP Mean (mmHg): 5 mmHg\nCPP: 72 mmHg", "m")
    assert not parsed.error
    sheet["neuro_vitals"]["m"] = parsed.rows
    assert sheet["neuro_devices"] is None
    before = deepcopy(sheet)
    result = generate_note(sheet)
    assert result["neuro_variant"] == "icp_monitoring"
    neuro = section(tree(render_note_docx(result)), "NEUROLOGY")
    assert "INTRACRANIAL PRESSURE MONITORING" in text(neuro)
    assert "Fentanyl at 2 mcg/kg/hr" in text(medication_cell(neuro))
    assert sheet == before


def test_missing_selected_template_fails_clearly_without_patient_data(tmp_path, monkeypatch):
    monkeypatch.setitem(NEURO_TEMPLATE_FILES, "tbi", tmp_path / "missing.docx")
    sheet = example("tbi")
    with pytest.raises(ValueError, match="neurologic template could not be read") as error:
        generate_note(sheet)
    assert sheet["room"] not in str(error.value)


@pytest.mark.parametrize("variant,phrase,distinctive", VARIANTS)
def test_attestation_does_not_acquire_neuro_tables_or_medications(variant, phrase, distinctive):
    result = generate_note(example(variant), note_type="attestation")
    assert result["neuro_variant"] is None
    assert result["neuro_phrase"] == result["neuro_reason"] == ""
    root = tree(render_note_docx(result, note_type="attestation"))
    for value in ("NEUROLOGY", "Fentanyl", "Clobazam", "Drips:", "Scheduled:", "PRN:"):
        assert value not in result["text"] + text(root)
    assert text(root).count("***") == result["text"].count("***") == 1
