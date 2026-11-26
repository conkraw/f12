"""Build an optional Epic note draft from one handoff snapshot.

This module has no UI, network, persistence or background work. It copies
documented medication text into the supplied note structure and includes
suggested Plan references for clinician editing. It uses existing medication
placements and recorded findings without calculating new values, expanding
Epic content, writing an examination or changing the source diagnosis list.
"""
from __future__ import annotations

from copy import deepcopy
import re

from note_medications import build_note_medications
from note_medication_rules import medication_note_candidates
from note_findings import clinical_note_candidates
from ventilation import mode_rule
from ventilator_modes import spec


# Exact phrase names transcribed from the supplied screenshots, with the
# invasive and noninvasive respiratory names and later additions supplied by
# the user. Matching patterns identify stated diagnoses, not diagnostic criteria.
_RULES = (
    ("acute_hypoxemic_invasive", "Acute hypoxemic respiratory failure with invasive support", "ACKZACUTEHYPOXEMICRESPIRATORYFAILUREINVASIVE", ""),
    ("acute_hypoxemic_noninvasive", "Acute hypoxemic respiratory failure with noninvasive support", "ACKZACUTEHYPOXEMICRESPIRATORYFAILURENONINVASIVE", ""),
    ("acute_liver_failure", "Acute liver failure", "ACKZACUTELIVERFAILURE", r"acute (?:liver|hepatic) failure"),
    ("acute_pain", "Acute pain", "ACKZACUTEPAIN", r"acute pain"),
    ("acute_poisoning", "Acute poisoning", "ACKZACUTEPOISONING", r"acute poisoning|toxic ingestion|drug overdose"),
    ("acute_renal_failure", "Acute renal failure or acute kidney injury", "ACKZACUTERENALFAILURE", r"acute (?:renal failure|kidney (?:failure|injury))|AKI"),
    ("adenovirus", "Adenovirus", "ACKZADENOVIRUS", r"adenovirus|adenoviral infection"),
    ("adrenal_insufficiency", "Adrenal insufficiency", "ACKZADRENALINSUFFICIENCY", r"adrenal insufficiency|adrenal crisis"),
    ("anaphylactic_shock", "Anaphylactic shock", "ACKZANAPHYLACTICSHOCK", r"anaphylactic shock"),
    ("anemia", "Anemia", "ACKZANEMIA", r"an(?:ae|e)mia"),
    ("arrhythmia", "Arrhythmia", "ACKZARRHYTHMIA", r"arrhythmias?|dysrhythmias?"),
    ("central_line_occlusion_risk", "At risk for central venous catheter occlusion", "ACKZATRISKFORCENTRALVENOUSCATHETEROCCLUSION", r"(?:at )?risk for (?:central venous catheter|central line) occlusion"),
    ("dvt_risk", "At risk for deep vein thrombosis", "ACKZATRISKFORDEEPVEINTHROMBOSIS", r"(?:at )?risk for (?:deep vein thrombosis|DVT)|DVT prophylaxis|venous thromboembolism prophylaxis"),
    ("fungal_infection_risk", "At risk for fungal infection", "ACKZATRISKFORFUNGALINFECTION", r"(?:at )?risk for fungal infection|antifungal prophylaxis"),
    ("gastric_ulcer_risk", "At risk for gastric ulcers", "ACKZATRISKFORGASTRICULCERS", r"(?:at )?risk for (?:stress[- ]induced )?(?:gastric|stress) ulcers?|stress[- ]ulcer prophylaxis"),
    ("malnutrition_risk", "At risk for malnutrition", "ACKZATRISKFORMALNUTRITION", r"(?:at )?risk for malnutrition"),
    ("pneumocystis_risk", "At risk for Pneumocystis jirovecii", "ACKZATRISKFORPNEUMOCYSTISJIROVECII", r"(?:at )?risk for pneumocystis(?: jirovecii)?|(?:PJP|PCP|pneumocystis) prophylaxis"),
    ("pressure_injury_risk", "At risk for pressure injury", "ACKZATRISKFORPRESSUREINJURY", r"(?:at )?risk for pressure (?:injury|ulcers?)"),
    ("refeeding_risk", "At risk for refeeding syndrome", "ACKZATRISKFORREFEEDINGSYNDROME", r"(?:at )?risk for refeeding syndrome"),
    ("seizure_risk", "At risk for seizures", "ACKZATRISKFORSEIZURES", r"(?:at )?risk for seizures?|seizure prophylaxis"),
    ("varicella_risk", "At risk for varicella", "ACKZATRISKFORVARICELLA", r"(?:at )?risk for varicella|varicella exposure"),
    ("bacterial_meningitis", "Bacterial meningitis", "ACKZBACTERIALMENINGITIS", r"bacterial meningitis"),
    ("bacterial_pneumonia", "Bacterial pneumonia", "ACKZBACTERIALPNEUMONIA", r"bacterial pneumonia"),
    ("benzodiazepine_dependence", "Benzodiazepine dependence", "ACKZBENZODIAZEPINEDEPENDENCE", r"benzodiazepine dependence|benzodiazepine withdrawal"),
    ("cardiogenic_shock", "Cardiogenic shock", "ACKZCARDIOGENICSHOCK", r"cardiogenic shock"),
    ("central_diabetes_insipidus", "Central diabetes insipidus", "ACKZCENTRALDIABETESINSIPIDUS", r"central diabetes insipidus|central DI"),
    ("coagulopathy", "Coagulopathy", "ACKZCOAGULOPATHY", r"coagulopathy"),
    ("constipation", "Constipation", "ACKZCONSTIPATION", r"constipation"),
    ("covid19", "COVID-19", "ACKZCOVID19", r"COVID[- ]?19|SARS[- ]CoV[- ]2 infection"),
    ("croup", "Croup", "ACKZCROUP", r"croup|laryngotracheobronchitis"),
    ("deep_vein_thrombosis", "Deep vein thrombosis", "ACKZDEEPVEINTHROMBOSIS", r"deep vein thrombosis|deep venous thrombosis|DVT"),
    ("delirium", "Delirium", "ACKZDELIRIUM", r"delirium"),
    ("diabetic_ketoacidosis", "Diabetic ketoacidosis", "ACKZDIABETICKETOACIDOSIS", r"diabetic ketoacidosis|DKA"),
    ("disseminated_intravascular_coagulation", "Disseminated intravascular coagulation", "ACKZDISSEMINATEDINTRAVASCULARCOAGULATION", r"disseminated intravascular coagulation|DIC"),
    ("dysphagia", "Dysphagia", "ACKZDYSPHAGIA", r"dysphagia"),
    ("ecls_status", "ECLS status", "ACKZECLSSTATUS", r"ECLS status|ECMO status|on (?:VA[- ]?|VV[- ]?)?(?:ECLS|ECMO)|(?:ECLS|ECMO) dependence"),
    ("encephalopathy", "Encephalopathy", "ACKZENCEPHALOPATHY", r"encephalopathy"),
    ("exposure_keratopathy", "Exposure keratopathy", "ACKZEXPOSUREKERATOPATHY", r"exposure keratopathy"),
    ("febrile_neutropenia", "Febrile neutropenia", "ACKZFEBRILENEUTROPENIA", r"febrile neutropenia|neutropenic fever"),
    ("heart_failure", "Heart failure", "ACKZHEARTFAILURE", r"heart failure|cardiac failure"),
    ("hemorrhagic_shock", "Hemorrhagic shock", "ACKZHEMORRHAGICSHOCK", r"h(?:ae|e)morrhagic shock"),
    ("herpes_simplex_encephalitis", "Herpes simplex encephalitis", "ACKZHERPESSIMPLEXENCEPHALITIS", r"herpes simplex encephalitis|HSV encephalitis"),
    ("hyperkalemia", "Hyperkalemia", "ACKZHYPERKALEMIA", r"hyperkal(?:ae|e)mia"),
    ("hypernatremia", "Hypernatremia", "ACKZHYPERNATREMIA", r"hypernatr(?:ae|e)mia"),
    ("hypertension", "Hypertension", "ACKZHYPERTENSION", r"(?<!pulmonary )hypertension|systemic hypertension"),
    ("hypoalbuminemia", "Hypoalbuminemia", "ACKZHYPOALBUMINEMIA", r"hypoalbumin(?:ae|e)mia"),
    ("hypocalcemia", "Hypocalcemia", "ACKZHYPOCALCEMIA", r"hypocalc(?:ae|e)mia"),
    ("hypoglycemia", "Hypoglycemia", "ACKZHYPOGLYCEMIA", r"hypoglyc(?:ae|e)mia"),
    ("hypokalemia", "Hypokalemia", "ACKZHYPOKALEMIA", r"hypokal(?:ae|e)mia"),
    ("hypomagnesemia", "Hypomagnesemia", "ACKZHYPOMAGNESEMIA", r"hypomagnes(?:ae|e)mia"),
    ("hyponatremia", "Hyponatremia", "ACKZHYPONATREMIA", r"hyponatr(?:ae|e)mia"),
    ("hypophosphatemia", "Hypophosphatemia", "ACKZHYPOPHOSPHATEMIA", r"hypophosphat(?:ae|e)mia"),
    ("medication_hypotension", "Hypotension due to medication", "ACKZHYPOTENSIONDUETOMEDICATION", r"hypotension (?:due to|secondary to|from) (?:medication|sedation|sedatives|fentanyl|midazolam)|(?:medication|sedation)[- ](?:related|induced) hypotension"),
    ("hypovolemic_shock", "Hypovolemic shock", "ACKZHYPOVOLEMICSHOCK", r"hypovol(?:ae|e)mic shock"),
    ("influenza", "Influenza", "ACKZINFLUENZA", r"influenza(?: [AB])?"),
    ("insomnia", "Insomnia", "ACKZINSOMNIA", r"insomnia"),
    ("lymphopenia", "Lymphopenia", "ACKZLYMPHOPENIA", r"lymphopenia|lymphocytopenia"),
    ("metabolic_acidosis_respiratory_distress", "Metabolic acidosis due to respiratory distress", "ACKZMETABOLICACIDOSISRESPIRATORYDISTRESS", r"metabolic acidosis (?:due to|from|secondary to|in the setting of) (?:decreased perfusion (?:from|due to) )?respiratory distress"),
    ("metabolic_acidosis_shock", "Metabolic acidosis due to shock", "ACKZMETABOLICACIDOSISSHOCK", r"metabolic acidosis (?:due to|from|secondary to|in the setting of) (?:\w+ )?shock"),
    ("neurogenic_shock", "Neurogenic shock", "ACKZNEUROGENICSHOCK", r"neurogenic shock"),
    ("neutropenia", "Neutropenia", "ACKZNEUTROPENIA", r"(?<!febrile )neutropenia"),
    ("opioid_dependence", "Opioid dependence", "ACKZOPIOIDDEPENDENCE", r"opioid dependence|opioid withdrawal"),
    ("parainfluenza", "Parainfluenza", "ACKZPARAINFLUENZA", r"parainfluenza"),
    ("pards", "Pediatric acute respiratory distress syndrome", "ACKZPARDS", r"PARDS|ARDS|(?:pediatric )?acute respiratory distress syndrome"),
    ("pleural_effusion_empyema", "Pleural effusion or empyema", "ACKZPLEURALEFFUSIONEMPYEMA", r"pleural effusion|empyema"),
    ("pneumothorax", "Pneumothorax", "ACKZPNEUMOTHORAX", r"pneumothorax"),
    ("post_cardiac_arrest_syndrome", "Post cardiac arrest syndrome", "ACKZPOSTCARDIACARRESTSYNDROME", r"post[- ]cardiac[- ]arrest syndrome"),
    ("prolonged_qt", "Prolonged QT interval", "ACKZPROLONGEDQTINTERVAL", r"prolonged QTc?(?: interval)?|long QTc?(?: interval)?|QTc? prolongation"),
    ("pulmonary_hypertension", "Pulmonary hypertension", "ACKZPULMONARYHYPERTENSION", r"pulmonary hypertension"),
    ("agitation_intubated", "Restlessness and agitation while intubated", "ACKZRESTLESSNESSANDAGITATIONINTUBATED", ""),
    ("agitation_nonintubated", "Restlessness and agitation without intubation", "ACKZRESTLESSNESSANDAGITATIONNONINTUBATED", ""),
    ("rhabdomyolysis", "Rhabdomyolysis", "ACKZRHABDOMYOLYSIS", r"rhabdomyolysis"),
    ("rhinovirus", "Rhinovirus", "ACKZRHINOVIRUS", r"rhinovirus|rhinoviral infection"),
    ("rsv", "Respiratory syncytial virus", "ACKZRSV", r"respiratory syncytial virus|RSV"),
    ("sepsis", "Sepsis", "ACKZSEPSIS", r"sepsis"),
    ("septic_shock", "Septic shock", "ACKZSEPTICSHOCK", r"septic shock"),
    ("status_asthmaticus", "Status asthmaticus", "ACKZSTATUSASTHMATICUS", r"status asthmaticus"),
    ("status_epilepticus", "Status epilepticus", "ACKZSTATUSEPILEPTICUS", r"status epilepticus"),
    ("stress_hyperglycemia", "Stress hyperglycemia", "ACKZSTRESSHYPERGLYCEMIA", r"stress[- ](?:induced )?hyperglyc(?:ae|e)mia"),
    ("supraventricular_tachycardia", "Supraventricular tachycardia", "ACKZSUPRAVENTRICULARTACHYCARDIA", r"supraventricular tachycardia|SVT"),
    ("siadh", "Syndrome of inappropriate ADH secretion", "ACKZSYNDROMEOFINAPPROPRIATEADHSECRETION", r"syndrome of inappropriate (?:ADH|antidiuretic hormone) secretion|SIADH"),
    ("tbi", "Traumatic brain injury", "ACKZTBI", r"traumatic brain injury|TBI"),
    ("thrombocytopenia", "Thrombocytopenia", "ACKZTHROMBOCYTOPENIA", r"thrombocytopenia"),
    ("tracheobronchomalacia", "Tracheobronchomalacia", "ACKZTRACHEOBRONCHOMALACIA", r"tracheobronchomalacia|tracheomalacia|bronchomalacia"),
    ("tracheostomy", "Tracheostomy", "ACKZTRACHEOSTOMY", r"tracheostomy(?: dependence| status)?|trach dependence"),
    ("transaminitis", "Transaminitis", "ACKZTRANSAMINITIS", r"transaminitis"),
    ("upper_airway_edema", "Upper airway edema", "ACKZUPPERAIRWAYEDEMA", r"upper airway (?:oe|e)dema|laryngeal (?:oe|e)dema"),
    ("upper_gi_bleeding", "Upper gastrointestinal bleeding", "ACKZUPPERGIBLEEDING", r"upper (?:GI|gastrointestinal) bleed(?:ing)?"),
    ("viral_bronchiolitis", "Viral bronchiolitis", "ACKZVIRALBRONCHIOLITIS", r"viral bronchiolitis|(?:RSV|rhinovirus|adenovirus)[- ](?:associated )?bronchiolitis"),
)

