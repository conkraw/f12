# Version 6.56: keep or delete difficult-airway details

Built from the supplied PICU655.zip. No clinical parser, lab logic, printed
layout, dependency or archive-schema change is included in this release.

## Updating a handoff

When Create / update handoff is pressed and difficult-airway details exist,
the app stages the parsed update and asks what to do with the existing airway
record. Choose Keep airway and update, Delete airway and update, or Cancel
update. Nothing is deleted merely by pasting or pressing Create / update.

The prompt also catches saved text when the difficult-airway print checkbox
is off, non-default structured answers, and a checked difficult-airway flag.
An entirely empty record does not add a prompt. A rejected import does not
ask to delete the airway record.

Keep retains the complete difficult-airway record and its current print flag.
Delete clears the complete record, not just the displayed sentence. Cancel
leaves the existing handoff unchanged and keeps the paste available.

After choosing Keep or Delete, Save handoff or change rooms to save the result.
While the choice is pending, saving or changing rooms asks the user to finish
or cancel that choice first. Tab changes and ordinary saves do not repeatedly
ask the question. A stale choice cannot apply to another room or a newer draft.

## Clearing all patients

Room actions > Delete all handoff data now offers two buttons:

- Delete all handoff data: removes all current handoff records, including
  difficult-airway details. Custom rooms are removed. Preset rooms are blank.
- Clear handoffs, keep difficult airway: removes all other patient data but
  keeps each complete difficult-airway record in its original room. This
  includes current unsaved airway edits in this session. Custom rooms remain
  only when they contain retained airway details. Other custom rooms are removed.

Both options remain available to any signed-in user without an Admin password.
Either reset button acts immediately. Medication mappings, custom categories,
settings, passwords and the separately stored SmartPhrase are preserved.

The keep-airway option creates otherwise-blank room handoffs with new internal
sheet IDs. Patient demographics, diagnoses, medications, labs, general notes,
ordinary Airway/Access fields and device information are not retained. The
original airway description, structured answers, source/date text and enabled
state are preserved without being reinterpreted. Confirm that retained details
belong to the current patient before keeping them on a subsequent import.
A room is a location, not a verified patient identity.

Failed writes and save conflicts retain the existing local data. A changed
reset generation prevents older sessions from restoring cleared drafts when
they reload. Other users should reload the saved archive after either reset.
A reset is not a physical purge of older archive versions, downloaded PDFs,
printouts or other users' already-open browser contents.

## Install

Extract the ZIP and upload this folder's contents into the application code
folder, replacing matching files. Keep app.py at the root. Restart the app
and refresh the browser. No re-pasting is required for this update.

Changed application files:

    app.py
    difficult_airway.py
    handoff_reset.py

Keep existing Secrets, both passwords, encryption key, mappings, category
settings, BMI reference data and shared archive unchanged. Do not rerun setup
generators. The archive schema remains 34, and requirements.txt is unchanged.

No live deployment or patient archive was modified. See TEST_REPORT.md for
verification and limitations. Historical update notes remain in the package.
