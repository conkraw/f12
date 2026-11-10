# Version 6.52 verification

Base archive: supplied PICU651.zip. ZIP integrity and all 316 source-manifest
entries verified before packaging.

Full local regression suite: 4310 passed in 94.74 seconds.
New focused suite: 77 passed. Test file: tests/test_antixa_bilirubin.py.

Checks cover Eastern calendar dates, midnight rollover, UTC-host handling,
multiple same-day values, date-only source order, numeric zero, supplied units
and flags, excluded results, pending/canceled/future values, failed imports,
no duplication between HEME and lower labs, empty/hidden DVT medication groups,
renamed and nested DVT categories, high total versus direct bilirubin, normal
newer results, admission boundaries, explicit high flags versus asterisk-only
flags, problem editing/dismissal, and text/HTML/PDF/batch export consistency.

A synthetic encrypted archive created by the unmodified Version 6.51 code
opened in 6.52 with exact equality of the complete archive object. Re-encryption
and reopening also preserved it, including custom categories/rooms, timestamps
and source lab rows.

The generated preview has two landscape pages, one per synthetic room. Both
were rendered to images and visually inspected. Page 1 shows a current-day
HEPLMW beneath the DVT medications. Page 2 shows a preceding-day HEPLMW in the
lower coagulation area. Each has one anti-Xa result and the new problem label.

Four application modules changed: app.py, categories.py, lab_windows.py and
problem_review.py. All other application modules are byte-identical to 6.51.
No live Streamlit deployment, private storage connection or patient archive was
accessed or modified. These tests are not clinical validation.
