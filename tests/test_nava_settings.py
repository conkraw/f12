"""Synthetic respiratory-only checks for dedicated invasive NAVA settings."""
from copy import deepcopy
from io import BytesIO
import re

import pytest
from pypdf import PdfReader

from exports import handoff_html, handoff_pdf, handoff_text
from importing import import_sections
from models import fields_with_medications, new_sheet, new_vault, save_sheet_in
from noninvasive import parse_respiratory
from security import generate_key, open_vault, seal_vault
from ventilation import LABELS, format_ventilation, parse_ventilation, validate_ventilation


MODE = "Neurally Adjusted Ventilatory Assist"
GENERAL = """Invasive Ventilation:
Mode: Vent Mode: Neurally Adjusted Ventilatory Assist
Respiratory Rate: Resp Rate (Set): 16
Set PIP:
Observed PIP: PIP Observed (cm H2O)  Avg: 24.9 cm H2O  Min: 21 cm H2O  Max: 31 cm H2O
Set TV: Vt (Set, mL): 35 mL
Observed TV: Vt Insp ml  Avg: 32.9  Min: 23  Max: 47
Set PEEP: PEEP (cm H2O): 5 cm H2O
Inspiratory Time: Insp Time (sec): 0.8 sec
FiO2: FiO2 set (%): 25 %
Pressure Support: Pressure Support (cm H2O): 12 cm H20
Home Ventilator Settings:
Pmin:
Pmax:
Timin:
Timax:"""
NAVA_ROWS = (
    "NAVA Level: NAVA level: 3",
    "Set PEEP: PEEP (cm H2O): 5 cm H2O",
    "Set FIO2: FiO2 (%): 21 %",
    "EDI Peak: EDI peak  Avg: 7.8  Min: 3.1  Max: 13.6",
    "EDI Min: EDI min  Avg: 0.8  Min: 0.1  Max: 3",
    "Observed PIP: PIP Observed (cm H2O)  Avg: 24.9 cm H2O  Min: 21 cm H2O  Max: 31 cm H2O",
    "Observed Tidal Volume: Vt (observed, mL)  Avg: 32.8 mL  Min: 22 mL  Max: 57 mL",
    "Observed Respiratory Rate: Resp Rate Observed  Avg: 32.8  Min: 24  Max: 45",
    "Apnea Time: Apnea Interval (sec): 10 seconds",
)
FIELDS = "NAVA Ventilator Settings:\n" + "\n".join(NAVA_ROWS)
BODY = GENERAL + "\n" + FIELDS
EXPECTED = """Mode: NAVA
NAVA Level: 3 cm H2O/µV
Set PEEP: 5 cm H2O
FiO2: 21 %
Edi Peak: 3.1–13.6 µV
Edi Min: 0.1–3 µV
Observed PIP: 21–31 cm H2O
Observed TV: 22–57 mL
Observed RR: 24–45 breaths/min
Apnea Time: 10 seconds"""


def parsed(source=BODY):
    result = parse_ventilation(source)
    assert not result.error, result.error
    assert result.status == "included"
    assert result.data is not None
    return result


def selected_fields(rows):
    return GENERAL + "\nNAVA Ventilator Settings:\n" + "\n".join(rows)


def test_dedicated_nava_settings_and_ranges_replace_generic_fields():
    result = parsed()
    before = deepcopy(result.data)
    assert format_ventilation(result.data) == EXPECTED
    assert result.data == before
    assert result.data["values"] == {
        "NAVA level": "3",
        "PEEP (cm H2O)": "5 cm H2O",
        "FiO2 (%)": "21 %",
        "EDI peak": "Avg: 7.8  Min: 3.1  Max: 13.6",
        "EDI min": "Avg: 0.8  Min: 0.1  Max: 3",
        "PIP Observed (cm H2O)": "Avg: 24.9 cm H2O  Min: 21 cm H2O  Max: 31 cm H2O",
        "Vt (observed, mL)": "Avg: 32.8 mL  Min: 22 mL  Max: 57 mL",
        "Resp Rate Observed": "Avg: 32.8  Min: 24  Max: 45",
        "Apnea Interval (sec)": "10 seconds",
    }
    validate_ventilation(result.data)
    assert not any("Resp Rate (Set)" in issue for issue in result.issues)


@pytest.mark.parametrize("mode", [MODE, "NAVA"])
def test_full_and_abbreviated_invasive_modes_use_nava_section(mode):
    assert format_ventilation(parsed(BODY.replace(MODE, mode, 1)).data) == EXPECTED


