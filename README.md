# PICU Handoff 6.73

## Current Shift outputs

This update adds a separate Current Shift block below the existing intake/output
summary in FEN/GI. The original 24-hour totals, calculations, labels, source
times, import behavior and editing controls are unchanged.

Synthetic example, using 20 kg and 7.5 elapsed hours:

```text
Current Shift (11pm - 6:30am)
UOP: 2.00 mL/kg/hr
Drains: 0.10 mL/kg/hr
Chest Tube: 0.20 mL/kg/hr
Other: 0.40 mL/kg/hr
```

Only supplied categories appear. Explicit zero remains zero. Missing categories
are not invented. Other is never added to UOP. No current-shift intake, total
output or net balance is displayed.

The new importer reads the H block's IO Current Shift / I/O this shift section.
It reads each category from the Out breakdown and uses that section's Weight.
It does not substitute the dosing weight or nutrition weight. The cutoff is
the source Intake/Output Summary timestamp within H, not Last data filed or
the time the handoff is printed later.

Shifts begin at 7am, 3pm and 11pm. Each rate is the documented volume divided
by the source weight and elapsed shift hours. The saved snapshot retains its
source cutoff when recalled or reprinted. Refresh it by pasting current data.

## Install

Extract PICU673.zip. Upload the contents of the enclosed application folder to
each existing app-code repository, replacing matching files. Keep app.py at its
existing deployed location. Include the new current_shift.py module.

Keep existing Streamlit Secrets, encryption key and encrypted data repositories.
Do not upload application files into a patient-data repository. No dependency or
schema migration is required. Restart and confirm:

Version 6.73 | Current Shift outputs

Re-paste each patient's SmartPhrase with the Current Shift section. Earlier
versions did not retain these values, so old saved handoffs cannot reconstruct
them. This ZIP has not been deployed to the hosted apps.

## Safety and retained features

Invalid or missing source time/weight withholds calculated rates. A failed new H
import clears the prior shift snapshot rather than leaving old rates available
as refreshed data. Import review explains the problem. Re-paste a valid current
source to restore the block. A partial update without H retains the original
snapshot and its original cutoff.

The output is a documented-volume average over elapsed shift time. It cannot
recover uncharted outputs or establish that charting is complete through the
cutoff. Source timestamps are interpreted in US Eastern time, matching the
existing app. Daylight-saving changes use actual elapsed hours. Ambiguous or
nonexistent source times and an exact shift-start time withhold rates.

The recent nutrition changes, including kcal/kg/day and omission of unknown
formula/rate, remain included. Medication mapping, storage and existing print
layout behavior are unchanged. See CURRENT_SHIFT_UPDATE.md and TEST_REPORT.md.
Packaged examples are synthetic.
