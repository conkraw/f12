# Version 6.51 verification

Base: supplied Version 6.50 ZIP, with ZIP and SHA-256 manifest verification.

Full local regression suite: 4233 passed in 91.95s (0:01:31)
Focused reset, workflow and header suite: 128 passed in 19.56s

The new test_clear_all_no_admin.py includes 21 checks covering signed-in users
with locked, expired or unlocked Admin grants, expired/logged-out app sessions,
missing Admin configuration, storage failures and version conflicts, empty
censuses, preserved settings, removal of obsolete password-widget state, no
unintended Admin unlock, and reset-generation handling for stale sessions.

The action remains explicit. Merely rendering the control does not delete data.
The shared archive is saved successfully before this session's drafts and
pending downloads are discarded. Failed writes retain the open patient work.

Only app.py changed among application modules. Remaining application code was
compared byte-for-byte with Version 6.50. No new schema or dependency changes.
UI and storage tests use simulations. No live deployment or patient archive was
tested, opened or modified.
