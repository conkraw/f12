"""Synthetic end-to-end checks for reported ventilator mode history."""
from copy import deepcopy
from html import unescape
from io import BytesIO
import json
import re

from pypdf import PdfReader

from exports import handoff_html, handoff_pdf, handoff_text
from importing import import_replacement, import_sections
from models import new_sheet, new_vault, save_sheet_in, validate_sheet
from noninvasive import parse_respiratory, read_fields
from security import generate_key, open_vault, seal_vault
from ventilation import LABELS, format_ventilation
from test_callbacks import app, open_room


PRVC = "Volume Targeted Pressure Control - Intermittent Mandatory Ventilation"
PRVC_PS = "Volume Targeted Pressure Control - PS"
NAVA = "Neurally Adjusted Ventilatory Assist"
PS_CPAP = "Pressure Support - Continuous Positive Airway Pressure"

GENERAL = """Invasive Ventilation:
Mode: Vent Mode: {mode}
Respiratory Rate: Resp Rate (Set): 21
Set TV: Vt (Set, mL): 180 mL
Set PEEP: PEEP (cm H2O): 6 cm H2O
Inspiratory Time: Insp Time (sec): 0.9 sec
FiO2: FiO2 set (%): 47 %
Pressure Support: Pressure Support (cm H2O): 10 cm H20
Observed PIP: PIP Observed (cm H2O) Avg: 22 cm H2O Min: 18 cm H2O Max: 27 cm H2O
Home Ventilator Settings:
Pmin:
Pmax:
Timin:
Timax:
Average Volume-Assured Pressure Support Settings:
AVAPS Target TV: Vt Set/Target ml: 999
Observed AVAPS TV: Vt (observed, mL): 998 mL
PS Max:
PS Min:
"""

NAVA_SETTINGS = """NAVA Ventilator Settings:
NAVA Level: NAVA level: 2.8
Set PEEP: PEEP (cm H2O): 7 cm H2O
Set FIO2: FiO2 (%): 33 %
EDI Peak: EDI peak Avg: 6.5 Min: 3.1 Max: 11.9
EDI Min: EDI min Avg: 1.6 Min: 0.2 Max: 3.7
Observed PIP: PIP Observed (cm H2O) Avg: 21 cm H2O Min: 16 cm H2O Max: 28 cm H2O
Observed Tidal Volume: Vt (observed, mL) Avg: 40 mL Min: 31 mL Max: 52 mL
Observed Respiratory Rate: Resp Rate Observed Avg: 40 Min: 29 Max: 59
Apnea Time: Apnea Interval (sec): 12 seconds
"""

CPAP_SETTINGS = """CPAP Trial Settings:
Pressure Support: Pressure Support (cm H2O): 8 cm H20
Set PEEP: PEEP (cm H2O): 9 cm H2O
FiO2: FiO2 set (%): 62 %
Weaning Tidal Volumes: Weaning Tidal Volume Avg: 144 mL Min: 105 mL Max: 210 mL
Weaning Tolerance: Weaning Tolerance: Good
"""

D_ETT = """Non-invasive Ventilation:
O2 Delivery Method: Endotracheal tube
FiO2 (%): 29 %
"""


def block(letter, value):
    marker = letter * 24
    return marker + "\n" + value.rstrip() + "\n" + marker + "\n"


def history_row(mode, date_time):
    return "Vent Mode: " + mode + " (" + date_time + " : SYNTHETIC_AUTHOR, RRT)"


def source(history, mode=PRVC, extra_sections=True):
    text = GENERAL.format(mode=mode)
    if extra_sections:
        text += NAVA_SETTINGS + CPAP_SETTINGS
    if history is not None:
        text += "All Vent Modes:\n\n" + "\n\n".join(history) + "\n"
    return text


def mixed_nava_source():
    return source([
        history_row(NAVA, "11/20/26 0613"),
        history_row(PRVC, "11/20/26 0500"),
        history_row(PRVC_PS, "11/19/26 2109"),
        history_row(PRVC, "11/20/26 1800"),
        history_row(NAVA, "11/20/26 1300"),
        history_row(NAVA, "11/20/26 1200"),
    ])


