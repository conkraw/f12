"""Synthetic end-to-end checks for the v6.68 handoff changes."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import re

import fitz
import pytest

from batching import available_handoffs
from categories import matching_target
from clinical_style import HIGH_COLOR, clinical_markup
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_html, handoffs_pdf
from github_store import StorageError
from importing import import_sections
from medications import ignored, visible, upsert_rule
from models import (SCHEMA_VERSION, automatic_vitals, fields_with_medications,
                    new_sheet, new_vault, save_sheet_in, upgrade_vault, validate_sheet)
from parser import parse_smartphrase
from problem_review import review_text, suggestions
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip, Panel


OVERRIDE = "midazolam 1 mg/mL injection - ADS Override Pull"
NORMAL = "midazolam injection 1 mg"


def block(letter, body):
    return letter * 12 + "\n" + body + "\n" + letter * 12


def ecg(value="425", date="11/13/2026"):
    return block("z", "ECG 12 lead " + date + "\nNarrative\n"
                 "IDENTITY_NARRATIVE_NOT_RETAINED\nQ-T Interval: 280 ms\n"
                 "QTC Calculation(Bazett): " + value + " ms")


def meds():
    return block("b", "Medications:\n•\t" + OVERRIDE + "\n•\t" + NORMAL +
                 "\t1 mg\tIntravenous\tq1h PRN")


def nirs():
    return block("e", "VITALS:\nHeart Rate: [90-130] 110\n"
                 "NIRS Range: rSO2 Cerebral %  Avg: 62.8 %  Min: 60 %  Max: 68 %\n"
                 "Last NIRS: rSO2 Cerebral %: 66 %")


def imported(text, original=None):
    result = import_sections(original or new_sheet("P4102"), text, new_vault()["settings"])
    assert not result.errors and not result.skipped, result.errors
    return result.sheet


@pytest.mark.parametrize("value,flagged", [("425", False), ("450", False), ("451", True), ("450.1", True)])
def test_threshold_is_shared_by_cardiac_flag_problems_and_rich_output(value, flagged):
    sheet = imported(ecg(value))
    line = "QTc: " + value + " msec [11/13/2026]" + (" (!)" if flagged else "")
    assert automatic_vitals(sheet)["Cardiovascular"] == line
    assert fields_with_medications(sheet)["Cardiovascular"] == line
    assert ("Long QTc" in review_text(sheet)) is flagged
    assert (HIGH_COLOR in clinical_markup(line)) is flagged
    assert ("(!)" in handoff_text(sheet)) is flagged


def test_ecg_has_no_current_date_admission_or_lab_window_restriction():
    sheet = imported(ecg("480", "01/02/2001"))
    sheet["admission_date"] = "11/13/2026"
    assert "QTc: 480 msec [01/02/2001] (!)" in handoff_text(sheet)
    for now in (datetime(2026, 11, 14, tzinfo=timezone.utc), datetime(2040, 1, 1, tzinfo=timezone.utc)):
        assert [r["label"] for r in suggestions(sheet, now) if r["key"] == "QTC"] == ["Long QTc"]


def test_newest_normal_result_removes_old_flag_and_problem():
    sheet = imported(ecg("480", "01/02/2001"))
    sheet = imported(ecg("425", "11/13/2026"), sheet)
    assert "(!)" not in handoff_text(sheet)
    assert "Long QTc" not in review_text(sheet)
    assert sheet["ecg"] == {"value": "425", "date": "11/13/2026"}


def test_omitted_z_preserves_snapshot_and_explicit_empty_z_clears():
    sheet = imported(ecg("480", "01/02/2001"))
    sheet = imported(nirs(), sheet)
    assert "Long QTc" in review_text(sheet)
    sheet = imported(block("z", "ECG:\nNo results found"), sheet)
    assert sheet["ecg"] is None
    assert "QTc" not in fields_with_medications(sheet)["Cardiovascular"]
    assert "Long QTc" not in review_text(sheet)


@pytest.mark.parametrize("source", [
    "zzzzzzzz\nECG 12 lead 11/13/2026\nQTC Calculation(Bazett): 490 ms",
    block("z", "ECG 12 lead 11/13/2026\nQTC Calculation(Bazett): invalid ms"),
    block("z", "ECG 12 lead 11/13/2026\nQTC Calculation(Bazett): 490 ms\nQTC Calculation(Bazett): 425 ms"),
])
def test_invalid_ecg_retains_reviewable_data_but_hides_old_output(source):
    original = imported(ecg("480", "01/02/2001"))
    before = deepcopy(original)
    result = import_sections(original, nirs() + "\n" + source, new_vault()["settings"])
    assert result.errors and result.skipped == ["z"]
    assert result.sheet["ecg"] == before["ecg"] and original == before
    assert "z" in result.sheet["import_warnings"]
    assert "NIRS: 60% to 68% [last 66]" in handoff_text(result.sheet)
    assert "QTc" not in handoff_text(result.sheet)
    assert "Long QTc" not in review_text(result.sheet)


def test_new_z_divider_is_valid_and_duplicate_patient_blocks_are_rejected():
    parsed = parse_smartphrase(ecg())
    assert "z" in parsed.blocks and not parsed.invalid
    original = new_sheet("P4102")
    result = import_sections(original, ecg() + "\n" + ecg("480"), new_vault()["settings"])
    assert result.sheet is None and result.errors


def test_ecg_word_in_diagnoses_is_not_a_section_heading():
    source = block("a", "Diagnoses:\nECG abnormality\nEKG findings") + "\n" + ecg()
    sheet = imported(source)
    assert sheet["fields"]["Diagnoses"] == "ECG abnormality\nEKG findings"
    assert sheet["ecg"]["value"] == "425"


def test_only_value_and_date_are_saved_and_old_vaults_still_open():
    old = new_vault()
    old["rooms"]["P4104"] = new_sheet("P4104")
    old_before = deepcopy(old)
    key = generate_key()
    assert open_vault(seal_vault(old, key), key) == old_before
    sheet = imported(ecg("480") + "\n" + nirs() + "\n" + meds())
    vault = save_sheet_in(old, sheet)
    opened = open_vault(seal_vault(vault, key), key)
    assert opened == vault and opened["schema"] == SCHEMA_VERSION == 34
    assert upgrade_vault(opened) == opened
    assert set(opened["rooms"]["P4102"]["ecg"]) == {"value", "date"}
    assert "IDENTITY_NARRATIVE_NOT_RETAINED" not in json.dumps(opened)
    assert "P4102" in available_handoffs(new_vault(), {"P4102": imported(ecg())})


def test_combined_changes_in_text_html_pdf_and_print_all():
    sheet = imported(ecg("480") + "\n" + nirs() + "\n" + meds())
    before = deepcopy(sheet)
    other = deepcopy(sheet)
    other["room"] = "P4104"
    printed = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    expected = ("QTc: 480 msec [11/13/2026] (!)", "NIRS: 60% to 68% [last 66]", "Long QTc")
    for markup in (handoff_text(sheet, printed), handoff_html(sheet, printed), handoffs_html([sheet, other], printed)):
        assert "ADS Override Pull" not in markup and NORMAL in markup
    html = handoff_html(sheet, printed)
    assert '<font color="#b00020"><b>QTc:</b></font>' in html
    assert '<font color="#b00020"> 480 msec [11/13/2026] (!)</font>' in html
    for data, pages in ((handoff_pdf(sheet, printed), 1), (handoffs_pdf([sheet, other], printed), 2)):
        with fitz.open(stream=data, filetype="pdf") as document:
            assert len(document) == pages
            for page in document:
                text = re.sub(r"\s+", " ", page.get_text())
                assert all(value in text for value in expected)
                assert "ADS Override Pull" not in text and NORMAL in text
                spans = [span for b in page.get_text("dict")["blocks"] if "lines" in b for line in b["lines"] for span in line["spans"]]
                qtc_spans = [span for span in spans if "msec" in span["text"] or "QTc:" in span["text"]]
                assert qtc_spans and all(span["color"] == 0xB00020 for span in qtc_spans)
    assert sheet == before


def test_default_ignore_can_be_restored_in_existing_editor_and_reimport(app):
    open_room(app)
    ss = app.st.session_state
    ss["paste"] = meds()
    app.create_handoff()
    row = ss["drafts"]["P4102"]["medications"][0]
    assert ignored(row)
    app.hide_medication("P4102", row["id"], False, None)
    assert visible(ss["drafts"]["P4102"]["medications"][0])
    ss["paste"] = meds()
    app.create_handoff()
    assert visible(ss["drafts"]["P4102"]["medications"][0])


def test_explicit_ignore_can_be_restored_and_saved(app):
    open_room(app)
    ss = app.st.session_state
    ss["paste"] = meds()
    app.create_handoff()
    row = ss["drafts"]["P4102"]["medications"][0]
    ss["test_category"] = "system:Ignore"
    app.medication_category_change("P4102", row["id"], "test_category", None)
    assert matching_target(row, ss["vault"]["settings"]) == "system:Ignore"
    app.hide_medication("P4102", row["id"], False, None)
    restored = ss["drafts"]["P4102"]["medications"][0]
    assert visible(restored) and matching_target(restored, ss["vault"]["settings"]) == "system:Other Medications"
    app.save_room(None)
    key = generate_key()
    reopened = open_vault(seal_vault(ss["vault"], key), key)
    assert visible(reopened["rooms"]["P4102"]["medications"][0])


def test_failed_restore_commit_leaves_ignore_and_settings_unchanged(app, monkeypatch):
    open_room(app)
    ss = app.st.session_state
    ss["paste"] = meds()
    app.create_handoff()
    row = ss["drafts"]["P4102"]["medications"][0]
    ss["test_category"] = "system:Ignore"
    app.medication_category_change("P4102", row["id"], "test_category", None)
    before = deepcopy((ss["vault"], ss["drafts"]))
    def fail(*args):
        raise StorageError("Synthetic save failure")
    monkeypatch.setattr(app, "commit", fail)
    app.hide_medication("P4102", row["id"], False, None)
    assert (ss["vault"], ss["drafts"]) == before


@pytest.mark.parametrize("match", ["exact", "prefix"])
@pytest.mark.parametrize("index", [0, 1])
def test_restore_overrides_explicit_legacy_ignore_rule(app, match, index):
    open_room(app)
    ss = app.st.session_state
    ss["paste"] = meds()
    app.create_handoff()
    row = ss["drafts"]["P4102"]["medications"][index]
    term = row["name"] if match == "exact" else "midazolam"
    ss["vault"]["settings"]["medication_mappings"] = upsert_rule([], term, "Ignore", match)
    app.reapply_open_mappings()
    assert ignored(ss["drafts"]["P4102"]["medications"][index])
    app.hide_medication("P4102", row["id"], False, None)
    restored = ss["drafts"]["P4102"]["medications"][index]
    assert visible(restored)
    assert "restored" in ss["notice"][1]
    assert matching_target(restored, ss["vault"]["settings"]) == "system:Other Medications"


def test_ignore_editor_is_reachable_and_restore_control_is_offered(app, monkeypatch):
    open_room(app)
    ss = app.st.session_state
    ss["paste"] = ecg("480") + "\n" + nirs() + "\n" + meds()
    app.create_handoff()
    equip(app, monkeypatch)
    expanders, buttons = [], []
    def expander(label, **kwargs):
        expanders.append(label)
        return Panel(app.st)
    app.st.expander = expander
    app.st.button = lambda label, **kwargs: buttons.append((label, kwargs)) or False
    app.handoff_page(None)
    assert "Ignored / hidden medications (1)" in expanders
    restores = [kwargs for label, kwargs in buttons if label == "Restore to handoff"]
    assert len(restores) == 1 and restores[0]["args"][2] is False
    validate_sheet(ss["drafts"]["P4102"])
