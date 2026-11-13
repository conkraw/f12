"""Synthetic chemotherapy grouping and schema-34 compatibility regressions."""
from copy import deepcopy
from io import BytesIO

import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader

from categories import (apply_category_rules, catalog, default_categories,
                        medication_blocks, placement, save_category,
                        set_category_rule, target_snapshot, validate_settings)
from chemotherapy import is_chemotherapy
from exports import handoff_html, handoff_pdf, handoff_text
from fen_gi import effective_section
from medication_groups import (automatic_group, group_for, set_group_rule,
                               apply_group_rules)
from medications import DESTINATIONS, parse_medications, validate_medication
from models import (SCHEMA_VERSION, fields_with_medications, new_sheet,
                    new_vault, validate_vault)
from security import open_vault, seal_vault


def order(name, route="Intravenous", frequency="Once"):
    result = parse_medications(
        name + "\tSYNTHETIC_DOSE\t" + route + "\t" + frequency + "\t\t\t"
    )
    assert not result.error
    assert len(result.rows) == 1
    return result.rows[0]


@pytest.mark.parametrize("name", [
    "asparaginase", "pegaspargase", "calaspargase pegol-mknl",
    "doxorubicin hydrochloride", "daunorubicin hydrochloride",
    "idarubicin hydrochloride", "mitoxantrone hydrochloride",
    "cyclophosphamide", "ifosfamide", "busulfan", "melphalan hydrochloride",
    "thiotepa", "temozolomide", "procarbazine hydrochloride", "dacarbazine",
    "carmustine", "lomustine", "methotrexate sodium", "cytarabine",
    "mercaptopurine", "thioguanine", "fludarabine phosphate", "clofarabine",
    "nelarabine", "cisplatin", "carboplatin", "oxaliplatin", "vincristine sulfate",
    "vinblastine sulfate", "vinorelbine tartrate", "etoposide phosphate",
    "irinotecan hydrochloride", "topotecan hydrochloride", "dactinomycin",
    "bleomycin sulfate", "gemcitabine hydrochloride", "paclitaxel", "docetaxel",
    "azacitidine", "decitabine",
])
def test_core_chemotherapy_orders_have_one_hematology_destination(name):
    row = order(name.upper() + " (SYNTHETIC_CHEMO)")
    before = deepcopy(row)
    assert automatic_group(row) == "chemotherapy"
    assert effective_section(row) == "Hematology"
    assert placement(row)["id"] == "group:chemotherapy"
    blocks = medication_blocks("Hematology", "", [row])
    assert blocks[0] == ("heading", "Chemotherapy")
    emitted = [value["id"] for section in DESTINATIONS
               for _, value in medication_blocks(section, "", [row])
               if isinstance(value, dict)]
    assert emitted == [row["id"]]
    assert row == before


@pytest.mark.parametrize("name", [
    "L-asparaginase", "asparaginase-E.coli", "asparaginase-erwinia chrysanthemi",
    "asparaginase erwinia chrysanthemi (recombinant)-rywn", "Erwinia asparaginase",
    "PEG-asparaginase", "PEG-L-asparaginase", "calaspargase pegol", "Rylaze",
    "Erwinaze", "Erwinase", "Elspar", "Oncaspar", "Asparlas",
    "Adriamycin", "liposomal doxorubicin", "doxorubicin.HCl", "Doxil", "Lipodox 50",
    "Vyxeos", "daunorubicin-cytarabine liposome", "Idamycin PFS", "Cytoxan", "Neosar",
    "Ifex", "Busulfex", "Myleran", "Alkeran", "Evomela", "Tepadina", "Temodar",
    "Matulane", "BiCNU", "Trexall", "Xatmep", "Cytosar-U", "Ara-C",
    "6-mercaptopurine", "Purinethol", "Purixan", "6-thioguanine", "Tabloid",
    "Clolar", "Arranon", "Paraplatin", "Eloxatin", "Oncovin", "Vincasar PFS",
    "Etopophos", "Vepesid", "Toposar", "Camptosar", "Hycamtin", "actinomycin D",
    "Cosmegen", "Gemzar", "Infugem", "Abraxane", "Taxotere", "Vidaza", "Onureg", "Dacogen",
])
def test_verified_brand_and_variant_orders_use_same_group(name):
    assert group_for(order(name)) == "chemotherapy"


@pytest.mark.parametrize("prefix", [
    "Or: ", "And: ", "Followed by: ", "[START ON 11/12/2026] ",
    "[Held by provider] ", "Or: [START ON 11/12/2026] [Held by provider] ",
])
def test_known_source_context_does_not_block_grouping(prefix):
    row = order(prefix + "doxorubicin (SYNTHETIC_CHEMO)")
    before = deepcopy(row)
    assert group_for(row) == "chemotherapy"
    assert placement(row)["name"] == "Chemotherapy"
    assert row == before