def imported(c_source, d_source=D_ETT):
    result = import_replacement("P4102", block("c", c_source) + block("d", d_source), new_vault()["settings"])
    assert not result.errors, result.errors
    assert result.sheet is not None
    validate_sheet(result.sheet)
    return result.sheet


def assert_compact_mode_headers(text, expected):
    mode_lines = [line for line in text.splitlines() if line.startswith("Mode: ")]
    assert len(mode_lines) == len(expected)
    for line, (mode, recorded_at) in zip(mode_lines, expected):
        assert line.startswith("Mode: " + mode)
        assert recorded_at in line
    assert text.splitlines().count("---") == len(expected) - 1
    for obsolete in ("Latest reported mode", "Last reported mode", "Other reported modes", "without setting timestamps"):
        assert obsolete not in text


def test_unordered_history_keeps_latest_prvc_and_distinct_prior_modes():
    sheet = imported(mixed_nava_source())
    data = sheet["ventilation"]
    assert data["mode"] == PRVC
    assert sheet["sbs_vent_mode"] == PRVC
    assert data["values"]["FiO2 set (%)"] == "47 %"
    assert data["values"]["PEEP (cm H2O)"] == "6 cm H2O"
    metadata = data["mode_history"]
    assert metadata["reported_at"] == "2026-11-20T18:00"
    assert metadata["latest_confirmed"] is True
    assert [entry["mode"] for entry in metadata["other_modes"]] == [NAVA, PRVC_PS]
    assert metadata["other_modes"][0]["reported_at"] == "2026-11-20T13:00"
    assert metadata["other_modes"][0]["values"]["FiO2 (%)"] == "33 %"
    assert metadata["other_modes"][1]["values"] == {}
    text = format_ventilation(data)
    assert text.index("Mode: PRVC-IMV") < text.index("Mode: NAVA") < text.index("Mode: PRVC-PS")
    assert text.count("Mode: NAVA") == 1
    assert "PS-CPAP" not in text
    assert "AVAPS" not in text
    assert "999" not in text and "998" not in text
    assert_compact_mode_headers(text, [
        ("PRVC-IMV", "11/20/26 18:00"),
        ("NAVA", "11/20/26 13:00"),
        ("PRVC-PS", "11/19/26 21:09"),
    ])


def test_cpap_history_uses_only_its_own_settings_and_never_nava_or_niv_values():
    sheet = imported(source([
        history_row(PRVC, "11/20/26 0600"),
        history_row(PRVC, "11/20/26 1900"),
        history_row(PS_CPAP, "11/20/26 1700"),
        history_row(PS_CPAP, "11/20/26 1545"),
    ]))
    data = sheet["ventilation"]
    previous = data["mode_history"]["other_modes"]
    assert len(previous) == 1 and previous[0]["mode"] == PS_CPAP
    assert data["values"]["FiO2 set (%)"] == "47 %"
    assert previous[0]["values"]["FiO2 set (%)"] == "62 %"
    text = format_ventilation(data)
    first, rest = text.split("\n---\n", 1)
    assert "FiO2: 47 %" in first and "FiO2: 62 %" not in first
    assert "FiO2: 62 %" in rest and "FiO2: 47 %" not in rest
    assert "FiO2: 29 %" not in text and "FiO2: 33 %" not in text
    assert "NAVA" not in text
    assert "105–210 mL" in text and "Good" in text
    assert sheet["noninvasive"] == []
    assert_compact_mode_headers(text, [("PRVC-IMV", "11/20/26 19:00"), ("PS-CPAP", "11/20/26 17:00")])


def test_latest_ps_cpap_selects_trial_values_and_keeps_invasive_route():
    c_source = source([
        history_row(PRVC, "11/20/26 0500"),
        history_row(PS_CPAP, "11/20/26 1800"),
        history_row(PRVC, "11/20/26 1700"),
    ])
    fields = read_fields(c_source, "C")
    assert fields["mode"] == PS_CPAP
    assert fields["peep"] == "9 cm H2O"
    assert fields["fio2_set"] == "62 %"
    parsed = parse_respiratory(c_source, D_ETT)
    assert not parsed.error, parsed.error
    assert parsed.devices == []
    assert parsed.invasive["mode"] == PS_CPAP
    sheet = imported(c_source)
    assert sheet["sbs_vent_mode"] == PS_CPAP
    assert sheet["ventilation"]["values"]["Pressure Support (cm H2O)"] == "8 cm H20"
    first = format_ventilation(sheet["ventilation"]).split("\n---\n", 1)[0]
    assert first.splitlines()[0] == "CPAP Trial Data"
    assert "Mode: PS-CPAP" in first
    assert "11/20/26 18:00" in next(line for line in first.splitlines() if line.startswith("Mode:"))
    assert "Set RR: 21" not in first and "Set TV: 180" not in first


