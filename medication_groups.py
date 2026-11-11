"""User-selected display groups. These labels do not infer clinical indications.

Heparin qualification inspects the ordered Dose only, never product strength or
pump rate. A grouping changes presentation, not the source order or clinical use.
"""
from __future__ import annotations
from copy import deepcopy
import re
from medications import is_bupivacaine, match_name, normalized
from chemotherapy import is_chemotherapy

ID_GROUPS = ("antibiotic", "antifungal", "antiviral")
HEME_GROUPS = ("dvt", "antiplatelet", "gcsf", "chemotherapy")
CV_GROUPS = ("antiarrhythmic", "antihypertensive", "inotrope", "vasopressor", "adrenocortical", "vasodilator")
RESP_GROUPS = ("airway_cerebral_steroid", "airway_tone", "antisialorrhea", "beta_agonist",
               "anticholinergic", "methylxanthine", "corticosteroid", "inhaled_corticosteroid",
               "pulmonary_hypertension", "allergy_immunology", "airway_vasoconstrictor")
# These groups follow the bedside sedation/PRN/paralytic blocks alphabetically.
NEURO_OTHER_GROUPS = ("antiepileptic", "antispasmodic",
                      "epidural", "fever", "insomnia", "neuromodulation")
NEURO_PRIORITY_GROUPS = ("sedative_prn", "paralytic_infusion", "paralytic_prn")
MODES = (("auto", "dvt", "fever", "sedative_prn", "paralytic_prn", "antiepileptic",
          "insomnia", "antispasmodic", "neuromodulation", "epidural",
          "paralytic_infusion") + RESP_GROUPS + CV_GROUPS + ID_GROUPS + ("antiplatelet", "gcsf", "chemotherapy", "other",))
MODE_LABELS = {
    "auto": "Automatic", "dvt": "DVT Prophylaxis",
    "chemotherapy": "Chemotherapy",
    "antiplatelet": "Antiplatelet Therapy", "gcsf": "G-CSF Stimulator", "antibiotic": "Antibiotics", "antifungal": "Antifungals", "antiviral": "Antivirals", "fever": "Fever Control",
    "sedative_prn": "PRN", "paralytic_prn": "Paralytic PRN", "antiepileptic": "Antiepileptic",
    "paralytic_infusion": "Paralytic Infusions",
    "airway_cerebral_steroid": "Airway/Cerebral Steroids",
    "insomnia": "Insomnia", "antispasmodic": "Antispasmodic",
    "neuromodulation": "Neuromodulation",
    "epidural": "Epidural",
    "beta_agonist": "Beta-Agonist", "anticholinergic": "Anticholinergic",
    "methylxanthine": "Methylxanthine", "corticosteroid": "Corticosteroid",
    "inhaled_corticosteroid": "Inhaled Corticosteroids", "airway_tone": "Airway Tone Modulator",
    "pulmonary_hypertension": "Pulmonary Hypertension",
    "allergy_immunology": "Allergy/Immunology",
    "airway_vasoconstrictor": "Airway Vasoconstrictor",
    "antisialorrhea": "Antisialorrhea Agents", "antiarrhythmic": "Antiarrhythmics",
    "antihypertensive": "Antihypertensives", "inotrope": "Inotrope Infusions",
    "vasopressor": "Vasopressors", "adrenocortical": "Adrenocortical Support",
    "vasodilator": "Vasodilators", "other": "No special grouping",
}
GROUP_NAMES = {key: value for key, value in MODE_LABELS.items() if key not in ("auto", "other")}
GROUP_SECTIONS = {
    **{key: "Hematology" for key in HEME_GROUPS},
    "antibiotic": "Infectious Disease", "antifungal": "Infectious Disease", "antiviral": "Infectious Disease", "fever": "Neurologic", "sedative_prn": "Neurologic",
    **{key: "Neurologic" for key in NEURO_PRIORITY_GROUPS + NEURO_OTHER_GROUPS},
    **{key: "Respiratory" for key in RESP_GROUPS},
    **{key: "Cardiovascular" for key in CV_GROUPS},
}

