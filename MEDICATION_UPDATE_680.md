# Medication display update 6.80

## Saline placement

The classifier requires sodium chloride or NaCl at the start of the product name, one 3% concentration, and an inhaled/nebulized route or formulation. A non-airway route, another concentration, a conflicting formulation or a recognized mixture rejects the match. Order volume is not part of the rule.

Qualifying orders receive fixed Respiratory / Airway Clearance placement. Old section, special group, GI group or category assignments cannot override it. Hidden, excluded and ignored orders remain suppressed. An explicit exact category choice can restore an ignored order.

A generic sodium chloride or NaCl prefix rule with an unconstrained Respiratory destination is ignored for nonqualifying products. Specific names, exact rules and explicit route/frequency category filters retain their behavior. Other destinations are unchanged.

When current settings establish that the generic rule caused an older saved Respiratory placement, the displayed copy recomputes from surviving mappings. With no applicable remaining mapping, the order appears in Other Medications. Without that settings evidence, the code does not guess the intent of an old saved section.

The saved mapping list is not deleted. The category catalog gains the new built-in without losing original slots or custom definitions. An existing custom Airway Clearance heading remains available, and each order prints once.

## Per-dose calculations

The structured Dose column supplies the amount. Product strength, Last Admin and pump rate are never substituted for it.

Eligible orders are medications displayed in the existing Sedative PRN category with a PRN frequency, plus intermittent chlorothiazide/furosemide and their Diuril/Lasix names. A renamed Sedative PRN category or child category still works. This release does not automatically recategorize clonidine, lorazepam or other medications into sedation.

An explicit mg/kg or mcg/kg source order is displayed as entered. For an unambiguous absolute mg or mcg amount:

    dose per kg = structured per-dose amount / weight in kg

Documented dosing weight takes precedence. Included measured kg/g weight is a labeled fallback only when dosing weight is blank. An invalid nonblank dosing weight or any I-block import warning prevents calculation. I/O weights, previous room data and estimated weights are not used.

Calculated values use three significant figures with trailing zeros removed. Small positive values are not rounded to zero. Original amounts remain visible. Microgram variants use mcg in the calculated annotation.

No calculation is added to concentrations, ranges, daily totals, continuous orders, infusion rates, custom handoff wording or unrecognized dose text. Missing values are never replaced with zero. These are ordered per-dose values, not totals administered.

## Output and caching

The editor, handoff section display, plain text, HTML and PDF use the same calculation. Emitted copies carry transient annotations that are never stored in the clinical record.

The PDF renderer identifier advances to 6.80-body-v1. The existing content signature includes complete source and rendered output. Dose, dosing weight, measured weight and import-warning changes therefore refresh the affected patient PDF. The session-private cache and Print all assembly logic are unchanged.

## Verification data

New tests and previews use synthetic orders and weights. The supplied EPIC examples were imported in memory for verification and were not copied into this package.

The two-room preview demonstrates 3 mL and 4 mL nebulizers, source mg/kg, calculated mg/kg and mcg/kg, dosing weight and labeled measured-weight fallback.