def test_latest_nava_uses_its_block_in_read_fields_import_and_sbs_gate():
    c_source = source([
        history_row(PRVC, "11/20/26 0600"),
        history_row(NAVA, "11/20/26 1900"),
        history_row(PRVC, "11/20/26 1800"),
    ])
    fields = read_fields(c_source, "C")
    assert fields["mode"] == NAVA
    assert fields["peep"] == "7 cm H2O"
    assert fields["fio2"] == "33 %"
    sheet = imported(c_source)
    assert sheet["sbs_vent_mode"] == NAVA
    assert sheet["ventilation"]["mode"] == NAVA
    first = format_ventilation(sheet["ventilation"]).split("\n---\n", 1)[0]
    assert "NAVA Level: 2.8" in first and "FiO2: 33 %" in first
    assert "11/20/26 19:00" in first.splitlines()[0]
    assert "FiO2: 47 %" not in first and "Set TV: 180" not in first


def test_history_date_rollover_uses_entire_timestamp():
    c_source = source([
        history_row(NAVA, "11/19/26 2358"),
        history_row(PRVC, "11/20/26 0002"),
        history_row(NAVA, "11/19/26 2300"),
    ])
    data = imported(c_source)["ventilation"]
    assert data["mode"] == PRVC
    assert data["mode_history"]["reported_at"] == "2026-11-20T00:02"


def test_repeated_abbreviation_and_full_label_are_one_mode_not_one_family():
    c_source = source([
        history_row(PRVC, "11/20/26 1800"),
        history_row("PRVC-IMV", "11/20/26 1700"),
        history_row(NAVA, "11/20/26 1300"),
        history_row("NAVA", "11/20/26 1200"),
        history_row(PRVC_PS, "11/20/26 0900"),
    ])
    text = format_ventilation(imported(c_source)["ventilation"])
    assert text.count("Mode: PRVC-IMV") == 1
    assert text.count("Mode: NAVA") == 1
    assert text.count("Mode: PRVC-PS") == 1


def test_charting_author_and_raw_history_are_absent_from_saved_record_and_exports():
    sheet = imported(mixed_nava_source())
    for value in (json.dumps(sheet), handoff_text(sheet), handoff_html(sheet)):
        assert "SYNTHETIC_AUTHOR" not in value
        assert "All Vent Modes:" not in value
        assert "RRT" not in value


def test_unfamiliar_historical_mode_keeps_its_label_without_borrowed_settings():
    unrecognized = "Unlisted support <check>"
    sheet = imported(source([
        history_row(PRVC, "11/20/26 1800"),
        history_row(unrecognized, "11/20/26 1100"),
    ]))
    previous = sheet["ventilation"]["mode_history"]["other_modes"]
    assert len(previous) == 1
    assert previous[0]["mode"] == unrecognized
    assert previous[0]["values"] == {}
    assert "Mode: " + unrecognized in handoff_text(sheet)
    html = handoff_html(sheet)
    assert "Unlisted support &lt;check&gt;" in html
    assert "Unlisted support <check>" not in html


def test_unknown_newest_mode_does_not_claim_older_supported_mode_is_latest():
    sheet = imported(source([
        history_row(PRVC, "11/20/26 1800"),
        history_row("Unlisted support", "11/20/26 1900"),
    ]))
    metadata = sheet["ventilation"]["mode_history"]
    assert metadata["latest_confirmed"] is False
    assert metadata["notes"]
    text = format_ventilation(sheet["ventilation"])
    assert "Latest reported mode" not in text
    assert "Unlisted support" in text
    assert "Mode history review:" in text
    assert all(note in text for note in metadata["notes"])


