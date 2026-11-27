"""Synthetic neurologic section selection, source precedence, and exclusions."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from devices import parse_devices
from models import new_sheet
from note_medications import build_note_medications
from note_neuro import NEURO_TEMPLATE_FILES, NEURO_TEMPLATE_NAMES, select_neuro_variant
from observations import parse_neuro
from vitals import parse_vitals


def handoff(diagnoses="", neuro="", respiratory="", cardiovascular=""):
    result = new_sheet("P4102")
    result["fields"].update({"Diagnoses":diagnoses,"Neurologic":neuro,
                             "Respiratory":respiratory,"Cardiovascular":cardiovascular})
    return result


def with_device(sheet,kind="ETT",section="devices",**changes):
    row = {"kind":kind,"include":True,"removed":False,"label":kind,"status":""}
    row.update(changes)
    sheet[section] = {"rows":[row]}
    return sheet


def with_mode(sheet,mode="PRVC",**changes):
    sheet["ventilation"] = {"mode":mode,"values":{}}
    sheet.update(changes)
    return sheet


def with_niv(sheet):
    sheet["noninvasive"] = [{"device":"HFNC","values":{"Flow":"10"},
                              "flow_inferred":False,"pressure_inferred":False}]
    return sheet


def select(sheet,**kwargs):
    return select_neuro_variant(sheet,**kwargs)["variant"]


@pytest.mark.parametrize("diagnosis,variant", [
    ("Traumatic brain injury","tbi"), ("TBI","tbi"),
    ("Status epilepticus","status_epilepticus"),
    ("Refractory nonconvulsive status epilepticus","status_epilepticus"),
    ("NCSE","status_epilepticus"), ("EVD in place","icp_monitoring"),
    ("Current ICP monitoring","icp_monitoring"),
    ("Postoperative cardiac patient","ct_patient"),
    ("POD 1 after cardiac surgery","ct_patient"),
    ("Currently intubated","intubated"), ("Extubated today","extubated"),
    ("","none"),
])
def test_documented_current_findings_choose_the_corresponding_template(diagnosis,variant):
    result = select_neuro_variant(handoff(diagnosis))
    assert result["variant"] == variant
    assert result["phrase"] == NEURO_TEMPLATE_NAMES[variant]
    assert result["label"] and result["reason"]
    assert result["warning"] == ""


@pytest.mark.parametrize("diagnosis", [
    "No TBI", "No current TBI", "Possible current status epilepticus", "Suspected TBI",
    "Rule out TBI", "TBI: none", "TBI is not present", "TBI ruled out", "TBI resolved",
    "TBI sequelae", "PMH: TBI", "PMH:\nTBI", "h/o traumatic brain injury",
    "History of status epilepticus", "Family history of status epilepticus",
    "Prior TBI", "Remote TBI", "At risk for status epilepticus",
    "Status epilepticus prophylaxis", "TBI screening", "TBI?", "Status epilepticus unconfirmed",
    "EVD placement planned for tomorrow", "EVD to be placed tomorrow", "EVD requested",
    "ICP monitoring will be started tomorrow", "Consider EVD placement", "EVD removed",
    "ICP monitoring discontinued", "Extubation planned tomorrow", "Not extubated",
    "Intubated tomorrow", "Previously extubated", "No current status epilepticus",
])
def test_negated_historical_uncertain_and_requested_findings_do_not_select_specific_sections(diagnosis):
    assert select(handoff(diagnosis)) == "none"


def test_current_statement_after_history_can_establish_new_active_condition():
    assert select(handoff("History of TBI, now TBI after a new injury")) == "tbi"
    assert select(handoff("PMH:\nTBI\nCurrent assessment:\nStatus epilepticus")) == "status_epilepticus"


def test_conflicting_active_and_negative_diagnoses_use_basic_section_and_warning():
    result = select_neuro_variant(handoff("TBI",neuro="No current TBI"))
    assert result["variant"] == "none"
    assert result["warning"]


def test_configured_diagnosis_destination_is_allowed_but_unrelated_goals_are_not():
    sheet = handoff()
    sheet["fields"]["Goals / Follow-up"] = "TBI"
    assert select(sheet) == "none"
    assert select(sheet,settings={"diagnoses_destination":"Goals / Follow-up"}) == "tbi"
    sheet["import_warnings"]["a"] = [{"action":"previous_retained"}]
    assert select(sheet,settings={"diagnoses_destination":"Goals / Follow-up"}) == "none"


@pytest.mark.parametrize("section", ["devices","neuro_devices"])
@pytest.mark.parametrize("kind,variant", [("ETT","intubated"),("EVD","icp_monitoring"),("ICP monitor","icp_monitoring")])
def test_current_included_device_facts_work_from_both_inventories(section,kind,variant):
    assert select(with_device(handoff(),kind,section)) == variant


@pytest.mark.parametrize("kind", ["ETT","EVD","ICP monitor"])
@pytest.mark.parametrize("changes", [
    {"include":False},{"removed":True},{"status":"Removed"},{"status":"Not currently present"},
    {"status":"No longer present"},{"status":"Not currently in place"},
    {"status":"Planned"},{"status":"To be placed tomorrow"},
])
def test_hidden_removed_and_planned_devices_never_supply_current_presence(kind,changes):
    assert select(with_device(handoff(),kind,**changes)) == "none"


def test_evd_clamping_preserves_present_device_and_lumbar_drain_is_not_icp_monitor():
    assert select(with_device(handoff(),"EVD",status="Clamped")) == "icp_monitoring"
    assert select(with_device(handoff(),"EVD",status="UNK")) == "icp_monitoring"
    assert select(with_device(handoff(),"ETT",status="Not removed")) == "intubated"
    sheet = with_device(handoff(),"Drain",label="Intracranial Pressure/Ventriculostomy Lumbar Drain")
    assert select(sheet) == "none"


@pytest.mark.parametrize("section,warning,action", [
    ("devices","u","devices_hidden"),("neuro_devices","v","neuro_devices_hidden"),
])
def test_failed_import_hidden_device_snapshot_is_not_resurrected(section,warning,action):
    sheet = with_device(handoff(),"EVD",section)
    sheet["import_warnings"][warning] = [{"action":action}]
    assert select(sheet) == "none"


def test_real_parsed_evd_selects_monitoring_without_dose_or_pressure_inference():
    parsed = parse_devices("Intracranial Pressure/Ventriculostomy Ventricular drainage catheter with ICP microsensor-Drain Status: Clamped","v")
    assert not parsed.error
    sheet = handoff()
    sheet["neuro_devices"] = parsed.data
    assert select(sheet) == "icp_monitoring"


@pytest.mark.parametrize("source", [
    "ICP Range: 1-22\nLast ICP: 10", "ICP Mean (mmHg): 5 mmHg", "CPP: 65 mmHg",
    "Last ICP: 0", "Last CPP: 65 mmHg",
])
def test_real_recorded_m_values_support_monitoring_without_device_row(source):
    parsed = parse_neuro(source,"m")
    assert not parsed.error
    sheet = handoff()
    sheet["neuro_vitals"]["m"] = parsed.rows
    assert select(sheet) == "icp_monitoring"


@pytest.mark.parametrize("change", ["hidden","failed","removed_device","removed_prose","stopped_prose","unknown"])
def test_hidden_failed_or_ceased_m_monitoring_cannot_select_icp(change):
    sheet = handoff()
    sheet["neuro_vitals"]["m"] = parse_neuro("Last ICP: 10","m").rows
    if change == "hidden":
        sheet["neuro_vitals"]["m"][0]["include"] = False
    elif change == "failed":
        sheet["import_warnings"]["m"] = [{"action":"previous_retained"}]
    elif change == "removed_device":
        with_device(sheet,"EVD",removed=True)
    elif change == "removed_prose":
        sheet["fields"]["Neurologic"] = "EVD removed"
    elif change == "stopped_prose":
        sheet["fields"]["Neurologic"] = "ICP monitoring discontinued"
    else:
        sheet["neuro_vitals"]["m"][0]["value"] = "UNK"
    assert select(sheet) == "none"


@pytest.mark.parametrize("mode", ["PRVC","PC-CMV","HFOV","Volume Control - Continuous Mandatory Ventilation"])
def test_known_current_primary_invasive_modes_select_ventilated_section(mode):
    assert select(with_mode(handoff(),mode)) == "intubated"


@pytest.mark.parametrize("mode", ["PS-CPAP","PS - CPAP","PS/CPAP","PS CPAP","CPAP Trial Data","CPAP NIV","BiPAP","Unknown current mode"])
def test_trials_noninvasive_or_unknown_modes_do_not_prove_intubation(mode):
    assert select(with_mode(handoff(),mode)) == "none"


def test_current_tube_corroborates_trial_but_history_never_does():
    assert select(with_device(with_mode(handoff(),"PS-CPAP"))) == "intubated"
    sheet = with_mode(handoff(),"Unknown current mode")
    sheet["ventilation"]["mode_history"] = {"latest_confirmed":True,
        "other_modes":[{"mode":"PRVC","include":True},{"mode":"PS-CPAP","include":True}]}
    assert select(sheet) == "none"
    sheet["ventilation"]["mode"] = "PRVC"
    sheet["ventilation"]["mode_history"]["latest_confirmed"] = False
    assert select(sheet) == "none"


@pytest.mark.parametrize("change", ["ventilator_off","failed_import","removed_ett"])
def test_off_failed_or_removed_airway_does_not_revive_retained_invasive_mode(change):
    sheet = with_mode(handoff())
    if change == "ventilator_off":
        sheet["sbs_vent_mode"] = ""
    elif change == "failed_import":
        sheet["import_warnings"]["cd"] = [{"action":"previous_retained"}]
    else:
        with_device(sheet,removed=True)
    assert select(sheet) == "none"


def test_current_trach_requires_ventilation_and_reintubation_overrides_removed_airway_history():
    sheet = with_device(handoff(),"Trach")
    assert select(sheet) == "none"
    assert select(with_mode(sheet)) == "intubated"
    sheet["devices"]["rows"].append({"kind":"ETT","include":True,"removed":True,"status":""})
    assert select(sheet) == "intubated"


def test_nonempty_source_mode_cache_alone_never_implies_intubation():
    sheet = with_niv(handoff())
    sheet["sbs_vent_mode"] = "PS-CPAP"
    assert select(sheet) == "none"


def test_conflicting_current_invasive_and_niv_support_uses_basic_section():
    result = select_neuro_variant(with_niv(with_mode(handoff())))
    assert result["variant"] == "none"
    assert result["warning"]


@pytest.mark.parametrize("source", ["NIRS: 69%","Last NIRS: rSO2 Cerebral %: 69 %","NIRS Range: rSO2 Cerebral % Avg: 65 Min: 59 Max: 73"])
def test_real_current_cerebral_nirs_data_selects_ct_section(source):
    parsed = parse_vitals(source)
    assert not parsed.error
    sheet = handoff()
    sheet["vitals"] = parsed.rows
    assert select(sheet) == "ct_patient"
    sheet["vitals"][0]["include"] = False
    assert select(sheet) == "none"
    sheet["vitals"][0]["include"] = True
    sheet["import_warnings"]["e"] = [{"action":"previous_retained"}]
    assert select(sheet) == "none"


@pytest.mark.parametrize("text", [
    "CT scan normal", "Head CT requested", "Cardiac patient admitted for bronchiolitis",
    "Congenital heart disease", "History of cardiac surgery", "Cardiac surgery planned tomorrow",
    "Cardiac surgery consult planned today", "rSO2 somatic 70%", "Possible cerebral oximetry monitoring",
])
def test_ct_scan_chd_historical_or_requested_cardiac_context_does_not_select_ct(text):
    assert select(handoff(text)) == "none"


@pytest.mark.parametrize("kind", ["y","l"])
def test_nonintubated_monitoring_uses_extubated_section_with_zero_scores_preserved(kind):
    sheet = with_niv(handoff())
    sheet["neuro_vitals"][kind] = [{"label":"CAPD" if kind=="y" else "WAT-1","value":"0","include":True,"section":"Neurologic"}]
    assert select(sheet) == "extubated"
    sheet["neuro_vitals"][kind][0]["include"] = False
    assert select(sheet) == "none"
    sheet["neuro_vitals"][kind][0]["include"] = True
    sheet["import_warnings"][kind] = [{"action":"previous_retained"}]
    assert select(sheet) == "none"


def test_not_currently_intubated_is_not_positive_intubation_and_does_not_create_a_conflict():
    result = select_neuro_variant(handoff(neuro="CAPD: 0",respiratory="Not currently intubated"))
    assert result["variant"] == "extubated"
    assert not result["warning"]


def test_score_or_niv_alone_does_not_assert_extubation():
    assert select(handoff(neuro="WAT-1: 0")) == "none"
    assert select(with_niv(handoff())) == "none"
    assert select(with_device(handoff(),removed=True)) == "none"


@pytest.mark.parametrize("name", ["Levetiracetam","Clobazam","Milrinone","Furosemide"])
def test_medication_alone_does_not_create_specific_neurologic_condition(name):
    medications = {"entries":[{"active":True,"source_name":name,"section":"Neurologic","group":"Scheduled"}]}
    assert select(handoff(),medications=medications) == "none"


def test_nonintubated_active_sedation_medications_can_supply_monitoring_context():
    sheet = with_niv(handoff())
    medications = {"entries":[{"active":True,"source_name":"Dexmedetomidine","group":"Drips"}]}
    assert select(sheet,medications=medications) == "extubated"
    medications["entries"][0]["active"] = False
    assert select(sheet,medications=medications) == "none"


def test_priority_and_source_immutability_for_overlapping_current_findings():
    sheet = with_device(with_mode(handoff("TBI\nStatus epilepticus")),"EVD",section="neuro_devices")
    sheet["vitals"] = parse_vitals("NIRS: 69%").rows
    before = deepcopy(sheet)
    meds = build_note_medications(sheet)
    before_meds = deepcopy(meds)
    result = select_neuro_variant(sheet,medications=meds)
    assert result["variant"] == "tbi"
    assert json.loads(json.dumps(result)) == result
    assert sheet == before and meds == before_meds
    sheet["fields"]["Diagnoses"] = "Status epilepticus"
    assert select(sheet) == "icp_monitoring"
    sheet["neuro_devices"] = None
    assert select(sheet) == "status_epilepticus"
    sheet["fields"]["Diagnoses"] = ""
    assert select(sheet) == "ct_patient"
    sheet["vitals"] = []
    assert select(sheet) == "intubated"


def test_all_results_have_metadata_and_all_assets_use_exact_agreed_paths():
    expected = {"ct_patient":"ACKNCTPATIENT","none":"ACKNNONE","icp_monitoring":"ACKNICPMONITORING",
                "intubated":"ACKNINTUBATED","tbi":"ACKNTBI","status_epilepticus":"ACKNSTATUSEPI","extubated":"ACKNEXTUBATED"}
    assert NEURO_TEMPLATE_NAMES == expected
    assert NEURO_TEMPLATE_FILES == {key:Path(__file__).parents[1]/"templates"/("neuro_"+key+".docx") for key in expected}
    result = select_neuro_variant({})
    assert set(result) == {"variant","phrase","label","reason","warning"}
    assert result["variant"] == "none" and not result["warning"]
