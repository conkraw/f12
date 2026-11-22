"""Synthetic AG table parsing and SmartPhrase boundary regressions."""
import unittest

from airway_clearance_devices import (
    airway_clearance_devices_text,
    parse_airway_clearance_devices,
    validate_airway_clearance_devices,
)
from parser import parse_smartphrase


def _block(key, content, suffix=""):
    marker = key * 12 + suffix
    return marker + "\n" + content + "\n" + marker + "\n"


def _diagnosis():
    return _block("a", "Diagnoses:\nSynthetic airway clearance example")


class AirwayClearanceDevicesParserTests(unittest.TestCase):
    def test_split_six_session_table_deduplicates_each_device_in_source_order(self):
        source = (
            "\t03/03/26 0100\t03/03/26 0300\t03/03/26 0500\nOther\n"
            "CPT Delivery Source\tIn-Exsufflator Cough Machine\tHFCWO\tIn-Exsufflator Cough Machine\n\n"
            "\t03/03/26 0900\t03/03/26 1300\t03/03/26 1700\nOther\n"
            "CPT Delivery Source\tIn-Exsufflator Cough Machine;HFCWO\tHFCWO;In-Exsufflator Cough Machine\tManual"
        )
        result = parse_airway_clearance_devices(source)
        self.assertFalse(result.error)
        self.assertEqual(result.devices, ["In-Exsufflator Cough Machine", "HFCWO", "Manual"])

    def test_devices_are_not_restricted_to_a_time_window_or_allowlist(self):
        source = (
            "\t02/01/26 0900\t03/03/26 0900\nOther\n"
            "CPT Delivery Source\tCustom oscillation device\tPEP/OPEP"
        )
        result = parse_airway_clearance_devices(source)
        self.assertFalse(result.error)
        self.assertEqual(result.devices, ["Custom oscillation device", "PEP/OPEP"])

    def test_windows_newlines_multidevice_whitespace_and_case_duplicates(self):
        result = parse_airway_clearance_devices(
            "Airway Clearance Devices:\r\n\t03/03/2026 9:00 AM\r\nOther\r\n"
            "CPT Delivery Source\t  Manual ; HFCWO ; manual ; hfcwo ; Custom\u00a0 device  \r\n"
        )
        self.assertFalse(result.error)
        self.assertEqual(result.devices, ["Manual", "HFCWO", "Custom device"])

    def test_empty_and_placeholder_only_sources_have_no_devices(self):
        for source in [
            "", "  \r\n", "No data recorded", "Airway Clearance Device:",
            "CPT Delivery Source", "CPT Delivery Source\t\t\t",
            "CPT Delivery Source\t-;--;\u2014;Unknown;UNK;N/A;None;Not documented\t03/03/26 0900",
        ]:
            with self.subTest(source=source):
                result = parse_airway_clearance_devices(source)
                self.assertEqual(result.devices, [])
                self.assertFalse(result.error)

    def test_unrecognized_nonempty_blocks_fail_without_partial_or_source_echo(self):
        for source in [
            "Unrecognized private source", "\t03/03/26 0900\nOther",
            "CPT Delivery Source\tManual\nUnrecognized private source",
            "CPT Delivery Source Manual",
        ]:
            with self.subTest(source=source):
                result = parse_airway_clearance_devices(source)
                self.assertEqual(result.devices, [])
                self.assertTrue(result.error)
                self.assertNotIn("private source", result.error)

    def test_nontext_source_is_rejected(self):
        result = parse_airway_clearance_devices(None)
        self.assertTrue(result.error)
        self.assertEqual(result.devices, [])

    def test_invalid_stored_values_are_rejected(self):
        for value in [
            None, "Manual", {}, [None], [""], ["  "], ["x\ny"], ["x\t y"],
            ["x\x00y"], ["x" * 201], ["Manual"] * 65,
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_airway_clearance_devices(value)

    def test_valid_values_and_output_suppression_for_old_sheets_and_failed_imports(self):
        validate_airway_clearance_devices([])
        validate_airway_clearance_devices(["Manual", "Custom device"])
        self.assertEqual(airway_clearance_devices_text({}), "")
        self.assertEqual(airway_clearance_devices_text({"airway_clearance_devices": []}), "")
        sheet = {"airway_clearance_devices": ["Manual", "In-Exsufflator Cough Machine"]}
        self.assertEqual(airway_clearance_devices_text(sheet), "Airway Clearance Device: Manual, In-Exsufflator Cough Machine")
        sheet["import_warnings"] = {"ag": []}
        self.assertEqual(airway_clearance_devices_text(sheet), "")

    def test_generic_parser_accepts_ag_table_without_heading(self):
        for suffix, upper in [("", False), ("a", False), ("", True)]:
            with self.subTest(suffix=suffix, upper=upper):
                ag = _block("ag", "\t03/03/26 0900\nOther\nCPT Delivery Source\tManual", suffix)
                if upper:
                    ag = ag.upper()
                result = parse_smartphrase(_diagnosis() + ag)
                self.assertFalse(result.diagnosis_error)
                self.assertFalse(result.invalid)
                self.assertIn("ag", result.blocks)
                self.assertFalse(result.issues)

    def test_missing_and_duplicate_ag_boundaries_are_rejected(self):
        result = parse_smartphrase(_diagnosis() + "ag" * 12 + "\nCPT Delivery Source\tManual\n")
        self.assertIn("ag", result.invalid)
        self.assertFalse(result.diagnosis_error)
        result = parse_smartphrase(_diagnosis() + _block("ag", "CPT Delivery Source\tManual") * 2)
        self.assertIn("ag", result.invalid)
        self.assertFalse(result.diagnosis_error)

    def test_malformed_ag_boundary_invalidates_ag_and_active_neighbor(self):
        result = parse_smartphrase(
            _diagnosis() + "af" * 12 + "\nPRN administrations:\n"
            + "agagagagagagagah\nCPT Delivery Source\tManual\n" + "ag" * 12
        )
        self.assertTrue({"ag", "af"}.issubset(result.invalid))
        self.assertFalse(result.diagnosis_error)
        self.assertTrue(any("Malformed divider" in issue for issue in result.issues))

    def test_neighboring_section_headings_cannot_be_imported_as_ag(self):
        for body in [
            "Medications:\nCPT Delivery Source\tManual",
            "CPT Delivery Source\tManual\nMedications:\nPRIVATE_SENTINEL",
        ]:
            with self.subTest(body=body):
                result = parse_smartphrase(_diagnosis() + _block("ag", body))
                self.assertIn("ag", result.invalid)
                self.assertFalse(result.diagnosis_error)
                self.assertNotIn("PRIVATE_SENTINEL", str(result.issues))

    def test_oversized_device_does_not_return_partial_names(self):
        result = parse_airway_clearance_devices("CPT Delivery Source\tManual\t" + "x" * 201)
        self.assertTrue(result.error)
        self.assertEqual(result.devices, [])


if __name__ == "__main__":
    unittest.main()
