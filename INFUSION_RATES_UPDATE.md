# Version 6.33: Last Admin infusion rates and Antiemetics

## Infusion rates

A continuous infusion with one explicit numeric rate in Last Admin now uses
that value as its emphasized dose-rate. This includes nitroprusside,
nicardipine and norepinephrine, as well as other continuous orders with an
explicit documented rate. The time from that field is displayed with it.

Synthetic illustration using the supplied nitroprusside row pattern:

    Last Admin rate: 6 mcg/kg/min [11/08/26 1016]
    Recorded rate: 2.52 mL/hr

The ordered Dose range 0.1-6 mcg/kg/min is retained in the editor and archive.
It is not printed as though it were the administered rate. The separate
Last Rate pump value is not converted into a weight-based dose. Units and
source numbers are copied, not calculated or compared to dosing limits.

The three named drugs, their supported name variants, and continuous orders
with explicit numeric dose-rate ranges show UNK if Last Admin has no usable
numeric rate. Other continuous orders retain the existing dose/pump display
when Last Admin contains only a quantity or an event such as Rate Verify.
PN total volume and lipid mass are not rates. Scheduled and PRN bolus doses
are not replaced with administration values.

Zero is a valid documented rate. An explicit Stopped, Paused, Held, Not given,
Not administered, or Discontinued event is labeled with its own wording.
The order stays in the handoff, while its older pump rate remains in the
editor rather than printing beside that non-running event as a current rate.
A stop event is not automatically interpreted as order discontinuation.

Multiple rate events or conflicting text in one Last Admin cell are not
silently merged or ranked. The app uses UNK for the named/range titration
orders until the source or the editable fields have been checked.

Medication details now include Last Admin rate, timestamp and status fields.
Changing a rate clears its old timestamp unless a new time is supplied.
These edits do not update Epic. Custom handoff wording continues to override
the automatic summary, so check or clear custom wording after a rate change.

## Antiemetics

Ondansetron and Zofran entries automatically appear under Antiemetics in
FEN/GI. Scheduled and PRN entries keep their dose, route and frequency. Hidden
and explicitly excluded entries remain hidden. Existing per-order grouping
choices take precedence. Other medications can be assigned using FEN/GI
display -> Antiemetics. The choice is remembered in the existing settings.

## Clipboard format

Canonical tab-separated Epic tables are unchanged. The explicit EN-space
clipboard format in the supplied sample is also supported using recognizable
route/frequency boundaries. Plain prose is never treated as a table. When a
single numerical rate cannot be assigned to Last Rate versus Last Admin,
it is not guessed, and a static warning explains the missing boundary.

## Existing handoffs and installation

Save open work. Extract PICU633.zip and upload the contents of
PICU_Handoff_v6_33_Infusion_Rates to the existing application code repository.
Keep app.py at the root. Replace matching files and include infusion_rates.py
and medication_columns.py. Restart and refresh the browser.

Keep current Secrets, both passwords, encryption key, GitHub token, mappings,
private data repository, and public CDC BMI reference data. Do not rerun any
key/password generators. No new Python dependencies are required.

The archive upgrades from schema 24 to 25 without changing existing room
fields or timestamps. New optional medication fields store only sanitized
Last Admin rate/status/time, not raw text or provider names. After saving
with v6.33, do not downgrade to an older application package.

Re-paste the full B medication section or the complete SmartPhrase, then
Create / update handoff and Save handoff. Old versions did not retain the
Last Admin value, so installation alone cannot recover it. A new B replaces
all medication rows and their administration snapshot. Omitting B preserves
existing medication information. No doses are carried between separate orders.

The infusion values are a chart snapshot, not a live pump connection.
See TEST_REPORT.md for verification and remaining limits.
