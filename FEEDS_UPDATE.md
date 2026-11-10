# Version 6.24: feeds from T in FEN/GI

## Display

Intake, Output and Net remain at the top of FEN/GI. Feeds follows a separator,
before GI prophylaxis, Bowel Regimen, Diuretics, notes and other medications.
The same block is used in the screen preview, PDF, HTML, text and Print all.

```
Feeds:
Feeding Method: NJ
Nutramigen @ 24 mL/hr
```

The new parser reads only the T section. It does not change the CBC, blood-gas,
medication, lab-result or recurring-order parsers. It does not consult orders in
R to fill gaps in the T snapshot.

## Which lines are used

Lines marked [REMOVED] are ignored entirely. They supply neither a method nor a
formula nor a rate. A removed-only section clears a previous feeding snapshot.

The full device label connects its formula with its own rate. Each unremoved
device keeps a separate entry. A rate from an NJ device is not assigned to a GT,
even when the formula names look similar. Unremoved entries are documented
source entries, not proof of simultaneous current bedside use.

Recognized routes include NJ, NG, OG, ND, GT, GJ, PEG, PEG-J, J, PEJ and PO.
A generic post-pyloric label remains Post-pyloric rather than being assumed NJ.
An unidentified method is UNK. Formula spelling and qualifiers are retained.
The Other (Comment) wrapper is removed when an actual formula follows it.

## Rate priority

Use the recorded hourly rate on the same device first. In the supplied Epic
format, the label Continuous Tube Feeding Ordered Rate mL/hr explicitly gives
the units, so a cell containing 24 mL is read as the documented 24 mL/hr rate.

If no usable primary rate is supplied, use an explicitly hourly Back Up Feed
Rate belonging to that same device. A generic backup rate is applied only when
there is exactly one active device. The editor identifies backup-derived rates.

An intake or volume of 87 mL is not an hourly rate. Back Up Feed Intake and
Intake (mL) are retained for review but never relabeled as mL/hr. If neither an
hourly primary nor backup rate can be established, the summary shows @ UNK.
No rate is calculated from total volume, duration, tube size, a previous handoff,
another tube, or a source order elsewhere in the paste.

Conflicting primary rates produce UNK and a review warning, not a choice of the
highest, lowest or backup rate. Zero is a recorded value and remains 0 mL/hr.

## Editing and reimporting

Go to Edit handoff, expand FEN / GI, then Edit feeds / review source. Change the
method, formula or rate, or uncheck Include this feeding entry. Use a rate with
mL/hr, or leave it blank for UNK. Source tube descriptions and backup intake
volumes are available in this editor but do not print.

Paste the full SmartPhrase or just paired T dividers, then click Create / update
handoff. The new T snapshot replaces previous automatic feeds without changing
separate notes. Omitting T preserves the snapshot. Empty T clears it.

A failed whole-T import does not cancel other sections. Previous feeds stay in
the editor but are hidden from the handoff until reviewed or reimported. Partial
conflicts keep readable fields and mark uncertain fields UNK. Existing technical
error reporting handles these diagnostics without storing raw feed text in logs.

Room-change autosave, saved timestamps, clear-all, custom-room deletion and
Admin access continue to work. Clear-all also clears feeding entries.

## Install and preserve settings

Extract PICU624.zip and upload the contents of PICU_Handoff_v6_24_Feeds into the
existing code repository. Keep app.py at the root, replace matching files and
include feeds.py. Restart the deployment and refresh the browser.

Keep app and Admin passwords, encryption key, token and private storage settings.
Do not run either password or key generator again. Dependencies are unchanged.

Schema 18 archives migrate to schema 19 by adding feeds=None to each handoff.
Earlier schemas remain supported. Existing fields, settings, reset generation
and save times are preserved. The next successful save uses the new schema.
Do not downgrade the application after saving with this version.

## Validation scope

Read TEST_REPORT.md. Supplied T excerpts were tested separately and were not
included as patient records in this package. Included example files are synthetic.
Hosted Streamlit and authenticated private GitHub storage were not tested.
