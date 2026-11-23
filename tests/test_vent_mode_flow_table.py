"""Synthetic Epic flow-table regressions. No patient records are retained."""
from copy import deepcopy

import pytest

from noninvasive import parse_respiratory, read_fields
from ventilation import format_ventilation, parse_ventilation, validate_ventilation


PRVC = "Volume Targeted PC - IMV"
PRVC_FULL = "Volume Targeted Pressure Control - Intermittent Mandatory Ventilation"
GENERAL = """Invasive Ventilation:
Mode: Vent Mode: {mode}
Respiratory Rate: Resp Rate (Set): 14
Set TV: Vt (Set, mL): 180 mL
Set PEEP: PEEP (cm H2O): 5 cm H2O
Inspiratory Time: Insp Time (sec): 0.9 sec
FiO2: FiO2 set (%): 31 %
Pressure Support: Pressure Support (cm H2O): 10 cm H20
Average Volume-Assured Pressure Support Settings:
AVAPS Respiratory Rate: 15
AVAPS Target TV: Vt Set/Target ml: 160
PS Min: 4
PS Max: 18
NAVA Ventilator Settings:
NAVA Level: 2.4
Set PEEP: PEEP (cm H2O): 8 cm H2O
Set FIO2: FiO2 (%): 29 %
CPAP Trial Settings:
Pressure Support: Pressure Support (cm H2O): 8 cm H20
Set PEEP: PEEP (cm H2O): 7 cm H2O
FiO2: FiO2 set (%): 40 %
Weaning Tidal Volumes: Weaning Tidal Volume Avg: 120 mL Min: 90 mL Max: 150 mL
Weaning Tolerance: Good
"""
D_ETT = "Non-invasive Ventilation:\nO2 Delivery Method: Endotracheal tube\nFiO2 (%): 27 %\n"


def table(times, modes):
    return "\t" + "\t".join(times) + "\nOther\nVent Mode\t" + "\t".join(modes) + "\n"


def source(*tables, mode=PRVC_FULL):
    return GENERAL.format(mode=mode) + "\nAll Vent Modes:\n\n" + "\n".join(tables)


def parsed(text):
    result = parse_ventilation(text)
    assert not result.error, result.error
    assert result.data is not None
    validate_ventilation(result.data)
    return result.data


def two_blocks(last=PRVC):
    return source(
        table(["03/03/26 1710", "03/04/26 0136", "03/04/26 0547"], [PRVC, PRVC, PRVC]),
        table(["03/04/26 0913", "03/04/26 1130", "03/04/26 1140"], [PRVC, "PS - CPAP", last]),
    )


def test_split_flow_table_keeps_latest_conventional_mode_and_prior_cpap_trial():
    data = parsed(two_blocks())
    assert data["mode"] == PRVC
    assert data["values"]["Vt (Set, mL)"] == "180 mL"
    assert data["values"]["PEEP (cm H2O)"] == "5 cm H2O"
    assert data["values"]["FiO2 set (%)"] == "31 %"
    meta = data["mode_history"]
    assert meta["reported_at"] == "2026-03-04T11:40"
    assert meta["latest_confirmed"] is True
    previous = meta["other_modes"]
    assert len(previous) == 1
    assert previous[0]["include"] is True
    assert previous[0]["reported_at"] == "2026-03-04T11:30"
    assert previous[0]["values"]["Pressure Support (cm H2O)"] == "8 cm H20"
    assert previous[0]["values"]["PEEP (cm H2O)"] == "7 cm H2O"
    assert previous[0]["values"]["FiO2 set (%)"] == "40 %"
    text = format_ventilation(data)
    assert text.count("Mode:") == 2
    main, trial = text.split("\n---\n")
    assert main.startswith("Mode: PRVC-IMV (03/04/26 11:40)")
    assert "Set TV: 180 mL" in main and "FiO2: 31 %" in main
    assert trial.startswith("CPAP Trial Data\nMode: PS-CPAP (03/04/26 11:30)")
    assert "Weaning TV: 90–150 mL" in trial
    assert "FiO2: 40 %" in trial and "Set RR:" not in trial


