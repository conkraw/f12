"""Synthetic AG import, replacement and encrypted archive regressions."""
from copy import deepcopy
import json
import unittest

from airway_clearance_devices import airway_clearance_devices_text
from error_store import new_error_event, validate_event
from exports import handoff_text
from import_review import diagnostic_text, review_summary
from importing import import_replacement, import_sections
from models import (ValidationError, fields_with_medications, new_sheet,
                    new_vault, save_sheet_in, validate_sheet, validate_vault)
from security import generate_key, open_vault, seal_vault


def block(key, text):
    marker = key * 8
    return marker + "\n" + text + "\n" + marker + "\n"


def table(*cells):
    times = [f"03/03/26 {800 + index:04d}" for index in range(len(cells))]
    return "\t" + "\t".join(times) + "\nOther\nCPT Delivery Source\t" + "\t".join(cells)


DIAGNOSIS = block("a", "Diagnoses:\n1. Synthetic clearance example")
SPLIT_TABLE = (table("In-Exsufflator Cough Machine", "HFCWO", "HFCWO;In-Exsufflator Cough Machine")
               + "\n\n" + table("Manual", "In-Exsufflator Cough Machine;HFCWO", "Manual"))


class AirwayClearanceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.settings = new_vault()["settings"]

    def imported(self, source, sheet=None):
        result = import_sections(sheet or new_sheet("P4102"), source, self.settings)
        self.assertFalse(result.errors, result.errors)
        self.assertIsNotNone(result.sheet)
        validate_sheet(result.sheet)
        return result.sheet

    def previous(self):
        sheet = new_sheet("P4102")
        sheet["airway_clearance_devices"] = ["OLD_DEVICE_SENTINEL"]
        sheet["fields"]["Respiratory"] = "Respiratory note"
        return sheet

    def test_all_split_table_devices_import_once_into_respiratory(self):
        source = DIAGNOSIS + block("ag", SPLIT_TABLE)
        sheet = self.imported(source)
        expected = ["In-Exsufflator Cough Machine", "HFCWO", "Manual"]
        self.assertEqual(sheet["airway_clearance_devices"], expected)
        respiratory = fields_with_medications(sheet)["Respiratory"]
        self.assertEqual(respiratory, "Airway Clearance Device: " + ", ".join(expected))
        output = handoff_text(sheet)
        for device in expected:
            self.assertEqual(output.count(device), 1)
        for unwanted in ("CPT Delivery Source", "03/03/26", "Other\n", "agagagag"):
            self.assertNotIn(unwanted, respiratory)

    def test_devices_follow_ventilatory_support_and_precede_notes(self):
        sheet = new_sheet("P4102")
        sheet["ventilation"] = {"mode": "PRVC", "values": {"PEEP (cm H2O)": "5 cm H2O"}}
        sheet["fields"]["Respiratory"] = "Respiratory note"
        sheet = self.imported(block("ag", table("Manual")), sheet)
        output = fields_with_medications(sheet)["Respiratory"]
        self.assertLess(output.index("Vent Settings"), output.index("Airway Clearance Device"))
        self.assertLess(output.index("Airway Clearance Device"), output.index("Respiratory note"))

    def test_new_ag_snapshot_replaces_old_devices_and_keeps_notes(self):
        previous = self.previous()
        sheet = self.imported(block("ag", table("Manual", "Manual")), previous)
        self.assertEqual(sheet["airway_clearance_devices"], ["Manual"])
        self.assertEqual(sheet["fields"]["Respiratory"], "Respiratory note")
        self.assertEqual(previous["airway_clearance_devices"], ["OLD_DEVICE_SENTINEL"])

    def test_empty_and_blank_cells_clear_old_devices_without_claiming_none(self):
        for body in ("", table("", "--", "")):
            with self.subTest(body=body):
                sheet = self.imported(block("ag", body), self.previous())
                self.assertEqual(sheet["airway_clearance_devices"], [])
                self.assertEqual(airway_clearance_devices_text(sheet), "")
                self.assertNotIn("Airway Clearance Device", fields_with_medications(sheet)["Respiratory"])

    def test_missing_or_malformed_ag_clears_stale_devices_and_logs_safe_diagnostic(self):
        sources = (
            "agagagag\n" + table("Manual"),
            block("ag", "UNRECOGNIZED_SYNTHETIC_SOURCE"),
        )
        for source in sources:
            with self.subTest(source=source):
                result = import_sections(self.previous(), source, self.settings)
                self.assertTrue(result.errors)
                self.assertIsNotNone(result.sheet)
                self.assertEqual(result.sheet["airway_clearance_devices"], [])
                self.assertIn("ag", result.sheet["import_warnings"])
                self.assertEqual(airway_clearance_devices_text(result.sheet), "")
                event = new_error_event(result.diagnostics)
                validate_event(event)
                event_text = json.dumps(event)
                self.assertNotIn("OLD_DEVICE_SENTINEL", event_text)
                self.assertNotIn("UNRECOGNIZED_SYNTHETIC_SOURCE", event_text)
                self.assertIn("AG block", diagnostic_text(result.diagnostics[0]))
                self.assertIn("prior airway clearance devices cleared", review_summary(result.sheet))

    def test_successful_ag_after_failed_ag_removes_warning(self):
        failed = import_sections(self.previous(), block("ag", "invalid table"), self.settings).sheet
        repaired = self.imported(block("ag", table("HFCWO")), failed)
        self.assertNotIn("ag", repaired["import_warnings"])
        self.assertEqual(airway_clearance_devices_text(repaired), "Airway Clearance Device: HFCWO")

    def test_partial_unrelated_import_preserves_existing_devices(self):
        previous = self.previous()
        sheet = self.imported(DIAGNOSIS, previous)
        self.assertEqual(sheet["airway_clearance_devices"], previous["airway_clearance_devices"])

    def test_full_room_replacement_without_ag_removes_old_devices_only_in_that_room(self):
        vault = save_sheet_in(new_vault(), self.previous())
        other = new_sheet("P4104")
        other["airway_clearance_devices"] = ["OTHER_ROOM_DEVICE"]
        vault = save_sheet_in(vault, other)
        before = deepcopy(vault)
        replacement = import_replacement("P4102", DIAGNOSIS, self.settings)
        self.assertFalse(replacement.errors)
        updated = save_sheet_in(vault, replacement.sheet)
        self.assertEqual(updated["rooms"]["P4102"].get("airway_clearance_devices", []), [])
        self.assertNotEqual(updated["rooms"]["P4102"]["id"], before["rooms"]["P4102"]["id"])
        self.assertEqual(updated["rooms"]["P4104"], before["rooms"]["P4104"])
        self.assertEqual(updated["settings"], before["settings"])
        self.assertEqual(vault, before)

    def test_full_replacement_with_invalid_ag_never_carries_old_devices(self):
        result = import_replacement("P4102", DIAGNOSIS + block("ag", "invalid table"), self.settings)
        self.assertIsNotNone(result.sheet)
        self.assertTrue(result.errors)
        self.assertEqual(result.sheet["airway_clearance_devices"], [])
        self.assertEqual(result.diagnostics[0]["action"], "not_imported")
        self.assertIn("No previous patient information", diagnostic_text(result.diagnostics[0]))
        validate_event(new_error_event(result.diagnostics))

    def test_encrypted_roundtrip_accepts_new_and_existing_sheets(self):
        old_sheet = new_sheet("P4104")
        new_sheet_value = self.imported(block("ag", SPLIT_TABLE))
        vault = save_sheet_in(save_sheet_in(new_vault(), old_sheet), new_sheet_value)
        validate_vault(vault)
        key = generate_key()
        encrypted = seal_vault(vault, key)
        restored = open_vault(encrypted, key)
        self.assertEqual(restored, vault)
        self.assertNotIn(b"In-Exsufflator", encrypted)
        self.assertNotIn("airway_clearance_devices", restored["rooms"]["P4104"])
        self.assertEqual(restored["rooms"]["P4102"]["airway_clearance_devices"],
                         ["In-Exsufflator Cough Machine", "HFCWO", "Manual"])

    def test_invalid_persisted_device_shape_rejected(self):
        for value in (None, "Manual", [""], ["Manual\nInjected heading"], [1]):
            with self.subTest(value=value):
                sheet = new_sheet("P4102")
                sheet["airway_clearance_devices"] = value
                with self.assertRaises(ValidationError):
                    validate_sheet(sheet)


if __name__ == "__main__":
    unittest.main()
