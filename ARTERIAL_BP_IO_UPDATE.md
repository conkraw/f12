# v6.67: arterial BP and source-hour I/O headings

## Changed application files

- arterial_pressure.py: new explicit arterial-label parser and nonmutating
  display adapter for new and legacy saved vital rows.
- vitals.py: arterial import handling and shared display adapter.
- fluid_balance.py: source-time validation and hour-window heading helper.
- fen_gi.py: shared heading in plain-text and rich-text output.
- clinical_style.py: emphasis for Cuff, ART BP, ART MAP and separate latest labels.
- app.py: version caption, matching I/O editor heading and source-time explanation.

## Behavior boundaries

Arterial labels must be explicit. An ordinary MAP, CVP, cuff BP, blood gas or
arterial-line device entry is not used as an arterial pressure measurement.
The parser reads the BP minimum/maximum pairs exactly as documented. It does
not independently combine the highest or lowest systolic/diastolic values.

Complete arterial summaries show their explicit Min and Max. Partial summaries
retain the supplied statistic labels. No missing endpoint is filled from Avg
or from the latest reading. Conflicting values/units in a new summary retain
the prior E block through the existing import-review warning workflow.

Arterial output is grouped at the cuff BP position when a cuff row exists.
Otherwise only the available arterial lines are shown. Other vitals remain
available. Included/excluded rows and explicit section overrides are respected.
The formatted output does not mutate the original vital rows.

I/O labels are based only on an explicit 24-hour source snapshot and its valid
summary date/time. The hour is truncated for display, never rounded to the next
hour. 12 a.m. and 12 p.m. are distinct. Missing time or a different reporting
period produces the original generic heading. Last-filed time is not a fallback.
Totals, source timestamps and the original reporting-period field are unchanged.
Reprinting does not change a stored snapshot's label or its totals.

## Compatibility

Archive schema remains 34. models.py, security.py, github_store.py,
mapping_sync.py, mapping_sync_ui.py, sync_diagnostics.py and requirements.txt
are unchanged from the supplied PICU666.zip. No storage migration, new key,
new Secrets field, or repository-path change is needed.

New tests use synthetic values. The supplied clinical example was checked
in the local runtime only and is not embedded in the application or test suite.