# This order is shared by automatic suggestions, optional plan selections,
# plain text and Word. System names are internal metadata, never Plan headings.
# Respiratory syndromes stay with Respiratory. Specific viral diagnoses stay
# adjacent at the end of Infectious Disease, including a viral coinfection.
_PLAN_GROUPS = (
    ("Neurologic", (
        "agitation_intubated", "agitation_nonintubated", "acute_pain",
        "opioid_dependence", "benzodiazepine_dependence", "delirium", "insomnia",
        "seizure_risk", "status_epilepticus", "encephalopathy", "tbi",
        "acute_poisoning", "central_diabetes_insipidus", "siadh",
        "exposure_keratopathy", "pressure_injury_risk",
    )),
    ("Respiratory", (
        "acute_hypoxemic_invasive", "acute_hypoxemic_noninvasive", "pards",
        "status_asthmaticus", "croup", "tracheobronchomalacia", "tracheostomy",
        "upper_airway_edema", "pleural_effusion_empyema", "pneumothorax",
        "pulmonary_hypertension", "metabolic_acidosis_respiratory_distress",
        "viral_bronchiolitis",
    )),
    ("Cardiovascular", (
        "arrhythmia", "supraventricular_tachycardia", "prolonged_qt",
        "heart_failure", "post_cardiac_arrest_syndrome", "ecls_status",
        "hypertension", "medication_hypotension", "cardiogenic_shock",
        "hypovolemic_shock", "hemorrhagic_shock", "neurogenic_shock",
        "anaphylactic_shock", "adrenal_insufficiency", "metabolic_acidosis_shock",
    )),
    ("FEN / GI", (
        "malnutrition_risk", "hypoalbuminemia", "refeeding_risk", "dysphagia", "gastric_ulcer_risk",
        "constipation", "upper_gi_bleeding", "acute_renal_failure",
        "acute_liver_failure", "transaminitis", "rhabdomyolysis",
        "hyperkalemia", "hypokalemia", "hypernatremia", "hyponatremia",
        "hypocalcemia", "hypomagnesemia", "hypophosphatemia", "hypoglycemia",
        "stress_hyperglycemia", "diabetic_ketoacidosis",
    )),
    ("Hematology", (
        "anemia", "thrombocytopenia", "coagulopathy",
        "disseminated_intravascular_coagulation", "neutropenia", "lymphopenia",
        "deep_vein_thrombosis", "dvt_risk", "central_line_occlusion_risk",
    )),
    ("Infectious Disease", (
        "sepsis", "septic_shock", "bacterial_pneumonia", "bacterial_meningitis",
        "febrile_neutropenia", "fungal_infection_risk", "pneumocystis_risk",
        "varicella_risk", "herpes_simplex_encephalitis", "adenovirus", "covid19",
        "influenza", "parainfluenza", "rhinovirus", "rsv",
    )),
)
_PLAN_POSITION = {
    key: (system_index, diagnosis_index)
    for system_index, (_, keys) in enumerate(_PLAN_GROUPS)
    for diagnosis_index, key in enumerate(keys)
}
_PLAN_SYSTEM = {key: system for system, keys in _PLAN_GROUPS for key in keys}