@pytest.mark.parametrize("mode", [
    "PS - CPAP", "ps-cpap", " PS  -  cpap ", "PS- CPAP", "PS -CPAP", "PS – CPAP",
    "Pressure Support - Continuous Positive Airway Pressure",
])
def test_prior_cpap_aliases_are_visible_without_changing_current_mode(mode):
    data = parsed(source(table(["03/04/26 1130", "03/04/26 1140"], [mode, PRVC])))
    assert data["mode"] == PRVC
    assert data["mode_history"]["reported_at"] == "2026-03-04T11:40"
    assert data["mode_history"]["other_modes"][0]["include"] is True
    assert "CPAP Trial Data\nMode: PS-CPAP (03/04/26 11:30)" in format_ventilation(data)


def test_repeated_cpap_trials_display_once_at_the_latest_trial_time():
    data = parsed(source(
        table(["03/04/26 1300", "03/04/26 0900"], ["PS - CPAP", "PS-CPAP"]),
        table(["03/04/26 2000", "03/04/26 1130"], [PRVC, "PS - CPAP"]),
    ))
    previous = data["mode_history"]["other_modes"]
    assert len(previous) == 1
    assert previous[0]["reported_at"] == "2026-03-04T13:00"
    text = format_ventilation(data)
    assert text.count("CPAP Trial Data") == 1
    assert "Mode: PS-CPAP (03/04/26 13:00)" in text
    assert "(03/04/26 09:00)" not in text and "(03/04/26 11:30)" not in text


def test_prior_cpap_without_scoped_settings_does_not_borrow_current_values():
    general = GENERAL.format(mode=PRVC_FULL).split("CPAP Trial Settings:", 1)[0]
    text = general + "All Vent Modes:\n" + table(
        ["03/04/26 1130", "03/04/26 1140"], ["PS - CPAP", PRVC])
    data = parsed(text)
    previous = data["mode_history"]["other_modes"][0]
    assert previous["include"] is True
    assert previous["values"] == {}
    main, trial = format_ventilation(data).split("\n---\n")
    assert "Set TV: 180 mL" in main and "Pressure Support: 10 cm H2O" in main
    assert trial == ("CPAP Trial Data\nMode: PS-CPAP (03/04/26 11:30)\n"
                     "Settings not available for this mode in the paste.")


def test_only_prior_cpap_is_visible_and_user_can_hide_it():
    data = parsed(source(table(
        ["03/04/26 1000", "03/04/26 1130", "03/04/26 1140"],
        ["NAVA", "PS - CPAP", PRVC])))
    previous = data["mode_history"]["other_modes"]
    nava = next(record for record in previous if record["mode"] == "NAVA")
    trial = next(record for record in previous if record["mode"] == "PS - CPAP")
    assert nava["include"] is False and trial["include"] is True
    output = format_ventilation(data)
    assert "CPAP Trial Data" in output and "Mode: NAVA" not in output
    trial["include"] = False
    assert "CPAP Trial Data" not in format_ventilation(data)


@pytest.mark.parametrize("mode", ["PS - CPAP", "ps-cpap", " PS  -  cpap ", "PS- CPAP", "PS -CPAP", "PS – CPAP"])
def test_newest_ps_cpap_uses_only_trial_settings_across_both_readers(mode):
    text = two_blocks(last=mode)
    data = parsed(text)
    assert data["mode_history"]["reported_at"] == "2026-03-04T11:40"
    assert data["mode_history"]["latest_confirmed"] is True
    assert data["values"]["Pressure Support (cm H2O)"] == "8 cm H20"
    assert data["values"]["PEEP (cm H2O)"] == "7 cm H2O"
    assert data["values"]["FiO2 set (%)"] == "40 %"
    assert "Vt (Set, mL)" not in data["values"]
    assert "Resp Rate (Set)" not in data["values"]
    fields = read_fields(text, "C")
    assert fields["peep"] == "7 cm H2O"
    assert fields["fio2_set"] == "40 %"
    support = parse_respiratory(text, D_ETT)
    assert not support.error
    assert support.invasive is not None and support.devices == []
    output = format_ventilation(data)
    assert output.startswith("CPAP Trial Data\nMode: PS-CPAP")
    assert "Weaning TV: 90–150 mL" in output
    assert "FiO2: 31 %" not in output and "Set RR:" not in output


