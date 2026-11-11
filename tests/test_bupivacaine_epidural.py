"""Synthetic 6.58 regressions for the requested bupivacaine placement."""
from copy import deepcopy
from io import BytesIO
import unittest

from cryptography.fernet import Fernet
from pypdf import PdfReader

from categories import (apply_category_rules, catalog, default_categories,
                        medication_blocks, placement, save_category,
                        set_category_rule, target_snapshot,
                        validate_settings)
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf
from fen_gi import effective_section
from medication_groups import group_for
from medications import (DESTINATIONS, destination_for, is_bupivacaine,
                         parse_medications)
from models import fields_with_medications, new_sheet, new_vault, validate_vault
from security import open_vault, seal_vault


def order(name="bupivacaine 0.1% SYNTHETIC_EPIMED", route="Epidural", frequency="Continuous"):
    result = parse_medications(
        name + "\t4 mL/hr\t" + route + "\t" + frequency + "\t\t3.5 mL/hr\t"
    )
    if result.error:
        raise AssertionError(result.error)
    return result.rows[0]


class BupivacainePlacementTests(unittest.TestCase):
    def test_complete_ingredient_match_in_standalone_and_combined_orders(self):
        for name in (
            "bupivacaine 0.1%", "BUPIVACAINE PF injection",
            "fentaNYL 2 mcg/mL-bupivacaine 0.1% infusion",
            "bupivacaine-fentanyl epidural solution",
            "[Held by provider] Bupivacaine (PF)",
            "[START ON 11/11/2026] bupivacaine 0.1%",
        ):
            with self.subTest(name=name):
                row = order(name)
                self.assertTrue(is_bupivacaine(name))
                self.assertEqual(row["section"], "Neurologic")
                self.assertEqual(group_for(row), "epidural")
                self.assertEqual(placement(row)["name"], "Epidural")

    def test_other_named_anesthetics_are_not_reclassified(self):
        for name in ("levobupivacaine", "ropivacaine", "fentanyl", "bupivacaineX"):
            with self.subTest(name=name):
                self.assertFalse(is_bupivacaine(name))
                self.assertNotEqual(group_for(order(name)), "epidural")

    def test_new_order_overrides_old_name_mapping_but_preserves_route(self):
        name = "bupivacaine 0.25% SYNTHETIC_EPIMED"
        rules = [{"name": "bupivacaine", "match": "prefix", "destination": "Cardiovascular"}]
        self.assertEqual(destination_for(name, rules), "Neurologic")
        row = order(name, route="Infiltration", frequency="Once")
        before = deepcopy(row)
        text = fields_with_medications(dict(new_sheet("P4102"), medications=[row]))["Neurologic"]
        self.assertIn("Epidural", text)
        self.assertIn("Infiltration", text)
        self.assertIn("Once", text)
        self.assertEqual(row, before)

    def test_saved_contrary_assignments_render_once_without_mutating_order(self):
        row = order("fentanyl-bupivacaine SYNTHETIC_EPIMED")
        row.update(section="Hematology", group_mode="dvt", gi_mode="bowel",
                   category_path=target_snapshot("gi:prophylaxis", default_categories()))
        sheet = new_sheet("P4102")
        sheet["medications"] = [row]
        before = deepcopy(sheet)
        self.assertEqual(effective_section(row), "Neurologic")
        self.assertEqual(placement(row)["id"], "group:epidural")
        visible = []
        for section in DESTINATIONS:
            visible.extend(item for _, item in medication_blocks(section, "", [row])
                           if isinstance(item, dict))
        self.assertEqual([item["id"] for item in visible], [row["id"]])
        fields = fields_with_medications(sheet)
        self.assertEqual(sum(value.count("SYNTHETIC_EPIMED") for value in fields.values()), 1)
        self.assertIn("4 mL/hr", fields["Neurologic"])
        self.assertIn("3.5 mL/hr", fields["Neurologic"])
        self.assertEqual(sheet, before)

    def test_existing_saved_catalog_and_custom_category_remain_valid(self):
        vault = new_vault()
        old_catalog = [c for c in default_categories() if c["id"] != "group:epidural"]
        old_catalog.append(dict(id="custom:existing_epidural", name="Epidural",
                                section="Neurologic", parent="", order=100))
        vault["settings"]["medication_categories"] = old_catalog
        vault["settings"]["medication_category_rules"] = [
            dict(name="bupivacaine", match="prefix", route="", frequency="", target="gi:bowel")
        ]
        sheet = new_sheet("P4102")
        sheet["medications"] = [order()]
        vault["rooms"][sheet["room"]] = sheet
        before = deepcopy(vault)
        validate_vault(vault)
        validate_settings(vault["settings"])
        expanded = catalog(vault["settings"])
        self.assertTrue(any(c["id"] == "group:epidural" for c in expanded))
        self.assertEqual([c for c in expanded if c["id"] == "custom:existing_epidural"],
                         [old_catalog[-1]])
        applied = apply_category_rules(sheet["medications"], vault["settings"])
        self.assertEqual(placement(applied[0])["name"], "Epidural")
        for field in ("name", "dose", "route", "frequency", "last_rate", "include", "hidden"):
            self.assertEqual(applied[0][field], sheet["medications"][0][field])
        key = Fernet.generate_key().decode()
        self.assertEqual(open_vault(seal_vault(vault, key), key), vault)
        self.assertEqual(vault, before)

    def test_hidden_and_excluded_orders_stay_hidden(self):
        for hidden, include in ((True, True), (False, False)):
            with self.subTest(hidden=hidden, include=include):
                row = order()
                row.update(hidden=hidden, include=include)
                row = apply_category_rules([row], new_vault()["settings"])[0]
                sheet = dict(new_sheet("P4102"), medications=[row])
                for text in (handoff_html(sheet), handoff_text(sheet)):
                    self.assertNotIn("SYNTHETIC_EPIMED", text)

    def test_full_legacy_catalog_keeps_every_existing_slot(self):
        vault = new_vault()
        old_catalog = [c for c in default_categories()
                       if c["id"] not in ("group:epidural", "group:chemotherapy")]
        for i in range(250 - len(old_catalog)):
            old_catalog.append(dict(id="custom:preserved_" + str(i), name="Preserved " + str(i),
                                    section="Neurologic", parent="", order=100))
        vault["settings"]["medication_categories"] = old_catalog
        before = deepcopy(vault)
        validate_vault(vault)
        self.assertEqual(len(catalog(vault["settings"])), 252)
        key = Fernet.generate_key().decode()
        self.assertEqual(open_vault(seal_vault(vault, key), key), before)
        edited = save_category(vault["settings"], "Renamed preserved", "Neurologic",
                               ident="custom:preserved_0")
        validate_settings(edited)
        self.assertEqual(len(edited["medication_categories"]), 252)
        with self.assertRaises(ValueError):
            save_category(edited, "Over the preserved limit", "Neurologic")
        self.assertEqual(vault, before)

    def test_renamed_epidural_category_and_children_do_not_absorb_bupivacaine(self):
        for child in (False, True):
            with self.subTest(child=child):
                settings = save_category(new_vault()["settings"], "Regional infusions",
                                         "Neurologic", ident="group:epidural")
                target = "group:epidural"
                if child:
                    target = "custom:regional_adjunct"
                    settings = save_category(settings, "Regional adjunct", "Neurologic",
                                             parent="group:epidural", ident=target)
                settings = set_category_rule(settings, "alfentanil", target)
                rows = [order("alfentanil SYNTHETIC_ALFMED"), order()]
                applied = apply_category_rules(rows, settings)
                before = deepcopy(applied)
                groups = {}
                current = ""
                for kind, value in medication_blocks("Neurologic", "", applied):
                    if kind == "heading":
                        current = value
                        groups[current] = []
                    elif isinstance(value, dict):
                        groups[current].append(value["name"])
                self.assertEqual(groups["Epidural"], [rows[1]["name"]])
                self.assertEqual(groups["Regional infusions"], [rows[0]["name"]])
                sheet = dict(new_sheet("P4102"), medications=applied)
                html = handoff_html(sheet)
                self.assertIn("<b>Epidural</b>", html)
                self.assertIn("<b>Regional infusions</b>", html)
                pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(handoff_pdf(sheet))).pages)
                for text in (html, pdf_text):
                    self.assertEqual(text.count("SYNTHETIC_EPIMED"), 1)
                    self.assertEqual(text.count("SYNTHETIC_ALFMED"), 1)
                    self.assertIn("Regional infusions", text)
                self.assertEqual(applied, before)

    def test_matching_epidural_assignments_share_one_heading(self):
        settings = set_category_rule(new_vault()["settings"], "alfentanil", "group:epidural")
        applied = apply_category_rules([order("alfentanil SYNTHETIC_ALFMED"), order()], settings)
        blocks = medication_blocks("Neurologic", "", applied)
        self.assertEqual([value for kind, value in blocks if kind == "heading"], ["Epidural"])
        self.assertEqual(sum(isinstance(value, dict) for _, value in blocks), 2)

    def test_single_and_batch_print_include_order_once_in_epidural_group(self):
        sheet = dict(new_sheet("P4102"), medications=[order()])
        before = deepcopy(sheet)
        outputs = [handoff_html(sheet), handoff_text(sheet)]
        for data in (handoff_pdf(sheet), handoffs_pdf([sheet])):
            outputs.append("\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages))
        for text in outputs:
            self.assertIn("Epidural", text)
            self.assertEqual(text.count("SYNTHETIC_EPIMED"), 1)
            self.assertIn("4 mL/hr", text)
            self.assertIn("3.5 mL/hr", text)
        self.assertEqual(sheet, before)


if __name__ == "__main__":
    unittest.main()
