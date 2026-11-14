"""Synthetic cerebral NIRS import, placement, absence and export checks."""
from copy import deepcopy
import re

import fitz
import pytest

from exports import handoff_html, handoff_pdf, handoff_text
from importing import import_sections
from models import new_sheet, new_vault, fields_with_medications, validate_sheet
from nirs import parse_nirs_line, nirs_display_rows
from vitals import parse_vitals, route, text_by_system


SUMMARY = "NIRS Range: rSO2 Cerebral % Avg: 65.4 % Min: 59 % Max: 73 %"
LATEST = "Last NIRS: rSO2 Cerebral %: 69 %"
EXPECTED = "NIRS: 59% to 73% [last 69]"


def block(text):
    return "eeeeeeee\nVITALS:\n" + text + "\neeeeeeee"


def sheet():
    result = import_sections(new_sheet("P4102"), block(SUMMARY + "\n" + LATEST), new_vault()["settings"])
    assert not result.errors and not result.skipped
    return result.sheet


def test_summary_and_last_are_neuro_only_and_do_not_use_average():
    parsed = parse_vitals("Heart Rate: 110\nSpO2: 96%\n" + SUMMARY + "\n" + LATEST)
    assert not parsed.error and not parsed.issues
    text = text_by_system(parsed.rows)
    assert text["Neurologic"] == EXPECTED
    assert text["Cardiovascular"] == "Heart Rate: 110"
    assert text["Respiratory"] == "SpO2: 96%"
    assert "Other" not in text
    assert "65.4" not in text["Neurologic"] and "Avg" not in text["Neurologic"]


@pytest.mark.parametrize("source,expected", [
    ("nirs range:\trSO₂ Cerebral %\tMaximum: 73\tAverage: 65.4\tMinimum: 59", "NIRS: 59% to 73%"),
    ("NIRS (%): Min: 59.50 Max: 73.00", "NIRS: 59.50% to 73.00%"),
    ("rSO2 Cerebral % Min: 0 Max: 100", "NIRS: 0% to 100%"),
    ("Cerebral rSO₂ (%): Avg: N/A Min: 59 Max: 73", "NIRS: 59% to 73%"),
    ("NIRS: Min: 59% Min: 59.0% Max: 73%", "NIRS: 59% to 73%"),
    ("NIRS: 69 %", "NIRS: 69%"),
    ("Last NIRS: rSO2 Cerebral %: 69", "NIRS: Last: 69%"),
    ("Last NIRS: rSO₂ Cerebral %: (!) 69 %", "NIRS: Last: (!) 69%"),
    ("NIRS: Min: 59 Max: 73\nLast NIRS: 69", "NIRS: 59 to 73 [last 69]"),
])
def test_supported_typography(source, expected):
    parsed = parse_vitals(source)
    assert not parsed.error and not parsed.issues
    assert text_by_system(parsed.rows) == {"Neurologic": expected}


@pytest.mark.parametrize("label", ["NIRS", "NIRS Range", "Last NIRS", "nirs (%)", "rSO₂ Cerebral %", "Cerebral rSO2"])
def test_labels_route_to_neurologic(label):
    assert route(label) == "Neurologic"


@pytest.mark.parametrize("source", [
    "NIRS Range: rSO2 Cerebral % No data recorded",
    "Last NIRS: rSO2 Cerebral %: --",
    "NIRS Range:", "Last NIRS: N/A", "NIRS (%): None",
    "NIRS Range: rSO2 Cerebral % Avg: -- Min: N/A Max: Not recorded",
])
def test_absent_data_has_no_placeholder_and_preserves_other_vitals(source):
    parsed = parse_vitals("BP: 106/60\n" + source + "\nResp: 20")
    assert not parsed.error
    assert text_by_system(parsed.rows) == {"Cardiovascular": "BP: 106/60", "Respiratory": "Resp: 20"}


@pytest.mark.parametrize("source", ["SpO2: 96%", "rSO2 Somatic %: 70%", "CVP (mean): 7 mmHg"])
def test_other_monitor_channels_are_not_nirs(source):
    assert parse_nirs_line(source) is None


@pytest.mark.parametrize("source", [
    "NIRS Range: rSO2 Cerebral % Avg: 65 Min: 59",
    "NIRS (%): Min: -- Max: 73",
    "NIRS: Avg: 65 %",
])
def test_incomplete_summaries_retain_labels_without_inventing_endpoints(source):
    parsed = parse_vitals(source)
    assert not parsed.error
    text = text_by_system(parsed.rows)["Neurologic"]
    assert " to " not in text and "[last" not in text
    assert any(stat in text for stat in ("Min:", "Max:", "Avg:"))


@pytest.mark.parametrize("source", [
    "NIRS: Min: 73% Max: 59%",
    "NIRS: Min: 59% Min: 60% Max: 73%",
    "NIRS: Min: 59% Max: 73 mmHg",
    "NIRS: Min: -1% Max: 73%",
    "NIRS: Min: 59% Max: 101%",
    "Last NIRS: rSO2 Cerebral %: missing value",
])
def test_invalid_values_preserve_previous_import_and_report_error(source):
    original = sheet()
    before = deepcopy(original)
    result = import_sections(original, block(source), new_vault()["settings"])
    assert result.errors and "e" in result.skipped
    assert result.sheet["vitals"] == before["vitals"]
    assert original == before


def test_display_respects_hidden_values_and_is_idempotent():
    rows = parse_vitals(LATEST + "\n" + SUMMARY).rows
    before = deepcopy(rows)
    display = nirs_display_rows(rows)
    assert nirs_display_rows(display) == display
    assert text_by_system(rows)["Neurologic"] == EXPECTED
    assert rows == before
    rows[0]["include"] = False
    assert text_by_system(rows)["Neurologic"] == "NIRS: 59% to 73%"
    rows[1]["include"] = False
    assert text_by_system(rows) == {}


def test_conflicting_latest_values_are_separate_and_not_arbitrarily_selected():
    parsed = parse_vitals(SUMMARY + "\n" + LATEST + "\nLast NIRS: 70%")
    assert text_by_system(parsed.rows)["Neurologic"] == "NIRS: 59% to 73%\nLast NIRS: 69%\nLast NIRS: 70%"


def test_import_export_and_reimport_absence():
    current = sheet()
    current["fields"]["Neurologic"] = "SYNTHETIC_NEURO_NOTE"
    validate_sheet(current)
    content = fields_with_medications(current)
    assert content["Neurologic"].index(EXPECTED) < content["Neurologic"].index("SYNTHETIC_NEURO_NOTE")
    assert all("NIRS" not in value for key, value in content.items() if key != "Neurologic")
    assert EXPECTED in handoff_text(current)
    assert "<b>NIRS:</b> 59% to 73% [last 69]" in handoff_html(current)
    with fitz.open(stream=handoff_pdf(current), filetype="pdf") as document:
        text = re.sub(r"\s+", " ", " ".join(page.get_text() for page in document))
        assert EXPECTED in text
    updated = import_sections(current, block("Heart Rate: 105"), new_vault()["settings"])
    assert not updated.errors
    assert "NIRS" not in fields_with_medications(updated.sheet)["Neurologic"]
    assert "SYNTHETIC_NEURO_NOTE" in fields_with_medications(updated.sheet)["Neurologic"]