PHRASE_CATALOG = tuple(
    {"id": key, "label": label, "phrase": phrase, "verified": bool(phrase),
     "system": _PLAN_SYSTEM[key]}
    for key, label, phrase, _ in sorted(_RULES, key=lambda row: _PLAN_POSITION[row[0]])
)

_PATTERNS = {
    key: re.compile(r"\b(?:" + pattern + r")\b", re.I)
    for key, _, _, pattern in _RULES if pattern
}
_RESP_FAILURE = re.compile(
    r"\b(?:acute(?:[- ]on[- ]chronic)? (?:hypoxemic|hypoxaemic|hypoxic) respiratory failure"
    r"|acute respiratory failure with hypoxia)\b", re.I
)
_AGITATION = re.compile(r"\b(?:restlessness(?: and agitation)?|agitation)\b", re.I)


def _phrase_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("A note phrase name must be text.")
    name = value.strip()
    if name.startswith("@") and name.endswith("@"):
        name = name[1:-1]
    elif name.startswith("."):
        name = name[1:]
    name = name.upper()
    if name and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,119}", name):
        raise ValueError("Use a phrase name with letters, digits or underscores only.")
    return name


def get_phrase_catalog(phrase_overrides: dict | None = None) -> list[dict]:
    """Return an independent catalog for optional diagnoses and exact-name edits."""
    catalog = deepcopy(list(PHRASE_CATALOG))
    if phrase_overrides is None:
        return catalog
    if not isinstance(phrase_overrides, dict):
        raise ValueError("The note phrase overrides must be a mapping.")
    known = {row["id"] for row in catalog}
    if set(phrase_overrides) - known:
        raise ValueError("A note phrase override has an unknown diagnosis identifier.")
    for row in catalog:
        if row["id"] in phrase_overrides:
            name = _phrase_name(phrase_overrides[row["id"]])
            # The user corrected this exact earlier name. Retain stored
            # settings compatibility while emitting the confirmed reference.
            if row["id"] == "arrhythmia" and name == "ACZKARRHYTHMIA":
                name = "ACKZARRHYTHMIA"
            if name != row["phrase"]:
                row["verified"] = False
            row["phrase"] = name
    return catalog


