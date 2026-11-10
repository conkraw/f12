# Version 6.56 verification

Base: supplied PICU655.zip. Tests use synthetic data only.

Working-tree complete suite: 4660 passed in 96.89 seconds.
Clean staged-ZIP extraction: 4660 passed in 97.86 seconds.
69 new parametrized regression cases in tests/test_airway_preservation.py.
The prior one-button reset UI check now asserts both requested reset choices.

Focused tests cover existing active and hidden airway text, structured answers,
keep/delete/cancel, invalid imports, latest blurred-widget edits, stale clicks,
room/sheet/request identity checks, repeated imports, interrupted sessions,
ordinary saves and room autosave, both reset modes, retained custom rooms,
unsaved airway drafts, failed and conflicting writes, stale sessions,
reset-generation changes, encrypted round trips and preserved settings.

A synthetic encrypted archive created using the original 6.55 code was opened
and re-encrypted without changing any saved fields. A keep-airway reset retained
only its airway record, and a subsequent full reset removed that record.

The new interface checks use Streamlit widget/callback simulations, not a live
browser or hosted service. No live deployment or patient archive was accessed.
No new clinical interpretation or printed handoff layout is introduced.

Clean delivery verification is recorded in DELIVERY_VERIFICATION.txt.
