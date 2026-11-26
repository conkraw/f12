"""Medication indications for review against the existing Epic phrase catalog.

Saved category snapshots are internal evidence only. They do not change the
flat medication list or its headings. Every result is a candidate, and the
caller owns selection, diagnosis qualifiers, and clinical review. No doses,
laboratory thresholds, or treatment recommendations are calculated here.
"""
from __future__ import annotations

import re

from medication_groups import automatic_system_group


_SEDATION = "_sedation"
_WITHDRAWAL = "_withdrawal"
_BUILTIN_RULES = {
    "group:antibiotic": ("sepsis",),
    "group:antifungal": ("fungal_infection_risk",),
    "group:antiepileptic": ("seizure_risk",),
    "group:antiepileptic_adjunct": ("seizure_risk",),
    "group:sedative_prn": (_SEDATION,),
    "group:eye_care_lubricants": ("exposure_keratopathy",),
    "group:neurorecovery_neurostimulant": ("encephalopathy",),
    "group:neurorecovery_supplement": ("encephalopathy",),
    "group:epidural": ("acute_pain",),
    "group:nsaids": ("acute_pain",),
    "group:iron_deficiency_anemia": ("anemia",),
    "group:sickle_cell_anemia": ("anemia",),
    "group:dvt": ("dvt_risk",),
    "group:gcsf": ("neutropenia",),
    "group:adh_analog": ("central_diabetes_insipidus",),
    "group:pulmonary_hypertension": ("pulmonary_hypertension",),
    "group:antiarrhythmic": ("arrhythmia",),
    "group:antihypertensive": ("hypertension",),
    "group:adrenocortical": ("adrenal_insufficiency",),
    "group:insomnia": ("insomnia",),
    "group:airway_tone": ("tracheobronchomalacia",),
    "gi:prophylaxis": ("gastric_ulcer_risk",),
    "gi:bowel": ("constipation",),
    "gi:hypoglycemia": ("hypoglycemia",),
    "gi:hypocalcemia": ("hypocalcemia",),
    "gi:hyponatremia": ("hyponatremia",),
    "gi:zinc_deficiency": (),
    # These indications have no single corresponding diagnosis in the supplied
    # catalog. Do not discard their mapping and relabel the drug by its name.
    "gi:prokinetic": (), "gi:diuretic": (), "gi:antiemetic": (),
    "gi:probiotic": (), "gi:tpn": (), "gi:iv_fluids": (),
    "group:fever": (), "group:chemotherapy": (), "group:antiplatelet": (),
    "group:antispasmodic": (),
    "group:neuromodulation": (), "group:airway_clearance": (),
    "group:antisialorrhea": (),
    "group:leukotriene_receptor_antagonist": (),
}