def _diagnosis_lines(sheet: dict, settings: dict | None) -> list[str]:
    fields = sheet.get("fields", {})
    keys = ["Diagnoses"]
    destination = (settings or {}).get("diagnoses_destination", "Diagnoses")
    if destination and destination not in keys:
        keys.append(destination)
    lines = []
    for key in keys:
        value = fields.get(key, "")
        if not isinstance(value, str):
            continue
        # Respect sentence boundaries and explicit contrast without treating a
        # decimal point or an abbreviation as a new diagnosis.
        for line in re.split(r"[\r\n]+|[;]|(?<=[.!])\s+(?=[A-Z])|\b(?:but|however)\b", value):
            line = re.sub(r"^\s*(?:[•*\-]|\d+[.)])\s*", "", line).strip()
            if line and line not in lines:
                lines.append(line)
    return lines


def _assertion(line: str, match: re.Match) -> str:
    """Recognize common scoped qualifiers, retaining uncertainty for review."""
    before, after = line[:match.start()].casefold(), line[match.end():].casefold()
    after = re.sub(r"^\s*[,:(-]\s*", "", after)
    # A new current statement can follow a history statement on the same line.
    before = re.split(r"\b(?:now|currently|new onset)\b", before)[-1]
    if re.search(r"\b(?:family history|maternal history|paternal history)\b", before):
        return "history"
    if (re.search(r"\b(?:no|without|negative for|absence of|denies|denied|ruled out|not consistent with)\b", before)
            or re.match(r"\s*(?:(?:is|was|has been)\s+)?(?:ruled out|excluded|absent|not present)\b", after)):
        return "negative"
    if (re.search(r"\b(?:history(?: of)?|hx(?: of)?|previous(?:ly)?|prior|resolved|status post|s/p)\b", before)
            or re.match(r"\s*(?:(?:is|was|has)\s+)?(?:resolved|historical|remote|in the past)\b", after)):
        return "history"
    if re.search(r"\b(?:at )?risk (?:for|of)\b", before) or re.match(r"\s*prophylaxis\b", after):
        return "risk"
    if (re.search(r"\b(?:possible|suspected|concern for|rule[- ]out|r/o|evaluate for|question of|cannot exclude|may have|differential)\b", before)
            or re.match(r"\s*(?:\?|(?:unlikely|not confirmed|unconfirmed|not ruled out|cannot be ruled out|possible|suspected)\b)", after)
            or "?" in before
            or "?" in after[:3]):
        return "uncertain"
    return "positive"


