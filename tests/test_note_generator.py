"""Synthetic checks for explicit, reviewable Epic note generation."""
from copy import deepcopy
import json
import re

import pytest

from medications import parse_medications
from models import new_sheet
from note_generator import generate_note, get_phrase_catalog


def order(name, dose, section="Neurologic", frequency="q12h", route="Intravenous", admin=""):
    source = "Medications:\n• " + "\t".join((name, dose, route, frequency, "", "", admin))
    parsed = parse_medications(source)
    assert not parsed.error
    row = parsed.rows[0]
    row["section"] = section
    return row


def sheet_with(*orders, diagnoses="", mode=None, noninvasive=None):
    sheet = new_sheet("P4102")
    sheet["medications"] = list(orders)
    sheet["fields"]["Diagnoses"] = diagnoses
    sheet["ventilation"] = {"mode": mode, "values": {}} if mode else None
    sheet["noninvasive"] = noninvasive or []
    return sheet


def indexed(result):
    return {row["id"]: row for row in result["suggestions"]}


def clinical_example_sheet():
    """Source-shaped synthetic examples from the requested automatic workflow."""
    from categories import default_categories, target_snapshot
    from diet import parse_diet
    from lab_windows import clock
    from labs import parse_labs
    from viral import parse_viral_panel

    sheet = sheet_with(
        order("Fentanyl infusion", "2 mcg/kg/hr", frequency="Continuous"),
        order("Clobazam", "100 mg", route="Oral"),
        order("Pantoprazole", "20 mg", section="FEN / GI"),
        order("Polyethylene glycol", "8.5 g", section="FEN / GI", route="Oral"),
        order("Ceftriaxone", "500 mg", section="Infectious Disease"),
        mode="PRVC",
    )
    categories = default_categories()
    for index, target in ((1, "group:antiepileptic"), (2, "gi:prophylaxis"),
                          (3, "gi:bowel"), (4, "group:antibiotic")):
        sheet["medications"][index]["category_path"] = target_snapshot(target, categories)
    stamp = clock().strftime("%m/%d/%Y %H:%M")
    viral = parse_viral_panel("RESPSYNVRNA\tDetected (A)\t" + stamp)
    labs = parse_labs("Labs:\n" + "\n".join(
        component + "\t" + value + "\t" + stamp
        for component, value in (("HGB", "8.1 (L)"), ("PLT", "75 (L)"),
                                 ("K", "2.9 (L)"), ("INR", "1.7 (H)"))
    ))
    diet = parse_diet("NPO")
    assert not viral.error and not labs.error and not diet.error
    sheet.update(viral_panel=viral.data, labs=labs.data, diet=diet.data)
    return sheet


EXAMPLE_PLANS = {
    "acute_hypoxemic_invasive", "agitation_intubated", "seizure_risk",
    "gastric_ulcer_risk", "constipation", "sepsis", "rsv", "malnutrition_risk",
    "anemia", "thrombocytopenia", "hypokalemia", "coagulopathy",
}


@pytest.mark.parametrize("note_type", ["progress", "attestation"])
def test_first_generation_includes_medication_support_viral_nutrition_and_lab_plans(note_type):
    sheet = clinical_example_sheet()
    before = deepcopy(sheet)
    result = generate_note(sheet, note_type=note_type)
    selected = {key for key, row in indexed(result).items() if row["selected"]}
    assert EXAMPLE_PLANS <= selected
    catalog = {row["id"]: row["phrase"] for row in get_phrase_catalog()}
    for key in EXAMPLE_PLANS:
        assert result["selected_plan_tokens"].count("@" + catalog[key] + "@") == 1
        assert "@" + catalog[key] + "@" in result["text"]
    for label in ("Bowel Regimen", "GI prophylaxis", "Antiepileptic", "Antibiotics"):
        assert label not in result["text"]
    if note_type == "progress":
        assert "Drips:\nFentanyl at 2 mcg/kg/hr" in result["text"]
        assert "Scheduled:" in result["text"]
        assert "Polyethylene glycol 8.5 g Q12H" in result["text"]
    else:
        assert "Fentanyl" not in result["text"] and "Polyethylene glycol" not in result["text"]
    assert sheet == before


