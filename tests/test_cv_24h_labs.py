"""Cardiovascular lab routing and strict 24-hour selection. Synthetic data only."""
from copy import deepcopy
from datetime import datetime, timedelta
from io import BytesIO
import re
from zoneinfo import ZoneInfo

import pytest
from pypdf import PdfReader

from blood_gases import gas_card, parse_gases
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_html, handoffs_pdf
from import_review import diagnostic
from importing import import_sections
from lab_windows import cardiac_labs_summary, display_clock, laboratory_data, rows_for
from labs import parse_labs
from models import fields_with_medications, new_sheet, new_vault, save_sheet_in
from security import generate_key, open_vault, seal_vault


ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=ET)
LABELS = {"METHB": "Methemoglobin", "O2SATV": "SvO2"}


def sheet(source=""):
    result = parse_labs("LABS:\nComponent\tValue\tDate\n" + source)
    assert not result.error, result.error
    data = new_sheet("P4102")
    data["labs"] = result.data
    return data


@pytest.mark.parametrize("code", LABELS)
@pytest.mark.parametrize("date,eligible", [
    ("11/11/2026 14:59:59", False),
    ("11/11/2026 15:00", True),
    ("11/11/2026 15:00:01", True),
    ("11/12/2026 14:59", True),
    ("11/12/2026 15:00", True),
    ("11/12/2026 15:00:01", False),
    ("11/10/2026", False),
    ("11/11/2026", False),
    ("11/12/2026", True),
    ("11/13/2026", False),
])
def test_exact_window_and_date_only_policy(code, date, eligible):
    data = sheet(f"{code}\t1.2\t{date}")
    assert bool(rows_for(data, code, NOW)) is eligible
    assert (LABELS[code] + ":" in cardiac_labs_summary(data, NOW)) is eligible


@pytest.mark.parametrize("code", LABELS)
@pytest.mark.parametrize("now,date,eligible", [
    (datetime(2026, 11, 12, 0, 0, tzinfo=ET), "11/11/2026", True),
    (datetime(2026, 11, 12, 0, 1, tzinfo=ET), "11/11/2026", False),
    (datetime(2026, 11, 1, 23, 0, tzinfo=ET), "11/01/2026", True),
    (datetime(2026, 11, 1, 23, 1, tzinfo=ET), "11/01/2026", False),
    (datetime(2026, 3, 9, 0, 0, tzinfo=ET), "03/08/2026", True),
])
def test_date_only_uses_elapsed_time_from_start_of_recorded_date(code, now, date, eligible):
    assert bool(rows_for(sheet(f"{code}\t1.2\t{date}"), code, now)) is eligible


@pytest.mark.parametrize("code", LABELS)
@pytest.mark.parametrize("now,date,eligible", [
    (datetime(2026, 11, 2, 0, 0, tzinfo=ET), "11/01/2026 01:30", True),
    (datetime(2026, 11, 2, 1, 0, tzinfo=ET), "11/01/2026 01:30", False),
    (datetime(2026, 11, 1, 1, 45, tzinfo=ET, fold=0), "11/01/2026 01:30", False),
    (datetime(2026, 11, 1, 1, 45, tzinfo=ET, fold=1), "11/01/2026 01:30", True),
    (datetime(2026, 3, 8, 4, 0, tzinfo=ET), "03/08/2026 02:30", False),
    (datetime(2026, 3, 8, 4, 0, tzinfo=ET), "03/08/2026 03:30", True),
])
def test_ambiguous_times_require_both_instants_and_nonexistent_times_are_omitted(code, now, date, eligible):
    assert bool(rows_for(sheet(f"{code}\t1.2\t{date}"), code, now)) is eligible


@pytest.mark.parametrize("code", LABELS)
def test_latest_timed_result_not_highest_value_or_first_row(code):
    data = sheet(f"{code}\t95.1\t11/12/2026 08:00\n"
                 f"{code}\t71.3\t11/12/2026 14:00\n"
                 f"{code}\t83.2\t11/12/2026 11:00")
    assert cardiac_labs_summary(data, NOW) == LABELS[code] + ": 71.3 [11/12/2026 14:00]"