def _current_support(sheet: dict) -> dict:
    """Use only the primary snapshot and current included airway devices."""
    current_devices = []
    snapshot = sheet.get("devices")
    if isinstance(snapshot, dict):
        for row in snapshot.get("rows", []):
            if isinstance(row, dict) and row.get("include", True) and not row.get("removed", False):
                status = str(row.get("status", ""))
                if not re.search(r"\b(?:removed|discontinued|extubated|decannulated)\b", status, re.I):
                    current_devices.append(row.get("kind", ""))
    invasive_airway = "ETT" in current_devices or "Trach" in current_devices
    vent = sheet.get("ventilation")
    mode = ""
    uncertain = False
    if isinstance(vent, dict):
        history = vent.get("mode_history") or {}
        uncertain = history.get("latest_confirmed") is False
        if not uncertain:
            mode = str(vent.get("mode", "")).strip()
    current_niv = []
    for row in sheet.get("noninvasive") or []:
        if isinstance(row, dict) and row.get("device"):
            current_niv.append(str(row["device"]))
    known = spec(mode) if mode else None
    mode_niv = bool(mode and ((known and known[2]) or mode_rule(mode) == "excluded"))
    # A current primary included mode is a support candidate. Its name alone
    # does not establish the indication for ventilation or acute hypoxemia.
    mode_invasive = bool(mode and mode_rule(mode) == "included")
    conflict = bool((mode_niv or current_niv) and (invasive_airway or mode_invasive))
    if conflict:
        kind = "unclear"
    elif mode_niv or current_niv:
        kind = "noninvasive"
    elif mode_invasive or invasive_airway:
        kind = "invasive"
    else:
        kind = "unknown"
    return {
        "kind": kind, "mode": mode, "noninvasive": current_niv,
        "endotracheal_tube": "ETT" in current_devices,
        "tracheostomy": "Trach" in current_devices,
        "uncertain": uncertain, "conflict": conflict,
    }