def test_shared_respiratory_reader_does_not_reject_generic_nava_conflicts():
    generic = GENERAL.replace("PEEP (cm H2O): 5", "PEEP (cm H2O): 8")
    generic = generic.replace(
        "Avg: 24.9 cm H2O  Min: 21 cm H2O  Max: 31 cm H2O",
        "Avg: 44 cm H2O  Min: 40 cm H2O  Max: 47 cm H2O",
    )
    result = parse_respiratory(generic + "\n" + FIELDS, None)
    assert not result.error, result.error
    assert result.devices == []
    assert format_ventilation(result.invasive) == EXPECTED


def test_conflicting_unused_generic_settings_do_not_replace_nava_source():
    source = GENERAL + "\nPEEP (cm H2O): 9 cm H2O\n" + FIELDS
    result = parse_respiratory(source, None)
    assert not result.error, result.error
    assert format_ventilation(result.invasive) == EXPECTED


@pytest.mark.parametrize("index,label", [
    (0, "NAVA Level:"),
    (1, "Set PEEP:"),
    (2, "FiO2:"),
    (3, "Edi Peak:"),
    (4, "Edi Min:"),
    (5, "Observed PIP:"),
    (6, "Observed TV:"),
    (7, "Observed RR:"),
    (8, "Apnea Time:"),
])
def test_missing_dedicated_values_do_not_borrow_from_generic_or_niv(index, label):
    rows = [row for i, row in enumerate(NAVA_ROWS) if i != index]
    d = """Non-invasive Ventilation:
O2 Delivery Method: Endotracheal tube
FiO2 (%): 80 %
EPAP (cm H2O): 10 cm H2O"""
    result = parse_respiratory(selected_fields(rows), d)
    assert not result.error, result.error
    assert result.devices == []
    output = format_ventilation(result.invasive)
    assert not any(line.startswith(label) for line in output.splitlines())
    assert "Set RR:" not in output
    assert "Set TV:" not in output
    assert "Pressure Support:" not in output
    assert "Inspiratory Time:" not in output


@pytest.mark.parametrize("placeholder", ["", "--", "No data recorded", "N/A", "None"])
def test_empty_and_placeholder_nava_fields_cannot_restore_generic_values(placeholder):
    rows = [row.split(":", 1)[0] + ": " + placeholder for row in NAVA_ROWS]
    result = parsed(selected_fields(rows))
    assert result.data["values"] == {}
    assert format_ventilation(result.data) == "Mode: NAVA"


def test_empty_nava_section_is_authoritative():
    result = parsed(selected_fields([]))
    assert result.data["values"] == {}
    assert format_ventilation(result.data) == "Mode: NAVA"


def test_scalar_observations_are_not_turned_into_ranges():
    replacements = {
        3: "EDI Peak: EDI peak: 7.8",
        4: "EDI Min: EDI min: 0.8",
        5: "Observed PIP: PIP Observed (cm H2O): 24.9 cm H2O",
        6: "Observed Tidal Volume: Vt (observed, mL): 32 mL",
        7: "Observed Respiratory Rate: Resp Rate Observed: 32",
    }
    rows = [replacements.get(i, row) for i, row in enumerate(NAVA_ROWS)]
    output = format_ventilation(parsed(selected_fields(rows)).data)
    for line in (
        "Edi Peak: 7.8 µV",
        "Edi Min: 0.8 µV",
        "Observed PIP: 24.9 cm H2O",
        "Observed TV: 32 mL",
        "Observed RR: 32 breaths/min",
    ):
        assert line in output.splitlines()
    assert "–" not in output


@pytest.mark.parametrize("stats,expected_tokens", [
    ("Avg: 7.8", ("Avg: 7.8",)),
    ("Avg: 7.8 Min: 3.1", ("Avg: 7.8", "Min: 3.1")),
    ("Avg: 7.8 Max: 13.6", ("Avg: 7.8", "Max: 13.6")),
])
def test_partial_statistics_do_not_fabricate_a_missing_range_bound(stats, expected_tokens):
    rows = list(NAVA_ROWS)
    rows[3] = "EDI Peak: EDI peak " + stats
    output = format_ventilation(parsed(selected_fields(rows)).data)
    peak = next(line for line in output.splitlines() if line.startswith("Edi Peak:"))
    assert all(token in peak for token in expected_tokens)
    assert "–" not in peak
    assert re.search(r"\d\s*-\s*\d", peak) is None


@pytest.mark.parametrize("extra", [
    "NAVA Level: NAVA level: 4",
    "Set PEEP: PEEP (cm H2O): 8 cm H2O",
    "Set FIO2: FiO2 (%): 30 %",
    "EDI Peak: EDI peak Avg: 9 Min: 4 Max: 16",
])
def test_conflicting_repeated_fields_within_nava_still_fail(extra):
    result = parse_respiratory(BODY + "\n" + extra, None)
    assert result.error
    assert result.invasive is None


