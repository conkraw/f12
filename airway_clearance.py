"""Recognize the requested 3% sodium chloride nebulizer display placement.

Match the individual formulation and recorded route. Other saline orders,
concentrations and mixtures keep their existing mappings. Source fields are
never changed here.
"""
from __future__ import annotations

import re


AIRWAY_ROUTES = {
    "neb", "nebs", "nebulization", "nebulisation", "nebulized", "nebulised",
    "inhalation", "inhaled", "respiratory (inhalation)",
}
_IDENTITY = re.compile(r"^(?:sodium\s+chloride|nacl)(?=$|[\s(])")
_CONCENTRATION = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%")
_AIRWAY_FORM = re.compile(r"\b(?:neb|nebs|nebulizer|nebuliser|nebulization|nebulisation|nebulized|nebulised|inhalation|inhaled|inhalant)\b")
_OTHER_FORM = re.compile(
    r"\b(?:injection|injectable|infusion|flush|lock|irrigation|enteral|oral|"
    r"ophthalmic|otic|topical|nasal|spray|tablet|capsule|enema|suppository)\b"
)
_MIXTURE = re.compile(r"\b(?:with|plus|and|in|mixed|admixture|compound(?:ed)?)\b|[+/]|%\s*[-–]\s*[a-z]")


def is_sodium_chloride_3_percent_nebulizer(row: dict) -> bool:
    """Require 3% sodium chloride plus an airway route or airway formulation.

    A documented non-airway route or a conflicting formulation always rejects
    the match. The volume is deliberately unrestricted, including 3 and 4 mL.
    Imports are local so medication-name helpers may also call this function.
    """
    from medications import match_name, normalized

    name = match_name(row.get("name", ""))
    route = normalized(row.get("route", ""))
    if not _IDENTITY.match(name) or (route and route not in AIRWAY_ROUTES):
        return False
    percentages = _CONCENTRATION.findall(name)
    if len(percentages) != 1 or not re.fullmatch(r"3(?:\.0+)?", percentages[0]):
        return False
    if _OTHER_FORM.search(name) or _MIXTURE.search(name):
        return False
    return route in AIRWAY_ROUTES or bool(_AIRWAY_FORM.search(name))


def broad_sodium_chloride_rule_applies(row: dict, rule: dict) -> bool:
    """Recognize only an unconstrained, literal saline-family prefix rule."""
    from medications import match_name, normalized

    term = normalized(rule.get("name", ""))
    if (term not in {"sodium chloride", "nacl"} or rule.get("match") != "prefix"
            or normalized(rule.get("route", "")) or normalized(rule.get("frequency", ""))):
        return False
    name = match_name(row.get("name", ""))
    return name == term or (name.startswith(term) and len(name) > len(term)
                            and not name[len(term)].isalnum())