@pytest.mark.parametrize("nutrition", ["npo", "tube_feeds", "pn"])
def test_each_requested_nutrition_source_includes_malnutrition_risk(nutrition):
    from diet import parse_diet
    from feeds import parse_feeds

    sheet = sheet_with()
    if nutrition == "npo":
        sheet["diet"] = parse_diet("NPO").data
    elif nutrition == "tube_feeds":
        sheet["feeds"] = parse_feeds("Feeding Method: NG\nFormula: Synthetic formula\nRate: 30 mL/hr").data
    else:
        sheet["medications"] = [order("Pediatric 2-in-1 PN (Continuous)", "30 mL/hr",
                                      section="FEN / GI", frequency="Continuous")]
    result = generate_note(sheet)
    assert indexed(result)["malnutrition_risk"]["selected"]
    assert "@ACKZATRISKFORMALNUTRITION@" in result["text"]


def test_saved_therapeutic_categories_supply_plans_without_becoming_note_subheadings():
    from categories import default_categories, target_snapshot

    categories = default_categories()
    rows = []
    for label, target, section in (
        ("Synthetic bowel agent", "gi:bowel", "FEN / GI"),
        ("Synthetic gastric agent", "gi:prophylaxis", "FEN / GI"),
        ("Synthetic seizure agent", "group:antiepileptic", "Neurologic"),
        ("Synthetic antibiotic agent", "group:antibiotic", "Infectious Disease"),
    ):
        row = order(label, "1 mg", section=section)
        row["category_path"] = target_snapshot(target, categories)
        rows.append(row)
    result = generate_note(sheet_with(*rows))
    for key in ("constipation", "gastric_ulcer_risk", "seizure_risk", "sepsis"):
        assert indexed(result)[key]["selected"]
    for label in ("Bowel Regimen", "GI prophylaxis", "Antiepileptic", "Antibiotics"):
        assert label not in result["text"]


def test_explicit_negatives_and_history_override_medication_and_lab_candidates():
    sheet = clinical_example_sheet()
    sheet["fields"]["Diagnoses"] = "Sepsis ruled out\nNo hypokalemia\nHistory of constipation"
    result = generate_note(sheet)
    rows = indexed(result)
    for key in ("sepsis", "hypokalemia", "constipation"):
        assert key not in rows or not rows[key]["selected"]
    for phrase in ("ACKZSEPSIS", "ACKZHYPOKALEMIA", "ACKZCONSTIPATION"):
        assert "@" + phrase + "@" not in result["text"]


def test_exact_template_tokens_and_medications_stay_in_their_main_sections():
    sheet = sheet_with(
        order("fentaNYL infusion", "2 mcg/kg/hr", frequency="Continuous"),
        order("cloBAZam tablet 100 mg", "100 mg", route="Oral"),
        order("fentaNYL injection 20 mcg", "20 mcg", frequency="q1h PRN"),
        order("pantoprazole injection 20 mg", "20 mg", section="FEN / GI"),
        order("ferrous sulfate", "15 mg", section="Hematology"),
        order("cefTRIAXone syringe 500 mg", "500 mg", section="Infectious Disease"),
        order("Unmapped example", "1 mg", section="Other Medications"),
    )
    before = deepcopy(sheet)
    result = generate_note(sheet)
    text = result["text"]
    neuro = text.split("NEUROLOGY", 1)[1].split("\n\nRESPIRATORY\n", 1)[0]
    assert "{CKNEUROSMARTLIST:45213}" not in text
    assert "{ACKNEUROEXAM:45450}" in neuro
    assert "Drips:\nFentanyl at 2 mcg/kg/hr" in neuro
    assert "Scheduled:\nClobazam 100 mg Q12H" in neuro
    assert "PRN:\nFentanyl 20 mcg Q1H PRN" in neuro
    assert "Antiepileptic" not in neuro
    assert "Pantoprazole" in text.split("{ACKFENGI:45365}")[1].split("HEMATOLOGY")[0]
    assert "Ferrous sulfate" in text.split("HEMATOLOGY")[1].split("INFECTIOUS DISEASES")[0]
    assert "Ceftriaxone" in text.split("INFECTIOUS DISEASES")[1].split("ASSESSMENT")[0]
    assert "ADDITIONAL MEDICATIONS\n\nOther Medications" in text
    assert "MEDICATIONS FOR REVIEW" not in text and "MEDICATIONS IN REVIEW" not in text
    assert "Unmapped example 1 mg Q12H" in text
    for token in (
        "@NAME@", "@MRN@", "@TODAYDATE@", "@CURHOSPDAY@", "@ICULOS@", "@CODE@", "@DIAGX@",
        "{overnightevents:45212}", "{ACKROS:45449}", "{ACKCVEXAM:45452}",
        "{ACKHLABS:45360}", "@FLOWSTAT(6:24)@", "@CULTUREHX@", "{ACKIDLABS:45351}",
        "@RESUFAST(MRSADNA:1,MRSANPADM:1)@", "{CKCLININDICATIONS:45218}",
        "@age@", "@sex@", "@ADMITDT@",
    ):
        assert text.count(token) == 1
    assert text.count("***") == 1
    assert "with ***." in text.split("ASSESSMENT")[1]
    assert "@ATRISKFORGASTRICULCERS@" not in text
    assert text.count("@ACKZATRISKFORGASTRICULCERS@") == 1
    assert sheet == before
    json.dumps(result)


