"""Current respiratory and cardiovascular handoff sections in actual notes."""
from copy import deepcopy

import pytest

from devices import parse_devices
from ecls import parse_ecls
from note_cardiovascular import CV_TEMPLATE_FILES
from note_generator import generate_note
from note_respiratory import RESP_TEMPLATE_FILES
from note_word import render_note_docx
from pacemaker import parse_pacemaker
from test_note_generator import order, sheet_with
from test_note_neuro_integration import W, medication_cell, section, text, tree


CASES = (
    ("pc", "art", "ACKRPC", "ACKCVART", "Set PIP:"),
    ("prvc", "art_cvl", "ACKRPRVC", "ACKCVARTCVL", "Set TV:"),
    ("avaps", "art_cvl_ecls", "ACKRAVAPS", "ACKCVARTCVLECLS", "AVAPS Target TV:"),
    ("bpap", "cvl", "ACKRBPAP", "ACKCVCVL", "Total Inspiratory Pressure:"),
    ("hfnc", "none", "ACKRHFNC", "ACKCVNONE", "Flow Rate:"),
    ("none", "art_cvl_pacemaker", "ACKRNONE", "ACKCVARTCVLPACEMAKER", "PHYSICAL EXAMINATION"),
    ("nava", "art_cvl_ecls", "ACKRNAVA", "ACKCVARTCVLECLS", "NAVA Level:"),
    ("home_vent", "art_cvl", "ACKRHOMEVENT", "ACKCVARTCVL", "Pmin:"),
)


def example(respiratory="prvc", cardiovascular="art_cvl", *, include_pacemaker=False):
    sheet = sheet_with(
        order("Terbutaline infusion", "0.1 mcg/kg/min", section="Respiratory", frequency="Continuous"),
        order("Budesonide", "0.5 mg", section="Respiratory", route="Nebulization"),
        order("Albuterol", "2.5 mg", section="Respiratory", frequency="q4h PRN", route="Nebulization"),
        order("Milrinone infusion", "0.5 mcg/kg/min", section="Cardiovascular", frequency="Continuous"),
        order("Enalapril", "2 mg", section="Cardiovascular", route="Oral"),
        order("Hydralazine", "1 mg", section="Cardiovascular", frequency="q6h PRN"),
        order("Clobazam", "100 mg", route="Oral"),
        order("Pantoprazole", "20 mg", section="FEN / GI"),
    )
    sheet["anthropometrics"] = {"age": "24 months"}
    modes = {"pc": "PC", "prvc": "PRVC", "avaps": "AVAPS", "nava": "NAVA", "home_vent": "PC"}
    if respiratory in modes:
        sheet["ventilation"] = {"mode": modes[respiratory], "values": {}}
        if respiratory == "home_vent":
            sheet["ventilation"]["values"] = {"Pmin": "8", "Pmax": "25", "Timin": "0.5", "Timax": "1.2"}
    elif respiratory in ("bpap", "hfnc"):
        sheet["noninvasive"] = [{
            "device": "BiPAP" if respiratory == "bpap" else "HFNC",
            "values": {"IPAP": "12", "EPAP": "6", "FiO2": "30"} if respiratory == "bpap" else {"Flow": "20", "FiO2": "30"},
            "flow_inferred": False, "pressure_inferred": False,
        }]
    else:
        sheet["fields"]["Respiratory"] = "Room air"
    line_text = []
    if cardiovascular in ("art", "art_cvl", "art_cvl_ecls", "art_cvl_pacemaker"):
        line_text.append("Arterial Line Right Radial-Site Assessment: Clean, Dry, Intact")
    if cardiovascular in ("cvl", "art_cvl", "art_cvl_ecls", "art_cvl_pacemaker"):
        line_text.append("CVC Right Internal jugular-Site Assessment: Clean, Dry, Intact")
    if line_text:
        parsed = parse_devices("\n".join(line_text))
        assert not parsed.error
        sheet["devices"] = parsed.data
    if cardiovascular == "art_cvl_ecls":
        parsed = parse_ecls("ECMO Mode: VA\nPump Flow (L/min): 2.3\nSet Speed (rev/min): 3400\nSweep Gas Flow Rate (L/min): 1.2\nBlender FiO2 (%): 50")
        assert not parsed.error
        sheet["ecls"] = parsed.data
    if cardiovascular == "art_cvl_pacemaker" or include_pacemaker:
        parsed = parse_pacemaker("Pacemaker: Yes\nPacer Mode: AAI\nAtrial Rate (beats/min): 140")
        assert not parsed.error
        sheet["pacemaker"] = parsed.data
    return sheet


def plain_sections(result):
    respiratory = result["text"].split("\n\nRESPIRATORY\n", 1)[1].split("\n\nCARDIOVASCULAR\n", 1)[0]
    cardiovascular = result["text"].split("\n\nCARDIOVASCULAR\n", 1)[1].split("\n\nFLUIDS ELECTROLYTES", 1)[0]
    return {"Respiratory": respiratory, "Cardiovascular": cardiovascular}


