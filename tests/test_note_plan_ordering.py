"""Synthetic integration checks for system-ordered plans in both note formats."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest

from categories import default_categories, target_snapshot
from lab_windows import display_clock
from medications import parse_medications
from models import new_sheet
from note_generator import generate_note, get_phrase_catalog
from note_word import render_note_docx
from viral import parse_viral_panel


NOW = datetime(2026, 11, 26, 18, tzinfo=timezone.utc)
STAMP = "11/26/2026 08:00"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SYSTEM_NAMES = ("Neurologic", "Respiratory", "Cardiovascular", "FEN / GI", "Hematology", "Infectious Disease")

SYSTEM_IDS = (
    {"agitation_intubated", "insomnia", "seizure_risk"},
    {"acute_hypoxemic_invasive", "tracheobronchomalacia"},
    {"arrhythmia", "hypertension"},
    {"gastric_ulcer_risk", "constipation"},
    {"anemia", "thrombocytopenia"},
    {"sepsis", "adenovirus", "covid19", "influenza", "parainfluenza", "rhinovirus", "rsv"},
)
VIRUS_IDS = {"adenovirus", "covid19", "influenza", "parainfluenza", "rhinovirus", "rsv"}
AUTO_IDS = {
    "agitation_intubated", "insomnia", "acute_hypoxemic_invasive",
    "tracheobronchomalacia", "arrhythmia", "gastric_ulcer_risk",
    "constipation", "anemia", "sepsis",
} | VIRUS_IDS


def _medication(name, dose, *, section, frequency="q12h", target=None):
    parsed = parse_medications("Medications:\n• " + "\t".join(
        (name, dose, "Intravenous", frequency, "", "", "")
    ))
    assert not parsed.error
    row = parsed.rows[0]
    row["section"] = section
    if target:
        row["category_path"] = target_snapshot(target, default_categories())
    return row


def _mixed_sheet():
    sheet = new_sheet("P4102")
    # Deliberately interleave systems in the source. The output must use the
    # requested system sequence independently of source and catalog order.
    sheet["fields"]["Diagnoses"] = "\n".join((
        "Sepsis", "Anemia", "Constipation", "Arrhythmia", "Insomnia",
        "Tracheobronchomalacia", "At risk for gastric ulcers",
    ))
    sheet["ventilation"] = {"mode": "PRVC", "values": {}}
    sheet["medications"] = [
        _medication("Fentanyl infusion", "2 mcg/kg/hr", section="Neurologic", frequency="Continuous"),
        _medication("Fentanyl", "20 mcg", section="Neurologic", frequency="q1h PRN"),
        _medication("Pantoprazole", "20 mg", section="FEN / GI", target="gi:prophylaxis"),
        _medication("Polyethylene glycol", "8.5 g", section="FEN / GI", target="gi:bowel"),
        _medication("Ceftriaxone", "500 mg", section="Infectious Disease", target="group:antibiotic"),
    ]
    viruses = parse_viral_panel("\n".join(
        component + "\tDetected (A)\t" + STAMP
        for component in ("RESPSYNVRNA", "FLUAVIRUSRNA", "ADENOVIRDNA",
                          "PARAFLU1RNA", "HUMRHINENRNA", "SARS-CoV-2")
    ))
    assert not viruses.error
    sheet["viral_panel"] = viruses.data
    return sheet


def _word_paragraphs(data):
    with ZipFile(BytesIO(data)) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
    return ["".join(part.text or "" for part in paragraph.iter(W + "t")).strip()
            for paragraph in document.iter(W + "p")]


def _assert_matching_plan_formats(result, note_type):
    tokens = result["selected_plan_tokens"]
    # Exact Plan paragraphs also reject additional system or subcategory
    # headings without forbidding the original template's examination labels.
    text_plan = result["text"].rsplit("\nPLAN\n", 1)[1]
    assert [line for line in text_plan.splitlines() if line.strip()] == tokens
    paragraphs = _word_paragraphs(render_note_docx(result, note_type=note_type))
    plan_index = paragraphs.index("PLAN")
    assert [line for line in paragraphs[plan_index + 1:] if line] == tokens
    return paragraphs


def _assert_plan_outputs(result, expected_ids, note_type):
    catalog = {row["id"]: row["phrase"] for row in get_phrase_catalog()}
    token_ids = {
        ("@" + catalog[key] + "@" if result["phrase_style"] == "at" else "." + catalog[key]): key
        for key in expected_ids
    }
    tokens = result["selected_plan_tokens"]
    assert len(tokens) == len(expected_ids)
    assert set(tokens) == set(token_ids)
    ordered_ids = [token_ids[token] for token in tokens]
    systems = {key: number for number, keys in enumerate(SYSTEM_IDS) for key in keys}
    assert [systems[key] for key in ordered_ids] == sorted(systems[key] for key in expected_ids)
    virus_positions = [index for index, key in enumerate(ordered_ids) if key in VIRUS_IDS]
    if virus_positions:
        assert virus_positions == list(range(virus_positions[0], virus_positions[-1] + 1))

    paragraphs = _assert_matching_plan_formats(result, note_type)
    for label in ("Bowel Regimen", "GI prophylaxis", "Antibiotics"):
        assert label not in result["text"]
        assert label not in paragraphs
    return paragraphs


@pytest.mark.parametrize("note_type", ["progress", "attestation"])
def test_first_generated_note_orders_systems_and_groups_detected_viruses(note_type):
    sheet = _mixed_sheet()
    before = deepcopy(sheet)
    with display_clock(NOW):
        result = generate_note(sheet, note_type=note_type)
    paragraphs = _assert_plan_outputs(result, AUTO_IDS, note_type)
    assert "@ACKZINSOMNIA@" in result["selected_plan_tokens"]
    assert "@ACKZTRACHEOBRONCHOMALACIA@" in result["selected_plan_tokens"]
    assert "@ACZKARRHYTHMIA@" in result["selected_plan_tokens"]
    if note_type == "progress":
        assert "Drips:" in paragraphs
        assert "Scheduled:" in paragraphs
        assert "PRN:" in paragraphs
        assert "Fentanyl at 2 mcg/kg/hr" in paragraphs
        assert "Fentanyl 20 mcg Q1H PRN" in paragraphs
    else:
        assert "MEDICATIONS FOR REVIEW" not in paragraphs
        assert not any("Fentanyl" in value or "Pantoprazole" in value for value in paragraphs)
    assert sheet == before


@pytest.mark.parametrize("note_type", ["progress", "attestation"])
@pytest.mark.parametrize("phrase_style", ["at", "dot"])
def test_manual_plan_selection_uses_system_order_instead_of_click_order(note_type, phrase_style):
    selected = [
        "rsv", "constipation", "arrhythmia", "anemia", "insomnia",
        "tracheobronchomalacia", "adenovirus", "seizure_risk", "sepsis",
        "hypertension", "thrombocytopenia", "influenza",
    ]
    sheet = _mixed_sheet()
    with display_clock(NOW):
        first = generate_note(sheet, selected_ids=selected, note_type=note_type, phrase_style=phrase_style)
        reversed_selection = generate_note(
            sheet, selected_ids=list(reversed(selected)), note_type=note_type, phrase_style=phrase_style,
        )
    _assert_plan_outputs(first, set(selected), note_type)
    _assert_plan_outputs(reversed_selection, set(selected), note_type)
    assert first["selected_plan_tokens"] == reversed_selection["selected_plan_tokens"]
    assert first["text"] == reversed_selection["text"]
    # Manual deselection still replaces automatic defaults.
    assert not any("ACKZACUTEHYPOXEMICRESPIRATORYFAILUREINVASIVE" in token
                   for token in first["selected_plan_tokens"])


def test_every_catalog_entry_has_one_system_and_catalog_systems_follow_requested_order():
    catalog = get_phrase_catalog()
    assert len(catalog) == 89
    assert len({row["id"] for row in catalog}) == len(catalog)
    assert {row["system"] for row in catalog} == set(SYSTEM_NAMES)
    positions = [SYSTEM_NAMES.index(row["system"]) for row in catalog]
    assert positions == sorted(positions)
    collapsed_systems = tuple(dict.fromkeys(row["system"] for row in catalog))
    assert collapsed_systems == SYSTEM_NAMES


@pytest.mark.parametrize("note_type", ["progress", "attestation"])
def test_all_infectious_plans_keep_viral_diagnoses_adjacent_in_text_and_word(note_type):
    catalog = get_phrase_catalog()
    infectious = [row for row in catalog if row["system"] == "Infectious Disease"]
    selected = [row["id"] for row in reversed(infectious)]
    with display_clock(NOW):
        result = generate_note(new_sheet("P4102"), selected_ids=selected, note_type=note_type)
    token_ids = {"@" + row["phrase"] + "@": row["id"] for row in infectious}
    assert len(result["selected_plan_tokens"]) == len(infectious)
    assert set(result["selected_plan_tokens"]) == set(token_ids)
    ordered_ids = [token_ids[token] for token in result["selected_plan_tokens"]]
    viral_ids = VIRUS_IDS | {"herpes_simplex_encephalitis"}
    assert set(ordered_ids[-len(viral_ids):]) == viral_ids
    assert set(ordered_ids[:-len(viral_ids)]) == set(selected) - viral_ids
    _assert_matching_plan_formats(result, note_type)


@pytest.mark.parametrize("note_type", ["progress", "attestation"])
@pytest.mark.parametrize("phrase_style", ["at", "dot"])
def test_milrinone_and_low_albumin_follow_cv_then_fengi_in_both_exports(note_type, phrase_style):
    from labs import parse_labs

    sheet = new_sheet("P4102")
    sheet["medications"] = [_medication(
        "Milrinone infusion", "0.5 mcg/kg/min", section="Cardiovascular",
        frequency="Continuous", target="group:inotrope",
    )]
    parsed = parse_labs("Labs:\nALB\t2.1 (L)\t" + STAMP)
    assert not parsed.error
    sheet["labs"] = parsed.data
    before = deepcopy(sheet)
    with display_clock(NOW):
        result = generate_note(sheet, note_type=note_type, phrase_style=phrase_style)
    names = ("ACKZHEARTFAILURE", "ACKZHYPOALBUMINEMIA")
    expected = ["@" + name + "@" if phrase_style == "at" else "." + name for name in names]
    assert result["selected_plan_tokens"] == expected
    paragraphs = _assert_matching_plan_formats(result, note_type)
    if note_type == "attestation":
        assert not any("Milrinone" in line for line in paragraphs)
    else:
        assert "Milrinone at 0.5 mcg/kg/min" in paragraphs
    assert sheet == before