def test_known_positive_diagnoses_use_exact_phrase_names_once():
    result = generate_note(sheet_with(diagnoses="1. Sepsis\n2. Anemia\n3. Hypokalemia\n4. Sepsis\n5. Pulmonary hypertension"))
    rows = indexed(result)
    assert {key for key, value in rows.items() if value["selected"]} == {"sepsis", "anemia", "hypokalemia", "pulmonary_hypertension"}
    assert result["text"].count("@ACKZSEPSIS@") == 1
    assert "@ACKZHYPERTENSION@" not in result["text"]


@pytest.mark.parametrize("diagnosis", [
    "No sepsis", "Without evidence of sepsis", "Sepsis ruled out", "Sepsis, resolved",
    "History of sepsis", "Hx: sepsis", "Prior sepsis", "Family history of sepsis",
    "Sepsis (resolved)", "No longer has sepsis",
])
def test_negative_and_historical_diagnoses_are_not_promoted(diagnosis):
    result = generate_note(sheet_with(diagnoses=diagnosis))
    assert "sepsis" not in indexed(result)
    assert "@ACKZSEPSIS@" not in result["text"]


@pytest.mark.parametrize("diagnosis", [
    "Possible sepsis", "Suspected sepsis", "Rule out sepsis", "Concern for sepsis",
    "Sepsis?", "? Sepsis", "?? Sepsis", "Sepsis not ruled out", "Sepsis unconfirmed",
])
def test_uncertain_positive_diagnoses_are_included_in_the_first_draft(diagnosis):
    result = generate_note(sheet_with(diagnoses=diagnosis))
    assert indexed(result)["sepsis"]["selected"] is True
    assert "@ACKZSEPSIS@" in result["text"]
    assert any("Uncertain diagnosis" in reason for reason in indexed(result)["sepsis"]["reasons"])


def test_risk_and_prophylaxis_do_not_become_the_disease():
    result = generate_note(sheet_with(diagnoses="At risk for deep vein thrombosis\nDVT prophylaxis\nAt risk for seizures"))
    rows = indexed(result)
    assert rows["dvt_risk"]["selected"]
    assert rows["seizure_risk"]["selected"]
    assert "deep_vein_thrombosis" not in rows
    assert "status_epilepticus" not in rows


def test_conflicting_diagnoses_are_unselected_until_review():
    result = generate_note(sheet_with(diagnoses="Sepsis\nSepsis ruled out"))
    assert not indexed(result)["sepsis"]["selected"]
    assert any("qualifier" in reason for reason in indexed(result)["sepsis"]["reasons"])


def test_current_noninvasive_support_adds_the_matching_plan_on_first_generation():
    support = [{"device": "HFNC", "values": {"Flow": "10"}, "flow_inferred": False, "pressure_inferred": False}]
    sheet = sheet_with(noninvasive=support)
    first = generate_note(sheet)
    assert indexed(first)["acute_hypoxemic_noninvasive"]["selected"]
    assert "@ACKZACUTEHYPOXEMICRESPIRATORYFAILURENONINVASIVE@" in first["text"]
    sheet["fields"]["Diagnoses"] = "Acute hypoxemic respiratory failure"
    second = generate_note(sheet)
    assert indexed(second)["acute_hypoxemic_noninvasive"]["selected"]
    assert "@ACKZACUTEHYPOXEMICRESPIRATORYFAILURENONINVASIVE@" in second["text"]


