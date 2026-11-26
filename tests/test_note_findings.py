"""Synthetic current-source findings for explicitly generated notes."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from cbc import parse_cbc
from diet import parse_diet
from feeds import parse_feeds
from lab_windows import display_clock
from labs import parse_labs
from medications import parse_medications
from models import new_sheet
from note_findings import clinical_note_candidates
from note_generator import get_phrase_catalog
from viral import parse_viral_panel


NOW = datetime(2026, 11, 25, 23, tzinfo=timezone.utc)
TODAY = "11/25/2026 0800"
YESTERDAY = "11/24/2026 0800"


def parsed(parser, text, **kwargs):
    result = parser(text, **kwargs)
    assert not result.error, result.error
    return result.data


def laboratory(*rows):
    sheet = new_sheet("P4102")
    sheet["labs"] = parsed(parse_labs, "Labs:\n" + "\n".join("\t".join(row) for row in rows))
    return sheet


def virology(*rows):
    sheet = new_sheet("P4102")
    for row in rows:
        sheet["viral_panel"]["rows"].extend(parsed(parse_viral_panel, "\t".join(row))["rows"])
    return sheet


def medication(name, rate="20 mL/hr", route="Intravenous"):
    source = "Medications:\n• " + "\t".join((name, rate, route, "Continuous", "", "", ""))
    result = parse_medications(source)
    assert not result.error
    return result.rows[0]


def candidates(sheet, **kwargs):
    return clinical_note_candidates(sheet, as_of=NOW, **kwargs)


def ids(sheet, **kwargs):
    return {item["id"] for item in candidates(sheet, **kwargs)["candidates"]}


def test_requested_lab_viral_npo_examples_are_read_only_and_use_catalog_ids():
    sheet = laboratory(("HGB", "8.1 (L)", TODAY), ("PLT", "75 (L)", TODAY),
                       ("K", "2.9 (L)", TODAY), ("INR", "1.7 (H)", TODAY))
    sheet["viral_panel"] = parsed(parse_viral_panel, "RESPSYNVRNA\tDetected (A)\t" + TODAY)
    sheet["diet"] = parsed(parse_diet, "NPO")
    settings = {"diagnoses_destination": "Neurologic"}
    before, settings_before = deepcopy(sheet), deepcopy(settings)
    result = candidates(sheet, settings=settings)
    assert {item["id"] for item in result["candidates"]} == {
        "anemia", "thrombocytopenia", "hypokalemia", "coagulopathy", "rsv", "malnutrition_risk"}
    assert all(set(item) == {"id", "reason"} and item["reason"] for item in result["candidates"])
    assert {item["id"] for item in result["candidates"]} <= {item["id"] for item in get_phrase_catalog()}
    assert result["warnings"] == []
    assert "2.9 (L)" in json.dumps(result) and "Detected (A)" in json.dumps(result)
    assert sheet == before and settings == settings_before


@pytest.mark.parametrize("component,value,expected", [
    ("HEMOGLOBIN", "8.1 (L)", "anemia"),
    ("PLATELETS", "75 (LL)", "thrombocytopenia"),
    ("SODIUM", "130 (L)", "hyponatremia"),
    ("POTASSIUM", "2.9 (LOW)", "hypokalemia"),
    ("MAGNESIUM", "1.1 (L)", "hypomagnesemia"),
    ("PHOSPHORUS", "1.5 (L)", "hypophosphatemia"),
    ("CALCIUM", "7.5 (L)", "hypocalcemia"),
    ("GLUCOSE", "55 (L)", "hypoglycemia"),
    ("K", "6.1 (H)", "hyperkalemia"),
    ("NA", "150 (H)", "hypernatremia"),
    ("AST", "120 (H)", "transaminitis"),
    ("ALT", "130 (HH)", "transaminitis"),
    ("INR", "1.7 (H)", "coagulopathy"),
    ("PT", "19 (HIGH)", "coagulopathy"),
    ("APTT", "60 (H)", "coagulopathy"),
    ("FIBRINOGEN", "95 (L)", "coagulopathy"),
])
def test_source_flags_map_to_existing_phrases(component, value, expected):
    assert ids(laboratory((component, value, TODAY))) == {expected}


@pytest.mark.parametrize("component,value", [("ALBUMIN", "2.1 (L)"), ("ALB", "2.1 g/dL (LOW)")])
def test_source_low_albumin_uses_canonical_label_without_changing_the_source(component, value):
    sheet = laboratory((component, value, TODAY))
    before = deepcopy(sheet)
    result = candidates(sheet)
    assert [item["id"] for item in result["candidates"]] == ["hypoalbuminemia"]
    assert "Albumin: " + value in result["candidates"][0]["reason"]
    assert "source marked low" in result["candidates"][0]["reason"]
    assert result["warnings"] == []
    assert sheet == before


def test_albumin_uses_only_an_existing_patient_limit_with_matching_source_units():
    sheet = laboratory(("ALB", "2.1 g/dL", TODAY))
    assert ids(sheet) == set()
    sheet["problem_review"] = {"enabled": True, "decisions": {},
                               "low_limits": {"ALBUMIN": {"value": "2.5", "unit": "g/dL"}}}
    before = deepcopy(sheet)
    result = candidates(sheet)
    assert [item["id"] for item in result["candidates"]] == ["hypoalbuminemia"]
    assert "below your limit 2.5 g/dL" in result["candidates"][0]["reason"]
    assert sheet == before
    sheet["problem_review"]["low_limits"]["ALBUMIN"]["unit"] = "g/L"
    assert ids(sheet) == set()


@pytest.mark.parametrize("newer", ["4.0 g/dL", "Pending", "2.1 (L) hemolyzed", "2.1 (L) (H)"])
def test_latest_albumin_normal_or_unusable_result_supersedes_old_low_across_aliases(newer):
    sheet = laboratory(("ALBUMIN", "2.1 (L)", YESTERDAY), ("ALB", newer, TODAY))
    assert ids(sheet) == set()


def test_excluded_latest_albumin_does_not_restore_prior_low_and_failed_import_stays_hidden():
    sheet = laboratory(("ALB", "2.1 (L)", YESTERDAY), ("ALBUMIN", "2.0 (L)", TODAY))
    sheet["labs"]["rows"][-1]["include"] = False
    assert ids(sheet) == set()
    sheet["labs"]["rows"][-1]["include"] = True
    sheet["import_warnings"] = {"g": []}
    assert ids(sheet) == set()


def test_future_and_preadmission_low_albumin_are_not_current_note_findings():
    sheet = laboratory(("ALB", "2.1 (L)", "11/20/2026"), ("ALBUMIN", "2.0 (L)", "11/27/2026"))
    sheet["admission_date"] = "11/24/2026"
    assert ids(sheet) == set()


def test_albumin_infusion_alone_does_not_supply_a_hypoalbuminemia_finding():
    sheet = new_sheet("P4102")
    sheet["medications"] = [medication("albumin human 25% infusion", "10 mL/hr")]
    assert ids(sheet) == set()


def test_absolute_cbc_counts_use_recorded_units_and_not_percentages():
    sheet = new_sheet("P4102")
    sheet["cbc"] = parsed(parse_cbc, "Lab\tUnits\t" + TODAY +
                          "\nHEMOGLOBIN\tg/dL\t8.1 (L)\nPLATELETS\tK/uL\t75 (L)"
                          "\nNEUTROS ABS\t10^3/uL\t0.8 (L)\nLYMPHS ABS AUTO\tK/uL\t0.5 (L)")
    assert ids(sheet) == {"anemia", "thrombocytopenia", "neutropenia", "lymphopenia"}
    sheet["cbc"]["rows"][2]["unit"] = "%"
    sheet["cbc"]["rows"][3]["unit"] = "%"
    assert ids(sheet) == {"anemia", "thrombocytopenia"}


def test_existing_patient_limits_and_starred_cbc_rules_are_reused_without_conversions():
    sheet = laboratory(("K", "3.1 mmol/L", TODAY), ("HGB", "10.2 g/dL*", TODAY),
                       ("PLT", "120 K/uL*", TODAY))
    sheet["problem_review"] = {"enabled": True, "decisions": {},
                               "low_limits": {"K": {"value": "3.5", "unit": "mmol/L"}}}
    assert ids(sheet) == {"anemia", "thrombocytopenia", "hypokalemia"}
    sheet["problem_review"]["low_limits"]["K"]["unit"] = "mg/dL"
    assert "hypokalemia" not in ids(sheet)


@pytest.mark.parametrize("value,expected", [("146", True), ("145", False), (">145", True),
                                           ("<150", False), ("146 mg/dL", False)])
def test_existing_sodium_rule_is_the_only_unconfigured_numeric_cutoff(value, expected):
    assert ("hypernatremia" in ids(laboratory(("NA", value, TODAY)))) is expected


def test_no_new_age_cutoffs_etiology_or_acid_base_causes_are_invented():
    sheet = laboratory(("K", "2.9", TODAY), ("MG", "1.1", TODAY), ("HGB", "8.1", TODAY),
                       ("PLT", "75", TODAY), ("CALCIUM", "7.5", TODAY), ("GLUCOSE", "250 (H)", TODAY),
                       ("CREATININE", "2.1 (H)", TODAY), ("BILITOT", "4 (H)", TODAY),
                       ("CK", "500 (H)", TODAY), ("CO2", "14 (L)", TODAY), ("FIB", "600 (H)", TODAY),
                       ("ANTI-XA", "0.8 (H)", TODAY))
    result = candidates(sheet)
    assert result["candidates"] == []
    assert any("cause" in warning and "CO2" in warning for warning in result["warnings"])


@pytest.mark.parametrize("component,older,newer,expected", [
    ("HGB", "8.1 (L)", "12.5", "anemia"),
    ("PLT", "75 (L)", "200", "thrombocytopenia"),
    ("K", "2.9 (L)", "4.0", "hypokalemia"),
    ("K", "6.1 (H)", "4.0", "hyperkalemia"),
    ("NA", "150", "140", "hypernatremia"),
    ("INR", "1.7 (H)", "1.0", "coagulopathy"),
    ("AST", "120 (H)", "25", "transaminitis"),
])
def test_latest_normal_replaces_older_abnormal_regardless_of_source_order(component, older, newer, expected):
    for rows in (((component, older, YESTERDAY), (component, newer, TODAY)),
                 ((component, newer, TODAY), (component, older, YESTERDAY))):
        assert expected not in ids(laboratory(*rows))


@pytest.mark.parametrize("value", ["Pending", "Cancelled", "2.9 (L) hemolyzed", "2.9 (L) (H)",
                                  "2.9 | 4.0", "-2.9 (L)", "No result"])
def test_latest_unusable_lab_does_not_restore_older_abnormal(value):
    sheet = laboratory(("K", "2.8 (L)", YESTERDAY), ("K", value, TODAY))
    assert ids(sheet) == set()


def test_hidden_latest_and_unordered_conflicts_do_not_restore_an_old_abnormal():
    sheet = laboratory(("K", "2.8 (L)", YESTERDAY), ("K", "4.1", TODAY))
    sheet["labs"]["rows"][-1]["include"] = False
    assert ids(sheet) == set()
    for dates in (("11/25/2026", "11/25/2026"), ("11/25/2026 0800", "11/25/2026")):
        sheet = laboratory(("K", "2.8 (L)", dates[0]), ("K", "4.1", dates[1]))
        result = candidates(sheet)
        assert result["candidates"] == []
        assert any("conflicting" in warning for warning in result["warnings"])


def test_real_collection_times_resolve_order_and_admission_excludes_earlier_data():
    sheet = laboratory(("K", "2.8 (L)", "11/25/2026 0800"), ("K", "4.1", "11/25/2026 0900"),
                       ("MG", "1.1 (L)", "11/27/2026"), ("PHOS", "1.0 (L)", "11/20/2026"))
    sheet["admission_date"] = "11/24/2026"
    assert ids(sheet) == set()


def test_q_snapshot_uses_standard_hgb_and_does_not_fall_back_after_empty_or_hidden_latest():
    sheet = laboratory(("HGB", "8.1 (L)", YESTERDAY))
    sheet["cbc"] = parsed(parse_cbc, "Lab\tUnits\t11/25/2026 0800\t11/24/2026 0800"
                          "\nHEMOGLOBIN\tg/dL\t12.5\t8.1 (L)\nHEMOGLOBIN ISTAT\tg/dL\t7.0 (L)\t--")
    assert ids(sheet) == set()
    sheet["cbc"]["rows"][0]["include"] = False
    assert ids(sheet) == set()
    sheet["cbc"] = {"rows": [], "notes": []}
    assert ids(sheet) == set()


def test_failed_general_and_cbc_imports_suppress_only_their_retained_results():
    sheet = laboratory(("K", "2.8 (L)", TODAY))
    sheet["cbc"] = parsed(parse_cbc, "Lab\tUnits\t" + TODAY + "\nHEMOGLOBIN\tg/dL\t8.1 (L)")
    sheet["import_warnings"] = {"g": []}
    assert ids(sheet) == {"anemia"}
    sheet["import_warnings"] = {"q": []}
    assert ids(sheet) == {"hypokalemia"}
    sheet["import_warnings"] = {"q": [], "g": []}
    assert ids(sheet) == set()


@pytest.mark.parametrize("component,expected", [
    ("ADENOVIRDNA", "adenovirus"), ("HUMRHINENRNA", "rhinovirus"),
    ("FLUAVIRUSRNA", "influenza"), ("FLUBVIRUSRNA", "influenza"),
    ("PARAFLU1RNA", "parainfluenza"), ("PARAFLU4RNA", "parainfluenza"),
    ("RESPSYNVRNA", "rsv"), ("Respiratory syncytial virus", "rsv"),
    ("SARS-CoV-2", "covid19"), ("COVID-19", "covid19"),
])
def test_supported_positive_viruses_use_verified_catalog_ids(component, expected):
    assert ids(virology((component, "Detected (A)", TODAY))) == {expected}


@pytest.mark.parametrize("result", ["Negative", "Not Detected", "Undetected", "Non-detected", "Pending",
                                   "Indeterminate", "Presumptive positive", "Positive control", "Negative (A)"])
def test_negative_and_uncertain_viral_results_are_not_positive(result):
    assert ids(virology(("RESPSYNVRNA", result, TODAY))) == set()


def test_latest_viral_negative_or_hidden_result_suppresses_old_positive_across_aliases():
    sheet = virology(("RESPSYNVRNA", "Detected", YESTERDAY), ("RSV", "Not detected", TODAY))
    assert ids(sheet) == set()
    sheet["viral_panel"]["rows"][-1]["result"] = "Detected"
    sheet["viral_panel"]["rows"][-1]["include"] = False
    assert ids(sheet) == set()
    sheet["viral_panel"]["rows"][-1]["include"] = True
    sheet["viral_panel"]["rows"][-1]["result"] = "Pending"
    assert ids(sheet) == set()


def test_edited_display_label_cannot_move_a_known_source_negative_to_another_virus():
    sheet = virology(("RESPSYNVRNA", "Detected", YESTERDAY), ("RSV", "Not detected", TODAY))
    sheet["viral_panel"]["rows"][-1]["name"] = "Adenovirus"
    assert ids(sheet) == set()


def test_viral_ambiguity_futures_and_import_errors_do_not_select_a_phrase():
    sheet = virology(("RESPSYNVRNA", "Detected", "11/25/2026"), ("RSV", "Negative", "11/25/2026"),
                     ("ADENOVIRDNA", "Detected", "11/27/2026"))
    result = candidates(sheet)
    assert result["candidates"] == []
    assert any("Conflicting latest viral" in warning for warning in result["warnings"])
    sheet = virology(("RESPSYNVRNA", "Detected", TODAY))
    sheet["import_warnings"] = {"o": []}
    assert ids(sheet) == set()


def test_distinct_influenza_subtypes_are_not_mistaken_for_serial_results():
    sheet = virology(("FLUAVIRUSRNA", "Detected", YESTERDAY), ("FLUBVIRUSRNA", "Not detected", TODAY))
    assert ids(sheet) == {"influenza"}


def test_combined_assay_retains_limitation_and_unknown_codes_are_not_reinterpreted():
    sheet = virology(("HUMRHINENRNA", "Detected", TODAY), ("SARSRNA", "Detected", TODAY),
                     ("Human metapneumovirus", "Positive", TODAY), ("Coronavirus OC43", "Positive", TODAY))
    result = candidates(sheet)
    assert {item["id"] for item in result["candidates"]} == {"rhinovirus"}
    assert "does not distinguish" in result["candidates"][0]["reason"]
    assert all(any(label in warning for warning in result["warnings"])
               for label in ("SARSRNA", "Human metapneumovirus", "Coronavirus OC43"))
    sheet["viral_panel"]["rows"][1]["name"] = "SARS-CoV-2"
    assert "covid19" in ids(sheet)


@pytest.mark.parametrize("source", ["npo", "enteral", "recorded", "diet_pn", "med_pn", "med_lipid"])
def test_requested_nutrition_sources_produce_risk_without_calculations(source):
    sheet = new_sheet("P4102")
    if source == "npo":
        sheet["diet"] = parsed(parse_diet, "NPO except medications")
    elif source == "enteral":
        sheet["diet"] = parsed(parse_diet, "Dietary Orders:\nInfant tube feeding Pediatric Tube Feeding; Synthetic Formula; Continuous Feeds; Gastrostomy tube; 18 hours; 32; 576; No Additives")
    elif source == "recorded":
        sheet["feeds"] = parsed(parse_feeds, "Feeding Method: NG\nFormula: Synthetic formula\nRate: 30 mL/hr")
    elif source == "diet_pn":
        sheet["diet"] = parsed(parse_diet, "Dietary Orders:\nTPN at 10 mL/hr")
    else:
        sheet["medications"] = [medication("Pediatric 2-in-1 PN (Continuous)" if source == "med_pn" else "SMOFlipid 20%")]
    before = deepcopy(sheet)
    assert ids(sheet) == {"malnutrition_risk"}
    assert sheet == before


@pytest.mark.parametrize("source", ["[Held by provider] NPO", "[START ON 11/27/2026] NPO", "Adult diet Regular"])
def test_held_future_and_regular_oral_diet_do_not_imply_current_nutrition_support(source):
    sheet = new_sheet("P4102")
    sheet["diet"] = parsed(parse_diet, source)
    assert ids(sheet) == set()


def test_hidden_and_failed_diet_and_superseded_recorded_feed_snapshot_do_not_reappear():
    sheet = new_sheet("P4102")
    sheet["diet"] = parsed(parse_diet, "NPO")
    sheet["diet"]["rows"][0]["include"] = False
    assert ids(sheet) == set()
    sheet["diet"]["rows"][0]["include"] = True
    sheet["import_warnings"] = {"x": [{"action": "diet_hidden"}]}
    assert ids(sheet) == set()
    sheet["import_warnings"] = {}
    sheet["diet"] = {"rows": [], "enteral": [], "parenteral": [], "recorded_feed_ids": []}
    sheet["feeds"] = parsed(parse_feeds, "Feeding Method: NG\nFormula: Synthetic formula\nRate: 30 mL/hr")
    assert ids(sheet) == set()
    sheet["diet"] = None
    sheet["import_warnings"] = {"t": [{"action": "feeds_hidden"}]}
    assert ids(sheet) == set()


@pytest.mark.parametrize("changes", [{"include": False}, {"formula": "UNK", "rate": "0 mL/hr"},
                                     {"formula": "", "rate": ""}, {"device": "[REMOVED] NG"}])
def test_excluded_or_empty_recorded_feeding_is_not_assumed_active(changes):
    sheet = new_sheet("P4102")
    sheet["feeds"] = parsed(parse_feeds, "Feeding Method: NG\nFormula: Synthetic formula\nRate: 30 mL/hr")
    sheet["feeds"]["rows"][0].update(changes)
    assert ids(sheet) == set()


@pytest.mark.parametrize("changes", [{"method": "PO", "rate": ""}, {"method": "UNK", "formula": "UNK"},
                                     {"formula": "UNK", "rate": "0.5 mL/hr"}])
def test_explicit_feeding_plan_does_not_require_a_known_formula_rate_and_route(changes):
    sheet = new_sheet("P4102")
    sheet["feeds"] = parsed(parse_feeds, "Feeding Method: NG\nFormula: Synthetic formula\nRate: 30 mL/hr")
    sheet["feeds"]["rows"][0].update(changes)
    assert ids(sheet) == {"malnutrition_risk"}


@pytest.mark.parametrize("method", ["PO", "UNK"])
def test_active_structured_feeding_orders_count_when_route_is_oral_or_unknown(method):
    sheet = new_sheet("P4102")
    sheet["diet"] = parsed(parse_diet, "Dietary Orders:\nInfant tube feeding Pediatric Tube Feeding; Synthetic Formula; Continuous Feeds; Gastrostomy tube; 18 hours; 32; 576; No Additives")
    sheet["diet"]["enteral"][0]["method"] = method
    assert ids(sheet) == {"malnutrition_risk"}


@pytest.mark.parametrize("qualifier", ["[Held by provider] ", "[Stopped] ", "[START ON 11/27/2026] "])
def test_pn_medication_status_is_respected(qualifier):
    sheet = new_sheet("P4102")
    sheet["medications"] = [medication(qualifier + "Pediatric 2-in-1 PN (Continuous)")]
    assert ids(sheet) == set()


def test_hidden_latest_pn_does_not_restore_old_bag_or_diet_duplicate():
    sheet = new_sheet("P4102")
    sheet["medications"] = [medication("[START ON 11/24/2026] Pediatric 2-in-1 PN"),
                            medication("[START ON 11/25/2026] Pediatric 2-in-1 PN")]
    sheet["medications"][-1]["include"] = False
    sheet["diet"] = parsed(parse_diet, "Dietary Orders:\nTPN at 10 mL/hr")
    assert ids(sheet) == set()


def test_prebuilt_medications_payload_is_reused_without_mutation(monkeypatch):
    from note_medications import build_note_medications
    sheet = new_sheet("P4102")
    sheet["medications"] = [medication("Pediatric 2-in-1 PN (Continuous)")]
    medication_data = build_note_medications(sheet, as_of=NOW)
    before = deepcopy(medication_data)

    def unexpected_rebuild(*args, **kwargs):
        raise AssertionError("The supplied medication payload must be reused")

    monkeypatch.setattr("note_findings.build_note_medications", unexpected_rebuild)
    assert ids(sheet, medications=medication_data) == {"malnutrition_risk"}
    assert medication_data == before


def test_existing_qtc_finding_is_reused_without_recalculation():
    sheet = new_sheet("P4102")
    sheet["ecg"] = {"value": "475", "date": "11/24/2026"}
    assert ids(sheet) == {"prolonged_qt"}
    sheet["ecg"]["value"] = "425"
    assert ids(sheet) == set()
    sheet["ecg"]["value"] = "475"
    sheet["import_warnings"] = {"z": []}
    assert ids(sheet) == set()


def test_default_clock_honors_display_context_for_reproducible_selection():
    sheet = laboratory(("K", "2.8 (L)", TODAY))
    with display_clock(NOW):
        assert clinical_note_candidates(sheet) == candidates(sheet)
    with display_clock(datetime(2026, 11, 24, 23, tzinfo=timezone.utc)):
        assert clinical_note_candidates(sheet)["candidates"] == []