def _route_for_line(line: str, support: dict) -> str:
    if re.search(r"\b(?:non[- ]?invasive|non[- ]?intubated|not intubated|without intubation|NIV|NIPPV|BiPAP|HFNC)\b", line, re.I):
        return "noninvasive"
    if re.search(r"\b(?:invasive ventilation|invasive support|intubated|endotracheal)\b", line, re.I):
        return "invasive"
    return support["kind"]


def _suggestions(sheet: dict, medications: dict, catalog: list[dict], settings: dict | None) -> tuple[list[dict], list[str]]:
    by_id = {row["id"]: row for row in catalog}
    found: dict[str, dict] = {}
    assertions: dict[str, set[str]] = {}
    warnings: list[str] = []
    support = _current_support(sheet)

    def record(key: str, state: str, reason: str, *, include: bool = True) -> None:
        assertions.setdefault(key, set()).add(state)
        if state in ("positive", "uncertain"):
            add(key, reason, selected=include)

    def add(key: str, reason: str, selected: bool = True) -> None:
        states = assertions.get(key, set())
        if states and states <= {"negative", "history", "risk"}:
            return
        if key not in found:
            found[key] = dict(by_id[key], reasons=[], selected=False)
        item = found[key]
        if reason not in item["reasons"]:
            item["reasons"].append(reason)
        item["selected"] = bool((item["selected"] or selected) and item["phrase"])

    for line in _diagnosis_lines(sheet, settings):
        for key, pattern in _PATTERNS.items():
            for match in pattern.finditer(line):
                state = _assertion(line, match)
                if key == "deep_vein_thrombosis" and re.match(r"\s+prophylaxis\b", line[match.end():], re.I):
                    continue
                reason = ("Uncertain diagnosis in handoff: " if state == "uncertain" else "Documented diagnosis: ") + line
                record(key, state, reason)
        for pattern, family in ((_RESP_FAILURE, "respiratory"), (_AGITATION, "agitation")):
            match = pattern.search(line)
            if not match:
                continue
            state = _assertion(line, match)
            route = _route_for_line(line, support)
            if family == "respiratory":
                # Current support decides which confirmed respiratory phrase
                # fits a documented diagnosis. Historical mode entries and an
                # older support label in a diagnosis must not add both plans.
                # Support-based suggestions are included in this editable
                # draft, while conflicting routes remain unresolved.
                if support["kind"] in ("invasive", "noninvasive"):
                    route = support["kind"]
                elif support["conflict"]:
                    route = "unclear"
            keys = (("acute_hypoxemic_invasive", "acute_hypoxemic_noninvasive")
                    if family == "respiratory" else ("agitation_intubated", "agitation_nonintubated"))
            if route in ("invasive", "noninvasive"):
                key = keys[0 if route == "invasive" else 1]
                # An invasive ventilator mode or tracheostomy does not prove
                # endotracheal intubation for the wording of the sedation plan.
                if (family == "agitation" and route == "invasive" and state == "positive"
                        and not support["endotracheal_tube"]
                        and not re.search(r"\b(?:intubated|endotracheal)\b", line, re.I)):
                    state = "uncertain"
                record(key, state, ("Uncertain diagnosis in handoff: " if state == "uncertain" else "Documented diagnosis: ") + line)
            else:
                for key in keys:
                    record(key, "uncertain" if state == "positive" else state,
                           "The handoff lists this diagnosis without one clear current support route.", include=False)

    if support["kind"] in ("invasive", "noninvasive"):
        key = "acute_hypoxemic_" + support["kind"]
        description = support["mode"] or ", ".join(support["noninvasive"]) or "a current invasive airway"
        add(key, "Suggested from current handoff support: " + description + ".")
    if support["uncertain"]:
        warnings.append("The latest ventilator mode is unconfirmed. Historical modes were not used to select note diagnoses.")
    if support["conflict"]:
        warnings.append("Invasive and noninvasive support conflict. Choose the applicable respiratory phrase under Edit included plans if needed.")
    if support["tracheostomy"]:
        add("tracheostomy", "A current included tracheostomy device is documented.")
    ecls = sheet.get("ecls")
    if isinstance(ecls, dict) and ecls.get("mode") in ("VA", "VV"):
        add("ecls_status", "Current handoff ECLS settings document " + ecls["mode"] + " support.", selected=True)

    for candidate in medication_note_candidates(medications, support=support, catalog=catalog):
        if candidate["id"] in by_id:
            add(candidate["id"], candidate["reason"])
    findings = clinical_note_candidates(sheet, settings=settings, medications=medications)
    for candidate in findings["candidates"]:
        if candidate["id"] in by_id:
            add(candidate["id"], candidate["reason"])
    warnings.extend(findings.get("warnings", []))

    # Explicit negative and historical statements are still respected.
    # Other suggestions are included for editing, without a confirmation step.
    for key, item in found.items():
        states = assertions.get(key, set())
        if states & {"negative", "history"}:
            item["selected"] = False
            item["reasons"].append("The diagnosis text also contains a negative or historical qualifier. Resolve this before selecting it.")
    return [found[row["id"]] for row in catalog if row["id"] in found], warnings


