# Version 6.34: week-old age parsing and flagged blood-count rules

## Age and sex

Epic's `Age:` followed by `5 wk.o.` on the next line is now accepted.
`Sex:` followed by `male` on the next line is also recognized. The handoff
places Age and Sex directly beneath Room, not in the diagnosis text.
Same-line metadata and existing years/months/days wording remain supported.
The abbreviated wk.o., wks.o., mo.o., mos.o., yr.o. and yrs.o. forms are
interpreted without changing their displayed wording. Infant ages do not
become an invented precise age in months for a BMI calculation.
BMI and its percentile remain hidden below age two.

## Problems

The compact Problems line now prints names without an automatically added
Possible prefix. It remains comma-separated, not a multi-line explanation.
Supporting observations and limitations remain in the Problems editor.
Removing a display qualifier does not change an item's review status, mark
it clinically confirmed, modify imported Diagnoses, or validate the diagnosis.
Saved hide and confirm choices and clinician-entered custom wording remain.

Two clinician-requested default rules were added:

- Asterisk-flagged hemoglobin below 11.5 g/dL produces Anemia.
- Asterisk-flagged platelets below 175 K/uL produces Thrombocytopenia.

Equality does not trigger either rule. A value without an asterisk does not
trigger the new asterisk-based rule. Existing L / LL / LOW handling remains.
The latest eligible CBC data are used, not the lowest historical value.
Standard hemoglobin still takes precedence over ISTAT, with ISTAT used only
when standard hemoglobin is unavailable. CBC trees are unchanged.

Matching source units are required. Numerically equivalent platelet units
such as 10^9/L are supported. Missing or unrelated units are not guessed or
silently converted. Patient-specific low-result limits, when explicitly set
in the Problems editor, take precedence over these defaults for that component.
These are configured workflow thresholds, not universal pediatric diagnostic
reference ranges. Check generated labels against the patient's clinical context.

## Install

Save open work. Extract PICU634.zip and upload the contents of
PICU_Handoff_v6_34_Age_Problems to the existing application code repository.
Replace matching files and keep app.py at the root. Restart the deployment
and refresh your browser. Re-paste the complete A section or full SmartPhrase,
click Create / update handoff, then Save handoff to repair a previously failed
age/sex import. The Problems display and thresholds apply to existing saved
eligible results without re-pasting.

Keep existing Streamlit Secrets, both passwords, encryption key, medication
mappings, private storage, and the public BMI reference file. Do not rerun the
setup generators. No new dependencies or archive schema changes are required.
No direct changes to a live GitHub repository are made by this package.