def test_confirmed_invasive_phrase_is_available_by_default_and_can_be_overridden():
    sheet = sheet_with(mode="PRVC", diagnoses="Acute hypoxemic respiratory failure")
    result = generate_note(sheet)
    candidate = indexed(result)["acute_hypoxemic_invasive"]
    assert candidate["phrase"] == "ACKZACUTEHYPOXEMICRESPIRATORYFAILUREINVASIVE"
    assert candidate["selected"] and candidate["verified"]
    assert not any("not visible" in warning or "exact name" in warning for warning in result["warnings"])
    assert "@ACKZACUTEHYPOXEMICRESPIRATORYFAILUREINVASIVE@" in result["text"]
    configured = generate_note(sheet, phrase_overrides={"acute_hypoxemic_invasive": "EXACTCONFIRMEDINVASIVE"}, selected_ids=["acute_hypoxemic_invasive"])
    assert "@EXACTCONFIRMEDINVASIVE@" in configured["text"]
    assert "@ACKZACUTEHYPOXEMICRESPIRATORYFAILUREINVASIVE@" not in configured["text"]


def test_current_invasive_support_alone_includes_the_matching_plan():
    result = generate_note(sheet_with(mode="PRVC"))
    candidate = indexed(result)["acute_hypoxemic_invasive"]
    assert candidate["verified"] and candidate["selected"]
    assert "@ACKZACUTEHYPOXEMICRESPIRATORYFAILUREINVASIVE@" in result["text"]
    assert any("support" in reason.lower() for reason in candidate["reasons"])


@pytest.mark.parametrize("mode,expected,opposite", [
    ("PRVC", "invasive", "noninvasive"),
    ("CPAP NIV", "noninvasive", "invasive"),
    ("BiPAP", "noninvasive", "invasive"),
])
def test_current_support_selects_only_its_matching_phrase_despite_old_modes(mode, expected, opposite):
    sheet = sheet_with(mode=mode, diagnoses="Acute hypoxemic respiratory failure")
    sheet["ventilation"]["mode_history"] = {
        "reported_at": "2026-11-25T15:00", "latest_confirmed": True, "notes": [],
        "other_modes": [{"mode": "CPAP NIV" if expected == "invasive" else "PRVC", "values": {}, "reported_at": "2026-11-25T08:00"}],
    }
    result = generate_note(sheet)
    rows = indexed(result)
    assert rows["acute_hypoxemic_" + expected]["selected"]
    assert "acute_hypoxemic_" + opposite not in rows
    assert result["selected_plan_tokens"] == ["@ACKZACUTEHYPOXEMICRESPIRATORYFAILURE" + expected.upper() + "@"]


def test_current_support_takes_precedence_over_an_older_route_label_in_diagnosis():
    sheet = sheet_with(
        diagnoses="Acute hypoxemic respiratory failure with invasive support",
        noninvasive=[{"device": "HFNC", "values": {"Flow": "10"}, "flow_inferred": False, "pressure_inferred": False}],
    )
    result = generate_note(sheet)
    assert indexed(result)["acute_hypoxemic_noninvasive"]["selected"]
    assert "acute_hypoxemic_invasive" not in indexed(result)


def test_conflicting_current_support_cannot_preselect_both_respiratory_plans():
    sheet = sheet_with(
        mode="PRVC", diagnoses="Acute hypoxemic respiratory failure with invasive support",
        noninvasive=[{"device": "HFNC", "values": {"Flow": "10"}, "flow_inferred": False, "pressure_inferred": False}],
    )
    result = generate_note(sheet)
    assert all(not row["selected"] for row in result["suggestions"] if row["id"].startswith("acute_hypoxemic"))
    assert result["selected_plan_tokens"] == []


