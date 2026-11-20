"""Synthetic ECLS placement, typography, and single/batch export checks."""
from copy import deepcopy
from datetime import datetime
from html import unescape
from io import BytesIO
import re
from zoneinfo import ZoneInfo

import fitz
import pytest
from pypdf import PdfReader

from anthropometrics import empty_anthropometrics
from clinical_style import clinical_markup
from ecls import ecls_text, parse_ecls
from exports import (handoff_html, handoff_pdf, handoff_text, handoffs_html,
                     handoffs_pdf, pdf_content_signature)
from lab_windows import display_clock
from labs import parse_labs
from models import new_sheet
from vitals import parse_vitals


NOW = datetime(2026, 11, 20, 10, 0, tzinfo=ZoneInfo("America/New_York"))
BODY = """System Readings
ECMO Mode: Veno-arterial
Oxygenator Day: 0
Pump Flow (L/min): 1.6 LPM
Set Speed (rev/min): 3100 Rev/Min
Sweep Gas Flow Rate (L/min): 0.7
Blender FiO2 (%): 40 %"""


def example(room="P4102"):
    sheet = new_sheet(room)
    parsed = parse_ecls(BODY)
    assert not parsed.error
    sheet["ecls"] = parsed.data
    sheet["dosing_weight"] = "20 kg"
    sheet["anthropometrics"] = empty_anthropometrics()
    sheet["anthropometrics"]["bsa"] = "0.8 m²"
    sheet["vitals"] = parse_vitals("VITALS:\nHeart Rate: 100\nBP: 100/60").rows
    sheet["labs"] = parse_labs("LABS:\nComponent\tValue\tDate\n"
                               "LACTATE\t1.1\t11/20/2026 09:00").data
    sheet["fields"]["Cardiovascular"] = "SYNTHETIC CV NOTES"
    return sheet


def plain(value):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", value)))


def pdf_text(value):
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(value)).pages)


@pytest.mark.parametrize("renderer", [
    lambda s: handoff_text(s, printed_at=NOW),
    lambda s: handoff_html(s, printed_at=NOW),
    lambda s: handoffs_html([s], printed_at=NOW),
    lambda s: pdf_text(handoff_pdf(s, printed_at=NOW)),
    lambda s: pdf_text(handoffs_pdf([s], printed_at=NOW)),
])
def test_ecls_below_cv_vitals_and_labs_before_notes_in_every_format(renderer):
    sheet = example()
    before = deepcopy(sheet)
    with display_clock(NOW):
        output = plain(renderer(sheet))
    assert output.count("ECLS settings:") == 1
    assert (output.index("Heart Rate:") < output.index("Lactate:")
            < output.index("ECLS settings:") < output.index("SYNTHETIC CV NOTES"))
    for expected in ("Mode: VA [Oxy Day: 0]", "Blood flow: 1.6 L/min",
                     "80.0 mL/kg/min", "[CI: 2 L/min/m²]",
                     "RPM: 3100", "Sweep: 0.7 L/min"):
        assert expected in output
    assert re.search(r"FiO[2₂]: 40%", output)
    assert sheet == before


def test_heading_is_bold_and_settings_are_body_text_in_html_and_pdf():
    sheet = example()
    assert clinical_markup("ECLS settings:\nMode: VA") == "<b>ECLS settings:</b>\nMode: VA"
    with display_clock(NOW):
        html = handoff_html(sheet)
        doc = fitz.open(stream=handoff_pdf(sheet), filetype="pdf")
    assert "<b>ECLS settings:</b>" in html
    assert "<b>Mode: VA" not in html
    assert len(doc) == 1
    spans = [span for page in doc for block in page.get_text("dict")["blocks"]
             if "lines" in block for line in block["lines"] for span in line["spans"]]
    headings = [s for s in spans if "ECLS settings:" in s["text"]]
    assert len(headings) == 1 and "Bold" in headings[0]["font"]
    assert headings[0]["size"] <= 8
    modes = [s for s in spans if "Mode: VA" in s["text"]]
    assert modes and all("Bold" not in s["font"] for s in modes)
    # The generated ECLS text fits within the page at the existing clinical size.
    assert all(0 <= s["bbox"][0] < s["bbox"][2] <= 792 for s in spans)
    assert all(0 <= s["bbox"][1] < s["bbox"][3] <= 612 for s in spans)


def test_absent_ecls_adds_no_heading_to_legacy_sheets():
    sheet = new_sheet("P4102")
    sheet["fields"]["Cardiovascular"] = "SYNTHETIC CV NOTES"
    with display_clock(NOW):
        outputs = [handoff_text(sheet), handoff_html(sheet), pdf_text(handoff_pdf(sheet))]
    assert all("ECLS settings" not in value for value in outputs)


def test_batch_keeps_each_room_ecls_separate():
    first = example()
    second = example("P4104")
    second["ecls"]["mode"] = "VV"
    second["ecls"]["rpm"] = "2500"
    with display_clock(NOW):
        doc = PdfReader(BytesIO(handoffs_pdf([first, second])))
        html = handoffs_html([first, second])
    assert len(doc.pages) == 2
    first_text, second_text = [plain(p.extract_text()) for p in doc.pages]
    assert "Mode: VA" in first_text and "RPM: 3100" in first_text
    assert "Mode: VV" not in first_text and "RPM: 2500" not in first_text
    assert "Mode: VV" in second_text and "RPM: 2500" in second_text
    assert "Mode: VA" not in second_text and "RPM: 3100" not in second_text
    assert html.count("<b>ECLS settings:</b>") == 2


@pytest.mark.parametrize("change", ["flow", "weight", "bsa", "remove"])
def test_current_ecls_and_denominators_invalidate_pdf_content_cache(change):
    first = example()
    second = deepcopy(first)
    if change == "flow":
        second["ecls"]["blood_flow_l_min"] = "1.7"
    elif change == "weight":
        second["dosing_weight"] = "21 kg"
    elif change == "bsa":
        second["anthropometrics"]["bsa"] = "0.9 m²"
    else:
        second.pop("ecls")
    with display_clock(NOW):
        assert pdf_content_signature(first) != pdf_content_signature(second)
    assert ecls_text(first) != ecls_text(second)
