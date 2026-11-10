# Version 6.29: demographics, fluid totals, latest vitals and Antiepileptic

## Update your existing app
Save open work, extract PICU629.zip and upload the contents of
PICU_Handoff_v6_29_Demographics_Vitals to your application code repository.
Keep app.py at the repository root. Include anthropometrics.py, bmi_reference.py
and the data folder. Keep all existing Secrets, both passwords, encryption key,
token, medication rules and private data repository unchanged. Do not run the
setup or password generators. No new Python packages are required.

The sidebar reads Version 6.29 | Demographics, latest vitals and Antiepileptic.
Schema 22 migrates to 23 without changing existing room fields or settings.
Do not downgrade after saving new demographic fields or Antiepileptic rules.

## Age, BMI, height and BSA
Age prints directly below Room. Missing age shows --, never an inferred age.
Enter values in Labs / Vitals > Demographics, age and measurements, or put
explicit labels in I / NUTRITION or N / Date of Admission. For example:

Age: 5 years 2 months
Sex: Female
BMI: 17.14 kg/m²
Height: 100 cm
BSA: 0.65 m²

BMI: followed by Body mass index is 17.14 kg/m². is also supported.
These are syntax examples, not calculated measurements for a particular patient.
The age and sex inputs are optional for ordinary handoff creation.
Age for a BMI percentile must be age at that BMI measurement, not age at admission.
No DOB is needed or captured. Sex is not inferred from growth-chart footnotes.

Measured weight, Z-score and dosing weight keep their existing order.
Recorded height, BSA and BMI follow in the demographics column. Height and BSA
stay omitted until supplied. BMI is copied from the source, not calculated from
dosing weight. BSA is not calculated. Its unit is m², not m/kg².

A new I block replaces BMI, height and BSA. If those fields are absent, old values
are cleared. Age and sex update only when explicitly supplied, so manually entered
age/sex are preserved across routine I updates. A blank explicit Age: or Sex:
clears that field. N can also carry the explicit demographics. Omitted sections
stay unchanged. Start a blank handoff for a new occupant of a room.

## Pediatric BMI percentile
See BMI_REFERENCE.md. A complete public CDC reference is NOT bundled in this ZIP.
Open protected Admin > BMI reference data and click Load / refresh public CDC
BMI reference once. If the server cannot download it, upload the official
bmi-age-2022.csv through that same panel. No patient information is sent.

Age must be documented in total months or years AND months, with explicit Male
or Female growth-chart sex. Years alone are not expanded into invented months.
Only ages 24 to under 240 months are calculated. Below age 2, no BMI percentile
is calculated. Adults use the displayed BMI without a pediatric percentile.
If inputs or reference data are missing, the handoff shows why a percentile is
unavailable. All other features remain usable. The app has not been clinically
validated against a live Epic deployment. Verify source inputs and the reference
before using the derived percentile in patient care.

## Intake/output per kilogram
In and Out use only the explicit positive dosing weight, never measured weight.
A recorded total of 100 mL and dosing weight of 10 kg prints:
In: 100 mL (10 mL/kg)

The original total and supplied units stay unchanged. Calculated mL/kg is rounded
to one decimal when needed. The denominator is displayed. Values refer to the
source reporting period, not mL/kg/hr and not urine output alone. Net is copied,
not recalculated or normalized. Missing/invalid dosing weight leaves the original
Intake/Output total with no derived value. Failed I imports suppress normalization
until the dosing weight is reviewed or successfully reimported.

## Ranges plus latest vital readings
E still provides the recorded range. Explicit Last lines append brackets:
ETCO2: 40 to 60 mmHg [55]
SpO2: 93% to 100% [97]
CVP (mean): 8 to 25 mmHg [12]

The bracket is the explicitly supplied last reading, not the average or midpoint.
Blank Last lines are omitted. A last reading without a range prints as a single
value. Source alert markers such as (!) are retained. Different pressure units
or conflicting latest values remain separate rather than being silently combined.
Re-paste the COMPLETE E block so its other vitals are preserved in the new snapshot.
No range is invented, corrected or substituted from a blood gas.

## Antiepileptic group
Neurologic now has a separate Antiepileptic heading. Automatic names are phenytoin,
fosphenytoin, phenobarbital, clobazam, levetiracetam, valproic acid and pentobarbital.
Capitalization and dated prefixes do not block matching. Each order appears once.
Continuous orders within the group retain emphasized infusion names and doses.
Hidden medications, held labels, PRN frequencies, doses and original mappings remain.

Add more generic names in protected Admin > Antiepileptic medications. These rules
are remembered in the same encrypted settings. Existing exact formulation/route/
frequency overrides take priority. You can also select Antiepileptic beside an
individual medication using Medication group. Grouping is a display choice and
is not a determination of clinical indication.

## Testing scope
The test suite, synthetic print preview and archive migration are checked locally.
No private repository, live deployment or real patient record was accessed for
persistence testing. User sample files are not included in this deliverable.
