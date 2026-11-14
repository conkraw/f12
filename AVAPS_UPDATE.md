# AVAPS settings in v6.69

When the invasive C-block mode is Average Volume-Assured Pressure Support,
the handoff uses the new AVAPS subsection. All available settings below appear
in Respiratory, below Vent Settings.

| Source | Handoff label | Unit handling |
| --- | --- | --- |
| AVAPS Respiratory Rate: AVAPS rate (cm H2O/min) | AVAPS rate | Preserves cm H2O/min from the inner source label |
| AVAPS Target TV: Vt Set/Target ml | Target TV | mL |
| Observed AVAPS TV: Vt (observed, mL) | Observed TV | mL |
| PS Min: Pressure Support Min (cm H2O) | PS Min | cm H2O |
| PS Max: Pressure Support Max (cm H2O) | PS Max | cm H2O |

## Source handling

The AVAPS rate in the supplied source has pressure/time units. It is not
converted or relabeled as Set RR. If a value explicitly disagrees with the
source unit, both the source label and value are retained and the import
reports a review issue. An actual Resp Rate (Set) stays separate.

Target and observed tidal volumes are stored separately. A dedicated AVAPS
observation takes priority over a generic C-block observation for AVAPS.
If the dedicated observation is missing, the existing generic observation or
documented expiratory/inspiratory observation can be shown. If the target is
missing, a documented conventional Vt (Set, mL) retains its Set TV label.

Blank settings and No data recorded are omitted. The new AVAPS subsection
does not add an AVAPS mode on its own. Its settings display only when the
documented invasive mode is AVAPS. A generic observed TV in another mode
cannot be replaced by the dedicated AVAPS observation.

The existing C/D boundary remains in place. D FiO2 is not substituted into
a blank C setting. FiO2 from E appears in respiratory vitals as before.
Explicit noninvasive AVAPS remains on the existing noninvasive path.

## Editing, recall and exports

The new values appear in the existing ventilation editor, and pending edits
are captured before printing. They use the same encrypted save/recall and
shared formatter as the other ventilation fields. App preview, text, HTML,
PDF and Print All therefore use the same AVAPS settings.

A fresh successful C/D import replaces the prior respiratory support snapshot.
Switching to another mode clears prior AVAPS settings from that snapshot.
Conflicting repeated fields use the existing section-review behavior.

## Update

Use app.py and ventilation.py together when upgrading from v6.68, or copy the
complete application package. Restart, confirm Version 6.69, then re-paste the
SmartPhrase. Existing archives open without migration. New AVAPS fields require
v6.69 or later after they are saved. Dependencies and Secrets are unchanged.

The examples folder includes synthetic AVAPS input and previews. QTc, NIRS
and override-pull changes from v6.68 remain included.