def test_old_modes_and_removed_airways_do_not_establish_current_support():
    sheet = sheet_with(mode="Unlisted current mode")
    sheet["ventilation"]["mode_history"] = {
        "reported_at": "2026-11-25T15:00", "latest_confirmed": True, "notes": [],
        "other_modes": [{"mode": "PRVC", "values": {}, "reported_at": "2026-11-25T08:00"}],
    }
    sheet["devices"] = {"rows": [{"kind": "ETT", "include": True, "removed": True, "status": ""}]}
    result = generate_note(sheet)
    assert not any(key.startswith("acute_hypoxemic") for key in indexed(result))
    sheet["ventilation"]["mode"] = "PRVC"
    sheet["ventilation"]["mode_history"]["latest_confirmed"] = False
    result = generate_note(sheet)
    assert not any(key.startswith("acute_hypoxemic") for key in indexed(result))
    assert any("latest ventilator mode is unconfirmed" in item for item in result["warnings"])


def test_sedation_and_other_medication_plans_are_included_without_confirmation():
    sheet = sheet_with(
        order("Fentanyl infusion", "2 mcg/kg/hr", frequency="Continuous"),
        order("Clobazam", "100 mg"),
        order("Polyethylene glycol", "8.5 g", section="FEN / GI"),
        order("Potassium chloride", "10 mEq", section="FEN / GI"),
        order("Enoxaparin", "20 mg", section="Hematology"),
        mode="PRVC",
    )
    rows = indexed(generate_note(sheet))
    for key in ("agitation_intubated", "seizure_risk", "constipation", "hypokalemia", "dvt_risk"):
        assert key in rows and rows[key]["selected"]
    assert "status_epilepticus" not in rows and "deep_vein_thrombosis" not in rows


def test_consistent_tracheostomy_support_includes_the_invasive_agitation_suggestion():
    sheet = sheet_with(
        order("Fentanyl infusion", "2 mcg/kg/hr", frequency="Continuous"),
        mode="PRVC", diagnoses="Restlessness and agitation",
    )
    sheet["devices"] = {"rows": [{"kind": "Trach", "include": True, "removed": False, "status": ""}]}
    candidate = indexed(generate_note(sheet))["agitation_intubated"]
    assert candidate["selected"]
    assert any("tracheostomy support" in reason for reason in candidate["reasons"])
    sheet["devices"]["rows"] = [{"kind": "ETT", "include": True, "removed": False, "status": ""}]
    assert indexed(generate_note(sheet))["agitation_intubated"]["selected"]


def test_not_intubated_diagnosis_uses_only_the_nonintubated_agitation_phrase():
    result = generate_note(sheet_with(diagnoses="Restlessness and agitation, not intubated"))
    rows = indexed(result)
    assert rows["agitation_nonintubated"]["selected"]
    assert "agitation_intubated" not in rows


def test_nasal_cannula_adds_noninvasive_plan_and_room_air_does_not():
    sheet = sheet_with(noninvasive=[{
        "device": "Nasal cannula", "values": {"Flow": "1"},
        "flow_inferred": False, "pressure_inferred": False,
    }])
    result = generate_note(sheet)
    assert indexed(result)["acute_hypoxemic_noninvasive"]["selected"]
    assert "@ACKZACUTEHYPOXEMICRESPIRATORYFAILURENONINVASIVE@" in result["text"]
    sheet["noninvasive"] = []
    sheet["fields"]["Respiratory"] = "Room air"
    assert not any(key.startswith("acute_hypoxemic") for key in indexed(generate_note(sheet)))


def test_antibiotics_add_sepsis_while_other_medications_use_their_supported_rules():
    sheet = sheet_with(
        order("Ceftriaxone", "500 mg", section="Infectious Disease"),
        order("Insulin", "1 unit/hr", frequency="Continuous"),
        order("Furosemide", "10 mg", section="Cardiovascular"),
        order("Levetiracetam", "200 mg"),
    )
    rows = indexed(generate_note(sheet))
    assert rows["sepsis"]["selected"]
    assert not ({"diabetic_ketoacidosis", "heart_failure", "status_epilepticus"} & set(rows))
    assert rows["seizure_risk"]["selected"]


def test_held_pantoprazole_does_not_select_ulcer_risk():
    sheet = sheet_with(order("[Held by provider] Pantoprazole", "20 mg", section="FEN / GI"))
    result = generate_note(sheet)
    assert "gastric_ulcer_risk" not in indexed(result)
    assert "[Held]" in result["text"]