def test_history_and_other_settings_survive_encrypted_roundtrip():
    sheet = imported(mixed_nava_source())
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    encrypted = seal_vault(vault, key)
    assert b"mode_history" not in encrypted and b"NAVA" not in encrypted
    restored = open_vault(encrypted, key)
    assert restored == vault
    assert restored["rooms"]["P4102"]["ventilation"] == sheet["ventilation"]
    assert format_ventilation(restored["rooms"]["P4102"]["ventilation"]) == format_ventilation(sheet["ventilation"])


def test_text_html_pdf_have_same_mode_order_and_keep_each_mode_once():
    sheet = imported(mixed_nava_source())
    pdf = PdfReader(BytesIO(handoff_pdf(sheet)))
    pdf_lines = "\n".join(page.extract_text() for page in pdf.pages)
    pdf_text = re.sub(r"\s+", " ", pdf_lines)
    html_text = unescape(re.sub(r"<[^>]*>", "", handoff_html(sheet)))
    expected = [
        ("PRVC-IMV", "11/20/26 18:00"),
        ("NAVA", "11/20/26 13:00"),
        ("PRVC-PS", "11/19/26 21:09"),
    ]
    for content in (handoff_text(sheet), html_text):
        assert_compact_mode_headers(content, expected)
    assert sum(line.strip() == "---" for line in pdf_lines.splitlines()) == 2
    for content in (handoff_text(sheet), html_text, pdf_text):
        assert content.index("Mode: PRVC-IMV") < content.index("Mode: NAVA") < content.index("Mode: PRVC-PS")
        assert content.count("Mode: PRVC-IMV") == 1
        assert content.count("Mode: NAVA") == 1
        assert content.count("Mode: PRVC-PS") == 1
        assert "FiO2: 47 %" in content and "FiO2: 33 %" in content
        assert "SYNTHETIC_AUTHOR" not in content
        for obsolete in ("Latest reported mode", "Last reported mode", "Other reported modes", "without setting timestamps"):
            assert obsolete not in content
        current = content[content.index("Mode: PRVC-IMV"):content.index("Mode: NAVA")]
        nava = content[content.index("Mode: NAVA"):content.index("Mode: PRVC-PS")]
        for fragment, timestamp, own_fio2, other_fio2 in (
            (current, "11/20/26 18:00", "FiO2: 47 %", "FiO2: 33 %"),
            (nava, "11/20/26 13:00", "FiO2: 33 %", "FiO2: 47 %"),
        ):
            assert timestamp in fragment
            assert fragment.index(timestamp) < fragment.index(own_fio2)
            assert own_fio2 in fragment and other_fio2 not in fragment
    assert "3.1-11.9" in pdf_text


def test_c_update_without_history_replaces_previous_history_and_remains_legacy_compatible():
    original = imported(mixed_nava_source())
    current_only = source(None, extra_sections=False)
    result = import_sections(original, block("c", current_only), new_vault()["settings"])
    assert not result.errors, result.errors
    assert set(result.sheet["ventilation"]) == {"mode", "values"}
    text = format_ventilation(result.sheet["ventilation"])
    assert "NAVA" not in text and "Other reported modes" not in text
    assert text.splitlines()[0] == "Mode: PRVC-IMV"
    assert "---" not in text.splitlines()


def test_whole_room_replacement_clears_history_when_new_patient_has_no_c_section():
    vault = save_sheet_in(new_vault(), imported(mixed_nava_source()))
    other = new_sheet("P4104")
    other["fields"]["Diagnoses"] = "OTHER_SYNTHETIC_ROOM"
    vault = save_sheet_in(vault, other)
    before_other = deepcopy(vault["rooms"]["P4104"])
    new = import_replacement("P4102", block("a", "Diagnoses:\n1. NEW_SYNTHETIC_ROOM"), vault["settings"])
    assert not new.errors, new.errors
    updated = save_sheet_in(vault, new.sheet)
    assert updated["rooms"]["P4102"]["ventilation"] is None
    assert "NAVA" not in handoff_text(updated["rooms"]["P4102"])
    assert updated["rooms"]["P4104"] == before_other


def load_app_history(app):
    open_room(app)
    app.st.session_state["paste"] = block("c", mixed_nava_source()) + block("d", D_ETT)
    app.create_handoff()
    return app.st.session_state


def history_widget_key(app, ss, index, label):
    sheet = ss["drafts"]["P4102"]
    item = sheet["ventilation"]["mode_history"]["other_modes"][index]
    field = "include" if label == "__include__" else str(LABELS.index(label))
    return app.ventilation_history_widget_key(sheet["id"], item["mode"], field)


