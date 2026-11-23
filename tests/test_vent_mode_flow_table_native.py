"""Native Streamlit import, replacement, preview, and print for mode tables."""
from copy import deepcopy
from html import unescape
from io import BytesIO
import re

from pypdf import PdfReader

from exports import handoff_pdf
from test_prn_preview_native import native_app, import_source
from test_vent_mode_flow_table import D_ETT, PRVC, two_blocks


def _phrase(latest):
    def block(letter, value):
        marker = letter * 24
        return marker + "\n" + value.rstrip() + "\n" + marker + "\n"

    return (block("a", "Diagnoses:\nSynthetic ventilator flow-table example")
            + block("c", two_blocks(latest)) + block("d", D_ETT))


def _preview_and_pdf(at, sheet):
    html = next(item.proto.srcdoc for item in at.get("iframe")
                if "Synthetic ventilator flow-table example" in item.proto.srcdoc)
    preview = unescape(re.sub(r"<[^>]*>", "", html))
    pdf = PdfReader(BytesIO(handoff_pdf(sheet)))
    printed = "\n".join(page.extract_text() for page in pdf.pages)
    return [re.sub(r"\s+", " ", text) for text in (preview, printed)]


def test_native_table_import_and_cpap_replacement_update_preview_saved_room_and_pdf(native_app):
    at = native_app
    import_source(at, _phrase(PRVC))
    conventional = deepcopy(at.session_state["drafts"]["P4102"])
    assert at.session_state["vault"]["rooms"]["P4102"] == conventional
    assert conventional["ventilation"]["mode"] == PRVC
    assert conventional["sbs_vent_mode"] == PRVC
    assert conventional["ventilation"]["values"]["FiO2 set (%)"] == "31 %"
    for text in _preview_and_pdf(at, conventional):
        assert "Mode: PRVC-IMV (03/04/26 11:40)" in text
        assert "Set TV: 180 mL" in text
        assert "FiO2: 31 %" in text
        assert text.count("CPAP Trial Data") == 1
        assert "Mode: PS-CPAP (03/04/26 11:30)" in text
        assert "Pressure Support: 8 cm H2O" in text
        assert "Set PEEP: 7 cm H2O" in text and "FiO2: 40 %" in text
        assert re.search(r"Weaning TV: 90[–-]150 mL", text)
        assert text.index("Mode: PRVC-IMV") < text.index("CPAP Trial Data")

    import_source(at, _phrase("PS - CPAP"))
    trial = deepcopy(at.session_state["drafts"]["P4102"])
    assert trial["id"] != conventional["id"]
    assert at.session_state["vault"]["rooms"]["P4102"] == trial
    assert trial["ventilation"]["mode"] == "PS - CPAP"
    assert trial["sbs_vent_mode"] == "PS - CPAP"
    assert trial["noninvasive"] == []
    assert trial["ventilation"]["values"]["FiO2 set (%)"] == "40 %"
    assert "Vt (Set, mL)" not in trial["ventilation"]["values"]
    for text in _preview_and_pdf(at, trial):
        assert text.count("CPAP Trial Data") == 1
        assert "Mode: PS-CPAP (03/04/26 11:40)" in text
        assert "Pressure Support: 8 cm H2O" in text
        assert "Set PEEP: 7 cm H2O" in text and "FiO2: 40 %" in text
        assert "Weaning TV:" in text
        assert "PRVC-IMV" not in text and "Set TV: 180" not in text
        assert "FiO2: 31 %" not in text
    assert not at.exception and not at.error