@pytest.mark.parametrize("resp,cv,resp_phrase,cv_phrase,distinctive", CASES)
def test_all_supplied_sections_select_from_handoff_and_keep_medications_in_the_correct_cell(resp, cv, resp_phrase, cv_phrase, distinctive):
    sheet = example(resp, cv)
    before = deepcopy(sheet)
    result = generate_note(sheet)
    assert result["respiratory_variant"] == resp and result["respiratory_phrase"] == resp_phrase
    assert result["cardiovascular_variant"] == cv and result["cardiovascular_phrase"] == cv_phrase
    assert result["respiratory_reason"] and result["cardiovascular_reason"]
    assert result["cardiovascular_include_pacemaker"] == (cv == "art_cvl_pacemaker")
    root = tree(render_note_docx(result))
    plain = plain_sections(result)
    assert distinctive in plain["Respiratory"] and distinctive in text(section(root, "RESPIRATORY"))
    for system, title, excluded in (("Respiratory", "RESPIRATORY", "Milrinone"), ("Cardiovascular", "CARDIOVASCULAR", "Budesonide")):
        table = section(root, title)
        cell = medication_cell(table)
        assert excluded not in text(table) + plain[system]
        assert "Clobazam" not in text(table) + plain[system]
        assert "Pantoprazole" not in text(table) + plain[system]
        assert "***" not in text(cell) + plain[system]
        for group in ("Drips", "Scheduled", "PRN"):
            assert group + ":" in text(cell) and group + ":" in plain[system]
            for medication in result["medications"]["sections"][system][group]:
                assert text(root).count(medication) == result["text"].count(medication) == 1
                assert medication in text(cell) and medication in plain[system]
    titles = [text(next(table.iter(W + "p"))) for table in root.find(W + "body").findall(W + "tbl")]
    assert titles[titles.index("NEUROLOGY"):titles.index("HEMATOLOGY") + 1] == [
        "NEUROLOGY", "RESPIRATORY", "CARDIOVASCULAR", "FLUIDS ELECTROLYTES NUTRITION/GASTROINTESTINAL", "HEMATOLOGY"]
    for old in ("{CKRESPLIST:45220}", "{CKCVLIST:45328}"):
        assert old not in text(root) + result["text"]
    assert text(root).count("***") == result["text"].count("***") == 2
    if resp == "avaps":
        assert "@FLOW24(3040000087)@" in plain["Respiratory"]
    if cv == "art_cvl_ecls":
        assert "EXTRACORPOREAL LIFE SUPPORT" in plain["Cardiovascular"]
    if cv == "art_cvl_pacemaker":
        assert "{ACKCVPACEMAKER:45347}" in plain["Cardiovascular"]
    assert sheet == before


@pytest.mark.parametrize("resp,cv,resp_phrase,cv_phrase,distinctive", CASES)
def test_empty_medication_cells_do_not_keep_placeholders_or_change_selection(resp, cv, resp_phrase, cv_phrase, distinctive):
    sheet = example(resp, cv)
    sheet["medications"] = []
    result = generate_note(sheet)
    root = tree(render_note_docx(result))
    assert result["respiratory_variant"] == resp and result["cardiovascular_variant"] == cv
    for title in ("RESPIRATORY", "CARDIOVASCULAR"):
        cell = medication_cell(section(root, title))
        assert text(cell) == "" and cell.find(W + "p") is not None
    assert text(root).count("***") == 2


def test_ecls_and_pacemaker_share_one_cv_section_and_one_medication_list():
    sheet = example("nava", "art_cvl_ecls", include_pacemaker=True)
    result = generate_note(sheet)
    assert result["cardiovascular_variant"] == "art_cvl_ecls"
    assert result["cardiovascular_include_pacemaker"]
    root = tree(render_note_docx(result))
    cv = section(root, "CARDIOVASCULAR")
    plain = plain_sections(result)["Cardiovascular"]
    for value in ("EXTRACORPOREAL LIFE SUPPORT", "@FLOW24(1120100493)@", "PACEMAKER", "{ACKCVPACEMAKER:45347}"):
        assert value in text(cv) and value in plain
    assert text(cv).count("{ACKCVPACEMAKER:45347}") == plain.count("{ACKCVPACEMAKER:45347}") == 1
    assert text(cv).count("MEDICATIONS") == plain.count("MEDICATIONS") == 1
    for values in result["medications"]["sections"]["Cardiovascular"].values():
        for value in values:
            assert text(cv).count(value) == plain.count(value) == 1


@pytest.mark.parametrize("mapping,variant", [(RESP_TEMPLATE_FILES, "prvc"), (CV_TEMPLATE_FILES, "art_cvl")])
def test_missing_selected_cardiorespiratory_template_fails_clearly(mapping, variant, tmp_path, monkeypatch):
    monkeypatch.setitem(mapping, variant, tmp_path / "missing.docx")
    with pytest.raises(ValueError, match="template could not be read"):
        generate_note(example())


def test_missing_pacemaker_supplement_fails_clearly_when_ecls_and_pacing_are_present(tmp_path, monkeypatch):
    monkeypatch.setitem(CV_TEMPLATE_FILES, "art_cvl_pacemaker", tmp_path / "missing.docx")
    with pytest.raises(ValueError, match="cardiovascular template could not be read"):
        generate_note(example("nava", "art_cvl_ecls", include_pacemaker=True))


def test_attestation_does_not_read_cardiorespiratory_assets_or_gain_medication_tables(tmp_path, monkeypatch):
    for mapping in (RESP_TEMPLATE_FILES, CV_TEMPLATE_FILES):
        for key in mapping:
            monkeypatch.setitem(mapping, key, tmp_path / "missing.docx")
    result = generate_note(example("nava", "art_cvl_ecls", include_pacemaker=True), note_type="attestation")
    assert result["respiratory_variant"] is result["cardiovascular_variant"] is None
    assert not result["cardiovascular_include_pacemaker"]
    output = text(tree(render_note_docx(result, note_type="attestation")))
    for value in ("Terbutaline", "Milrinone", "EXTRACORPOREAL LIFE SUPPORT", "PACEMAKER", "MEDICATIONS"):
        assert value not in output + result["text"]
