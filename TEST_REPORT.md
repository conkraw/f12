# Version 6.53 verification

Base: supplied PICU652.zip. ZIP CRC and all 320 source-manifest entries verified.
Baseline regression suite: 4310 passed in 92.84 seconds.
Full updated suite from a clean staged-ZIP extraction: 4380 passed in 94.32 seconds.
New focused suite: 70 checks in tests/test_compact_workspace.py.

Coverage includes active-tab rendering, input size and tab order, no automatic
PDF preflight, optional preflight, pending note and medication capture before
widget cleanup, difficult-airway edits, room autosave, blocked invalid edits,
failed saves and conflicting writes, hidden-tab state restoration, no clinical
archive writes on tab selection, session-scoped messages, HTML escaping,
per-room alert retention, new-patient isolation, reset failure preservation,
successful clear-all cleanup, logout cleanup, bounded message memory,
nonclinical guide refresh timing, and persistent print-target preferences.

The existing interface smoke harness still traverses all tabs for broad
coverage. Focused tests separately model the selected tab and inactive-widget
cleanup. Older layout assertions were updated for the new compact header.
The clinical tests and clinical implementation modules were not changed.

Changed application/deployment files: app.py, workspace_ui.py (new),
requirements.txt (Streamlit >=1.55,<2). All other original top-level Python
modules, including models.py, clinical parsers, exports.py, encryption and
storage modules, are byte-identical to 6.52. The archive schema is unchanged.

Using the same synthetic 13-medication handoff and fixed display time,
plain-text and HTML exports are byte-identical to 6.52. The rendered PDF page
is pixel-identical. It was also visually inspected.

Local render benchmark: seven measured runs after one warm-up. Median preview
rendering was 0.184552 seconds in 6.52 and
0.054322 seconds in 6.53, a
70.6 percent reduction in this simulation. UI input controls
constructed fell from 206 to 3, and eager PDF fits from 1 to 0. HTML preview
rendering remains 1. Data and method are in PERFORMANCE_REPORT.json.

These are local Python widget simulations, not a live Streamlit/browser test
or a hosted-app performance measurement. Streamlit could not be installed in
this environment because external package access was unavailable. The native
stateful-tab API was checked against the official Streamlit 1.55 documentation.
End-to-end speed depends on hosting, browser and shared-storage latency.

No live deployment, credentials, shared patient archive or production records
were accessed or modified. No patient data was added to the delivered tests.
The final ZIP's source bytes and checksums are verified separately.
