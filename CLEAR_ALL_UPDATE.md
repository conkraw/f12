# Version 6.51: clear all without an Admin password

Built from the supplied Version 6.50 ZIP. Any user with a valid app login can
open Handoff > Delete all handoff data and press Delete all handoff data.
There is no Admin-password field, separate Admin grant, or second confirmation.
The collapsed section retains a warning that this clears the shared patient list.

App sign-in and session-expiry checks remain required. The Admin workspace and
its settings edits still require the separate Admin password. Deletion neither
unlocks Admin nor extends an Admin grant.

The existing reset operation is unchanged: commit the empty census first, then
clear this session's patient drafts, editor fields, notes, and download handles.
Custom rooms are removed and preset rooms remain blank. All non-room settings,
medication/category rules, the published guide, passwords and technical logs
are retained. A failed or conflicting write leaves open work intact.

Other users must reload the saved archive. Existing version-conflict and reset-
generation checks remain in place. This does not erase earlier archive versions,
files already downloaded, or printouts. Session-only mode clears only that session.

Install: replace app.py from this folder in an existing 6.50 installation, restart
the app and refresh the browser. Or replace the complete application-code folder.
Keep Secrets, encryption keys, mappings, BMI reference data and storage unchanged.
No new dependencies, archive migration, or re-pasting are needed. Installing the
update does not itself delete handoffs. No live storage was accessed.