@pytest.mark.parametrize("name", [
    "dexamethasone", "Decadron", "dexamethasone chemotherapy premedication",
    "prednisone", "prednisolone", "methylprednisolone", "hydrocortisone",
    "budesonide", "fluticasone", "leucovorin", "levoleucovorin", "mesna",
    "dexrazoxane", "glucarpidase", "allopurinol", "rasburicase", "ondansetron",
    "filgrastim", "pegfilgrastim", "hydroxyurea", "Siklos", "Hydrea",
    "rituximab", "blinatumomab", "imatinib", "sirolimus", "azathioprine",
    "doxorubicinX", "vincristinex", "asparaginase-like product",
    "calaspargase pegol-mknlx", "doxorubicin-antibody", "PEG",
    "saline (for doxorubicin)", "mesna with ifosfamide", "CHOP protocol",
])
def test_steroids_supportive_agents_and_nonmatches_are_not_chemotherapy(name):
    assert not is_chemotherapy(name)
    assert group_for(order(name)) != "chemotherapy"


def test_dexamethasone_and_filgrastim_keep_their_existing_defaults():
    assert group_for(order("dexamethasone")) == "airway_cerebral_steroid"
    assert effective_section(order("dexamethasone")) == "Respiratory"
    assert group_for(order("filgrastim")) == "gcsf"


@pytest.mark.parametrize("route,frequency,dose", [
    ("Oral", "Weekly", "SYNTHETIC_LOW_DOSE"),
    ("Intrathecal", "Once", "SYNTHETIC_OTHER_DOSE"),
])
def test_default_never_depends_on_dose_route_or_indication(route, frequency, dose):
    row = order("methotrexate", route, frequency)
    row["dose"] = dose
    before = deepcopy(row)
    assert group_for(row) == "chemotherapy"
    assert row == before


def test_explicit_group_other_group_and_gi_choices_remain_authoritative():
    row = order("methotrexate")
    row["section"] = "Other Medications"
    row["group_mode"] = "other"
    assert group_for(row) == ""
    assert effective_section(row) == "Other Medications"
    row["group_mode"] = "antibiotic"
    assert effective_section(row) == "Infectious Disease"
    row.update(group_mode="auto", gi_mode="endocrine")
    assert group_for(row) == ""
    assert effective_section(row) == "FEN / GI"


def test_new_group_is_a_valid_persisted_manual_choice():
    row = order("SYNTHETIC_UNLISTED_DRUG")
    rules = set_group_rule([], row, "chemotherapy")
    selected = apply_group_rules([row], rules)[0]
    validate_medication(selected)
    assert group_for(selected) == "chemotherapy"
    vault = new_vault()
    vault["settings"]["medication_groups"] = rules
    validate_vault(vault)


def test_saved_category_snapshot_and_mapping_override_auto_placement():
    row = order("cyclophosphamide (SYNTHETIC_CHEMO)")
    snapshot = target_snapshot("system:Other Medications", default_categories())
    saved = dict(row, category_path=snapshot)
    assert placement(saved) == snapshot
    assert effective_section(saved) == "Other Medications"
    settings = save_category(new_vault()["settings"], "Immune treatment", "Other Medications",
                             ident="custom:immune")
    settings = set_category_rule(settings, "cyclophosphamide", "custom:immune")
    mapped = apply_category_rules([row], settings)[0]
    assert placement(mapped)["id"] == "custom:immune"
    assert effective_section(mapped) == "Other Medications"
    assert not medication_blocks("Hematology", "", [mapped])
    assert all(mapped[key] == row[key] for key in row)


def test_renamed_and_moved_builtin_remains_user_controlled():
    settings = save_category(new_vault()["settings"], "Protocol medications", "Other Medications",
                             ident="group:chemotherapy")
    row = apply_category_rules([order("doxorubicin")], settings)[0]
    assert placement(row)["name"] == "Protocol medications"
    assert effective_section(row) == "Other Medications"
    assert not medication_blocks("Hematology", "", [row])


@pytest.mark.parametrize("field,value", [("hidden", True), ("include", False)])
def test_automatic_grouping_never_restores_hidden_or_excluded_orders(field, value):
    row = order("doxorubicin (SYNTHETIC_CHEMO)")
    row[field] = value
    before = deepcopy(row)
    mapped = apply_category_rules([row], new_vault()["settings"])[0]
    sheet = dict(new_sheet("P4102"), medications=[mapped])
    assert "SYNTHETIC_CHEMO" not in handoff_text(sheet)
    assert "SYNTHETIC_CHEMO" not in handoff_html(sheet)
    assert mapped == before


