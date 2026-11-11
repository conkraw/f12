# Chemotherapy display defaults

Version 6.63 places the following named medicines under Hematology > Chemotherapy when their display group is Automatic. This is an organizational default. A medicine can have a non-oncology indication, so existing explicit group and category choices still take precedence. The app does not infer an indication or change an order's dose, route, frequency, visibility, or source name.

The matcher uses a complete generic or listed alias at the start of the medication name. It ignores the existing recognized order annotations for matching. Salt and formulation words may follow a matched name. It does not classify unrelated orders from an incidental mention of a drug, a protocol abbreviation, or a broad drug-name suffix.

## Curated roster

Names are matched without case sensitivity. Brand aliases are for recognition of imported orders, including older names, and do not imply current product availability.

| Generic name | Additional recognized aliases and variants |
|---|---|
| Asparaginase | L-asparaginase, L asparaginase, asparaginase-E.coli, asparaginase-E. coli, asparaginase-erwinia, Erwinia asparaginase, recombinant asparaginase Erwinia chrysanthemi, crisantaspase, colaspase, Elspar, Erwinaze, Erwinase, Rylaze |
| Pegaspargase | Oncaspar, PEG-asparaginase, PEG asparaginase, PEG-L-asparaginase, PEG L-asparaginase |
| Calaspargase pegol | calaspargase pegol-mknl, Asparlas |
| Doxorubicin | Adriamycin, doxorubicin.HCl, liposomal doxorubicin, Doxil, Lipodox |
| Daunorubicin | daunorubicin-cytarabine, Vyxeos |
| Idarubicin | Idamycin, including Idamycin PFS |
| Mitoxantrone | Generic name |
| Cyclophosphamide | Cytoxan, Neosar |
| Ifosfamide | Ifex |
| Busulfan | Busulfex, Myleran |
| Melphalan | Alkeran, Evomela |
| Thiotepa | Tepadina |
| Temozolomide | Temodar |
| Procarbazine | Matulane |
| Dacarbazine | Generic name |
| Carmustine | BiCNU |
| Lomustine | Generic name |
| Methotrexate | Trexall, Xatmep |
| Cytarabine | Cytosar, Cytosar-U, Ara-C, cytosine arabinoside |
| Mercaptopurine | 6-mercaptopurine, Purinethol, Purixan |
| Thioguanine | 6-thioguanine, tioguanine, Tabloid, Lanvis |
| Fludarabine | Generic name |
| Clofarabine | Clolar |
| Nelarabine | Arranon |
| Cisplatin | Generic name |
| Carboplatin | Paraplatin |
| Oxaliplatin | Eloxatin |
| Vincristine | Oncovin, Vincasar, including Vincasar PFS |
| Vinblastine | Generic name |
| Vinorelbine | Generic name |
| Etoposide | Etopophos, Vepesid, Toposar |
| Irinotecan | Camptosar |
| Topotecan | Hycamtin |
| Dactinomycin | actinomycin D, Cosmegen |
| Bleomycin | Generic name |
| Gemcitabine | Gemzar, Infugem |
| Paclitaxel | Abraxane |
| Docetaxel | Taxotere |
| Azacitidine | Vidaza, Onureg |
| Decitabine | Dacogen |

The asparaginase generic also covers full names beginning with asparaginase, including asparaginase Erwinia chrysanthemi (recombinant)-rywn. Generic doxorubicin covers following hydrochloride and liposome formulation words. A combination order beginning with daunorubicin, including Vyxeos, remains one order.

## Boundaries

Dexamethasone and other corticosteroids are excluded from automatic Chemotherapy grouping. Existing steroid display groups remain in use. Supportive medicines such as leucovorin, mesna, dexrazoxane, glucarpidase, rasburicase, allopurinol, antiemetics, and growth factors are also excluded.

Hydroxyurea, including Siklos, is excluded because it is also used for pediatric sickle cell disease. Targeted therapies and immunotherapies are not added through a broad class-name rule. The roster is deliberately bounded, and an unlisted drug can still be assigned through the app's existing category controls.

Methotrexate and cyclophosphamide have non-oncology indications. Their automatic display grouping does not establish why a patient receives them. A saved explicit choice can keep these orders in another category.

## Sources

The roster was checked against these primary NCI and FDA resources. These references identify medicines and aliases, rather than provide dosing instructions.

- NCI pediatric drug list: https://www.cancer.gov/about-cancer/treatment/drugs/childhood-cancer-fda-approved-drugs
- NCI leukemia drug list, including Vyxeos: https://www.cancer.gov/about-cancer/treatment/drugs/leukemia
- NCI generic and brand index: https://www.cancer.gov/about-cancer/treatment/drugs/cancer-drugs
- Asparaginase aliases: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/asparaginase
- Pegaspargase aliases: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/pegaspargase
- Erwinia asparaginase aliases: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/asparaginase-erwinia-chrysanthemi
- Recombinant Erwinia asparaginase: https://www.cancer.gov/about-cancer/treatment/drugs/asparaginase-erwinia-chrysanthemi-recombinant
- Calaspargase pegol: https://www.cancer.gov/publications/dictionaries/cancer-terms/def/calaspargase-pegol
- Doxorubicin aliases: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/doxorubicin-hydrochloride
- Liposomal doxorubicin: https://www.cancer.gov/about-cancer/treatment/drugs/doxorubicin-hydrochloride-liposome
- Cyclophosphamide aliases: https://seer.cancer.gov/seertools/seerrx/rx/53c44b08102c1290262dcd2c/
- Vincristine aliases: https://seer.cancer.gov/seertools/seerrx/rx/53c44b0e102c1290262dd131/
- Etoposide aliases: https://seer.cancer.gov/seertools/seerrx/rx/53c44af4102c1290262dbe65/
- Cytarabine aliases: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/cytarabine
- Cytosar-U: https://seer.cancer.gov/seertools/seerrx/rx/53c44b07102c1290262dccd5/
- Mercaptopurine aliases: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/mercaptopurine
- Thioguanine aliases: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/thioguanine
- Carboplatin aliases: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/carboplatin
- Dactinomycin aliases: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/dactinomycin
- FDA Siklos pediatric sickle cell indication: https://www.accessdata.fda.gov/scripts/opdlisting/oopd/detailedIndex.cfm?cfgridkey=400413
- FDA Xatmep pediatric arthritis indication: https://www.accessdata.fda.gov/scripts/opdlisting/oopd/detailedIndex.cfm?cfgridkey=479515
- Cyclophosphamide tablet label, including pediatric nephrotic syndrome: https://www.dailymed.nlm.nih.gov/dailymed/fda/fdaDrugXsl.cfm?setid=15d30249-4714-4b13-b8ca-5dff38424282