# Specific indications are checked before broad class names or parent groups.
# These aliases supplement exact catalog labels, identifiers, and phrase names.
_INDICATION_ALIASES = (
    (r"\b(?:hepatic|toxic|metabolic|hypoxic|ischemic|traumatic) encephalopathy\b", ("encephalopathy",)),
    (r"\b(?:opioid|opiate)s?\b.*\b(?:dependence|withdrawal|wean|taper)\b|\b(?:withdrawal|wean|taper)\b.*\b(?:opioid|opiate)s?\b", ("opioid_dependence",)),
    (r"\b(?:benzodiazepines?|benzos?)\b.*\b(?:dependence|withdrawal|wean|taper)\b|\b(?:withdrawal|wean|taper)\b.*\b(?:benzodiazepines?|benzos?)\b", ("benzodiazepine_dependence",)),
    (r"\b(?:hypokalaemia|potassium (?:replacement|repletion|supplementation))\b", ("hypokalemia",)),
    (r"\b(?:hyponatraemia|sodium (?:replacement|repletion|supplementation))\b", ("hyponatremia",)),
    (r"\b(?:hypophosphataemia|(?:phosphate|phosphorus) (?:replacement|repletion|supplementation))\b", ("hypophosphatemia",)),
    (r"\b(?:hypomagnesaemia|magnesium (?:replacement|repletion|supplementation))\b", ("hypomagnesemia",)),
    (r"\b(?:hypocalcaemia|calcium (?:replacement|repletion|supplementation))\b", ("hypocalcemia",)),
    (r"\b(?:PJP|PCP|pneumocystis)\b.*\b(?:prophylaxis|prevention|risk)\b", ("pneumocystis_risk",)),
    (r"\b(?:seizure prophylaxis|seizure prevention)\b", ("seizure_risk",)),
    (r"\b(?:DVT|VTE|thrombosis)\b.*\b(?:prophylaxis|prevention|risk)\b", ("dvt_risk",)),
    (r"\b(?:central (?:line|catheter)|catheter occlusion|line patency)\b.*\b(?:prophylaxis|prevention|flush|lock|patency)\b|\b(?:heparin|catheter) flush(?:es)?\b", ("central_line_occlusion_risk",)),
    (r"\b(?:stress ulcer|gastric ulcer|gastric protection|gastroprotection|GI prophylaxis)\b", ("gastric_ulcer_risk",)),
    (r"\b(?:upper GI|upper gastrointestinal) bleed(?:ing)?\b", ("upper_gi_bleeding",)),
    (r"\b(?:antifungal|fungal infection) (?:prophylaxis|prevention)\b", ("fungal_infection_risk",)),
    (r"\b(?:adrenal replacement|adrenocortical support|stress dose steroid)\b", ("adrenal_insufficiency",)),
    (r"\b(?:central DI|ADH analog)\b", ("central_diabetes_insipidus",)),
    (r"\b(?:iron deficiency|sickle cell) an(?:ae|e)mia\b", ("anemia",)),
    (r"\b(?:G CSF|GCSF|granulocyte colony stimulating)\b", ("neutropenia",)),
)
_CLASS_ALIASES = (
    (r"\b(?:antibiotics?|antibacterials?|cephalosporins?|carbapenems?|penicillins?|aminoglycosides?|fluoroquinolones?|macrolides?)\b", ("sepsis",)),
    (r"\b(?:bowel (?:regimen|management|medications?)|laxatives?|stool softeners?)\b", ("constipation",)),
    (r"\b(?:GI prophylaxis|acid suppression|proton pump inhibitors?|H2 blockers?)\b", ("gastric_ulcer_risk",)),
    (r"\b(?:antiepileptics?|antiepileptic adjunct|anticonvulsants?|anti seizure medications?)\b", ("seizure_risk",)),
    (r"\b(?:sedatives?|sedation|analgosedation)\b", (_SEDATION,)),
    (r"\b(?:withdrawal|wean|taper)\b", (_WITHDRAWAL,)),
    (r"\b(?:eye care|ocular lubricants?|eye lubricants?|exposure keratopathy)\b", ("exposure_keratopathy",)),
    (r"\b(?:neurorecovery|neurostimulants?)\b", ("encephalopathy",)),
    (r"\b(?:antihypertensives?|blood pressure control)\b", ("hypertension",)),
    (r"\banti ?arrhythmics?\b", ("arrhythmia",)),
    (r"\b(?:sleep medications?|sleep aids?|insomnia)\b", ("insomnia",)),
    (r"\bairway tone(?: modulators?)?\b", ("tracheobronchomalacia",)),
    (r"\b(?:analgesia|analgesics?|pain control|epidural|NSAIDS?)\b", ("acute_pain",)),
    (r"\bantifungals?\b", ("fungal_infection_risk",)),
)
_NO_PLAN_LABELS = re.compile(
    r"\b(?:prokinetics?|motility|antipyretics?|fever control|antiemetics?|probiotics?|"
    r"parenteral nutrition|TPN|PPN|maintenance fluids?|maintenance electrolytes?|"
    r"surgical prophylaxis|perioperative prophylaxis|therapeutic anticoagulation)\b", re.I
)
_LOCAL_ROUTE = re.compile(r"topical|ophthalm|\beyes?\b|otic|irrigation|apply externally", re.I)
_LOCAL_FORM = re.compile(r"\b(?:ophthalmic|otic|ointment|cream)\b", re.I)
_NEGATIVE_LABEL = re.compile(r"\b(?:no|not|without|ruled out|history of|previous|resolved)\b", re.I)
_MILRINONE = re.compile(r"(?<![A-Za-z0-9_-])milrinone(?=$|[\s(,])", re.I)

