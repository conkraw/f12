"""Focused source and export checks for the seven newly supplied diagnoses."""
from copy import deepcopy
from io import BytesIO
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest

from models import new_sheet
from note_generator import generate_note, get_phrase_catalog
from note_word import render_note_docx


PHRASES = {
    "hlhs": "ACKZHLHS",
    "chylous_effusion": "ACKZCHYLOUSEFFUSION",
    "prematurity": "ACKZPREMATURITY",
    "trisomy13": "ACKZTRISOMY13",
    "trisomy18": "ACKZTRISOMY18",
    "trisomy21": "ACKZTRISOMY21",
    "metachromatic_leukodystrophy": "ACKZMETACHROMATICLEUKODYSTROPHY",
}
SAMPLE_NAMES = {
    "hlhs": "HLHS", "chylous_effusion": "Chylothorax", "prematurity": "Prematurity",
    "trisomy13": "Trisomy 13", "trisomy18": "Trisomy 18", "trisomy21": "Down syndrome",
    "metachromatic_leukodystrophy": "Metachromatic leukodystrophy",
}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def source(diagnoses="", demographics=""):
    sheet = new_sheet("P4102")
    sheet["fields"]["Diagnoses"] = diagnoses
    sheet["fields"]["Demographics / Weight"] = demographics
    return sheet


def included(diagnoses="", demographics="", **kwargs):
    result = generate_note(source(diagnoses, demographics), note_type="attestation", **kwargs)
    return {row["id"] for row in result["suggestions"] if row["selected"]}


@pytest.mark.parametrize("key,diagnosis", [
    ("hlhs", "HLHS"),
    ("hlhs", "Hypoplastic left heart syndrome"),
    ("hlhs", "Hypoplastic-left-heart-syndrome"),
    ("hlhs", "History of HLHS"),
    ("hlhs", "PMH: hypoplastic left heart syndrome"),
    ("hlhs", "S/p repair of HLHS"),
    ("chylous_effusion", "Chylothorax"),
    ("chylous_effusion", "Chylous pleural effusion"),
    ("chylous_effusion", "Chylous effusion"),
    ("chylous_effusion", "Pleural effusion (chylous)"),
    ("trisomy13", "Trisomy13"),
    ("trisomy13", "Trisomy 13"),
    ("trisomy13", "T13"),
    ("trisomy13", "Patau syndrome"),
    ("trisomy13", "Patau's syndrome"),
    ("trisomy13", "47,XX,+13"),
    ("trisomy18", "Trisomy-18"),
    ("trisomy18", "T18"),
    ("trisomy18", "Edwards syndrome"),
    ("trisomy18", "Edwards’ syndrome"),
    ("trisomy18", "47, XY, +18"),
    ("trisomy21", "Trisomy 21"),
    ("trisomy21", "T21"),
    ("trisomy21", "Down syndrome"),
    ("trisomy21", "Down's syndrome"),
    ("trisomy21", "Down’s syndrome"),
    ("trisomy21", "47,XY,+21"),
    ("trisomy21", "History of Down syndrome"),
    ("trisomy21", "PMH: Down syndrome"),
    ("metachromatic_leukodystrophy", "Metachromatic leukodystrophy"),
    ("metachromatic_leukodystrophy", "Metachromatic leucodystrophy"),
    ("metachromatic_leukodystrophy", "Late infantile MLD"),
    ("metachromatic_leukodystrophy", "Juvenile MLD"),
    ("metachromatic_leukodystrophy", "Adult-onset MLD"),
    ("metachromatic_leukodystrophy", "MLD"),
    ("metachromatic_leukodystrophy", "Diagnosis: MLD"),
    ("metachromatic_leukodystrophy", "Primary diagnosis: MLD"),
    ("metachromatic_leukodystrophy", "Metachromatic leukodystrophy (MLD)"),
    ("metachromatic_leukodystrophy", "History of metachromatic leukodystrophy"),
])
def test_exact_new_diagnoses_and_bounded_aliases_are_automatically_included(key, diagnosis):
    assert included(diagnosis) & PHRASES.keys() == {key}