def test_identical_nava_repetitions_do_not_duplicate_output():
    result = parsed(BODY + "\n" + NAVA_ROWS[0] + "\n" + NAVA_ROWS[2])
    assert format_ventilation(result.data) == EXPECTED


@pytest.mark.parametrize("mode", [
    "Pressure Control",
    "Volume Targeted Pressure Control - Continuous Mandatory Ventilation",
    "Average Volume-Assured Pressure Support",
])
def test_nava_subsection_does_not_change_other_invasive_modes(mode):
    generic = GENERAL.replace(MODE, mode, 1)
    generic = generic.replace("PEEP (cm H2O): 5", "PEEP (cm H2O): 8")
    baseline = parse_respiratory(generic, None)
    with_nava = parse_respiratory(generic + "\n" + FIELDS, None)
    assert not baseline.error
    assert not with_nava.error, with_nava.error
    assert with_nava.invasive == baseline.invasive
    assert format_ventilation(with_nava.invasive) == format_ventilation(baseline.invasive)


def test_nava_niv_remains_noninvasive_and_uses_its_existing_source():
    generic = GENERAL.replace(MODE, MODE + " - Non Invasive Ventilation", 1)
    generic = generic.replace("PEEP (cm H2O): 5", "PEEP (cm H2O): 8")
    result = parse_respiratory(generic + "\n" + FIELDS, None)
    assert not result.error, result.error
    assert result.invasive is None
    assert len(result.devices) == 1
    assert result.devices[0]["device"] == "NAVA NIV"
    assert result.devices[0]["values"] == {
        "Set RR": "16", "EPAP": "8 cm H2O", "FiO2": "25 %",
    }


def test_nava_subsection_does_not_identify_an_unknown_or_missing_mode():
    unknown = parse_ventilation(BODY.replace(MODE, "Synthetic unknown mode", 1))
    assert not unknown.error
    assert unknown.status == "unknown" and unknown.data is None
    missing = parse_ventilation(FIELDS)
    assert missing.data is None


def test_conflicting_modes_are_not_resolved_by_the_nava_heading():
    source = GENERAL + "\nVent Mode: Pressure Control\n" + FIELDS
    result = parse_respiratory(source, None)
    assert result.error and result.invasive is None


def test_case_spacing_markers_and_crlf_keep_nava_source_selection():
    source = BODY.replace(
        "NAVA Ventilator Settings:", "  nAvA   Ventilator   settings:   "
    ).replace(
        NAVA_ROWS[0], "(S) nava level: (S) NAVA level: (S) 3"
    ).replace(
        "EDI Peak: EDI peak", "edi   peak: EDI PEAK"
    ).replace("\n", "\r\n")
    assert format_ventilation(parsed(source).data) == EXPECTED


def test_following_home_vent_section_does_not_override_nava():
    following = """Home Ventilator Settings:
Pmin: 12 cm H2O
Pmax: 30 cm H2O
Set PEEP: PEEP (cm H2O): 9 cm H2O
FiO2: FiO2 set (%): 45 %"""
    source = "Invasive Ventilation:\nVent Mode: " + MODE + "\n" + FIELDS + "\n" + following
    assert format_ventilation(parsed(source).data) == EXPECTED


def test_other_modes_keep_fields_after_nava_section_ends():
    after = """Home Ventilator Settings:
Pmin: 12 cm H2O
Pmax: 30 cm H2O
Set PEEP: PEEP (cm H2O): 9 cm H2O
FiO2: FiO2 set (%): 45 %"""
    before = "Invasive Ventilation:\nVent Mode: Pressure Control\n"
    baseline = parsed(before + after)
    with_nava = parsed(before + FIELDS + "\n" + after)
    assert with_nava.data == baseline.data


def test_editor_field_indices_and_saved_structure_remain_compatible():
    original_labels = (
        "Vent Mode", "Resp Rate (Set)", "Vt (Set, mL)", "Vt (observed, mL)",
        "PEEP (cm H2O)", "Mean Airway Pressure", "Insp Time (sec)",
        "PIP Observed (cm H2O)", "Pressure Support (cm H2O)",
        "Trigger Sensitivity Flow (L/min)", "FiO2 (%)", "PIP Set (cm H2O)",
        "Vt Insp ml", "Vt Exp ml", "FiO2 set (%)", "Pmin", "Pmax",
        "Ti Min", "Ti Max", "AVAPS rate (cm H2O/min)",
        "AVAPS Respiratory Rate", "Vt Set/Target ml",
        "Pressure Support Min (cm H2O)", "Pressure Support Max (cm H2O)",
        "AVAPS Observed TV (mL)",
    )
    assert LABELS[:len(original_labels)] == original_labels
    assert {
        "NAVA level", "EDI peak", "EDI min", "Resp Rate Observed", "Apnea Interval (sec)"
    }.issubset(LABELS[len(original_labels):])
    assert set(parsed().data) == {"mode", "values"}