_TOP = """PEDIATRIC CRITICAL CARE MEDICINE PROGRESS NOTE

PATIENT INFORMATION
Patient Name: @NAME@
Medical Record Number: @MRN@
Date of Service: @TODAYDATE@
Hospital Day #: @CURHOSPDAY@
Pediatric Intensive Care Unit Day #: @ICULOS@
Code Status: @CODE@

DIAGNOSES
@DIAGX@

SUBJECTIVE

INTERVAL EVENTS
{overnightevents:45212}

REVIEW OF SYSTEMS
{ACKROS:45449}

OBJECTIVE
"""

_SYSTEM_ANCHORS = (
    ("Neurologic", "{CKNEUROSMARTLIST:45213}"),
    ("Respiratory", "{CKRESPLIST:45220}"),
    ("Cardiovascular", "{CKCVLIST:45328}"),
    ("FEN / GI", "{ACKFENGI:45365}"),
)
_SECTION_ALIASES = {"Neurology": "Neurologic", "FEN/GI": "FEN / GI", "Infectious Diseases": "Infectious Disease"}


# Paragraph text from the user's ATTENDING ATTESTATION.docx in source order.
# Medication information is intentionally absent from this template. Preserve
# the user's SmartLists and placeholders rather than inventing exam findings.
_ATTESTATION_TEMPLATE = """ATTENDING ATTESTATION
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
"""


def _selected_plan_tokens(suggestions: list[dict], phrase_style: str) -> list[str]:
    phrases = []
    for row in suggestions:
        if row["selected"] and row["phrase"]:
            token = ("@" + row["phrase"] + "@") if phrase_style == "at" else ("." + row["phrase"])
            if token not in phrases:
                phrases.append(token)
    return phrases


def _medication_lines(groups: dict | None) -> str:
    lines = []
    for group in ("Drips", "Scheduled", "PRN"):
        values = (groups or {}).get(group) or []
        if values:
            lines.append(group + ":")
            lines.extend(str(value) for value in values)
            lines.append("")
    return "\n".join(lines).rstrip()


