# Version 6.25: ETCO2 and CVP in vital signs

This is the complete app package, based on Version 6.24. No live GitHub
repository or hosted app was accessed or changed.

## New display

E / VITALS now accepts the Epic summaries for ETCO2 and CVP, including a line
without a colon between the monitor name and Avg. The recorded Min and Max
print in the same range-only style as SpO2. Avg is omitted.

Synthetic examples:

ETCO2 (mmHg) Avg: 42.2 mmHg Min: 28 mmHg Max: 61 mmHg
becomes ETCO2: 28 to 61 mmHg, at the top of RESP with respiratory vitals.

CVP (mean) Avg: 7.4 mmHg Min: 3 mmHg Max: 12 mmHg
becomes CVP (mean): 3 to 12 mmHg, at the top of CARDIAC with cardiovascular vitals.

Both come before support, infusion groups, other medications and manual notes.
No mapping is required. The existing Labs / Vitals editor allows correction or
exclusion. PDF, HTML, plain text, Print all, and existing saves use the same rows.

## Missing information and boundaries

The exact missing-data line No data recorded is ignored. Explicit missing-data
markers after a recognized ETCO2 or CVP label are also omitted. No placeholder,
zero, normal value, or inferred monitor result is created.

Ordinary labeled measurements, including a single value or bracketed range,
stay verbatim. Numeric Min/Max summaries preserve recorded decimal precision,
zeros and negative CVP values. Pressure units are preserved and only typography
is normalized. There is no unit conversion and no clinical clipping of extreme
values. A supplied ETCO2 maximum above 100 is not treated as an SpO2 percentage.

The app does not use blood-gas PCO2, chemistry CO2, an order to monitor CVP,
previous rooms, or another section to supply these vital signs.

Incomplete or conflicting summary limits are not guessed. The existing section
recovery displays a warning, retains the previous E snapshot as not refreshed,
and allows valid unrelated sections to import. No missing endpoint is filled
from the average. Duplicate conflicting limits and inconsistent units are
reported, not silently resolved.

## Updating a handoff

After installation, re-paste the full SmartPhrase or the complete E / VITALS
block, including the other vital signs you need. Click Create / update handoff.
Importing E replaces all E-block vital signs. Omitted E preserves the earlier E
snapshot. An empty or missing-data-only E clears it. No data from K/L/M is
cleared by an E update. Repeated import does not duplicate the rows.

Previously saved records are not reparsed automatically. Existing fields,
settings, passwords, encryption key, saved timestamps, room lists, reset
generation and medication choices remain unchanged.

## Install

Extract PICU625.zip, open PICU_Handoff_v6_25_ETCO2_CVP, and copy all its contents
into the existing application code repository. Replace matching files and keep
app.py at the repository root. Restart the deployment and refresh the browser.

Keep Streamlit Secrets, both passwords, the encryption key, GitHub token and
private data repository unchanged. Do not run the setup generators again.
Dependencies and the schema-19 storage format are unchanged. Installation
clears no handoffs. No direct GitHub write is part of this update.

Expected sidebar: Version 6.25 | ETCO2 and CVP in vitals

See TEST_REPORT.md for the exact validation performed and its limits.
