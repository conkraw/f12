# PICU Handoff 6.51

This complete app package is built from Version 6.50. Any signed-in user can
clear all patient handoffs without the separate Admin password.

Open Handoff > Delete all handoff data and press Delete all handoff data.
The button clears the current shared patient list and this session's patient
drafts. Custom rooms are removed. Preset rooms remain blank. Saved medication
mappings, categories, SmartPhrase settings, passwords and technical logs remain.
Other users must reload the saved archive. Earlier archive versions, downloads
and printouts are not deleted.

Only app.py changes among application modules. The app login and protected
Admin settings remain unchanged. No new dependencies, schema migration, or
re-pasting are required. Replace app.py in an existing 6.50 deployment, restart,
and refresh. Keep existing Secrets, keys and stored settings unchanged.

See CLEAR_ALL_UPDATE.md for details. Test results are in DELIVERY_VERIFICATION.txt.
The package does not contain live patient data or deployment credentials.