_NAME_RULES = (
    (r"\b(?:pantoprazole|Protonix|omeprazole|esomeprazole|lansoprazole|famotidine)\b", "gastric_ulcer_risk"),
    (r"\b(?:levetiracetam|clobazam|lacosamide|phenobarbital|phenytoin|fosphenytoin|valproate|valproic acid|topiramate)\b", "seizure_risk"),
    (r"\b(?:enoxaparin|dalteparin)\b", "dvt_risk"),
    (r"\b(?:polyethylene glycol|senna|sennosides|docusate|lactulose|bisacodyl)\b", "constipation"),
    (r"\bpotassium chloride\b", "hypokalemia"),
    (r"\b(?:sodium|potassium) phosphate\b", "hypophosphatemia"),
    (r"\bmagnesium (?:sulfate|oxide)\b", "hypomagnesemia"),
    (r"\bcalcium (?:gluconate|chloride|carbonate)\b", "hypocalcemia"),
    (r"\b(?:sildenafil|tadalafil|bosentan)\b", "pulmonary_hypertension"),
    (r"\b(?:amlodipine|nicardipine|labetalol)\b", "hypertension"),
    (r"\bmethadone\b", "opioid_dependence"),
    (r"\b(?:oseltamivir|peramivir|zanamivir)\b", "influenza"),
    (r"\b(?:erythromycin|cefepime|ceftriaxone|cefazolin|cefotaxime|ceftazidime|cefuroxime|cefdinir|cephalexin|ceftaroline|ampicillin|amoxicillin|penicillin|piperacillin|meropenem|imipenem|ertapenem|vancomycin|linezolid|daptomycin|clindamycin|metronidazole|azithromycin|clarithromycin|doxycycline|minocycline|sulfamethoxazole|trimethoprim|gentamicin|tobramycin|amikacin|ciprofloxacin|levofloxacin|moxifloxacin|oxacillin|nafcillin|rifampin|aztreonam)\b", "sepsis"),
)
_REVIEWS = {
    "sepsis": "Review the medication indication and confirm whether sepsis applies.",
    "constipation": "Review constipation versus prevention or another indication.",
    "gastric_ulcer_risk": "Review gastric ulcer prophylaxis versus another indication.",
    "seizure_risk": "Review seizure prophylaxis versus treatment of an established seizure disorder.",
    "dvt_risk": "Review DVT prophylaxis versus therapeutic or circuit anticoagulation.",
    "central_line_occlusion_risk": "Confirm the central catheter and patency indication.",
    "hypokalemia": "Review documented hypokalemia versus maintenance supplementation.",
    "hyponatremia": "Review documented hyponatremia versus maintenance supplementation.",
    "hypophosphatemia": "Review documented hypophosphatemia versus maintenance supplementation.",
    "hypomagnesemia": "Review documented hypomagnesemia and the treatment indication.",
    "hypocalcemia": "Review documented hypocalcemia and the treatment indication.",
    "exposure_keratopathy": "Review exposure keratopathy versus preventive eye care.",
    "encephalopathy": "Review the neurologic indication and whether encephalopathy is documented.",
    "opioid_dependence": "Review opioid dependence or withdrawal versus analgesia.",
    "benzodiazepine_dependence": "Review benzodiazepine dependence or withdrawal versus another indication.",
    "fungal_infection_risk": "Review fungal infection prophylaxis versus treatment.",
    "pneumocystis_risk": "Confirm the Pneumocystis prophylaxis indication.",
    "central_diabetes_insipidus": "Review central diabetes insipidus versus another indication.",
    "adrenal_insufficiency": "Review adrenal insufficiency or replacement therapy versus another steroid indication.",
    "neutropenia": "Review documented neutropenia versus prevention.",
    "anemia": "Review the current anemia diagnosis and treatment indication.",
    "acute_pain": "Review acute pain versus a chronic or nonanalgesic indication.",
    "pulmonary_hypertension": "Confirm pulmonary hypertension as the indication.",
    "hypertension": "Confirm systemic hypertension as the indication.",
    "insomnia": "Review insomnia and the sleep medication indication.",
    "tracheobronchomalacia": "Review tracheobronchomalacia and the airway medication indication.",
    "arrhythmia": "Review the rhythm diagnosis and antiarrhythmic medication indication.",
    "heart_failure": "Review the heart failure diagnosis and medication indication.",
}


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _label_text(value: str) -> str:
    return re.sub(r"[_/\-]+", " ", _text(value))