def test_import_text_html_and_pdf_use_the_same_nava_content():
    source = "cccccccc\n" + BODY + "\ncccccccc"
    imported = import_sections(new_sheet("P4102"), source, new_vault()["settings"])
    assert not imported.errors, imported.errors
    sheet = imported.sheet
    assert sheet["sbs_vent_mode"] == MODE
    assert "Vent Settings\n" + EXPECTED in fields_with_medications(sheet)["Respiratory"]
    assert EXPECTED in handoff_text(sheet)
    html = handoff_html(sheet)
    for value in ("NAVA Level", "3.1–13.6", "0.1–3", "22–57", "24–45", "Apnea Time"):
        assert value in html
    reader = PdfReader(BytesIO(handoff_pdf(sheet)))
    pdf_text = re.sub(r"\s+", " ", " ".join(page.extract_text() for page in reader.pages))
    for line in EXPECTED.replace("–", "-").splitlines():
        assert line in pdf_text
    assert "FiO2: 25 %" not in pdf_text
    assert "Set TV: 35" not in pdf_text


def test_nava_source_values_survive_encrypted_save_and_reload():
    source = "cccccccc\n" + BODY + "\ncccccccc"
    imported = import_sections(new_sheet("P4102"), source, new_vault()["settings"])
    assert not imported.errors, imported.errors
    vault = save_sheet_in(new_vault(), imported.sheet)
    key = generate_key()
    encrypted = seal_vault(vault, key)
    assert b"EDI peak" not in encrypted
    restored = open_vault(encrypted, key)
    assert restored == vault
    assert format_ventilation(restored["rooms"]["P4102"]["ventilation"]) == EXPECTED


@pytest.mark.parametrize("index,blank,label", [
    (0, "NAVA Level: NAVA level:", "NAVA Level:"),
    (1, "Set PEEP: PEEP (cm H2O):", "Set PEEP:"),
    (2, "Set FIO2: FiO2 (%):", "FiO2:"),
    (3, "EDI Peak: EDI peak:", "Edi Peak:"),
    (4, "EDI Min: EDI min:", "Edi Min:"),
    (5, "Observed PIP: PIP Observed (cm H2O):", "Observed PIP:"),
    (6, "Observed Tidal Volume: Vt (observed, mL):", "Observed TV:"),
    (7, "Observed Respiratory Rate: Resp Rate Observed:", "Observed RR:"),
])
def test_nested_blank_smartlinks_keep_later_fields_in_nava_scope(index, blank, label):
    rows = list(NAVA_ROWS)
    rows[index] = blank
    result = parse_respiratory(selected_fields(rows), None)
    assert not result.error, result.error
    expected_lines = [line for line in EXPECTED.splitlines() if not line.startswith(label)]
    assert format_ventilation(result.invasive).splitlines() == expected_lines
    assert result.invasive["values"]["Apnea Interval (sec)"] == "10 seconds"


@pytest.mark.parametrize("flag", ["No", "Off", "False"])
def test_generic_ventilator_off_survives_nava_selection_and_suppresses_sbs(flag):
    from models import automatic_vitals

    c_body = GENERAL + "\nVentilator On: " + flag + "\n" + FIELDS
    history = "Target Arousal Level:\nSBS Last 24 Hours:\nLast SBS Ever: Target Arousal Level (SBS): SBS -1"
    source = "cccccccc\n" + c_body + "\ncccccccc\nkkkkkkkk\n" + history + "\nkkkkkkkk"
    imported = import_sections(new_sheet("P4102"), source, new_vault()["settings"])
    assert not imported.errors, imported.errors
    assert imported.sheet["sbs_vent_mode"] == ""
    assert automatic_vitals(imported.sheet)["Neurologic"].startswith("SBS: None\n")
    assert format_ventilation(imported.sheet["ventilation"]) == EXPECTED


@pytest.mark.parametrize("first_mode,nested_mode", [
    (MODE, "Pressure Control"),
    ("Pressure Control", MODE),
])
def test_conflicting_mode_inside_nava_section_is_preserved_for_validation(first_mode, nested_mode):
    generic = GENERAL.replace(MODE, first_mode, 1)
    source = generic + "\n" + FIELDS + "\nMode: Vent Mode: " + nested_mode
    result = parse_respiratory(source, None)
    assert result.error
    assert result.invasive is None

