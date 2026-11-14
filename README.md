# PICU Handoff 6.75

Built from the supplied PICU674.zip. No live application or repository was changed.

## What changed

Current Shift now uses 7am-7pm and 7pm-7am shifts instead of the previous
7am/3pm/11pm schedule. Every output rate uses the actual elapsed time from
7am or 7pm to the source I/O summary timestamp, not a fixed 12-hour denominator.
At 6:30am the interval is 7pm-6:30am, or 11.5 hours on an ordinary day.
At 5:12pm the interval is 7am-5:12pm, or 10.2 hours.

UOP, Drains, Chest Tube and Other remain separate, all in mL/kg/hr.
The current-shift Weight remains the denominator. Last data filed and later
print time are never substituted for the source summary timestamp.
Missing/invalid source time or weight and zero elapsed time still withhold rates.
Eastern daylight-saving changes use actual elapsed time. Ambiguous local times
remain withheld rather than guessed.

Only the label "Last BM (24 Hours):" is bold. Yes/No is regular weight.
The line sits directly beneath the Bowel Regimen medications, or the empty
Bowel Regimen line, without a blank line, added gap or separator above it.
AC stool detection and the stored boolean are unchanged. No still means no
positive documented signal, not proof that a bowel movement did not occur.
The undated AC data must already represent the intended past-24-hour window.

## What did not change

The 24-hour I/O values, source timestamps, calculations, labels and H/S source
selection are unchanged from 6.74. Nutrition, medication mappings, other clinical
parsers, encryption, storage and dependencies are also unchanged.

## Install

Extract the ZIP and replace matching application files in the app-code repository.
The five required changed modules are listed in UPDATE_FILES.txt. No new module
or dependency is needed relative to 6.74. Do not replace Streamlit Secrets,
encryption keys or separate encrypted data/mapping repositories.

Restart the deployment and confirm:
Version 6.75 | 12-hour shifts + BM label

Existing 6.73/6.74 current-shift snapshots store volumes, weight and source time,
not precomputed rates. Opening or reprinting them in 6.75 automatically uses the
corrected schedule. Re-pasting is not required solely for this correction.
Old downloaded PDFs/HTML/text files will not change. Download fresh copies.
Re-paste only to refresh clinical data or to recover data never imported.

Update every deployment that should use the corrected schedule. An older
running build will still calculate using its old schedule even with the same data.

## Verification

597 selected tests passed in completed runs: 238 focused and 359 compatibility.
Tests cover 7am/7pm boundaries, every minute of an ordinary day, overnight and
calendar crossings, daylight-saving behavior, all requested output categories,
legacy encrypted snapshots, unchanged 24-hour I/O, UI callbacks, label-only
bolding, and no added vertical gap in individual/Print All PDFs.
Synthetic one-room and two-room PDFs were generated and the one-room layout
was visually checked. See TEST_REPORT.md for commands and limits.
