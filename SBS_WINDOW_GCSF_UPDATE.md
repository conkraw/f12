# Version 6.46: the explicit SBS 24-hour field and filgrastim

Built from the supplied PICU645.zip. This is a complete app package.

## SBS import

The K block now follows the user's named fields:

    Target Arousal Level:
    SBS Last 24 Hours:
    Last SBS Ever: Target Arousal Level (SBS): SBS -1

Only the content belonging to SBS Last 24 Hours is eligible. Last SBS Ever is
ignored, even when it contains a plausible score or a recent timestamp. In the
example above, the recent field is blank, so the handoff displays SBS: None.
A successful K import clears the old K warning and replaces the previous SBS
snapshot. Omitting K in a partial import leaves the current stored snapshot
unchanged. An included empty K clears the stored SBS record.

A single value from Epic's explicitly filtered 24-hour field does not require an
extra recording timestamp to be pasted. Zero is a real score. Identical repeated
values collapse to one. Different undated values are not guessed into a latest
observation and create an in-app import error, without blocking other sections.

When explicit observation dates AND times are present, the latest score within
the rolling preceding 24 hours is used. Older and future observations are not
selected. Date-only observations do not establish an exact last-24-hour reading.
An explicit target label is preserved as SBS target, never relabelled as measured.

For an untimed value from the explicitly filtered field, the stored time is a
REPORT/SNAPSHOT time, not an observation time. The printed S-section I/O summary
time is used as the SmartPhrase snapshot time, with H as fallback. For a K-only
paste, the import time anchors the snapshot. The app relies on Epic's field label
to establish the source's 24-hour filtering. It cannot know an individual
observation's exact age without a recording timestamp. Refresh from Epic for a
current snapshot. An undated snapshot is not printed more than 24 hours after its
report/import time. Saving, editing a value, or switching rooms never renews it.

The compact printed line contains no extra timing explanation. The editor shows
snapshot provenance and permits editing/hiding the source-filtered value. Adding
an explicitly timestamped observed SBS replaces the untimed snapshot provenance.
CAPD and WAT-1 retain their existing order after SBS.

## Hematology category

Filgrastim, filgrastim biosimilar names, and the supported product aliases now
default to Hematology / G-CSF Stimulator. The requested GM-CSF label was corrected
explicitly: filgrastim is a granulocyte colony-stimulating factor, not GM-CSF.
Reference: the FDA-approved NEUPOGEN label hosted by DailyMed:
https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=97cc73cc-b5b7-458a-a933-77b00523e193

The category remains editable and can be nested in Admin. Existing explicit
assignments and hidden settings retain priority. No medication order, dose,
route, frequency, or saved administration rate is changed or duplicated.
Sargramostim and pegfilgrastim are not newly auto-assigned by this narrow rule.

## Upgrade from 6.45

Upload the complete contents of this folder into your existing application code
folder, replacing matching files. Keep app.py at the root. Restart the app and
refresh the browser. There are no new dependencies.

Keep both passwords, private Secrets, encryption key, mappings, custom category
settings, BMI reference data, and the shared data archive unchanged. Do not run
the setup generators. The archive schema upgrades from 30 to 31 to support the
SBS window provenance and the new built-in category. Avoid downgrading after save.

Re-paste the complete K section or full SmartPhrase, click Create / update
handoff, then save. The new category applies to existing stored medication rows,
unless an explicit category assignment overrides it.

Sidebar: Version 6.46 | SBS 24-hour field and G-CSF category