@pytest.mark.parametrize("diagnosis", [
    "Prematurity", "History of prematurity", "Hx of prematurity", "PMH: prematurity",
    "Former premature infant", "Premature infant of 30 weeks gestation",
    "Preterm newborn, gestational age 32 completed weeks",
    "Born prematurely", "Born preterm", "Born at 28 weeks", "Delivered at 36 weeks 6 days",
    "Ex-28-week infant", "ex 32 weeker", "ex32wk", "Ex-29+4-week infant", "Former 35-week infant",
    "Birth GA: 36w6d", "Birth gestational age: 36 6/7 weeks", "Gestational age at birth: 30 weeks",
    "Birth history:\nGestational age: 32 weeks", "Possible prematurity", "Possible ex-32-week infant",
])
def test_documented_prematurity_and_birth_gestation_remain_patient_status(diagnosis):
    assert "prematurity" in included(diagnosis)


@pytest.mark.parametrize("demographics", [
    "Age: 4 months\nBirth GA: 32w4d", "Born at 36 weeks 6 days\nCurrent age: 12 weeks",
    "Birth history:\nGestational age: 34 weeks\nAge: 7 months",
    "History of prematurity\nAge: 2 years",
])
def test_explicit_birth_history_in_demographics_is_supported_without_using_current_age(demographics):
    assert included(demographics=demographics) & PHRASES.keys() == {"prematurity"}


@pytest.mark.parametrize("diagnosis", [
    "Age: 32 weeks", "32-week-old infant", "Corrected age: 28 weeks", "Postmenstrual age: 35 weeks",
    "HC Age: 30 weeks", "Gestational age: 32 weeks", "Born 30 weeks ago", "Born at 3 weeks of age",
    "Term newborn", "Full-term infant", "Born at 37 weeks", "Birth GA: 37w0d", "Born at 40 weeks",
    "Possible ex-37-week infant", "Possible birth GA: 40 weeks", "Birth GA: 36w7d", "Birth GA: 0 weeks",
    "Low birth weight infant", "Very low birth weight", "Premature atrial contractions",
    "Premature ventricular contractions", "Premature rupture of membranes", "Preterm labor",
    "Prenatal concern for prematurity", "Possible fetal preterm birth", "At risk for prematurity",
    "History of possible prematurity", "No history of prematurity", "Prematurity ruled out",
    "Mother was born at 32 weeks", "Sibling born at 30 weeks", "Family history of prematurity",
    "Prematurity in mother", "Prematurity (family history)", "Family history:\nPrematurity",
])
def test_current_age_term_birth_and_nonpatient_or_unproven_prematurity_do_not_create_the_plan(diagnosis):
    assert "prematurity" not in included(diagnosis, demographics=diagnosis)


@pytest.mark.parametrize("key", PHRASES)
@pytest.mark.parametrize("template", [
    "No {}", "Negative for {}", "Not consistent with {}", "{} ruled out", "{} (resolved)",
    "Family history of {}", "Maternal history of {}", "Mother has {}", "Sibling: {}",
    "{} in father", "{} (family history)", "FHx: {}", "Family history:\n{}", "{}: No", "{}: None",
    "Not currently diagnosed with {}", "No currently diagnosed {}",
])
def test_new_diagnoses_respect_negation_resolution_and_family_history(key, template):
    assert key not in included(template.format(SAMPLE_NAMES[key]))


@pytest.mark.parametrize("diagnosis", [
    "Hypoplastic aortic arch", "Hypoplastic left ventricle", "Hypoplastic left heart valve",
    "HLHS2", "T130", "T180", "T210", "AT21", "Trisomy 21q duplication", "Trisomy 130",
    "Downward gaze", "Patau screening", "Edwards device", "46,XX", "46,XY,dup(21q)",
    "46,XX,rob(14;21)", "47,XY,+210", "47,XY,+8", "Maximum daily dose (MLD)",
    "Manual lymphatic drainage (MLD)", "PT: MLD daily", "MLD dose 10 mg",
    "Arylsulfatase A deficiency", "ARSA gene variant",
    "Prenatal concern for trisomy 21", "NIPT positive for T21", "Screening for trisomy 18",
    "Non-chylous pleural effusion", "Nonchylous pleural effusion",
])
def test_similar_words_screening_and_ambiguous_abbreviations_do_not_add_new_diagnoses(diagnosis):
    assert not included(diagnosis) & PHRASES.keys()