# These are the user's display groups, not inferred medication indications.
# Match the medication at the start of the product name. For example,
# norepinephrine must not match epinephrine, or enalaprilat match enalapril.
ANTIARRHYTHMICS = (
    "esmolol", "amiodarone", "procainamide", "mexiletine", "flecainide",
    "propranolol", "sotalol", "diltiazem", "verapamil", "digoxin",
)
ANTIHYPERTENSIVES = (
    "enalapril", "metoprolol", "amlodipine", "lisinopril", "hydrochlorothiazide",
    "clonidine", "atenolol", "carvedilol", "losartan", "valsartan", "captopril",
    "labetalol", "nifedipine", "isradipine",
)
INOTROPES = ("milrinone", "dobutamine", "epinephrine", "dopamine")
VASOPRESSORS = ("norepinephrine", "vasopressin", "phenylephrine")
VASODILATORS = ("nitroglycerin", "nitroglycerine", "nicardipine", "nicadipine", "hydralazine", "enalaprilat", "enalapriatat")
IV_ROUTES = {"intravenous", "iv", "intra arterial", "intraarterial", "ia"}


def _starts(name: str, names: tuple[str, ...]) -> bool:
    return bool(re.match(r"^(?:" + "|".join(re.escape(n) for n in names) + r")(?=$|[\s(,])", name))


def _route(row: dict) -> str:
    return normalized(row.get("route", "")).replace("-", " ")


def _continuous_iv(row: dict) -> bool:
    # No drug in a local-anesthetic mixture, no rescue bolus, no nebulized dose.
    if _route(row) not in IV_ROUTES or is_prn(row):
        return False
    if row.get("infusion_mode") == "other":
        return False
    return row.get("infusion_mode") == "infusion" or bool(
        re.search(r"\bcontinuous\b|\btitrat(?:e|able)\b", normalized(row.get("frequency", "")))
    )


def _local_form(row: dict, name: str) -> bool:
    # Do not recategorize topical hydrocortisone, eye/nose drops, or local products.
    route = _route(row)
    return (bool(re.search(r"topical|ophthalm|otic|nostril|nasal|rectal|buccal|nebul|inhal|irrigation|infiltrat|intraderm", route))
            or bool(re.search(r"\b(?:cream|ointment|ophthalmic|otic|nasal|enema|suppository|suppositories)\b", name)))


