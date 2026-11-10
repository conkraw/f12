# Version 6.39: medication categories and simpler printing

Built from the delivered Version 6.38 package. The Version 6.35-derived compact
layout, Version 6.37 difficult-airway feature, and Version 6.38 ventilator rules
remain. There is no Version 6.36 font picker.

## Interface changes

The routine PDF layout table (Room, PDF pages, Body text, Layout) and its explanatory
caption are removed. A warning still appears if the actual PDF exceeds the chosen
page target. The PDF renderer still fits pages and never drops clinical content.

Only PDF handoff download buttons remain in Preview / print and Print all.
The on-screen HTML preview is retained. The internal HTML/text exporters remain
for compatibility and automated tests, but no longer have handoff download buttons.
SmartPhrase and user-guide downloads are not affected.

The pictured synthetic-data/approval sidebar notice is removed. Built-in routine
status messages use shared storage instead of naming the storage provider.
Save times, unsaved-state warnings, access controls, session limits, encrypted
storage, conflict checks, setup documentation and error reporting still work.
Removing a label does not change or strengthen security. Hosting approval and
local data-handling requirements remain described in the setup documentation.
Existing published custom instructions are not silently overwritten.

## New automatic display groups

Respiratory / Antisialorrhea Agents:
scopolamine and glycopyrrolate.

Cardiovascular / Antiarrhythmics:
esmolol, amiodarone, procainamide, lidocaine (IV infusion only), mexiletine,
flecainide, propranolol, sotalol, diltiazem, verapamil and digoxin.

Cardiovascular / Antihypertensives:
enalapril, metoprolol, amlodipine, lisinopril, hydrochlorothiazide, clonidine,
atenolol, carvedilol, losartan, valsartan, captopril, labetalol, nifedipine
and isradipine. Repeated names in the request are represented once.

Cardiovascular / Inotrope Infusions:
continuous IV milrinone, dobutamine, epinephrine and dopamine.
Rescue boluses and nebulized epinephrine are not moved into this infusion group.

Cardiovascular / Vasopressors:
IV norepinephrine, vasopressin and phenylephrine. Nasal and ophthalmic products
are not automatically moved to this group.

Cardiovascular / Adrenocortical Support:
systemic hydrocortisone. Topical/rectal local preparations are not automatically
moved to this group.

Cardiovascular / Vasodilators:
nitroglycerin, nicardipine, hydralazine and enalaprilat. Enalapril and enalaprilat
are kept distinct. Nitroprusside was not added to this requested default list and
keeps its prior mapping/generic infusion grouping unless assigned manually.

FEN/GI / Endocrine Medications:
levothyroxine, insulin (including continuous infusions and Lantus), and metformin.
Synthroid and Levoxyl name prefixes are also recognized. Subcutaneous Lantus
orders remain regular medication entries, not continuous infusions.

Canonical name matching includes the requested spelling variants glycopyrollate,
nicadipine, nitroglycerine and enalapriatat. Matching does not rewrite the original
source medication/formulation name, dose, route, frequency or administration rate.

## Rendering and overrides

The cardiovascular groups appear in the order requested, after vitals, pacemaker
information and cardiac labs. An infusion stays in its category with the existing
bold medication name and emphasized Last Admin rate. It is not duplicated under
CV Infusions. Unclassified CV infusions keep that general group.

Respiratory Infusions remain available. Antisialorrhea Agents appear separately.
Endocrine Medications appear in FEN/GI after Antiemetics, before separate notes
and other FEN/GI medications. Insulin infusions use the same emphasized rate style.
Empty headings do not print. All existing hidden/excluded orders remain hidden.

Choose a medication's system and Medication group to override a default.
For Endocrine Medications use FEN/GI display. Choices are remembered in shared
settings and editable in Admin. A deliberate group override takes precedence
rather than duplicating the order. For example, select Neurologic for clonidine
when that is the intended placement. Its new automatic cardiovascular grouping
is then disabled for that formulation, route and frequency.

These categories are user-defined display labels, not inferred indications.
No new diagnosis rules, medication recommendations, dose conversions, or changes
to the Last Admin selection logic were added.

## Install

Extract PICU639.zip and open PICU_Handoff_v6_39_Medication_Categories.
Upload its contents into the existing application code repository, replacing
matching files. Keep app.py at the root. Restart the deployment and refresh.
Keep the existing Secrets, both passwords, encryption key, medication mappings,
BMI reference data and private data repository. Do not rerun setup generators.
No dependencies or new secret fields are required.

Look for: Version 6.39 | Medication categories and simpler printing

No re-pasting is needed to group already captured medications. The new defaults
are applied when the saved handoff is displayed. Explicit grouping overrides
remain authoritative. Existing archive values are not rewritten during display.
Schema remains 26, but older releases do not understand the new group choices.
Do not downgrade after saving one of those choices without restoring a compatible
backup. Back up the current code and encrypted archive before updating.

See TEST_REPORT.md for exactly what was tested. No live deployment or private
repository was modified or tested in this work.