def test_existing_saved_order_is_grouped_once_in_all_exports_without_mutation():
    row = order("doxorubicin (SYNTHETIC_CHEMO)")
    sheet = dict(new_sheet("P4102"), medications=[row])
    before = deepcopy(sheet)
    fields = fields_with_medications(sheet)
    assert "Chemotherapy" in fields["Hematology"]
    assert sum(value.count("SYNTHETIC_CHEMO") for value in fields.values()) == 1
    pdf = PdfReader(BytesIO(handoff_pdf(sheet)))
    outputs = (handoff_text(sheet), handoff_html(sheet),
               "\n".join(page.extract_text() for page in pdf.pages))
    for output in outputs:
        assert "Chemotherapy" in output
        # PDF line wrapping may split the synthetic marker inside its word.
        compact = "".join(output.split())
        assert compact.count("SYNTHETIC_CHEMO") == 1
        assert "SYNTHETIC_DOSE" in compact
    assert sheet == before


def legacy_settings(*, before_epidural=False, full=False):
    settings = new_vault()["settings"]
    omitted = {"group:chemotherapy", "group:leukotriene_receptor_antagonist"}
    if before_epidural:
        omitted.add("group:epidural")
    items = [item for item in default_categories() if item["id"] not in omitted]
    if full:
        limit = 250 if before_epidural else 251
        for index in range(limit - len(items)):
            items.append(dict(id="custom:kept_" + str(index), name="Kept " + str(index),
                              section="Other Medications", parent="", order=100))
    settings["medication_categories"] = items
    return settings


def test_schema34_saved_catalog_and_name_collisions_expand_without_mutation():
    vault = new_vault()
    vault["settings"] = legacy_settings()
    for index, name in enumerate(("Chemotherapy", "Chemotherapy (default)")):
        vault["settings"]["medication_categories"].append(
            dict(id="custom:collision_" + str(index), name=name, section="Hematology",
                 parent="", order=100))
    sheet = dict(new_sheet("P4102"), medications=[order("doxorubicin")])
    vault["rooms"]["P4102"] = sheet
    before = deepcopy(vault)
    validate_vault(vault)
    expanded = catalog(vault["settings"])
    chemo = next(item for item in expanded if item["id"] == "group:chemotherapy")
    assert chemo["name"] == "Chemotherapy (default 2)"
    assert expanded[:len(before["settings"]["medication_categories"])] == before["settings"]["medication_categories"]
    mapped = apply_category_rules(sheet["medications"], vault["settings"])[0]
    assert placement(mapped)["id"] == "group:chemotherapy"
    assert placement(mapped)["name"] == "Chemotherapy (default 2)"
    key = Fernet.generate_key().decode()
    assert open_vault(seal_vault(vault, key), key) == before
    assert vault == before
    assert vault["schema"] == SCHEMA_VERSION == 34


@pytest.mark.parametrize("before_epidural", [False, True])
def test_full_historical_catalog_preserves_every_slot_and_still_enforces_limit(before_epidural):
    settings = legacy_settings(before_epidural=before_epidural, full=True)
    before = deepcopy(settings)
    expanded = catalog(settings)
    assert len(expanded) == 253
    validate_settings(settings)
    assert expanded[:len(before["medication_categories"])] == before["medication_categories"]
    edited = save_category(settings, "Retained renamed", "Other Medications",
                           ident="custom:kept_0")
    assert len(edited["medication_categories"]) == 253
    with pytest.raises(ValueError, match="at most 250"):
        save_category(edited, "No remaining original slot", "Other Medications")
    assert settings == before


def test_catalog_backfill_is_idempotent_and_does_not_replace_existing_builtin():
    settings = legacy_settings()
    expanded = catalog(settings)
    settings["medication_categories"] = expanded
    assert catalog(settings) == expanded
    renamed = save_category(settings, "Selected chemotherapy label", "Other Medications",
                            ident="group:chemotherapy")
    assert catalog(renamed) == renamed["medication_categories"]


def test_catalog_backfill_does_not_allow_missing_older_builtins_or_duplicate_ids():
    settings = legacy_settings()
    settings["medication_categories"] = [item for item in settings["medication_categories"]
                                         if item["id"] != "group:dvt"]
    with pytest.raises(ValueError, match="Built-in categories"):
        validate_settings(settings)
    settings = legacy_settings()
    duplicate = deepcopy(next(item for item in settings["medication_categories"]
                              if item["id"] == "group:epidural"))
    duplicate["name"] = "Duplicate reserved ID"
    settings["medication_categories"].append(duplicate)
    with pytest.raises(ValueError, match="already exists"):
        validate_settings(settings)
