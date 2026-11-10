# Version 6.30: lab windows and suggested-problem review

## Install
Save current work. Extract PICU630.zip, open PICU_Handoff_v6_30_Problem_Review,
and replace the matching application files with the complete folder contents.
Keep app.py at the repository root. Include lab_windows.py and problem_review.py.
Keep the existing app password, Admin password, encryption key, token, private
repository, medication mappings and BMI reference file. Do not run the setup
or password generators. No new Python dependencies are required.

The sidebar reads:
Version 6.30 | Lab windows and suggested problem review

Schema 23 migrates to 24 without changing any previous sheet, setting or save
stamp. The optional problem_review field stores per-room decisions and limits.
Do not downgrade after saving with this version. Installing does not clear rooms.

## Display windows

| Test | Selection | Placement |
|---|---|---|
| Lactate, including LACWB, LACTATE, LAC, LACTATEVEN and LACTATEART | Earliest and latest numeric results in the rolling 24-hour window, or one result once | Cardiovascular |
| THEOPH / theophylline | Latest numeric result within 24 hours | Respiratory |
| CRP and PROCAL / procalcitonin | Latest numeric result for each on or after admission | Infectious Disease |
| CK, CPK and explicit total creatine kinase | Latest numeric result within 24 hours | Lower Lab Results / Trends, CK (last 24h) |
| NTPROBNP / NT-proBNP | Latest numeric result from all supplied dates | Cardiovascular |

The current Eastern clock is the reference, not the newest laboratory date.
At export, every selected room and every fitting attempt uses one shared instant.
A supplied collection time is used for exact elapsed-24-hour filtering, including
across daylight-saving transitions. Future-dated results are not selected.

Date-only values cannot prove an exact 24-hour interval. A previous-day value
that might overlap the cutoff is retained with a visible timing-unverified
qualifier. Older calendar dates are excluded. Same-day ties without times follow
Epic's supplied order with an ordering qualification. No collection time is invented.

Missing or failed admission information suppresses the automatic CRP/procalcitonin
summary and displays that admission is needed. A known admission date is inclusive.
Older laboratory values remain in Labs / Vitals and encrypted storage. These are
output filters, not deletion or an audit-history rewrite. Failed G imports do not
supply new time-filtered displays.

Lactate summary lines omit codes such as LACWB. Values retain their original
units, comparators, flags and dates. No unit conversion, extrapolation or new
measurement is performed. The raw code remains in the editor.

All time means all dates supplied to this handoff, not automatic access to an
entire Epic chart. CK-MB is not relabeled CK. BNP is not relabeled NT-proBNP.
Canceled, pending, improperly collected and other nonnumeric statuses are not
selected as measured results. Hidden/excluded rows remain excluded.

Downloaded files are snapshots. Regenerate a PDF to refresh the time filters.
Downloaded HTML explicitly retains its lab-evaluation timestamp even if its
print-time display updates later.

## Suggested Problems / Review Required

A pale highlighted, full-width band sits immediately below the system columns,
above Other Medications and the laboratory trees. It is visually separate from
source Diagnoses. An empty band is omitted. Print fitting accounts for its height
and uses continuation pages rather than cutting off content.

Open the Suggested problems tab for the evidence and limitations. A prompt can be
left as Needs review, edited, marked Confirmed by me, or dismissed from printing.
The printed labels are Review for and Reviewed by user. A checkbox hides the
whole band without deleting source results or review decisions. These choices
save with the room and its normal autosave. No individual reviewer identity is
inferred from the shared app login.

Changed supporting results, relevant orders or admission date generate a different
evidence fingerprint. A previous confirmation or dismissal cannot silently approve
that changed evidence. Diagnoses imported from A and separately written notes are
never rewritten by the suggestion engine.

### Rules and guardrails

- An eligible medication mapped to Infectious Disease prompts review for Sepsis.
  It does not establish infection, indication, organ dysfunction or sepsis.
- Recorded HFNC, BiPAP, CPAP, invasive ventilation or supported oxygen-device
  entries prompt review for Acute hypoxemic respiratory failure. Device presence
  alone does not determine acuity, hypoxemia, baseline dependence or airway-protection
  indication. Review these in the chart.
- A greater-than-50% rise between the latest two comparable creatinine results,
  with established chronological order within 7 days, prompts Acute kidney injury.
  A fall, zero baseline, incompatible units, censored value such as <0.2, or a
  same-date pair without collection times does not establish that rise. This is
  the requested narrow review rule, not a complete KDIGO classifier. It does not
  evaluate the separate absolute-increase or urine-output criteria or stage AKI.
- The latest eligible sodium, potassium, albumin, serum CO2, magnesium, phosphorus,
  hemoglobin and platelet result can prompt Hyponatremia, Hypokalemia,
  Hypoalbuminemia, Metabolic acidosis, Hypomagnesemia, Hypophosphatemia, Anemia or
  Thrombocytopenia, respectively. By default it must be explicitly marked L, LL or
  LOW. Low serum CO2 alone does not identify the acid-base diagnosis.
- Bowel-regimen medication use prompts Constipation review. A preventive regimen
  is not proof of constipation.

Held, future, removed, discontinued, ADS-only, hidden or excluded medication rows
are not used as new medication-trigger evidence. Failed relevant imports are not
used to infer current problems. Lab prompts use the latest supplied result since
admission when known, never an earlier low result after a later normal result.
The printed evidence retains the actual result date, which may not be today.

### CBC flags and optional patient-specific limits

An asterisk is an abnormal flag without low/high direction. It is not automatically
interpreted as anemia or thrombocytopenia. The Q-section parser and standard-Hgb-over-
ISTAT selection are unchanged. Explicit L/LL/LOW flags still work.

Under Suggested problems, expand Patient-specific low-result limits (optional).
Enter a clinician-verified limit and source units for that patient. A numeric
comparison is made only if units are present and match. No universal pediatric
threshold is supplied, no units are assumed, and no percentage is converted into
an absolute count. Limits are local to that handoff, not shared medication rules.
A source flag remains visible and may still create a review prompt even when a
custom limit differs.

This feature is an incomplete documentation-review aid, not a diagnosis, a billing
code generator, a sepsis score, or a treatment recommendation. No prompt does not
mean no illness. The treating team remains responsible for interpreting the data.

## Also fixed
The valid Epic BSA phrase 'Body surface area is 0.31 meters squared.' is now read
without rejecting the nutrition section. Invalid mass-based BSA units remain
rejected. No BSA is calculated from dosing weight.

## Verification and scope
See TEST_REPORT.md for the executed automated tests, original-version migration,
provided-specimen checks and synthetic preview inspection. Clinical input parsers
for CBCs, blood gases, medications, feeds, vitals and respiratory devices were not
rewritten. The production deployment and private GitHub connection were not tested.

## Clinical references behind the safeguards
SCCM, Sepsis Definitions: https://sccm.org/clinical-resources/sepsis-definitions
KDIGO Work Group summary, AKI definition: https://pmc.ncbi.nlm.nih.gov/articles/PMC4057151/
These references explain why simple medication or creatinine-difference triggers
are not equivalent to established diagnoses. The limited review rules above are
not represented as complete implementations of these definitions.