def automatic_system_group(row: dict) -> str:
    """Requested defaults, including the fixed bupivacaine placement."""
    name = match_name(row.get("name", ""))
    if is_bupivacaine(name):
        return "epidural"
    if is_chemotherapy(name):
        return "chemotherapy"
    # Filgrastim is G-CSF, not GM-CSF. Match the generic and its biosimilar
    # suffixes without accidentally matching pegfilgrastim or a mixture.
    if re.match(r"^(?:filgrastim(?:-[a-z]{4})?|tbo-filgrastim|nivestym|neupogen|zarxio|releuko|nypozi|filkri)(?=$|[\s(,])", name):
        return "gcsf"
    if _starts(name, ("aspirin", "cangrelor")):
        return "antiplatelet"
    # Organizational defaults only. Existing explicit category assignments win.
    # Erythromycin retains the user's Prokinetic Agents default.
    if _starts(name, ("micafungin", "fluconazole", "voriconazole", "amphotericin")):
        return "antifungal"
    if _starts(name, ("acyclovir", "valacyclovir", "aciclovir", "valaciclovir")):
        return "antiviral"
    antibiotics = ("cefepime", "ceftriaxone", "cefazolin", "cefotaxime", "ceftazidime",
        "cefuroxime", "cefdinir", "cephalexin", "ceftaroline", "ampicillin",
        "ampicillin-sulbactam", "amoxicillin", "amoxicillin-clavulanate", "penicillin",
        "piperacillin-tazobactam", "meropenem", "imipenem-cilastatin", "ertapenem",
        "vancomycin", "linezolid", "daptomycin", "clindamycin", "metronidazole",
        "azithromycin", "clarithromycin", "doxycycline", "minocycline",
        "sulfamethoxazole-trimethoprim", "trimethoprim-sulfamethoxazole",
        "gentamicin", "tobramycin", "amikacin", "ciprofloxacin", "levofloxacin",
        "moxifloxacin", "oxacillin", "nafcillin", "rifampin", "aztreonam")
    if _starts(name, antibiotics):
        route = _route(row)
        if not re.search(r"topical|ophthalm|eyes?|otic|irrigation|apply externally", route) and not re.search(r"\b(?:ophthalmic|otic|ointment|cream)\b", name):
            return "antibiotic"
    if _starts(name, ("dexamethasone",)):
        # Systemic dexamethasone only. Eye/ear/topical preparations keep their
        # existing mapping. The category is a user-requested display label.
        return "" if _local_form(row, name) else "airway_cerebral_steroid"
    if _starts(name, ("diphenhydramine", "benadryl")):
        return "allergy_immunology"
    # Match racemic products only, not epinephrine/norepinephrine infusions
    # or emergency injections. Existing category overrides take priority.
    racemic = (_starts(name, ("racepinephrine", "racemic epinephrine",
                "epinephrine racemic", "epinephrine, racemic",
                "epinephrine (racemic)", "asthmanefrin")))
    if racemic:
        route = _route(row)
        inhaled_routes = {"nebulization", "nebulisation", "nebulized", "nebulised",
                          "inhalation", "inhaled", "respiratory (inhalation)"}
        nonairway_form = bool(re.search(r"\b(?:injection|injectable|infusion|autoinjector|auto-injector)\b", name))
        return "airway_vasoconstrictor" if (not route or route in inhaled_routes) and not nonairway_form else ""
    if _starts(name, ("albuterol",)):
        return "beta_agonist"
    if _starts(name, ("ipratropium", "ipratroppium")):
        return "anticholinergic"
    if _starts(name, ("aminophylline",)):
        return "methylxanthine"
    if _starts(name, ("methylprednisolone", "prednisone", "prednisolone")):
        return "" if _local_form(row, name) else "corticosteroid"
    if _starts(name, ("bethanechol",)):
        return "airway_tone"
    if _starts(name, ("sildenafil",)):
        return "pulmonary_hypertension"
    if _starts(name, ("budesonide", "fluticasone", "mometasone")):
        route = _route(row)
        inhaled = route in {"inhalation", "inhaled", "nebulization", "nebulisation", "nebulized", "nebulised"}
        # Do not classify oral, nasal, topical, ophthalmic or otic products as inhaled.
        if not route and re.search(r"\b(?:inhaler|inhalant|inhalation|nebulizer)\b", name):
            inhaled = True
        return "inhaled_corticosteroid" if inhaled else ""
    if _starts(name, ("melatonin", "trazodone")):
        return "insomnia"
    if _starts(name, ("baclofen",)):
        return "antispasmodic"
    if _starts(name, ("gabapentin", "pregabalin")):
        return "neuromodulation"
    if _starts(name, ("scopolamine", "glycopyrrolate", "glycopyrollate")):
        return "antisialorrhea"
    if _starts(name, ("lidocaine",)):
        return "antiarrhythmic" if _continuous_iv(row) else ""
    if _starts(name, INOTROPES):
        return "inotrope" if _continuous_iv(row) else ""
    if _starts(name, VASOPRESSORS):
        return "vasopressor" if _route(row) in IV_ROUTES else ""
    if _starts(name, ANTIARRHYTHMICS):
        return "antiarrhythmic"
    if _starts(name, ANTIHYPERTENSIVES):
        return "antihypertensive"
    if _starts(name, ("hydrocortisone",)):
        return "" if _local_form(row, name) else "adrenocortical"
    if _starts(name, VASODILATORS):
        return "vasodilator"
    return ""


def is_prn(row: dict) -> bool:
    """Only the recorded frequency establishes PRN status."""
    return bool(re.search(r"\bprn\b|\bas[ -]+needed\b", normalized(row.get("frequency", ""))))


