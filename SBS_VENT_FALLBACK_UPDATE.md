# Version 6.48: ventilator-gated last-available SBS

Built from the supplied Version 6.47 package. This change is limited to SBS
selection, the source-mode condition for its historical fallback, and the
related editor and archive validation. The recent VANCOTROUGH filter, short
Handoff instructions, protected Delete all action, bold empty group labels,
medication categories, printing layout and other clinical parsers are retained.

## Selection order

1. Use the newest eligible timestamped SBS in the last 24 hours, or the existing
   valid Epic-filtered SBS Last 24 Hours snapshot.
2. Only when there is no such value, use the separately parsed Last SBS Ever
   result if the saved respiratory snapshot contains a recognized Vent Mode.
3. Without a qualifying mode or a usable historical result, the explicit recent
   field continues to show SBS: None. An entirely absent K section retains the
   existing no-SBS-line behavior.

The mode list includes all 22 labels supplied previously, their existing display
abbreviations, and the generic PC/PRVC/VC families already recognized by the app.
It includes the named noninvasive CPAP, BiLevel, AVAPS and NAVA modes. A positive
pressure inferred only from D does not satisfy this rule. HFNC, nasal cannula,
room air, a tracheostomy or ETT alone, unknown labels and blank modes do not.
An explicit Ventilator On: No/Off/False blocks the historical fallback.

A mode-presence rule is not an independent confirmation of current bedside
ventilator use. Review carried-forward Epic mode fields before sharing a sheet.

## Historical display

Example observed result: SBS: -1 (last available)
Example source-labelled target: SBS target: -1 (last available)

A supplied observation date/time is retained in brackets. An undated historical
value remains undated. Neither import time, report time nor save time is assigned
as a measurement time. Targets stay targets and are never called observed SBS.
Zero remains a valid result. Recent data always takes priority over the separate
Last SBS Ever field. Conflicting, future-dated, invalid and excluded historical
values are not used. A failed K import suppresses both recent and historical SBS.
A failed respiratory import suppresses historical fallback but does not suppress
a valid recent SBS. No additional warning text is printed on the handoff.

The result stays above CAPD and WAT-1. No extra line is added beyond the single
SBS line. The rule is the same in preview, PDF, Print all and text generation.

## Import and editing

Keep the current paired K structure:

    Target Arousal Level:
    SBS Last 24 Hours:
    Last SBS Ever: Target Arousal Level (SBS): SBS -1

With a recognized C-section Vent Mode, this produces the historical target
example above. The K parser stores its recent and historical values separately.
A recent-only partial update still replaces K, rather than carrying history
from a previous K import. Omitting K preserves the saved record. Empty K clears it.

Successful respiratory imports replace the mode condition along with the C/D
snapshot. A D-only replacement with no C mode clears the condition. Clearing a
ventilator block or removing the corresponding pressure device in the editor
also disables its historical fallback. Re-paste C and D together for a complete
respiratory refresh. Modes remain stored independently of whether the rendering
rules have enough pressure/settings data to print a CPAP or BiPAP device.

Labs / Vitals -> Neurologic observations -> Observed SBS / recording time
shows the selected result, the qualifying mode and the Last SBS Ever fields.
The historical value, supplied date/time and inclusion flag can be edited.
An explicit exclusion remains respected. New patient and Delete all still clear
these fields with the rest of the patient record.

## Install

Replace matching application files with this folder's contents. Keep app.py at
the root. Restart the app and refresh your browser. Preserve your current
Secrets, passwords, encryption key, categories, medication mappings, BMI
reference data and shared archive. Do not rerun setup generators. No new
Python dependencies are required.

The sidebar shows Version 6.48 | Ventilator-gated SBS fallback.

The archive schema upgrades from 31 to 32 without changing existing room fields,
save times or settings. This is required to retain the historical result and the
explicit source-mode condition. Earlier versions discarded Last SBS Ever, so
re-paste the complete C, D and K sections or the full SmartPhrase to capture it.
Existing stored timestamped observations and legacy targets can be used when
they already include the needed data. Do not downgrade after saving schema 32.

These are software display rules, not clinical assessment or sedation advice.
See TEST_REPORT.md for local verification and limitations.