def _render_note(medications: dict, suggestions: list[dict], phrase_style: str, note_type: str = "progress") -> str:
    phrases = _selected_plan_tokens(suggestions, phrase_style)
    if note_type == "attestation":
        return _ATTESTATION_TEMPLATE + ("\n".join(phrases) + "\n" if phrases else "")
    sections: dict[str, dict] = {}
    for original, groups in medications.get("sections", {}).items():
        name = _SECTION_ALIASES.get(original, original)
        destination = sections.setdefault(name, {key: [] for key in ("Drips", "Scheduled", "PRN")})
        for group in destination:
            destination[group].extend(groups.get(group) or [])
    blocks = [_TOP.rstrip()]
    for section, token in _SYSTEM_ANCHORS:
        block = token
        meds = _medication_lines(sections.get(section))
        if meds:
            block += "\n\n" + meds
        blocks.append(block)
    hematology = "HEMATOLOGY\nMEDICATIONS"
    meds = _medication_lines(sections.get("Hematology"))
    if meds:
        hematology += "\n" + meds
    hematology += "\nPERTINENT LABORATORY DATA\n{ACKHLABS:45360}"
    blocks.append(hematology)
    infectious = "INFECTIOUS DISEASES\nVITAL SIGNS\nTemperature: @FLOWSTAT(6:24)@\nMEDICATIONS"
    meds = _medication_lines(sections.get("Infectious Disease"))
    if meds:
        infectious += "\n" + meds
    infectious += """
CULTURE DATA
@CULTUREHX@
RESPIRATORY VIRAL PANEL DATA
@RESUFAST(ADENOVIRDNA:,HUMRHINENRNA:,FLUAVIRUSRNA:,PARAFLU1RNA:,PARAFLU2RNA:,PARAFLU3RNA:,PARAFLU4RNA:,RESPSYNVRNA:,SARSRNA:)@
PERTINENT LABORATORY DATA
{ACKIDLABS:45351}
MRSA SCREEN
@RESUFAST(MRSADNA:1,MRSANPADM:1)@"""
    blocks.append(infectious)
    standard_sections = {name for name, _ in _SYSTEM_ANCHORS} | {"Hematology", "Infectious Disease"}
    extras = []
    for section, groups in sections.items():
        meds = _medication_lines(groups)
        if section not in standard_sections and meds:
            extras.append(str(section) + "\n" + meds)
    if extras:
        blocks.append("ADDITIONAL MEDICATIONS\n\n" + "\n\n".join(extras))
    blocks.append("ASSESSMENT\nThe patient is a @age@ @sex@ who presented to the Pediatric Intensive Care Unit on @ADMITDT@ with ***.\n{CKCLININDICATIONS:45218}")
    blocks.append("PLAN" + ("\n" + "\n".join(phrases) if phrases else ""))
    return "\n\n".join(blocks).rstrip() + "\n"


def generate_note(
    sheet: dict, *, phrase_style: str = "at", phrase_overrides: dict | None = None,
    selected_ids=None, settings: dict | None = None, note_type: str = "progress",
) -> dict:
    """Generate a reviewable note only when explicitly called by the UI.

    ``selected_ids=None`` includes the suggested plans automatically. An explicit collection
    replaces those defaults and can add any catalog entry. Missing phrase names
    remain omitted, even when selected. ``note_type`` chooses the progress or
    attestation template. Attestation text never contains medication lists,
    although medications still provide reviewable plan suggestions internally.
    Inputs are never mutated.
    """
    if not isinstance(sheet, dict):
        raise ValueError("Choose a handoff before generating a note.")
    if phrase_style not in ("at", "dot"):
        raise ValueError("Choose at-sign or dot phrase formatting.")
    if note_type not in ("progress", "attestation"):
        raise ValueError("Choose a progress note or attending attestation.")
    catalog = get_phrase_catalog(phrase_overrides)
    medications = build_note_medications(sheet)
    suggestions, warnings = _suggestions(sheet, medications, catalog, settings)
    warnings = list(dict.fromkeys(list(medications.get("warnings") or []) + warnings))
    if selected_ids is not None:
        if isinstance(selected_ids, str):
            raise ValueError("Selected note diagnoses must be a collection of identifiers.")
        chosen = set(selected_ids)
        known = {row["id"] for row in catalog}
        if chosen - known:
            raise ValueError("A selected note diagnosis has an unknown identifier.")
        present = {row["id"]: row for row in suggestions}
        for row in catalog:
            if row["id"] in chosen and row["id"] not in present:
                present[row["id"]] = dict(row, reasons=["Added during note review."], selected=False)
        suggestions = [present[row["id"]] for row in catalog if row["id"] in present]
        for row in suggestions:
            row["selected"] = bool(row["id"] in chosen and row["phrase"])
        if any(row["id"] in chosen and not row["phrase"] for row in suggestions):
            warning = "A selected diagnosis has no configured phrase name and was omitted from the plan."
            if warning not in warnings:
                warnings.append(warning)
    return {
        "text": _render_note(medications, suggestions, phrase_style, note_type),
        "suggestions": suggestions, "warnings": warnings, "medications": medications,
        "note_type": note_type, "phrase_style": phrase_style,
        "selected_plan_tokens": _selected_plan_tokens(suggestions, phrase_style),
    }
