"""Source timestamp I/O windows. Every fixture is synthetic."""
from copy import deepcopy
from datetime import datetime, timezone
import re

import fitz
import pytest

from fluid_balance import empty_balance, balance_heading, parse_balance
from fen_gi import fen_gi_body
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf, handoffs_html
from importing import import_sections
from models import new_sheet, new_vault, save_sheet_in
from security import generate_key, seal_vault, open_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip


def source(time="0710", date="11/13/2026", period="Last 24 hours", filed="0600"):
    return (f"Intake/Output Summary ({period}) at {date} {time}\n"
            f"Last data filed at {date} {filed}\nGross per 24 hour\n"
            "Intake\t123.4 ml\nOutput\t100 ml\nNet\t23.4 ml")


def data(time="0710", **kwargs):
    result = parse_balance(source(time, **kwargs))
    assert not result.error
    return result.data


def sheet(time="0710"):
    result = import_sections(new_sheet("P4102"), "ssssssss\n" + source(time) + "\nssssssss", new_vault()["settings"])
    assert not result.errors
    return result.sheet


@pytest.mark.parametrize("time,window", [
    ("0600", "6a-6a"), ("0610", "6a-6a"), ("0659", "6a-6a"),
    ("0700", "7a-7a"), ("0710", "7a-7a"), ("0759", "7a-7a"),
    ("610", "6a-6a"), ("6:45", "6a-6a"), ("7:10 AM", "7a-7a"),
    ("07:10am", "7a-7a"), ("1816", "6p-6p"), ("6:59 pm", "6p-6p"),
    ("1910", "7p-7p"), ("0000", "12a-12a"), ("0059", "12a-12a"),
    ("1200", "12p-12p"), ("12:59 PM", "12p-12p"), ("12:59 AM", "12a-12a"),
    ("2359", "11p-11p"), ("11:10 PM", "11p-11p"),
])
def test_hour_labels_preserve_am_pm_without_rounding(time, window):
    snapshot = data(time)
    before = deepcopy(snapshot)
    assert balance_heading(snapshot) == "Intake/Output (" + window + ")"
    assert snapshot == before


@pytest.mark.parametrize("hour", range(24))
@pytest.mark.parametrize("minute", [0, 10, 59])
def test_every_hour_and_boundaries(hour, minute):
    label = str(hour % 12 or 12) + ("a" if hour < 12 else "p")
    assert balance_heading(data(f"{hour:02}{minute:02}")) == f"Intake/Output ({label}-{label})"


@pytest.mark.parametrize("period", ["Last 24 hours", "last 24 hrs", "24 hours", "24h", "Past 24 hours"])
def test_explicit_24h_periods(period):
    assert balance_heading(data(period=period)) == "Intake/Output (7a-7a)"


@pytest.mark.parametrize("period", ["", "Last 8 hours", "Last 12 hours", "Last 48 hours", "Today", "Since admission"])
def test_unknown_or_other_periods_do_not_get_a_24_hour_label(period):
    assert balance_heading(data(period=period)) == "Intake/Output"


@pytest.mark.parametrize("stamp", ["", "11/13/2026", "11/13/2026 2460", "11/13/2026 2400",
    "11/13/2026 0760", "11/13/2026 13:10 PM", "11/13/2026 00:10 AM",
    "02/30/2026 0710", "13/01/2026 0710"])
def test_missing_or_invalid_time_cannot_create_a_false_window(stamp):
    snapshot = data()
    snapshot["as_of"] = stamp
    assert balance_heading(snapshot) == "Intake/Output"


def test_date_only_and_none_do_not_fall_back_to_last_filed():
    snapshot = data(filed="1800")
    snapshot["as_of"] = "11/13/2026"
    assert balance_heading(snapshot) == "Intake/Output"
    assert balance_heading(None) == "Intake/Output"
    assert balance_heading(empty_balance()) == "Intake/Output"