def automatic_group(row: dict) -> str:
    system_group = automatic_system_group(row)
    if system_group:
        return system_group
    name = match_name(row.get("name", ""))
    if re.match(r"^enoxaparin\b", name):
        return "dvt"
    if re.match(r"^heparin\b", name):
        # Avoid flush/lock mixtures even if an unusual source has a misleading dose.
        if re.search(r"\b(?:flush|lock|taurolidine)\b", name) or normalized(row.get("route", "")) in {"intracatheter", "irrigation"}:
            return ""
        dose = normalized(row.get("dose", ""))
        # Keep exact units. A numeric value or range must occur in Dose.
        if re.search(r"(?<![\w/])\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?\s*units?\s*/\s*kg\s*/\s*(?:hr|h|hour)(?![\w/])", dose):
            return "dvt"
    if re.match(r"^(?:acetaminophen|ibuprofen)\b", name):
        return "fever"
    if re.match(r"^(?:phenytoin|fosphenytoin|phenobarbital|clobazam|clobozam|levetiracetam|valproic acid|pentobarbital)\b", name):
        return "antiepileptic"
    if _starts(name, ("rocuronium", "cisatracurium", "vecuronium")) and _continuous_iv(row):
        return "paralytic_infusion"
    if is_prn(row):
        if re.match(r"^(?:fentanyl|midazolam|ketamine|morphine|hydromorphone)\b", name):
            return "sedative_prn"
        if re.match(r"^(?:rocuronium|cisatracurium|vecuronium)\b", name):
            return "paralytic_prn"
    return ""


def group_for(row: dict) -> str:
    # The user's bupivacaine rule also applies to existing saved orders with
    # older group choices. Leave those source choices untouched in storage.
    if is_bupivacaine(row.get("name", "")):
        return "epidural"
    mode = row.get("group_mode", "auto")
    # An explicit GI override wins over automatic defaults, not over an explicit
    # special-group choice. UI callbacks clear the competing explicit choice.
    if mode == "auto" and row.get("gi_mode", "auto") in ("prophylaxis", "bowel", "diuretic", "antiemetic", "endocrine", "prokinetic", "tpn", "hypoglycemia"):
        return ""
    return automatic_group(row) if mode == "auto" else mode if mode in GROUP_NAMES else ""


def group_key(row: dict) -> tuple[str, str, str]:
    return match_name(row["name"]), normalized(row["route"]), normalized(row["frequency"])


def validate_group_rules(rules: list[dict]) -> None:
    if not isinstance(rules, list) or len(rules) > 1500:
        raise ValueError("The medication group rules are invalid or too large.")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) - {"match"} != {"name", "route", "frequency", "mode"}:
            raise ValueError("A medication group rule has an invalid structure.")
        for key in ("name", "route", "frequency"):
            if not isinstance(rule[key], str) or len(rule[key]) > 4000 or any(c in rule[key] for c in "\n\r\t"):
                raise ValueError("A medication group rule contains invalid text.")
        if not rule["name"] or rule["mode"] not in MODES[1:]:
            raise ValueError("A medication group rule has an invalid choice.")
        if "match" in rule and (rule["match"] != "prefix" or rule["mode"] != "antiepileptic" or rule["route"] or rule["frequency"]):
            raise ValueError("An Antiepileptic prefix rule is invalid.")
        key = (rule["name"], rule["route"], rule["frequency"], rule.get("match", "exact"))
        if key in seen:
            raise ValueError("Duplicate medication group rules were found.")
        seen.add(key)


def set_group_rule(rules: list[dict], row: dict, mode: str) -> list[dict]:
    if mode not in MODES:
        raise ValueError("Choose a valid medication group.")
    key = group_key(row)
    result = [deepcopy(r) for r in rules if (r["name"], r["route"], r["frequency"]) != key]
    if mode != "auto":
        result.append(dict(zip(("name", "route", "frequency"), key), mode=mode))
    result.sort(key=lambda r: (r["name"], r["route"], r["frequency"]))
    validate_group_rules(result)
    return result


def group_mode_for(row: dict, rules: list[dict]) -> str:
    key = group_key(row)
    exact = next((r["mode"] for r in rules if r.get("match") != "prefix" and (r["name"], r["route"], r["frequency"]) == key), None)
    if exact is not None:
        return exact
    return "antiepileptic" if any(r.get("match") == "prefix" and re.match(r"^" + re.escape(r["name"]) + r"(?=$|[^a-z0-9])", key[0]) for r in rules) else "auto"


def apply_group_rules(rows: list[dict], rules: list[dict]) -> list[dict]:
    validate_group_rules(rules)
    result = deepcopy(rows)
    for row in result:
        mode = group_mode_for(row, rules)
        if mode != "auto" or "group_mode" in row:
            row["group_mode"] = mode
    return result
