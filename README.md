# PICU Handoff 6.69

## AVAPS settings in Respiratory

When the invasive ventilation mode is Average Volume-Assured Pressure Support,
the handoff reads the AVAPS subsection of C. It includes the documented AVAPS
rate, target tidal volume, observed tidal volume, and minimum and maximum
pressure support. Blank settings and No data recorded are omitted.

This synthetic example shows the output:

```text
Mode: AVAPS
AVAPS rate: 3 cm H2O/min
Target TV: 130 mL
Observed TV: 145 mL
PS Min: 9 cm H2O
PS Max: 24 cm H2O
```

The nested source label AVAPS rate (cm H2O/min) retains that unit. It does not
become a respiratory rate in breaths per minute. A separately documented
Resp Rate (Set) still appears as Set RR. Target and observed volumes remain
separate. The new AVAPS fields are editable and survive encrypted save/recall.

The same settings appear in the app preview, text, HTML, PDF and Print All.
They display only with the invasive AVAPS mode. Other modes keep their existing
rules. Explicit noninvasive AVAPS continues to use the noninvasive parser.

FiO2 recorded in E remains in respiratory vitals. A blank C FiO2 is not filled
with a D or E value. See AVAPS_UPDATE.md for field mapping and compatibility.

## Included from 6.68

Cardiac shows the newest dated QTc Calculation(Bazett) supplied by the ECG
section, with no recency cutoff, as QTc: 425 msec [11/13/2026]. A value greater
than 450 is red, has (!), and adds Long QTc to Problems. Exactly 450 is unflagged.

NIRS appears in Neuro only when available, using minimum to maximum and the
latest value. Override-pull medication entries default to Ignore and stay out
of Other Medications and handoff exports. You can restore an individual entry
from Ignored / hidden medications. QTC_NIRS_OVERRIDE_UPDATE.md has the details.

## Install the update

This folder contains the complete application. Replace the application files
in each app-code repository, keeping app.py at its deployed location. If each
app already runs 6.68, the application code changes are app.py and ventilation.py.
Copy both together. UPDATE_FILES.txt also explains updates from 6.67.

Restart each app and confirm:

```text
Version 6.69 | AVAPS ventilator settings
```

Use each app's existing Streamlit Secrets, encryption key and separate data
repository. No new dependency or Secrets field is required. Paste the updated
SmartPhrase again to populate the AVAPS fields in an existing handoff.

## Validation and compatibility

See TEST_REPORT.md for executed checks and ARCHIVE_COMPATIBILITY.txt for saved
record details. The examples directory contains synthetic input and PDF/HTML
previews. The supplied clinical sample is not included in the package.

This package has not been deployed to the live apps. Existing QTc, NIRS,
medication controls, arterial BP, I/O headings and Mapping Sync are included.