def test_manual_selection_can_add_catalog_plans_and_clear_all_defaults():
    sheet = sheet_with(order("Pantoprazole", "20 mg", section="FEN / GI"))
    assert "@ACKZATRISKFORGASTRICULCERS@" in generate_note(sheet)["text"]
    assert generate_note(sheet, selected_ids=[])["text"].rstrip().endswith("PLAN")
    result = generate_note(sheet, phrase_style="dot", selected_ids=["tbi", "rhinovirus"])
    assert ".ACKZTBI" in result["text"] and ".ACKZRHINOVIRUS" in result["text"]
    assert "@ACKZATRISKFORGASTRICULCERS@" not in result["text"]
    assert indexed(result)["tbi"]["selected"]
    assert indexed(result)["tbi"]["reasons"] == ["Added during note review."]


def test_alternate_diagnoses_destination_is_supported_without_scanning_all_notes():
    sheet = sheet_with()
    sheet["fields"]["Other"] = "Sepsis"
    sheet["fields"]["Tasks"] = "Ask whether prior sepsis was resolved"
    assert "sepsis" not in indexed(generate_note(sheet))
    result = generate_note(sheet, settings={"diagnoses_destination": "Other"})
    assert indexed(result)["sepsis"]["selected"]


def test_catalog_is_independent_and_invalid_names_cannot_insert_arbitrary_note_text():
    catalog = get_phrase_catalog()
    assert sum(row["verified"] for row in catalog) == 96
    assert len({row["id"] for row in catalog}) == len(catalog)
    original_phrase = catalog[0]["phrase"]
    catalog[0]["phrase"] = "MUTATED"
    assert get_phrase_catalog()[0]["phrase"] == original_phrase
    with pytest.raises(ValueError):
        generate_note(sheet_with(), phrase_overrides={"tbi": "VALID@\nFABRICATED EXAM"})
    with pytest.raises(ValueError):
        generate_note(sheet_with(), selected_ids=["unknown_diagnosis"])
    with pytest.raises(ValueError):
        generate_note(sheet_with(), phrase_style="expand")


def test_progress_output_remains_default_and_returns_word_rendering_metadata():
    result = generate_note(sheet_with(diagnoses="Sepsis"))
    assert result["note_type"] == "progress" and result["phrase_style"] == "at"
    assert result["text"].startswith("PEDIATRIC CRITICAL CARE MEDICINE PROGRESS NOTE")
    assert result["selected_plan_tokens"] == ["@ACKZSEPSIS@"]


@pytest.mark.parametrize("old_name", ["ACZKARRHYTHMIA", "@ACZKARRHYTHMIA@", ".aczkarrhythmia"])
@pytest.mark.parametrize("phrase_style", ["at", "dot"])
def test_corrected_arrhythmia_reference_also_updates_an_old_saved_name_at_generation(old_name, phrase_style):
    overrides = {"arrhythmia": old_name}
    before = deepcopy(overrides)
    result = generate_note(sheet_with(diagnoses="Arrhythmia"),
                           phrase_overrides=overrides, phrase_style=phrase_style)
    expected = "@ACKZARRHYTHMIA@" if phrase_style == "at" else ".ACKZARRHYTHMIA"
    assert result["selected_plan_tokens"] == [expected]
    assert expected in result["text"] and "ACZKARRHYTHMIA" not in result["text"]
    assert overrides == before


def test_empty_progress_note_clears_only_the_two_medication_placeholders():
    text = generate_note(sheet_with())["text"]
    assert "***" not in text.split("HEMATOLOGY", 1)[1].split("ASSESSMENT", 1)[0]
    assert text.count("***") == 1 and "with ***." in text


@pytest.mark.parametrize("diagnosis", ["Hypoalbuminemia", "Hypoalbuminaemia"])
def test_documented_hypoalbuminemia_uses_the_supplied_fengi_phrase(diagnosis):
    sheet = sheet_with(diagnoses=diagnosis)
    result = generate_note(sheet)
    assert result["selected_plan_tokens"] == ["@ACKZHYPOALBUMINEMIA@"]
    assert indexed(result)["hypoalbuminemia"]["system"] == "FEN / GI"


