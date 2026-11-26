"""Synthetic mapping evidence without changes to medication output text."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from categories import default_categories, target_snapshot
from medications import parse_medications
from models import new_sheet
from note_generator import get_phrase_catalog
from note_medication_rules import medication_note_candidates
from note_medications import build_note_medications


CATALOG = get_phrase_catalog()
SUPPORT = {"kind": "invasive", "tracheostomy": False, "endotracheal_tube": True}
NOW = datetime(2026, 11, 25, 20, tzinfo=timezone.utc)


def entry(name="Synthetic medication", **changes):
    row = {"id": "synthetic", "name": name, "source_name": name,
           "section": "Neurologic", "group": "Scheduled", "active": True,
           "route": "Intravenous", "frequency": "q12h", "dose": "1 mg"}
    row.update(changes)
    return row


def custom_path(name, *, parent_id="", parent_name="", section="FEN / GI"):
    return {"id": "custom:synthetic", "name": name, "section": section,
            "parent_id": parent_id, "parent_name": parent_name,
            "order": 100, "parent_order": 100}


def candidates(*rows, support=None, catalog=CATALOG):
    return medication_note_candidates({"entries": list(rows)}, support=support or SUPPORT, catalog=catalog)


def ids(*rows, **kwargs):
    return {item["id"] for item in candidates(*rows, **kwargs)}


@pytest.mark.parametrize("category,key", [
    ("group:antibiotic", "sepsis"),
    ("gi:bowel", "constipation"),
    ("gi:prophylaxis", "gastric_ulcer_risk"),
    ("group:antiepileptic", "seizure_risk"),
    ("group:eye_care_lubricants", "exposure_keratopathy"),
    ("group:iron_deficiency_anemia", "anemia"),
    ("group:adh_analog", "central_diabetes_insipidus"),
    ("group:gcsf", "neutropenia"),
    ("group:pulmonary_hypertension", "pulmonary_hypertension"),
    ("group:antihypertensive", "hypertension"),
    ("group:adrenocortical", "adrenal_insufficiency"),
    ("group:dvt", "dvt_risk"),
    ("group:epidural", "acute_pain"),
    ("gi:hypoglycemia", "hypoglycemia"),
])
def test_builtin_ids_match_unknown_drugs_and_survive_category_rename(category, key):
    path = target_snapshot(category, default_categories())
    path["name"] = "Renamed organizational heading"
    row = entry(category_path=path)
    assert ids(row) == {key}
    # Built-in routing is independent of the optional catalog-label matcher.
    assert ids(row, catalog=None) == {key}


@pytest.mark.parametrize("catalog_entry", CATALOG, ids=lambda row: row["id"])
def test_custom_leaf_can_match_every_existing_catalog_diagnosis(catalog_entry):
    row = entry(category_path=custom_path(catalog_entry["label"]))
    # Unknown support permits the one explicitly named route without adding
    # its opposite. Ordinary sedative grouping still needs support evidence.
    assert ids(row, support={"kind": "unknown"}) == {catalog_entry["id"]}


@pytest.mark.parametrize("label", ["hypokalemia", "HYPOKALEMIA", "hypokalemia management", "ACKZHYPOKALEMIA", "@ACKZHYPOKALEMIA@"])
def test_custom_leaf_matches_labels_identifiers_and_exact_phrase_names(label):
    row = entry(category_path=custom_path(label))
    assert ids(row) == {"hypokalemia"}


def test_specific_leaf_indication_wins_over_bowel_parent_and_lactulose_name():
    row = entry("Lactulose", category_path=custom_path(
        "Hepatic encephalopathy", parent_id="gi:bowel", parent_name="Bowel Regimen"))
    assert ids(row) == {"encephalopathy"}


def test_specific_disease_label_wins_over_prophylaxis_parent():
    row = entry("Enoxaparin", category_path=custom_path(
        "Deep vein thrombosis", parent_id="group:dvt", parent_name="DVT Prophylaxis"))
    assert ids(row) == {"deep_vein_thrombosis"}


def test_parent_builtin_id_is_used_when_child_does_not_name_an_indication():
    row = entry(category_path=custom_path(
        "Selected treatment agents", parent_id="group:antibiotic", parent_name="Renamed parent"))
    assert ids(row) == {"sepsis"}


def test_parent_custom_name_can_supply_a_catalog_diagnosis():
    row = entry(category_path=custom_path(
        "Selected agents", parent_id="custom:parent", parent_name="SIADH"))
    assert ids(row) == {"siadh"}


@pytest.mark.parametrize("label,key", [
    ("Potassium replacement", "hypokalemia"),
    ("Sodium replacement", "hyponatremia"),
    ("Phosphorus repletion", "hypophosphatemia"),
    ("Magnesium supplementation", "hypomagnesemia"),
    ("Calcium replacement", "hypocalcemia"),
    ("Opioid wean", "opioid_dependence"),
    ("Benzodiazepine withdrawal", "benzodiazepine_dependence"),
    ("Eye care and lubricants", "exposure_keratopathy"),
    ("PJP prophylaxis", "pneumocystis_risk"),
])
def test_custom_indication_aliases_use_existing_catalog_ids(label, key):
    assert ids(entry(category_path=custom_path(label))) == {key}


@pytest.mark.parametrize("name,key", [
    ("Methadone", "opioid_dependence"),
    ("Lorazepam", "benzodiazepine_dependence"),
])
def test_generic_withdrawal_category_uses_the_named_drug_class(name, key):
    assert ids(entry(name, category_path=custom_path("Withdrawal medications"))) == {key}


def test_unrepresented_alpha2_withdrawal_does_not_become_hypertension_or_an_invented_plan():
    assert ids(entry("Clonidine", category_path=custom_path("Withdrawal medications"))) == set()


@pytest.mark.parametrize("kind,key", [("invasive", "agitation_intubated"), ("noninvasive", "agitation_nonintubated")])
def test_sedation_category_uses_only_current_support_route(kind, key):
    row = entry("Synthetic sedative", category_path=custom_path("Sedation"), group="Drips")
    assert ids(row, support={"kind": kind}) == {key}


def test_tracheostomy_support_uses_single_invasive_agitation_candidate():
    row = entry("Fentanyl", group="Drips", frequency="Continuous")
    result = candidates(row, support={"kind": "invasive", "tracheostomy": True, "endotracheal_tube": False})
    assert {item["id"] for item in result} == {"agitation_intubated"}
    assert "tracheostomy support" in result[0]["reason"]


def test_unclear_support_does_not_add_both_agitation_variants():
    row = entry("Fentanyl", group="Drips", frequency="Continuous", category_path=custom_path("Sedation"))
    assert ids(row, support={"kind": "unclear"}) == set()
    row["category_path"] = custom_path("Restlessness and agitation while intubated")
    assert ids(row, support={"kind": "unclear"}) == set()


def test_unknown_support_keeps_existing_dexmedetomidine_review_fallback():
    row = entry("Dexmedetomidine", group="Drips", frequency="Continuous")
    assert ids(row, support={"kind": "unknown"}) == {"agitation_nonintubated"}


@pytest.mark.parametrize("name,key", [
    ("Ceftriaxone", "sepsis"), ("Polyethylene glycol", "constipation"),
    ("Potassium chloride", "hypokalemia"), ("Sodium phosphate", "hypophosphatemia"),
    ("Magnesium sulfate", "hypomagnesemia"), ("Calcium gluconate", "hypocalcemia"),
    ("Heparin flush", "central_line_occlusion_risk"), ("Methadone", "opioid_dependence"),
    ("Pantoprazole", "gastric_ulcer_risk"),
])
def test_known_name_fallbacks_remain_available(name, key):
    assert key in ids(entry(name))


def test_prokinetic_mapping_prevents_erythromycin_antibiotic_fallback():
    row = entry("Erythromycin", category_path=target_snapshot("gi:prokinetic", default_categories()))
    assert ids(row) == set()


def test_a_mapped_bowel_indication_beats_magnesium_electrolyte_name_fallback():
    row = entry("Magnesium oxide", category_path=target_snapshot("gi:bowel", default_categories()))
    assert ids(row) == {"constipation"}


def test_drugs_with_multiple_indications_do_not_invent_dka_heart_failure_or_status():
    result = ids(entry("Insulin"), entry("Furosemide"), entry("Levetiracetam"))
    assert result == {"seizure_risk"}


def test_local_antibiotic_does_not_create_systemic_sepsis_candidate():
    row = entry("Ciprofloxacin ophthalmic solution", route="Both Eyes")
    assert ids(row) == set()
    row["category_path"] = target_snapshot("group:antibiotic", default_categories())
    assert ids(row) == set()


@pytest.mark.parametrize("active", [False, None, "true", 1])
def test_only_explicit_active_entries_are_eligible(active):
    assert ids(entry("Ceftriaxone", active=active)) == set()


def test_future_held_hidden_and_stopped_source_orders_do_not_supply_candidates():
    source = "Medications:\n" + "\n".join((
        "• [START ON 01/01/2099] ceftriaxone\t1 mg\tIntravenous\tq12h\t\t\t",
        "• [Held by provider] ceftriaxone\t1 mg\tIntravenous\tq12h\t\t\t",
        "• [Stopped] ceftriaxone\t1 mg\tIntravenous\tq12h\t\t\t",
        "• ceftriaxone\t1 mg\tIntravenous\tq12h\t\t\t",
    ))
    parsed = parse_medications(source)
    assert not parsed.error
    parsed.rows[-1]["hidden"] = True
    sheet = new_sheet("P4102")
    sheet["medications"] = parsed.rows
    medications = build_note_medications(sheet, NOW)
    assert medication_note_candidates(medications, support=SUPPORT, catalog=CATALOG) == []


def test_category_metadata_does_not_change_flat_output_and_results_are_independent():
    parsed = parse_medications("Medications:\n• Synthetic therapy\t1 mg\tIntravenous\tq12h\t\t\t")
    row = parsed.rows[0]
    row["category_path"] = custom_path("Hepatic encephalopathy", parent_id="gi:bowel", parent_name="Bowel Regimen")
    sheet = new_sheet("P4102")
    sheet["medications"] = [row]
    medications = build_note_medications(sheet, NOW)
    before = deepcopy((medications, CATALOG, SUPPORT, sheet))
    result = medication_note_candidates(medications, support=SUPPORT, catalog=CATALOG)
    assert result == [{"id": "encephalopathy", "reason": "Synthetic therapy is linked to this plan by its saved medication mapping. Review the neurologic indication and whether encephalopathy is documented."}]
    assert medications["sections"]["FEN / GI"] == {"Drips": [], "Scheduled": ["Synthetic therapy 1 mg Q12H"], "PRN": []}
    assert "Bowel Regimen" not in json.dumps(medications["sections"])
    assert "Hepatic encephalopathy" not in json.dumps(medications["sections"])
    assert (medications, CATALOG, SUPPORT, sheet) == before


def test_duplicate_evidence_is_deduplicated_without_selection_or_new_phrase_fields():
    row = entry("Ceftriaxone")
    result = candidates(row, deepcopy(row))
    assert len(result) == 1
    assert set(result[0]) == {"id", "reason"}


def test_missing_phrase_for_ambiguous_custom_category_does_not_invent_a_name():
    assert ids(entry(category_path=custom_path("Unrepresented indication"))) == set()
    assert ids(entry("Ceftriaxone"), catalog=[]) == set()


def test_pn_nutrition_signal_is_left_for_the_findings_helper():
    row = entry("Pediatric 2-in-1 PN", category_path=target_snapshot("gi:tpn", default_categories()))
    assert ids(row) == set()