def test_last_filed_hour_does_not_override_summary_hour():
    assert balance_heading(data("0710", filed="0600")) == "Intake/Output (7a-7a)"
    assert balance_heading(data("0659", filed="0500")) == "Intake/Output (6a-6a)"


def test_two_digit_year_and_leap_year():
    assert balance_heading(data(date="11/13/26")) == "Intake/Output (7a-7a)"
    assert balance_heading(data(date="2/29/2024")) == "Intake/Output (7a-7a)"


def test_totals_and_metadata_are_unchanged_and_title_is_hidden_with_totals():
    snapshot = data()
    before = deepcopy(snapshot)
    text = fen_gi_body("", [], snapshot)
    assert text == "Intake/Output (7a-7a):\nIntake: 123.4 ml\nOutput: 100 ml\nNet: 23.4 ml"
    assert snapshot == before
    snapshot["include"] = False
    assert fen_gi_body("", [], snapshot) == ""


def test_saved_snapshot_stays_at_its_source_hour_when_reprinted():
    s = sheet("0614")
    before = deepcopy(s)
    for print_hour in (7, 8, 18):
        printed_at = datetime(2026, 11, 14, print_hour, 10, tzinfo=timezone.utc)
        assert "Intake/Output (6a-6a):" in handoff_text(s, printed_at)
        assert "<b>Intake/Output (6a-6a):</b>" in handoff_html(s, printed_at)
    assert s == before


def test_latest_s_import_replaces_hour_and_non_s_import_preserves_it():
    s = sheet("0614")
    updated = import_sections(s, "ssssssss\n" + source("0710") + "\nssssssss", new_vault()["settings"])
    assert not updated.errors
    assert balance_heading(updated.sheet["intake_output"]) == "Intake/Output (7a-7a)"
    no_s = import_sections(updated.sheet, "eeeeeeee\nBP: 104/54\neeeeeeee", new_vault()["settings"])
    assert no_s.sheet["intake_output"] == updated.sheet["intake_output"]


def test_text_html_pdf_and_mixed_hour_print_all():
    s = sheet("0614")
    other = sheet("0710")
    other["room"] = "P4104"
    before = deepcopy([s, other])
    assert "Intake/Output (6a-6a):" in handoff_text(s)
    assert "<b>Intake/Output (6a-6a):</b>" in handoff_html(s)
    html = handoffs_html([s, other])
    assert html.count("<b>Intake/Output (6a-6a):</b>") == 1
    assert html.count("<b>Intake/Output (7a-7a):</b>") == 1
    with fitz.open(stream=handoffs_pdf([s, other]), filetype="pdf") as doc:
        assert len(doc) == 2
        for page, label in zip(doc, ("6a-6a", "7a-7a")):
            text = re.sub(r"\s+", " ", page.get_text())
            assert "Intake/Output (" + label + "):" in text
            assert "Intake: 123.4 ml" in text
    with fitz.open(stream=handoff_pdf(s), filetype="pdf") as doc:
        assert "Intake/Output (6a-6a):" in re.sub(r"\s+", " ", doc[0].get_text())
    assert [s, other] == before


def test_encrypted_recall_preserves_io_metadata_and_window():
    vault = save_sheet_in(new_vault(), sheet())
    key = generate_key()
    reopened = open_vault(seal_vault(vault, key), key)
    assert reopened == vault
    assert balance_heading(reopened["rooms"]["P4102"]["intake_output"]) == "Intake/Output (7a-7a)"


def test_editor_heading_and_source_time_explanation(app, monkeypatch):
    open_room(app)
    equip(app, monkeypatch)
    headings, captions = [], []
    app.st.subheader = lambda text: headings.append(text)
    app.st.caption = lambda text: captions.append(text)
    app.intake_output_editor(sheet())
    assert headings == ["Intake/Output (7a-7a)"]
    assert any("As of 11/13/2026 0710" in text for text in captions)
    assert any("not the time you reprint" in text for text in captions)