@pytest.mark.parametrize("diagnosis", ["No hypoalbuminemia", "History of hypoalbuminemia"])
def test_qualified_hypoalbuminemia_does_not_enter_the_plan_automatically(diagnosis):
    assert generate_note(sheet_with(diagnoses=diagnosis))["selected_plan_tokens"] == []


def test_attestation_keeps_exact_source_text_and_smartlists_without_medication_lists():
    sheet = sheet_with(
        order("Fentanyl infusion", "2 mcg/kg/hr", frequency="Continuous"),
        order("Pantoprazole injection 20 mg", "20 mg", section="FEN / GI"),
        order("Clobazam tablet 100 mg", "100 mg", route="Oral"),
        diagnoses="Acute hypoxemic respiratory failure", mode="PRVC",
    )
    before = deepcopy(sheet)
    result = generate_note(sheet, note_type="attestation")
    expected = """ATTENDING ATTESTATION
I personally examined the patient separately and discussed the case with the resident/physician assistant and with any services involved in a multidisciplinary fashion. I agree with the resident/physician's assistant documentation with any exceptions noted below.

SUBJECTIVE

INTERVAL EVENTS
{overnightevents:45212}

REVIEW OF SYSTEMS
{ACKROS:45449}

OBJECTIVE

PHYSICAL EXAMINATION
Neurologic Examination:
{ACKNEUROEXAM:45450}
Respiratory Examination:
{ACKRESPEXAM:45451}\x20
Cardiovascular Examination:
{ACKCVEXAM:45452}
Abdominal Examination:
{ACKABDEXAM:45453}

ASSESSMENT
The patient is a @age@ @sex@ who presented to the Pediatric Intensive Care Unit on @ADMITDT@ with ***.
{CKCLININDICATIONS:45218}
PLAN
@ACKZACUTEHYPOXEMICRESPIRATORYFAILUREINVASIVE@
@ACKZATRISKFORGASTRICULCERS@
"""
    assert result["text"].split("\nPLAN\n", 1)[0] == expected.split("\nPLAN\n", 1)[0]
    assert result["note_type"] == "attestation"
    assert result["phrase_style"] == "at"
    assert {
        "@ACKZACUTEHYPOXEMICRESPIRATORYFAILUREINVASIVE@",
        "@ACKZATRISKFORGASTRICULCERS@",
        "@ACKZATRISKFORSEIZURES@",
        "@ACKZRESTLESSNESSANDAGITATIONINTUBATED@",
    } <= set(result["selected_plan_tokens"])
    assert indexed(result)["gastric_ulcer_risk"]["selected"]
    assert "Fentanyl" not in result["text"] and "Pantoprazole" not in result["text"]
    assert "Clobazam" not in result["text"] and "MEDICATIONS" not in result["text"]
    assert all(label not in result["text"] for label in ("Drips:", "Scheduled:", "PRN:"))
    assert sheet == before


def test_attestation_uses_only_selected_tokens_and_supports_dot_format_and_custom_names():
    result = generate_note(
        sheet_with(order("Pantoprazole", "20 mg", section="FEN / GI")),
        note_type="attestation", phrase_style="dot", selected_ids=["tbi", "acute_hypoxemic_invasive"],
        phrase_overrides={"acute_hypoxemic_invasive": "MYINVASIVEPHRASE"},
    )
    assert result["text"].split("\nPLAN\n")[1] == ".ACKZTBI\n.MYINVASIVEPHRASE\n"
    assert result["selected_plan_tokens"] == [".ACKZTBI", ".MYINVASIVEPHRASE"]
    assert result["phrase_style"] == "dot"
    assert "@ACKZATRISKFORGASTRICULCERS@" not in result["text"]
    empty = generate_note(sheet_with(), note_type="attestation", selected_ids=[])
    assert empty["text"].endswith("\nPLAN\n")
    assert empty["selected_plan_tokens"] == []


@pytest.mark.parametrize("note_type", ["consult", "", None, "Attestation"])
def test_unknown_note_type_is_rejected(note_type):
    with pytest.raises(ValueError, match="progress note or attending attestation"):
        generate_note(sheet_with(), note_type=note_type)
