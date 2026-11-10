# PICU Handoff 6.17: Medication groups, CV infusions and calcium

Complete ZIP update. No direct repository changes were made.

## Installation

Save open work, extract PICU617.zip, and open PICU_Handoff_v6_17_Medication_Groups.
Copy all contents into the existing app-code repository, replacing matching
files. Keep app.py at the root. Include the new medication_groups.py. Restart
the deployment and refresh each team member's browser session.

Keep the existing Streamlit Secrets, password, encryption key, token, private
data repository, mappings and hidden-medication rules. Do not run the secrets
generator. No new dependencies are needed. Schema 17 adds one empty reusable
medication_groups setting when opening an older archive. All previous settings
and room fields, including Version 6.16 import warnings, are preserved. The next
successful save writes schema 17. Do not mix files or downgrade only part of the
application after saving with the new version.

Sidebar: Version 6.17 | Medication groups, CV infusions and calcium

## Automatic display groups

| Column | Heading | Rule |
| --- | --- | --- |
| HEME | DVT Prophylaxis | Enoxaparin and cangrelor. Heparin only when its ordered Dose explicitly contains a numeric Units/kg/hr value or range. |
| FEN / GI | Diuretics | Bumetanide, chlorothiazide and furosemide. |
| NEURO | Fever Control | Acetaminophen and ibuprofen, scheduled or PRN. |
| NEURO | PRN | Fentanyl, midazolam, ketamine, morphine and hydromorphone with PRN/as-needed frequency. |
| NEURO | Paralytic PRN | Rocuronium, cisatracurium and vecuronium with PRN/as-needed frequency. |
| CARDIAC | CV Infusions | Continuous parenteral orders mapped to Cardiovascular, or an explicit infusion display choice. |

These are the user's display labels, not inferred clinical indications.
In particular, the DVT Prophylaxis heading does not determine whether an
antithrombotic is being used for prophylaxis or whether its dose is prophylactic.
The Units/kg/hr condition applies only to heparin, not enoxaparin or cangrelor.
Heparin flushes, catheter locks, irrigation mixtures and mL/hr carriers do not
qualify by their name, concentration or Last Rate. The actual Dose field is used.
No dosing values, concentrations, rates, indications or missing values are
calculated, substituted or supplied by a group.

Known held/start/sequence prefixes do not interfere with matching. Those labels
remain on the handoff. Orders remain separate, even when names repeat. Hidden
and excluded orders remain hidden/excluded. Each visible order appears once.
Custom handoff wording stays authoritative. The original medication records and
existing system mappings are kept, even when an automatic display group takes
precedence. No new broad drug-name mapping is silently written.

## Visual order and emphasis

NEURO: imported observations first, then Infusions, PRN, Paralytic PRN,
Fever Control, separate notes and remaining medications. Empty headings do not
print. Infusions replaces the old all-capitals heading.

CARDIAC: vitals remain at the top, then any lactate, then CV Infusions, separate
notes and remaining medications. CV infusion names are bold. The explicit Dose
is bold and underlined, like the neurologic infusions. A different recorded pump
rate stays on a separate line. Dose units are not confused with pump-rate units.
PRN syringes are not inferred to be continuous infusions from the product name.

FEN / GI: Intake/Output/Net remain first, followed by GI prophylaxis,
Bowel Regimen, Diuretics, separate notes and remaining medications.

HEME: DVT Prophylaxis, then separate notes and remaining hematology medications.
Existing vital-sign positioning is preserved.

The same grouping drives the editor previews, PDF, HTML, text and Print all.
PDF and HTML carry the bold formatting. Plain text carries the group names.
Compact one-page fitting and safe continuation pages remain supported. Infusion
names and their doses are kept together where feasible rather than clipped.

## Overrides

In Medications, use Medication group to choose Automatic, one of the four
special groups, or No special grouping. Use FEN/GI display for the GI groups,
including Diuretics. Neuro and CV display controls share the existing infusion
setting. Changing the system away from an automatic destination disables the
conflicting group for that formulation, route and frequency.

Choices save through the existing encrypted archive. Admin now includes
Medication subgroup choices as well as FEN/GI display choices and Infusion
display choices. They remain editable when no handoff is open. Failed saves do
not claim persistence or alter the draft. Room autosave captures pending choices.
Hidden-medication controls remain separate and take precedence over all groups.

Automatic defaults apply when displaying existing saved orders. Re-pasting is
not required just for these headings. Saved overrides can still change their
presentation. Updated shared rules affect open drafts and subsequent imports,
not the historic content of closed saved handoffs without a save/reimport.

## Calcium

The existing lab parser already recognizes CA as calcium. Regression tests now
explicitly verify CA beside Mg and Phos beneath both latest and preceding BMP
trees, with the recorded dates and abnormal flags. Calcium is not calculated
from albumin and is not substituted for ionized calcium. No result is invented
when CA is absent. Paste a full G block including CA to add a newly supplied
result. The G block replaces its previous lab snapshot, so include the other
G-block results you still need.

CBC Q selection, latest gas P selection, ANC/ALC, specimen/time handling and the
lab drawing code are unchanged. Their source files compare byte-for-byte with
the original Version 6.16 package.

## Testing and example

See TEST_REPORT.md for executed checks and limitations. The synthetic example
in examples/synthetic_medication_groups.txt is a layout fixture, not a treatment
plan. It does not add example buttons back to the daily screen. The packaged
examples/medication_groups_preview.pdf is a one-page landscape preview. Its
milrinone and dexmedetomidine were mapped to Cardiovascular and Neurologic for
that illustration. Other requested name-based groups work without new mappings.

Room-change autosave, custom-room removal, P-prefixed presets, partial-import
recovery, encrypted technical error logging, timestamping, and all prior
features remain. No user handoff archive, deployment secret or live storage
connection was accessed for this update.