def test_timestamp_order_wins_over_table_and_column_position():
    text = source(
        table(["03/04/26 1140", "03/04/26 1130"], [PRVC, "PS - CPAP"]),
        table(["03/04/26 0547", "03/03/26 1710"], ["NAVA", PRVC]),
    )
    data = parsed(text)
    assert data["mode"] == PRVC
    assert data["mode_history"]["reported_at"] == "2026-03-04T11:40"


@pytest.mark.parametrize("line_ending", ["\n", "\r\n", "\r"])
def test_date_rollover_and_clock_formats(line_ending):
    text = source(
        table(["12/31/26 2358", "01/01/2027 12:02 AM", "12/31/2026 11:59 PM"], [PRVC, "PS - CPAP", "NAVA"]),
    ).replace("\n", line_ending)
    data = parsed(text)
    assert data["mode"] == "PS - CPAP"
    assert data["mode_history"]["reported_at"] == "2027-01-01T00:02"


@pytest.mark.parametrize("modes,expected,time", [
    ([PRVC, "", "PS - CPAP"], "PS - CPAP", "11:40"),
    (["", "PS - CPAP", ""], "PS - CPAP", "11:30"),
    ([PRVC, "PS - CPAP"], "PS - CPAP", "11:30"),
    ([PRVC, "No data recorded", "--"], PRVC, "09:13"),
])
def test_empty_mode_cells_keep_their_timestamp_alignment(modes, expected, time):
    data = parsed(source(table(["03/04/26 0913", "03/04/26 1130", "03/04/26 1140"], modes)))
    assert data["mode"] == expected
    assert data["mode_history"]["reported_at"] == "2026-03-04T" + time


@pytest.mark.parametrize("empty", ["", "All Vent Modes:\n", "All Vent Modes:\n" + table(["03/04/26 1130", "03/04/26 1140"], ["", "--"])])
def test_empty_or_absent_flow_history_keeps_legacy_snapshot(empty):
    data = parsed(GENERAL.format(mode=PRVC_FULL) + empty)
    assert data["mode"] == PRVC_FULL
    assert data["values"]["PEEP (cm H2O)"] == "5 cm H2O"
    assert "mode_history" not in data
    assert "CPAP Trial Data" not in format_ventilation(data)


def test_flow_table_can_supply_mode_when_original_smartlink_is_removed():
    text = two_blocks().replace("Mode: Vent Mode: " + PRVC_FULL + "\n", "")
    data = parsed(text)
    assert data["mode"] == PRVC
    assert data["values"]["Vt (Set, mL)"] == "180 mL"
    assert data["values"]["FiO2 set (%)"] == "31 %"
    assert data["mode_history"]["latest_confirmed"] is True


def test_a_different_latest_mode_does_not_borrow_generic_settings():
    data = parsed(source(table(["03/04/26 1130", "03/04/26 1140"], [PRVC, "Pressure Control"])))
    assert data["mode"] == "Pressure Control"
    assert data["values"] == {}
    assert "Set TV: 180" not in format_ventilation(data)


@pytest.mark.parametrize("mode,key,value", [
    ("Neurally Adjusted Ventilatory Assist", "NAVA level", "2.4"),
    ("Average Volume-Assured Pressure Support", "Vt Set/Target ml", "160"),
])
def test_special_latest_mode_selects_its_dedicated_section(mode, key, value):
    text = source(table(["03/04/26 1130", "03/04/26 1140"], [PRVC, mode]))
    data = parsed(text)
    assert data["mode"] == mode
    assert data["values"][key] == value
    assert "Vt (Set, mL)" not in data["values"]
    assert "Weaning Tidal Volume" not in data["values"]
    assert read_fields(text, "C")["mode"] == mode


def test_latest_niv_mode_uses_existing_noninvasive_route():
    text = source(table(["03/04/26 1130", "03/04/26 1140"], [PRVC, "BiLevel NIV"]))
    d = "O2 Delivery Method: Bi-PAP mask\nIPAP: 12\nEPAP: 6\nFiO2 (%): 35 %\n"
    result = parse_respiratory(text, d)
    assert not result.error
    assert result.invasive is None
    assert len(result.devices) == 1
    assert result.devices[0]["device"] == "BiPAP"
    assert result.devices[0]["values"] == {"IPAP": "12", "EPAP": "6", "FiO2": "35 %"}