def _catalog_aliases(catalog) -> dict[str, list[str]]:
    aliases = {}
    for item in catalog or ():
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        values = [item["id"], item.get("label", ""), item.get("phrase", "")]
        phrase = _text(item.get("phrase", ""))
        if phrase.startswith("ACKZ"):
            values.append(phrase[4:])
        for value in values:
            key = _normalize(_text(value))
            if key:
                ids = aliases.setdefault(key, [])
                if item["id"] not in ids:
                    ids.append(item["id"])
    return aliases


def _sedation_ids(entry: dict, support: dict) -> list[str]:
    kind = support.get("kind", "unknown")
    if kind == "invasive":
        return ["agitation_intubated"]
    if kind == "noninvasive":
        return ["agitation_nonintubated"]
    if kind == "unknown" and re.search(r"\bdexmedetomidine\b", _text(entry.get("source_name")), re.I):
        return ["agitation_nonintubated"]
    return []


def _resolve(ids, entry: dict, support: dict) -> list[str]:
    resolved = []
    for key in ids:
        if key == _SEDATION:
            resolved.extend(_sedation_ids(entry, support))
        elif key == _WITHDRAWAL:
            name = _text(entry.get("source_name"))
            if re.search(r"\b(?:methadone|morphine|hydromorphone|fentanyl|oxycodone|buprenorphine)\b", name, re.I):
                resolved.append("opioid_dependence")
            elif re.search(r"\b(?:lorazepam|diazepam|midazolam|clonazepam|chlordiazepoxide)\b", name, re.I):
                resolved.append("benzodiazepine_dependence")
        elif key.startswith("agitation_") and support.get("kind") in ("invasive", "noninvasive", "unclear"):
            resolved.extend(_sedation_ids(entry, support))
        else:
            resolved.append(key)
    return list(dict.fromkeys(resolved))


def _local_antibiotic(entry: dict) -> bool:
    return bool(_LOCAL_ROUTE.search(_text(entry.get("route")))
                or _LOCAL_FORM.search(_text(entry.get("source_name"))))


def _category_ids(entry: dict, support: dict, aliases: dict) -> list[str] | None:
    path = entry.get("category_path")
    if not isinstance(path, dict):
        return None
    for id_key, name_key in (("id", "name"), ("parent_id", "parent_name")):
        ident = _text(path.get(id_key))
        label = _label_text(_text(path.get(name_key)))
        exact = aliases.get(_normalize(label), [])
        if not exact:
            # Allow a diagnosis-named category with a simple organizational
            # suffix, without matching arbitrary partial clinical text.
            stem = re.sub(r"\s+(?:medications?|meds|management|treatment)$", "", label, flags=re.I)
            exact = aliases.get(_normalize(stem), [])
        if exact:
            return _resolve(exact, entry, support)
        assertion_label = re.sub(r"\b(?:without intubation|not intubated)\b", "nonintubated", label, flags=re.I)
        if assertion_label and _NEGATIVE_LABEL.search(assertion_label):
            return []
        specific = [key for pattern, keys in _INDICATION_ALIASES
                    if re.search(pattern, label, re.I) for key in keys]
        if specific:
            return _resolve(specific, entry, support)
        if label and _NO_PLAN_LABELS.search(label):
            return []
        if ident in _BUILTIN_RULES:
            ids = _resolve(_BUILTIN_RULES[ident], entry, support)
            return [] if ids == ["sepsis"] and _local_antibiotic(entry) else ids
        classes = [key for pattern, keys in _CLASS_ALIASES
                   if re.search(pattern, label, re.I) for key in keys]
        if classes:
            ids = _resolve(classes, entry, support)
            return [key for key in ids if key != "sepsis" or not _local_antibiotic(entry)]
    return None