@pytest.mark.parametrize("code", LABELS)
@pytest.mark.parametrize("first_date,second_date", [
    ("11/12/2026", "11/12/2026"),
    ("11/12/2026", "11/12/2026 14:00"),
    ("11/12/2026 08:00", "11/12/2026"),
    ("11/12/2026 14:00", "11/12/2026 14:00"),
])
def test_missing_times_and_exact_ties_preserve_source_order(code, first_date, second_date):
    data = sheet(f"{code}\t71.3\t{first_date}\n{code}\t83.2\t{second_date}")
    assert cardiac_labs_summary(data, NOW) == LABELS[code] + ": 71.3 [" + first_date + "]"


@pytest.mark.parametrize("code", LABELS)
@pytest.mark.parametrize("value", ["0", "0.8", "1.2 % (H)", "71.3%", "<1 %", "82.4 (L)"])
def test_source_values_flags_and_units_preserved_without_inferred_percent(code, value):
    data = sheet(f"{code.lower()}\t{value}\t11/12/2026 14:00")
    before = deepcopy(data)
    assert cardiac_labs_summary(data, NOW) == LABELS[code] + ": " + value + " [11/12/2026 14:00]"
    assert data == before


@pytest.mark.parametrize("code", ["METHB_ALT", "METHB2", "O2SATVX", "O2SATA", "O2SAT", "O2SATVEN"])
def test_other_codes_are_not_substituted_or_removed(code):
    data = sheet(f"{code}\t82.4\t11/12/2026 14:00")
    assert cardiac_labs_summary(data, NOW) == ""
    assert [row["component"] for row in laboratory_data(data, NOW)["rows"]] == [code]


@pytest.mark.parametrize("code", LABELS)
@pytest.mark.parametrize("value", ["Pending", "Canceled", "Hemolyzed", "--", "1.2 pending"])
def test_nonresults_do_not_replace_a_measured_result(code, value):
    data = sheet(f"{code}\t{value}\t11/12/2026 14:00\n{code}\t1.2\t11/12/2026 13:00")
    assert cardiac_labs_summary(data, NOW) == LABELS[code] + ": 1.2 [11/12/2026 13:00]"


def test_excluded_rows_failed_import_and_missing_codes_leave_no_generated_result():
    data = sheet("METHB\t1.2\t11/12/2026 14:00\nO2SATV\t71.3\t11/12/2026 14:00")
    for row in data["labs"]["rows"]:
        row["include"] = False
    assert cardiac_labs_summary(data, NOW) == ""
    for row in data["labs"]["rows"]:
        row["include"] = True
    data["import_warnings"]["g"] = [diagnostic("g", "section_parse_failed")]
    assert cardiac_labs_summary(data, NOW) == ""
    assert laboratory_data(data, NOW)["rows"] == []
    assert cardiac_labs_summary(sheet(), NOW) == ""


def test_only_cardiovascular_displays_codes_and_expiration_preserves_source_and_notes():
    data = sheet("METHB\t1.2 %\t11/12/2026 14:00\n"
                 "METHB\t8.9 %\t11/10/2026 09:00\n"
                 "O2SATV\t71.3 %\t11/12/2026 14:00\n"
                 "O2SATV\t42.8 %\t11/10/2026 09:00\n"
                 "PHV\t7.37\t11/12/2026 14:00\n"
                 "NA\t140\t11/12/2026 14:00")
    data["fields"]["Cardiovascular"] = "Synthetic cardiovascular note"
    data["fields"]["Lab Results / Trends"] = "Synthetic laboratory note"
    before = deepcopy(data)
    with display_clock(NOW):
        fields = fields_with_medications(data)
        lower = laboratory_data(data)
    assert "Methemoglobin: 1.2 %" in fields["Cardiovascular"]
    assert "SvO2: 71.3 %" in fields["Cardiovascular"]
    assert "8.9" not in fields["Cardiovascular"] and "42.8" not in fields["Cardiovascular"]
    assert "Synthetic cardiovascular note" in fields["Cardiovascular"]
    assert "Synthetic laboratory note" in fields["Lab Results / Trends"]
    assert "NA: 140" in fields["Lab Results / Trends"]
    assert all(row["component"] not in LABELS for row in lower["rows"])
    assert "O2 saturation" not in gas_card(lower)["rows"]
    for forbidden in ("METHB", "Methemoglobin", "O2SATV", "SvO2", "O2 saturation", "8.9", "42.8"):
        assert forbidden not in fields["Lab Results / Trends"]
    later = NOW + timedelta(hours=24)
    with display_clock(later):
        expired = fields_with_medications(data)
    assert expired["Cardiovascular"] == "Synthetic cardiovascular note"
    assert "Synthetic laboratory note" in expired["Lab Results / Trends"]
    assert not cardiac_labs_summary(data, later)
    assert data == before


