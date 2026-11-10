# Version 6.44: empty medication groups and ICP/CPP

Built from the delivered Version 6.43 package.

## Empty medication groups

The handoff shows these compact entries when their categories contain no orders:

- Hematology: DVT Prophylaxis: None
- FEN/GI: GI Prophylaxis: None, Bowel Regimen: None, Diuretics: None
- Neurologic: Fever Control: None

A populated category lists its medications instead. No order is duplicated or
moved by this display change. Existing categorization, infusion emphasis,
exclusions and visibility choices are preserved. Renamed or moved built-in
categories follow their configured name, system and parent category. A drug in
a subcategory counts as present in its parent.

None is based only on the medication list and category assignments available
in this handoff. It is not a query of the live medication chart. A hidden or
excluded order still counts as present, so hiding a drug does not falsely
produce None. When B fails to import, empty-category claims are suppressed.
These safeguards do not unhide medications. Empty default rooms are still
excluded from Print all.

## M-section pressure trends

Accepted source examples include:

    ICP Range: 1-22 mmHg
    Last ICP: 10 mmHg
    CPP Range: CPP Avg: 63 mmHg Min: 45 mmHg Max: 85 mmHg
    Last CPP: CPP: 68 mmHg

An optional ICP Trends heading and Epic's repeated labels are supported.
Range/Last values can also follow their labels on the next line.

The printed output is:

    ICP: 1-22 [10 mm Hg]
    CPP: 45-85 [68 mm Hg]

Only documented endpoints and last readings are used. The average is not
substituted for a missing value. A range without a last reading prints with
units but no brackets. A last reading without a range prints as one value.
Zero, negative and decimal values are retained. No data recorded and empty
fields do not become numeric readings. The older single-value M format is
unchanged. No unit conversion, pressure calculation or normal-range judgment
is performed.

New ranges and last readings are editable independently in Labs / Vitals,
under Neurologic observations. An omitted M leaves prior M values unchanged.
An included empty M clears them. An invalid M does not block other sections.
Its previous values remain in the editor but do not print until a successful
reimport. Existing in-app warnings and technical error logging remain in use.

SBS, CAPD and WAT-1 keep their previous order. ICP/CPP remain in the neurologic
observations above the medication groups. CAPD: None behavior is unchanged.

## Install

Upload this folder's contents into the existing application code directory,
replacing matching files. Keep app.py at the root. Include empty_groups.py and
icp_cpp.py. Restart the deployment and refresh the browser.

Keep current Secrets, passwords, encryption key, medication mappings, category
settings, BMI reference data and shared storage unchanged. Do not rerun setup
generators. No dependency changes are required.

Existing handoffs get the empty-category display without re-pasting. Re-paste
the complete M section or full SmartPhrase to capture the new pressure fields,
then Create / update handoff and Save handoff.

The archive advances from schema 28 to 29 to support optional layout snapshots
for renamed/moved empty groups. Existing clinical values, timestamps and settings
are preserved. Avoid downgrading after saving with this release.

No live deployment, private archive or clinical connection was accessed.