def test_app_history_setting_edit_changes_only_the_selected_mode(app):
    ss = load_app_history(app)
    original = deepcopy(ss["drafts"]["P4102"]["ventilation"])
    key = history_widget_key(app, ss, 0, "NAVA level")
    ss[key] = "3.2"
    app.ventilation_history_change("P4102", 0, "NAVA level", key)
    data = ss["drafts"]["P4102"]["ventilation"]
    assert data["values"] == original["values"]
    assert data["mode_history"]["other_modes"][0]["values"]["NAVA level"] == "3.2"
    assert data["mode_history"]["other_modes"][1] == original["mode_history"]["other_modes"][1]
    app.save_room(None)
    assert ss["vault"]["rooms"]["P4102"]["ventilation"] == data


def test_app_history_toggle_hides_only_that_mode_and_preserves_its_record(app):
    ss = load_app_history(app)
    key = history_widget_key(app, ss, 0, "__include__")
    ss[key] = False
    app.ventilation_history_change("P4102", 0, "__include__", key)
    data = ss["drafts"]["P4102"]["ventilation"]
    assert data["mode_history"]["other_modes"][0]["include"] is False
    text = format_ventilation(data)
    assert "Mode: NAVA" not in text
    assert "Mode: PRVC-IMV" in text and "Mode: PRVC-PS" in text
    assert text.splitlines().count("---") == 1
    assert "11/20/26 13:00" not in text
    ss[key] = True
    app.ventilation_history_change("P4102", 0, "__include__", key)
    restored = format_ventilation(ss["drafts"]["P4102"]["ventilation"])
    assert "NAVA Level: 2.8" in restored
    assert restored.splitlines().count("---") == 2


def test_app_manual_primary_mode_change_removes_imported_timestamp_claim(app):
    ss = load_app_history(app)
    key = "vent_" + ss["drafts"]["P4102"]["id"] + "_0"
    ss[key] = "Pressure Control"
    app.ventilation_change("P4102", "Vent Mode", key)
    data = ss["drafts"]["P4102"]["ventilation"]
    assert data["mode"] == "Pressure Control"
    assert ss["drafts"]["P4102"]["sbs_vent_mode"] == "Pressure Control"
    assert data["mode_history"]["reported_at"] == ""
    assert data["mode_history"]["latest_confirmed"] is False
    assert data["values"] == {}
    assert sum(item["mode"] == PRVC for item in data["mode_history"]["other_modes"]) == 1


def test_app_promoting_nava_uses_nava_settings_and_cannot_resave_stale_prvc_widgets(app):
    ss = load_app_history(app)
    sheet = ss["drafts"]["P4102"]
    old_primary = deepcopy(sheet["ventilation"])
    nava_values = deepcopy(old_primary["mode_history"]["other_modes"][0]["values"])
    for index, label in enumerate(LABELS):
        ss["vent_" + sheet["id"] + "_" + str(index)] = old_primary["mode"] if index == 0 else old_primary["values"].get(label, "")
    key = "vent_" + sheet["id"] + "_0"
    ss[key] = NAVA
    app.ventilation_change("P4102", "Vent Mode", key)
    current = ss["drafts"]["P4102"]["ventilation"]
    assert current["mode"] == NAVA
    assert current["values"] == nava_values
    assert current["values"]["FiO2 (%)"] == "33 %"
    assert "FiO2 set (%)" not in current["values"]
    assert current["mode_history"]["reported_at"] == ""
    assert current["mode_history"]["latest_confirmed"] is False
    assert sum(item["mode"] == PRVC for item in current["mode_history"]["other_modes"]) == 1
    assert not any(item["mode"] == NAVA for item in current["mode_history"]["other_modes"])
    app.save_room(None)
    saved = ss["vault"]["rooms"]["P4102"]["ventilation"]
    assert saved["values"] == nava_values
    assert saved["mode"] == NAVA
    assert saved["mode_history"] == current["mode_history"]


