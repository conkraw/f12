# PICU Handoff 6.68

## QTc from the ECG section

The new Z block reads QTc Calculation(Bazett) and the date of its ECG.
Cardiac displays the newest dated Bazett result supplied, with no recency or
admission-date cutoff. A result from years ago remains eligible.

```text
QTc: 425 msec [11/13/2026]
```

When the value is greater than 450 msec, the QTc line is red in the preview,
HTML and PDF, includes (!), and adds Long QTc to the existing Problems review.
Exactly 450 is not flagged. The threshold follows the requested display rule.
A newer normal QTc removes the automatic flag and Long QTc problem.

The parser uses the explicitly named Bazett result, not Q-T interval or another
QTc formula. Multiple ECGs are selected by their own dates and available times.
An undated result does not receive an invented date. Conflicting newest results
remain available for review through the existing import warning workflow.

Only the QTc value and ECG date are retained. The ECG narrative is not stored.
A new empty Z block clears the snapshot. Omitting Z keeps the prior snapshot.
An unreadable Z block retains previous data for review but hides its automatic
QTc and Long QTc output until reviewed or successfully reimported.

## NIRS in Neuro

The E vital-sign block accepts NIRS Range and Last NIRS, including Epic's
repeated rSO2 Cerebral % label. A synthetic example displays:

```text
NIRS: 60% to 68% [last 66]
```

The summary uses documented minimum, maximum and latest values. It does not
use the average as an endpoint. Absent NIRS data produces no placeholder.
Partial data keeps its available labels. Existing inclusion and section
controls continue to apply. A fresh E block without NIRS removes prior NIRS.

## Override-pull medication entries

Medication names containing Override Pull, including ADS Override Pull and
Override-Pull, default to Ignore. They do not appear in system medication
lists, Other Medications, or individual and combined handoff exports.
A normal order for the same medication remains visible.

Open Medications, then Ignored / hidden medications to find these retained
entries. Choose Restore to handoff or select a specific category to include
one deliberately. The exact entry's choice is remembered for future imports.
Broad drug mappings and automatic drug groups do not restore an override entry.
Existing saved override entries are also excluded without requiring reimport.

## Install the update

This folder contains the complete application. Replace its application files
in each app-code repository, keeping app.py at its existing deployed location.
Include the new ecg.py and nirs.py modules. UPDATE_FILES.txt lists the files
changed from v6.67. Restart each app and confirm:

```text
Version 6.68 | QTc, NIRS and override-pull medications
```

Use the existing Streamlit Secrets, encryption key and separate data repository
for each app. There are no new dependencies or Secrets fields. Update all three
apps before syncing mappings that use the new Ignore destination.

Paste the updated SmartPhrase again to add ECG and NIRS to an existing handoff.
The included SMARTPHRASE_TEMPLATE.txt illustrates the new Z boundaries and E
labels. Keep your institution's real SmartLink definitions.

## Validation and compatibility

See TEST_REPORT.md for executed checks and ARCHIVE_COMPATIBILITY.txt for saved
record details. The supplied clinical sample is not included in this package.
The examples directory contains a separate synthetic input and PDF/HTML preview.

The package has not been deployed to your live apps. Existing arterial BP,
source-hour I/O headings, medication mappings and Mapping Sync remain included.
