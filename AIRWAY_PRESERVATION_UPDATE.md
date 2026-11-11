# Version 6.56 airway retention: superseded in 6.62

The special airway carry-forward workflow from version 6.56 has been removed.
Its previous instructions no longer apply.

Create / update handoff now applies the normal section update immediately.
There is no Keep airway, Delete airway, or Cancel update prompt. Existing
manual difficult-airway details follow the same sheet's normal update behavior.
Current editor values are captured before the update, and sections not supplied
by the SmartPhrase retain their values.

Delete all handoff data removes complete patient records, including all
difficult-airway details, current drafts, and custom rooms. There is no
keep-airway reset option. A failed or conflicting shared save keeps the current
data available. After a successful reset, stale sessions must reload before they
can save against the new archive.

The ordinary Difficult airway editor and its printed alert remain available.
Starting a blank patient handoff does not inherit the previous record's airway
details. Medication rules, categories, settings, passwords, and the separately
stored SmartPhrase remain unchanged by the reset.

These changes do not alter the archive schema or require new dependencies.
