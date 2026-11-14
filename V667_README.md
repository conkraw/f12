# PICU Handoff 6.67

## Arterial blood pressure layout

When arterial pressure readings are available in the E vital-sign block, the
cardiac section groups cuff blood pressure, arterial BP and arterial MAP:

```text
Cuff: BP (88-116)/(42-70) 104/54
ART BP: 80/40 to 112/65 [last 108/60]
ART MAP: 52 to 75 mmHg [last 72]
```

These are synthetic example values. Cuff BP is unchanged when no arterial
pressure reading is present. The source minimum/maximum BP pairs remain paired.
No MAP, endpoint or latest value is calculated. The average is not substituted
for a missing endpoint. Missing readings are not displayed as zero.

The latest value is appended when a single compatible latest reading is
available. Conflicting latest readings or mismatched units stay separately
labeled rather than being silently reconciled. Explicit inclusion choices and
vital-sign section overrides remain in effect.

Older saved arterial vital rows are recognized at display time. This changes
presentation, not the stored patient values. A handoff that never imported the
arterial readings needs a new E-block import before they can appear.

## Intake/Output hour window

For a source summary explicitly covering 24 hours, the title uses the hour
of the summary's own timestamp:

| Source summary time | Printed heading |
| --- | --- |
| 06:00 through 06:59 | Intake/Output (6a-6a) |
| 07:10 | Intake/Output (7a-7a) |
| 18:16 | Intake/Output (6p-6p) |
| 00:10 | Intake/Output (12a-12a) |
| 12:10 | Intake/Output (12p-12p) |

The heading abbreviates the hour. It does not recalculate totals or assert that
the source was collected exactly at minute zero. The full source date/time,
including minutes, remains visible in the editor's As of line.

The timestamp is taken from `Intake/Output Summary (Last 24 hours) at ...` in
the S block. It is not taken from Last data filed, the server clock, or the time
you later reprint a saved handoff. A 6 a.m. snapshot stays labeled 6a-6a when
reprinted later. Import a newer S block to update the snapshot and its window.
Each patient retains their own source hour in Print All.

When the source time is missing/invalid or the reporting period is not explicitly
24 hours, the heading remains Intake/Output. No reporting window is guessed.

## Deploy on web-based Streamlit

Replace the application files in each app-code repository with this folder's
contents, keeping app.py at the location used by that app. Include the new
arterial_pressure.py module. Restart the app and confirm:

`Version 6.67 | Arterial BP and I/O time windows`

Keep all existing web-based Streamlit Secrets, repository settings and the same
encryption key. No new Secrets fields or dependencies are required. Do not
replace files in the encrypted data repositories.

The package includes the complete application. UPDATE_FILES.txt identifies the
six application files changed from v6.66. Existing Mapping Sync diagnostics,
medication groups and patient-recall storage remain in place.

## Validation and scope

See TEST_REPORT.md for executed tests and verification limits. No live GitHub
repository was accessed or changed, and this package has not been deployed to
your apps. The example handoff you supplied is not included in the ZIP.

See ARTERIAL_BP_IO_UPDATE.md for implementation details and
MAPPING_SYNC_SETUP.md for the unchanged Mapping Sync configuration.
