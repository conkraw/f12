# Theophylline level in Respiratory, Version 6.18

## What changed

The G / LABS section now recognizes THEOPH and displays the latest included
result as Theophylline level in RESP. Exact Theophylline and Theophylline Level
labels are also recognized, without fuzzy matching or substituting other tests.
The original component code, value, date, inclusion setting and every retained
row remain editable in Labs / Vitals.

Printed order: respiratory vital signs, existing respiratory support settings,
theophylline level, then separate respiratory notes and medications. Separators
keep the level distinct from medications. Only one included theophylline result
prints, and it is no longer repeated in the lower Lab Results / Trends area.
This applies to the handoff preview, PDF, HTML, text, and Print all.

The latest available date is used. When all results on that date have collection
times, the latest time is used. If times are absent or incomplete, the existing
lab rule preserves the order supplied by Epic. A date-only result is not claimed
to have a verified intraday collection order. Original units, flags, decimal
precision and inequality signs remain unchanged. No units, therapeutic range,
interpretation or medication-dose adjustment is added.

If THEOPH is absent, there is no automatic theophylline line. Excluding the newest
row selects the next included result, consistent with the other lab controls.
Exclude all theophylline rows to omit the line completely without deleting them.

## Importing and older records

Paste the full SmartPhrase or the complete paired G block. Importing G replaces
the whole G laboratory snapshot, not only THEOPH. Include the other lab results
you still need. Omitting G preserves it. A successful new G snapshot without
THEOPH clears the old automatic theophylline display. Existing partial-import
warnings apply if G cannot be parsed and prior values are retained.

A THEOPH row that is already stored in an older handoff automatically moves to
RESP when that handoff is reopened or printed. It does not require a new mapping.
Manual notes are not rewritten. Nothing is inferred from a medication order.

## Installation

Save open work. Extract PICU618.zip, open PICU_Handoff_v6_18_Theophylline, and
upload the contents into the existing application-code repository. Replace
matching files and keep app.py at the root. Restart the deployment and refresh
the browser.

Keep the existing Streamlit Secrets, password, encryption key, GitHub token,
private data repository and saved mappings. Do not run create_secrets.py or
Generate_Secrets.ipynb again. No new dependencies or archive-schema changes are
required. The archive remains schema 17. No repository was modified directly.

Sidebar: Version 6.18 | Theophylline level in Respiratory

## Verification

The unmodified 6.17 package passed its 1,578 tests. The updated package passes
1,621 automated tests, including 43 new theophylline checks. Existing tests were
not modified or disabled. See TEST_REPORT.md. The bundled example is synthetic,
not a patient record or a treatment plan. The live deployment and authenticated
private handoff store were not tested.
