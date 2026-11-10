# Version 6.43: CAPD, Vent Settings and medication categories

Built from the delivered Version 6.42 package. No changes to the clinical
medication-dose parser, ventilator values, lab trees or infusion-rate selection.

## CAPD from Y

The Y section accepts the documented total, including:

    yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy
    CAPD: Cornell Assessment of Pediatric Delirium Score: 24
    yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy

The Neurologic column displays the arousal target, CAPD, then WAT-1 before
medications. A score of zero prints as 0. No available score prints as None.
None means unavailable or not assessed, not a negative delirium screen.
No item scores are calculated and no delirium diagnosis is generated.

Only a single whole-number total from 0 to 32 is accepted. Identical repeats
collapse to one entry. Conflicting totals, unsupported fragments or incomplete
Y dividers do not replace the prior stored entry. Other valid sections import.
The prior CAPD remains in the editor but is not printed after a Y import error.
The handoff instead shows CAPD: None until corrected, reviewed or reimported.

A paired empty Y section clears CAPD. Omitting Y during a partial-section update
preserves the stored CAPD. Old handoffs without a CAPD total show None.
Edit imported scores under Labs / Vitals, Neurologic observations. Excluding a
score shows None instead. Scores save with the room through existing save and
room-change autosave. Starting a new patient clears the old observation.
The missing-score placeholder does not make an unused room appear in Print all.

Range reference (not a diagnostic rule):
https://pmc.ncbi.nlm.nih.gov/articles/PMC9157792/

## Medication display defaults

Respiratory / Allergy/Immunology: diphenhydramine (including Benadryl).
FEN / GI / Prokinetic Agents: erythromycin and prucalopride.
Erythromycin eye and skin preparations are not automatically placed in this GI
group. A category is an organizational default, not a determination of why a
medication was prescribed. Explicit category assignments can keep erythromycin
under Infectious Disease when it is being used for that purpose.

These categories support the existing category/subcategory editor. Hidden
orders remain hidden and each visible order has a single destination. Existing
explicit assignments and custom categories take priority. Doses, routes,
frequencies and Last Admin rates are unchanged.

## Vent Settings heading

A bold Vent Settings heading appears above documented invasive/home ventilation
or CPAP, BiPAP, AVAPS NIV or NAVA NIV support settings. Respiratory vital signs
remain above it. An empty section or HFNC/nasal-cannula-only summary does not
produce a misleading empty ventilator heading. Both HTML preview and PDF use
the same generated heading. The actual settings are unchanged.

## Upgrade

Upload the contents of PICU_Handoff_v6_43_CAPD_Categories into the existing code
directory. Keep app.py at the root and include capd.py. Restart and refresh.
Do not change Secrets, passwords, encryption keys, stored mappings, BMI reference
data or the shared data archive. Do not rerun setup generators. No new Python
dependencies are required.

The archive upgrades from schema 27 to 28. Existing fields, custom rooms and
save times stay unchanged. Existing customized catalogs gain only missing new
built-in definitions. Existing category IDs, names, positions and rules are
preserved. Do not downgrade after saving with this version.

Existing stored medication and vent data use the new presentation immediately.
Paste the paired Y section or full SmartPhrase to add CAPD, then save. The
SMARTPHRASE_TEMPLATE.txt gains a Y placeholder, but the team's separately
published SmartPhrase is not overwritten automatically.