def test_chylous_evidence_does_not_duplicate_generic_effusion_but_separate_disease_is_retained():
    assert included("Chylous pleural effusion") == {"chylous_effusion"}
    assert included("Pleural effusion (chylous)") == {"chylous_effusion"}
    assert included("Chylous pleural effusion\nEmpyema") == {"chylous_effusion", "pleural_effusion_empyema"}
    assert included("Chylothorax\nOther pleural effusion") == {"chylous_effusion", "pleural_effusion_empyema"}
    assert included("History of chylothorax") == set()


def test_family_history_does_not_cancel_a_separate_explicit_patient_condition():
    assert included("Family history:\nDown syndrome\nPatient:\nDown syndrome") == {"trisomy21"}
    assert included("HLHS\nNo family history of HLHS") == {"hlhs"}
    assert included("History of prematurity\nFamily history of prematurity") == {"prematurity"}


def test_term_birth_conflicting_with_prematurity_is_not_automatically_selected():
    result = generate_note(source("Prematurity\nBirth GA: 40 weeks"), note_type="attestation")
    row = next(row for row in result["suggestions"] if row["id"] == "prematurity")
    assert row["selected"] is False
    assert "@ACKZPREMATURITY@" not in result["selected_plan_tokens"]


@pytest.mark.parametrize("note_type", ["progress", "attestation"])
@pytest.mark.parametrize("style", ["at", "dot"])
def test_new_tokens_are_deduplicated_system_ordered_editable_and_identical_in_word(note_type, style):
    sheet = source("\n".join((
        "HLHS", "Chylothorax", "Metachromatic leukodystrophy", "Metachromatic leukodystrophy, ARSA-related",
        "Trisomy21", "History of prematurity", "Patau syndrome", "Edwards syndrome",
        "Hypoalbuminemia", "Anemia", "Sepsis",
    )))
    before = deepcopy(sheet)
    result = generate_note(sheet, note_type=note_type, phrase_style=style)
    expected_ids = ["metachromatic_leukodystrophy", "prematurity", "trisomy13", "trisomy18", "trisomy21",
                    "chylous_effusion", "hlhs", "hypoalbuminemia", "anemia", "sepsis"]
    catalog = {row["id"]: row for row in get_phrase_catalog()}
    expected = ["@" + catalog[key]["phrase"] + "@" if style == "at" else "." + catalog[key]["phrase"] for key in expected_ids]
    assert result["selected_plan_tokens"] == expected
    assert len(expected) == len(set(expected))
    assert result["text"].split("\nPLAN\n", 1)[1].split() == expected
    with ZipFile(BytesIO(render_note_docx(result, note_type=note_type))) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = ["".join(t.text or "" for t in p.iter(W + "t")) for p in document.iter(W + "p")]
    assert [p for p in paragraphs[paragraphs.index("PLAN") + 1:] if p] == expected
    assert sheet == before
    manual = generate_note(sheet, selected_ids=["hlhs", "trisomy21"], note_type=note_type)
    assert manual["selected_plan_tokens"] == ["@ACKZTRISOMY21@", "@ACKZHLHS@"]
    assert generate_note(sheet, selected_ids=[], note_type=note_type)["selected_plan_tokens"] == []


def test_new_catalog_entries_preserve_six_system_order_and_exact_names():
    catalog = get_phrase_catalog()
    by_id = {row["id"]: row for row in catalog}
    for key, phrase in PHRASES.items():
        assert by_id[key]["phrase"] == phrase and by_id[key]["verified"] is True
    assert by_id["metachromatic_leukodystrophy"]["system"] == "Neurologic"
    assert by_id["chylous_effusion"]["system"] == "Respiratory"
    assert by_id["hlhs"]["system"] == "Cardiovascular"
    assert list(dict.fromkeys(row["system"] for row in catalog)) == [
        "Neurologic", "Respiratory", "Cardiovascular", "FEN / GI", "Hematology", "Infectious Disease",
    ]
    assert len(catalog) == 96


def test_custom_diagnosis_destination_and_duplicate_source_lines_remain_read_only():
    sheet = source("Metachromatic leukodystrophy")
    sheet["fields"]["Cardiovascular"] = "HLHS\nChylous pleural effusion\nMetachromatic leukodystrophy"
    before = deepcopy(sheet)
    result = generate_note(sheet, settings={"diagnoses_destination": "Cardiovascular"}, note_type="attestation")
    assert result["selected_plan_tokens"] == ["@ACKZMETACHROMATICLEUKODYSTROPHY@", "@ACKZCHYLOUSEFFUSION@", "@ACKZHLHS@"]
    assert sheet == before
