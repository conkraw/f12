# PICU Handoff 6.53

Built from the supplied Version 6.52 package.

The Handoff workspace is compact: room and save controls, a 68-pixel SmartPhrase
paste field, then Preview / print and the editing tabs. Alerts sits immediately
after Difficult airway. Routine import notices use small text there, without a
stack of blue banners. Failed actions and save conflicts keep a short visible
status line. Clinical parsing, calculations, saved data and printed layout are
unchanged.

Only the selected tab is rendered. PDF page fitting is deferred until download
or an explicit Check page count request. No shared cache of patient data is
introduced. Notes and other edited fields are captured before a tab switch.

## Update from 6.52

Replace the application files with the contents of this folder, including
`workspace_ui.py` and `requirements.txt`. Streamlit 1.55 or later is required
for the native on-demand tab API. Restart/rebuild the deployment and refresh
the browser. Keep the existing Secrets, passwords, encryption key, mappings,
category settings, BMI reference file and shared archive. Do not rerun the
setup generators. No re-pasting or archive migration is required.

Routine room actions, custom-room removal, save-status list and Delete all
handoff data are now inside Room actions. Clearing all remains available to
any signed-in user. Its data-loss warning and existing conflict checks remain.

See COMPACT_WORKSPACE_UPDATE.md for details and TEST_REPORT.md for verification.
Historical update notes describe earlier releases and are not current setup
instructions. The live deployment and shared patient archive were not accessed.
