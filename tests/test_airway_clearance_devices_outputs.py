"""Synthetic airway clearance text, HTML and PDF output regressions."""
from copy import deepcopy
from datetime import datetime, timezone
from html import unescape
from io import BytesIO
import re
import unittest

from pypdf import PdfReader

from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from importing import import_replacement, import_sections
from models import new_vault


PRINTED_AT = datetime(2026, 3, 4, 12, tzinfo=timezone.utc)


def block(marker, body):
    divider = marker * 8
    return divider + "\n" + body + "\n" + divider + "\n"


def table(*cells):
    timestamps = [f"03/03/26 {800 + index:04d}" for index in range(len(cells))]
    return "\t" + "\t".join(timestamps) + "\nOther\nCPT Delivery Source\t" + "\t".join(cells)


def synthetic_sheet(devices=("Manual", "In-Exsufflator Cough Machine", "HFCWO"), room="P4102"):
    source = block("a", "Diagnoses:\nSynthetic airway clearance example")
    source += block("c", "Invasive Ventilation:\nVent Mode: PRVC-IMV\n"
                    "Resp Rate (Set): 10\nVt (Set, mL): 100\n"
                    "PEEP (cm H2O): 5\nFiO2 set (%): 30 %")
    combined = ";".join(devices)
    source += block("ag", table(combined, combined, combined)
                    + "\n\n" + table(combined, combined, combined))
    result = import_replacement(room, source, new_vault()["settings"])
    if result.errors or result.sheet is None:
        raise AssertionError(result.errors)
    result.sheet["fields"]["Respiratory"] = "Synthetic respiratory note"
    return result.sheet


def normalized(text):
    return " ".join(text.split())


def output_texts(sheet):
    html = handoff_html(sheet, printed_at=PRINTED_AT)
    pdf = handoff_pdf(sheet, printed_at=PRINTED_AT)
    return {
        "text": normalized(handoff_text(sheet, printed_at=PRINTED_AT)),
        "html": normalized(unescape(re.sub(r"<[^>]*>", "", html))),
        "pdf": normalized("\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)),
    }


class AirwayClearanceOutputTests(unittest.TestCase):
    def test_devices_appear_once_after_support_and_before_notes_in_all_outputs(self):
        devices = ("Manual", "In-Exsufflator Cough Machine", "HFCWO")
        for kind, text in output_texts(synthetic_sheet(devices)).items():
            with self.subTest(output=kind):
                self.assertEqual(text.count("Airway Clearance Device:"), 1)
                for device in devices:
                    self.assertEqual(text.count(device), 1)
                self.assertLess(text.index("Mode: PRVC-IMV"), text.index("Airway Clearance Device:"))
                self.assertLess(text.index("Airway Clearance Device:"), text.index("Synthetic respiratory note"))
                self.assertNotIn("CPT Delivery Source", text)
                self.assertNotIn("03/03/26 0800", text)

    def test_custom_device_markup_is_escaped_and_preserved(self):
        device = "Custom <device> & adjunct"
        sheet = synthetic_sheet((device,))
        markup = handoff_html(sheet, printed_at=PRINTED_AT)
        self.assertIn("<b>Airway Clearance Device:</b> Custom &lt;device&gt; &amp; adjunct", markup)
        self.assertNotIn("Custom <device>", markup)
        for kind, text in output_texts(sheet).items():
            with self.subTest(output=kind):
                self.assertEqual(text.count(device), 1)

    def test_empty_and_failed_tables_hide_device_subsection_in_all_outputs(self):
        previous = synthetic_sheet(("OLD_DEVICE_SENTINEL",))
        for body in ("", "Unrecognized synthetic row"):
            result = import_sections(previous, block("ag", body), new_vault()["settings"])
            self.assertIsNotNone(result.sheet)
            for kind, text in output_texts(result.sheet).items():
                with self.subTest(body=body, output=kind):
                    self.assertNotIn("Airway Clearance Device:", text)
                    self.assertNotIn("OLD_DEVICE_SENTINEL", text)
                    self.assertIn("Synthetic respiratory note", text)
            self.assertEqual(previous["airway_clearance_devices"], ["OLD_DEVICE_SENTINEL"])

    def test_review_warning_hides_retained_device_names(self):
        sheet = synthetic_sheet(("HIDDEN_DEVICE_SENTINEL",))
        failed = import_sections(sheet, block("ag", "Unrecognized synthetic row"), new_vault()["settings"])
        retained = deepcopy(failed.sheet)
        retained["airway_clearance_devices"] = ["HIDDEN_DEVICE_SENTINEL"]
        for kind, text in output_texts(retained).items():
            with self.subTest(output=kind):
                self.assertNotIn("Airway Clearance Device:", text)
                self.assertNotIn("HIDDEN_DEVICE_SENTINEL", text)

    def test_pdf_bundle_keeps_each_rooms_devices_on_its_own_page(self):
        first = synthetic_sheet(("Manual", "HFCWO"), "P4102")
        second = synthetic_sheet(("Oscillatory PEP",), "P4104")
        reader = PdfReader(BytesIO(handoffs_pdf([first, second], printed_at=PRINTED_AT)))
        self.assertEqual(len(reader.pages), 2)
        first_text, second_text = [normalized(page.extract_text()) for page in reader.pages]
        self.assertIn("P4102", first_text)
        self.assertIn("P4104", second_text)
        self.assertEqual(first_text.count("Airway Clearance Device:"), 1)
        self.assertEqual(second_text.count("Airway Clearance Device:"), 1)
        self.assertIn("Manual, HFCWO", first_text)
        self.assertNotIn("Oscillatory PEP", first_text)
        self.assertIn("Oscillatory PEP", second_text)
        self.assertNotIn("Manual", second_text)
        self.assertNotIn("HFCWO", second_text)


if __name__ == "__main__":
    unittest.main()
