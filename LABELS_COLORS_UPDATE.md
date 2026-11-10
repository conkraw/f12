# Version 6.54: labels, colors and medication groups

Built from the supplied PICU653.zip, retaining its compact workspace and
on-demand tabs. No new dependencies. Requires the existing Streamlit >=1.55.

## Display

Generated SBS, CAPD, WAT, respiratory and cardiovascular vital labels, ICP/CPP,
and temperature are bold through the colon. Values retain regular weight.
Intake/Output has its own bold heading. Laboratory labels including MCV,
ANC, ALC, Ca, Mg, and Phos are bold. Inflammatory markers is bold.

Explicit H/HH/high flags color the associated numeric result red. L/LL/low
flags color it blue. A numeric result flagged only with an asterisk is red.
An explicit low flag plus an asterisk keeps the result blue and the asterisk
red. All original characters, flags, dates and units remain available. Color
does not create a high or low interpretation or change a stored result.
Growth-chart footnote asterisks are not treated as abnormal lab flags.

This styling applies to HTML previews, the PDF export, Print all, normal lab
trees and wrapped laboratory summaries. Text export remains plain text.
The existing infusion name and rate emphasis is unchanged.

## Editable categories

Infectious Disease now includes Antifungals (micafungin, fluconazole,
voriconazole, amphotericin) and Antivirals (acyclovir, valacyclovir, including
aciclovir/valaciclovir spellings). Amphotericin irrigation retains its route.

FEN/GI includes Hypoglycemia: for a documented continuous intravenous
50% dextrose infusion. It does not capture 5% or 10% dextrose, a 50 mL bag,
a one-time or PRN bolus, or another drug diluted in dextrose. This is a
medication display category, not a new hypoglycemia problem-list diagnosis.

Categories can be moved or renamed in Admin. Hidden orders stay hidden,
explicit category assignments remain authoritative, and orders print once.
A manual assignment can be reset to Automatic to use the new defaults.

## Problem-list rules

The latest eligible calcium result explicitly flagged high generates
Hypercalcemia. The latest eligible phosphorus result explicitly flagged high
generates Hyperphosphatemia. The latest PT, INR or aPTT/PTT result explicitly
flagged high generates one Coagulopathy prompt. High fibrinogen, heparin
anti-Xa or LMWH anti-Xa alone does not trigger Coagulopathy. Existing
admission-date, future-result, inclusion and failed-import filters apply.
A newer normal result is not replaced by an older high result. Asterisk-only
results do not activate these new high-result rules. No thresholds are inferred.

The rules are editable/dismissible prompts with supporting evidence in Problems,
not verified diagnoses. Imported Diagnoses are not changed. They require
clinical review, including medication and reference-range context.

## Installation

Replace the full application folder contents, including clinical_style.py and
models.py. Keep app.py at the root. Restart and refresh the deployment.
Keep current Secrets, both passwords, encryption key, medication mappings,
custom category settings, BMI reference data and shared archive unchanged.
Do not rerun setup generators. Existing stored results and medications do not
need re-pasting. Existing PDFs must be regenerated to show the new style.

Archive schema 32 upgrades to 33 by adding missing built-in category IDs.
Existing patient fields, notes, category names/placements, user rules and saved
timestamps are preserved. Avoid downgrading after saving with this release.

## Scope

No live deployment or shared patient archive was accessed. All added tests and
the supplied preview are synthetic. Hosting/browser performance was not tested.
The clinical import parsers, window selection and shared-storage implementation
are unchanged. The requested problem rules and display routing are changed.