def test_p_snapshot_saturation_stays_a_gas_result_without_becoming_svo2():
    data = sheet()
    parsed = parse_gases("Lab\tUnits\t11/10/26 09:00\nPH VEN\t\t7.37\nO2 SAT VEN\t%\t64.2")
    assert not parsed.error, parsed.error
    data["blood_gas"] = parsed.data
    with display_clock(NOW):
        fields = fields_with_medications(data)
    assert "SvO2" not in fields["Cardiovascular"]
    assert "O2 saturation: 64.2 %" in fields["Lab Results / Trends"]


def test_other_recent_labs_keep_their_existing_previous_day_overlap_rule():
    data = sheet("METHB\t1.2\t11/11/2026\nO2SATV\t71.3\t11/11/2026\n"
                 "THEOPH\t10.5\t11/11/2026\nCK\t135\t11/11/2026\n"
                 "VANCOTROUGH\t12.5\t11/11/2026\nLACTATE\t1.1\t11/11/2026")
    assert not rows_for(data, "METHB", NOW) and not rows_for(data, "O2SATV", NOW)
    for code in ("THEOPH", "CK", "VANCOTROUGH", "LACTATE"):
        assert len(rows_for(data, code, NOW)) == 1


def test_import_archive_and_actual_single_and_batch_exports_select_once():
    source = ("gggggggggggg\nLABS:\n"
              "METHB\t8.9 %\t11/10/2026 09:00\n"
              "O2SATV\t42.8 %\t11/10/2026 09:00\n"
              "METHB\t1.2 %\t11/12/2026 14:00\n"
              "O2SATV\t71.3 %\t11/12/2026 14:00\n"
              "PHV\t7.37\t11/12/2026 14:00\n"
              "gggggggggggg")
    imported = import_sections(new_sheet("P4102"), source, new_vault()["settings"])
    assert not imported.errors, imported.errors
    data = imported.sheet
    data["fields"]["Cardiovascular"] = "Synthetic cardiovascular note"
    vault = save_sheet_in(new_vault(), data)
    key = generate_key()
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == vault
    data = restored["rooms"]["P4102"]
    before = deepcopy(data)
    assert "SvO2: 71.3 %" in cardiac_labs_summary(data, NOW)
    outputs = [handoff_text(data, printed_at=NOW),
               handoff_html(data, printed_at=NOW),
               handoffs_html([data], printed_at=NOW)]
    for renderer in (handoff_pdf, lambda item, printed_at: handoffs_pdf([item], printed_at=printed_at)):
        pdf = renderer(data, printed_at=NOW)
        outputs.append("\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages))
    for output in outputs:
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", output))
        assert plain.count("Methemoglobin:") == 1
        assert plain.count("SvO2:") == 1
        assert "Methemoglobin: 1.2 %" in plain
        assert "SvO2: 71.3 %" in plain
        assert "Synthetic cardiovascular note" in plain
        assert "8.9 %" not in plain and "42.8 %" not in plain
        assert "O2 saturation:" not in plain
    later = handoff_text(data, printed_at=NOW + timedelta(hours=24))
    assert "Methemoglobin:" not in later and "SvO2:" not in later
    assert "Synthetic cardiovascular note" in later
    assert data == before