def test_unknown_latest_mode_retains_label_without_guessing_or_older_current_mode():
    data = parsed(source(table(["03/04/26 1130", "03/04/26 1140"], [PRVC, "Unlisted support mode"])))
    assert data["mode"] == "Unlisted support mode"
    assert data["values"] == {}
    assert data["mode_history"]["reported_at"] == "2026-03-04T11:40"
    text = format_ventilation(data)
    assert "Mode: Unlisted support mode" in text
    assert "Mode: PRVC-IMV" not in text
    corrupted = deepcopy(data)
    corrupted["values"]["PEEP (cm H2O)"] = "5"
    with pytest.raises(ValueError):
        validate_ventilation(corrupted)


def test_history_stops_at_the_next_source_section():
    text = two_blocks() + "\nNon-invasive Ventilation:\n" + table(["03/04/26 2359"], ["PS - CPAP"])
    data = parsed(text)
    assert data["mode"] == PRVC
    assert data["mode_history"]["reported_at"] == "2026-03-04T11:40"


@pytest.mark.parametrize("bad_date", ["", "03/55/26 1130", "03/04/26 2961"])
def test_bad_timestamp_cell_does_not_shift_neighboring_mode_values(bad_date):
    data = parsed(source(table(["03/04/26 0913", bad_date, "03/04/26 1140"], [PRVC, "PS - CPAP", "NAVA"])))
    assert data["mode"] == "NAVA"
    assert data["mode_history"]["reported_at"] == "2026-03-04T11:40"
    assert data["mode_history"]["latest_confirmed"] is False
    prior = next(item for item in data["mode_history"]["other_modes"] if item["mode"] == "PS - CPAP")
    assert prior["reported_at"] == ""
    assert prior["include"] is False
    assert "CPAP Trial Data" not in format_ventilation(data)
    assert any("missing or invalid times" in note for note in data["mode_history"]["notes"])


def test_extra_mode_cell_is_not_assigned_a_neighboring_timestamp():
    data = parsed(source(
        table(["03/04/26 1000"], [PRVC]),
        table(["03/04/26 1140"], [PRVC, "PS - CPAP"]),
    ))
    assert data["mode"] == PRVC
    assert data["mode_history"]["reported_at"] == "2026-03-04T10:00"
    assert data["mode_history"]["latest_confirmed"] is False
    assert "CPAP Trial Data" not in format_ventilation(data)


def test_different_modes_at_same_newest_timestamp_remain_unconfirmed():
    data = parsed(source(table(["03/04/26 1140", "03/04/26 1140"], [PRVC, "PS - CPAP"])))
    assert data["mode_history"]["latest_confirmed"] is False
    assert any("share the newest timestamp" in note for note in data["mode_history"]["notes"])
    prior = data["mode_history"]["other_modes"][0]
    assert prior["include"] is True
    assert prior["reported_at"] == "2026-03-04T11:40"
    assert "Mode: PS-CPAP (03/04/26 11:40)" in format_ventilation(data)


@pytest.mark.parametrize("latest,expected", [("PS - CPAP", "PS-CPAP"), ("Unlisted support mode", "Unlisted support mode")])
def test_import_and_exports_use_latest_mode_without_retaining_raw_history(latest, expected):
    from exports import handoff_html, handoff_text
    from importing import import_replacement
    from models import new_vault, validate_sheet

    def block(letter, content):
        marker = letter * 24
        return marker + "\n" + content + "\n" + marker + "\n"

    result = import_replacement("P4102", block("c", two_blocks(latest)) + block("d", D_ETT), new_vault()["settings"])
    assert not result.errors, result.errors
    assert result.sheet is not None
    validate_sheet(result.sheet)
    assert result.sheet["sbs_vent_mode"] == latest
    assert result.sheet["noninvasive"] == []
    if latest == "Unlisted support mode":
        assert result.sheet["ventilation"]["values"] == {}
    for output in (handoff_text(result.sheet), handoff_html(result.sheet)):
        assert expected in output
        assert "CPAP Trial Data" in output
        assert "PRVC-IMV" not in output
        assert "All Vent Modes" not in output