def test_app_stale_historical_index_cannot_edit_reordered_mode(app):
    ss = load_app_history(app)
    stale_key = history_widget_key(app, ss, 0, "NAVA level")
    key = "vent_" + ss["drafts"]["P4102"]["id"] + "_0"
    ss[key] = NAVA
    app.ventilation_change("P4102", "Vent Mode", key)
    before = deepcopy(ss["drafts"]["P4102"]["ventilation"])
    ss[stale_key] = "4.9"
    app.ventilation_history_change("P4102", 0, "NAVA level", stale_key)
    assert ss["drafts"]["P4102"]["ventilation"] == before


def test_pending_primary_mode_change_in_snapshot_cannot_import_stale_prvc_widgets(app):
    ss = load_app_history(app)
    sheet = ss["drafts"]["P4102"]
    original = deepcopy(sheet["ventilation"])
    nava_values = deepcopy(original["mode_history"]["other_modes"][0]["values"])
    for index, label in enumerate(LABELS):
        key = "vent_" + sheet["id"] + "_" + str(index)
        ss[key] = original["mode"] if index == 0 else original["values"].get(label, "")
    ss["vent_" + sheet["id"] + "_0"] = NAVA

    snapshot = app.editor_snapshot("P4102")

    current = snapshot["ventilation"]
    assert current["mode"] == NAVA
    assert snapshot["sbs_vent_mode"] == NAVA
    assert current["values"] == nava_values
    assert current["values"]["FiO2 (%)"] == "33 %"
    assert "FiO2 set (%)" not in current["values"]
    assert "Vt (Set, mL)" not in current["values"]
    assert current["mode_history"]["reported_at"] == ""
    assert current["mode_history"]["latest_confirmed"] is False
    previous = current["mode_history"]["other_modes"]
    assert sum(item["mode"] == PRVC for item in previous) == 1
    assert not any(item["mode"] == NAVA for item in previous)
    assert next(item["values"] for item in previous if item["mode"] == PRVC) == original["values"]
    assert ss["vent_" + sheet["id"] + "_" + str(LABELS.index("FiO2 set (%)"))] == ""
    assert ss["vent_" + sheet["id"] + "_" + str(LABELS.index("FiO2 (%)"))] == "33 %"


def test_cyclic_mode_promotion_preserves_edits_despite_stale_history_widget(app):
    ss = load_app_history(app)
    sheet = ss["drafts"]["P4102"]
    original_prvc_values = deepcopy(sheet["ventilation"]["values"])
    old_nava_widget = history_widget_key(app, ss, 0, "NAVA level")
    ss[old_nava_widget] = "2.8"
    mode_key = "vent_" + sheet["id"] + "_0"
    ss[mode_key] = NAVA
    app.ventilation_change("P4102", "Vent Mode", mode_key)

    # Simulate the old historical widget remaining until the next UI cleanup.
    ss[old_nava_widget] = "2.8"
    nava_key = "vent_" + sheet["id"] + "_" + str(LABELS.index("NAVA level"))
    ss[nava_key] = "3.6"
    app.ventilation_change("P4102", "NAVA level", nava_key)
    assert ss["drafts"]["P4102"]["ventilation"]["values"]["NAVA level"] == "3.6"

    ss[mode_key] = PRVC
    app.ventilation_change("P4102", "Vent Mode", mode_key)
    app.save_room(None)

    saved = ss["vault"]["rooms"]["P4102"]["ventilation"]
    assert saved["mode"] == PRVC
    assert saved["values"] == original_prvc_values
    previous = saved["mode_history"]["other_modes"]
    nava_entries = [item for item in previous if item["mode"] == NAVA]
    assert len(nava_entries) == 1
    assert nava_entries[0]["values"]["NAVA level"] == "3.6"
    assert not any(item["mode"] == PRVC for item in previous)


def test_app_new_paste_cannot_reuse_history_widgets_or_old_settings(app):
    ss = load_app_history(app)
    previous_id = ss["drafts"]["P4102"]["id"]
    key = history_widget_key(app, ss, 0, "NAVA level")
    ss[key] = "3.2"
    app.ventilation_history_change("P4102", 0, "NAVA level", key)
    ss["paste"] = block("c", source(None, extra_sections=False)) + block("d", D_ETT)
    app.create_handoff()
    current = ss["drafts"]["P4102"]
    assert current["id"] != previous_id
    assert set(current["ventilation"]) == {"mode", "values"}
    assert "NAVA" not in handoff_text(current)

