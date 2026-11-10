# PICU Handoff 6.59 verification

Base: PICU658.zip. All checks used synthetic data.

219 focused MRSA, demographics, laboratory routing and styling tests passed in
2.11 seconds. This includes 35 new combined-code cases and 22 existing MRSA
cases. There was one unrelated anyio pytest plugin deprecation warning.

Coverage includes both MRSADNA and MRSANPADM, tab and collapsed-space parsing,
case and colon handling, either component as newest, reversed paste order,
newer negative or pending results after an older positive result, complete
same-day times, month/year/leap boundaries, excluded and future rows, and
unchanged source rows and lab component names.

When same-day times are incomplete, tests confirm the existing source-order
convention without manufacturing a time. The selected laboratory result date
remains visible. Upload and handoff-save dates do not select the result.

Text, HTML, single-sheet PDF and Print All checks show a single MRSA Screen.
PDF font inspection confirms the label is bold and the value is regular.
Both lab codes remain in the source lab editor and are omitted from duplicate
bottom lab cards. An encrypted archive round trip preserves all source rows.

Only app.py, labs.py and mrsa.py changed among application modules. Archive
schema, dependencies and the other 6.58 features are unchanged. The running
hosted app and patient archive were not accessed.

The packaged ZIP CRC and SHA256 file manifest were verified. Generated caches,
compiled bytecode and local test data are excluded.