def _fallback_ids(entry: dict, support: dict) -> list[str]:
    name = _text(entry.get("source_name") or entry.get("name"))
    row = {key: entry.get(key, "") for key in ("route", "frequency", "dose", "section")}
    row["name"] = name
    automatic = automatic_system_group(row)
    if automatic == "antiarrhythmic" and isinstance(entry.get("category_path"), dict):
        # A saved effective category already had its chance to match above.
        # Do not override a different current placement merely because a drug
        # can also be used as an antiarrhythmic, especially IV lidocaine.
        automatic = ""
    if "group:" + automatic in _BUILTIN_RULES:
        ids = _resolve(_BUILTIN_RULES["group:" + automatic], entry, support)
    else:
        ids = [key for pattern, key in _NAME_RULES if re.search(pattern, name, re.I)]
    if entry.get("group") == "Drips" and re.search(
        r"\b(?:fentanyl|midazolam|dexmedetomidine|morphine|hydromorphone|ketamine|pentobarbital|propofol)\b", name, re.I
    ):
        ids.extend(_sedation_ids(entry, support))
    if re.search(r"\bheparin\b", name, re.I):
        ids.append("central_line_occlusion_risk" if re.search(r"\b(?:flush|lock)\b", name, re.I) else "dvt_risk")
    return list(dict.fromkeys(key for key in ids if key != "sepsis" or not _local_antibiotic(entry)))


def _reason(key: str, entry: dict, support: dict, mapped: bool) -> str:
    name = _text(entry.get("name") or entry.get("source_name")) or "Medication"
    if key == "agitation_intubated":
        route = "tracheostomy support" if support.get("tracheostomy") and not support.get("endotracheal_tube") else "invasive support"
        return name + " is listed with " + route + ". Review the restlessness and agitation indication and the wording of the intubated plan."
    if key == "agitation_nonintubated":
        return name + " is listed without documented invasive support. Confirm nonintubated status and the restlessness and agitation indication."
    lead = " is linked to this plan by its saved medication mapping. " if mapped else " is listed. "
    return name + lead + _REVIEWS.get(key, "Review whether this indication applies to the current note.")


def medication_note_candidates(medications: dict, *, support: dict, catalog=None) -> list[dict]:
    """Return existing phrase IDs and reasons for active medication entries.

    ``catalog`` optionally supplies current id/label/phrase records so a custom
    category can match any existing diagnosis or exact phrase name. A recognized
    leaf indication wins over a parent category or generic medication name.
    The user's explicit milrinone rule also adds a heart-failure candidate
    alongside any applicable category indication.
    Missing or ambiguous catalog indications never produce invented names.
    Categories remain metadata. This function never modifies medication text,
    input rows, the handoff, or the supplied catalog.
    """
    if not isinstance(medications, dict) or not isinstance(support, dict):
        return []
    aliases = _catalog_aliases(catalog)
    allowed = None if catalog is None else {item["id"] for item in catalog
                                            if isinstance(item, dict) and isinstance(item.get("id"), str)}
    output = []
    seen = set()
    for entry in medications.get("entries", []):
        if not isinstance(entry, dict) or entry.get("active") is not True:
            continue
        if entry.get("section") == "Ignore":
            continue
        ids = _category_ids(entry, support, aliases)
        mapped = ids is not None
        if ids is None:
            ids = _fallback_ids(entry, support)
        # This explicit user-requested medication rule supplements its saved
        # category rather than replacing it. Other drug/category precedence
        # remains unchanged, and inactive entries were already excluded above.
        requested = (["heart_failure"] if _MILRINONE.search(
            _text(entry.get("source_name") or entry.get("name"))) else [])
        for key in dict.fromkeys(ids + requested):
            if allowed is not None and key not in allowed:
                continue
            reason = _reason(key, entry, support, mapped and key not in requested)
            signature = (key, reason)
            if signature not in seen:
                output.append({"id": key, "reason": reason})
                seen.add(signature)
    return output
