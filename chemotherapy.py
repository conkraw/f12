"""Explicit chemotherapy display defaults, not inferred treatment indications.

Only a complete drug name at the start of an order is matched. The curated
conventional-drug roster and source references are in CHEMOTHERAPY_REFERENCE.md.
Steroids, supportive medicines, hydroxyurea and targeted/immunotherapies are
intentionally absent. Source orders and explicit presentation choices are not
changed by this matcher.
"""
from __future__ import annotations

import re

from medications import match_name


# Generic names also cover following salt/formulation words. Keep aliases
# explicit so a shared suffix, protocol name or incidental mention cannot
# classify an unrelated medicine as chemotherapy.
CHEMOTHERAPY_DRUGS = {
    "asparaginase": (
        "l-asparaginase", "l asparaginase", "asparaginase-e.coli",
        "asparaginase-e. coli", "asparaginase-erwinia",
        "erwinia asparaginase", "recombinant asparaginase erwinia chrysanthemi",
        "crisantaspase", "colaspase", "elspar", "erwinaze", "erwinase", "rylaze",
    ),
    "pegaspargase": (
        "oncaspar", "peg-asparaginase", "peg asparaginase",
        "peg-l-asparaginase", "peg l-asparaginase",
    ),
    "calaspargase pegol": ("calaspargase pegol-mknl", "asparlas"),
    "doxorubicin": (
        "adriamycin", "doxorubicin.hcl", "liposomal doxorubicin",
        "doxil", "lipodox",
    ),
    "daunorubicin": ("daunorubicin-cytarabine", "vyxeos"),
    "idarubicin": ("idamycin",),
    "mitoxantrone": (),
    "cyclophosphamide": ("cytoxan", "neosar"),
    "ifosfamide": ("ifex",),
    "busulfan": ("busulfex", "myleran"),
    "melphalan": ("alkeran", "evomela"),
    "thiotepa": ("tepadina",),
    "temozolomide": ("temodar",),
    "procarbazine": ("matulane",),
    "dacarbazine": (),
    "carmustine": ("bicnu",),
    "lomustine": (),
    "methotrexate": ("trexall", "xatmep"),
    "cytarabine": ("cytosar", "cytosar-u", "ara-c", "cytosine arabinoside"),
    "mercaptopurine": ("6-mercaptopurine", "purinethol", "purixan"),
    "thioguanine": ("6-thioguanine", "tioguanine", "tabloid", "lanvis"),
    "fludarabine": (),
    "clofarabine": ("clolar",),
    "nelarabine": ("arranon",),
    "cisplatin": (),
    "carboplatin": ("paraplatin",),
    "oxaliplatin": ("eloxatin",),
    "vincristine": ("oncovin", "vincasar"),
    "vinblastine": (),
    "vinorelbine": (),
    "etoposide": ("etopophos", "vepesid", "toposar"),
    "irinotecan": ("camptosar",),
    "topotecan": ("hycamtin",),
    "dactinomycin": ("actinomycin d", "cosmegen"),
    "bleomycin": (),
    "gemcitabine": ("gemzar", "infugem"),
    "paclitaxel": ("abraxane",),
    "docetaxel": ("taxotere",),
    "azacitidine": ("vidaza", "onureg"),
    "decitabine": ("dacogen",),
}
CHEMOTHERAPY_NAMES = tuple(
    name for generic, aliases in CHEMOTHERAPY_DRUGS.items()
    for name in (generic, *aliases)
)
_NAME = re.compile(
    r"^(?:" + "|".join(re.escape(name) for name in sorted(
        CHEMOTHERAPY_NAMES, key=len, reverse=True
    )) + r")(?=$|[\s(,])"
)


def is_chemotherapy(name: str) -> bool:
    """Return the organizational default from a named ingredient or alias."""
    return bool(_NAME.match(match_name(name)))
