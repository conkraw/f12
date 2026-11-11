# PICU Handoff 6.63 verification

Base: PICU662.zip. This release adds the Hematology > Chemotherapy display
category and removes requested order annotations from displayed medication names.

## Chemotherapy placement

The explicit roster contains 40 generic entries and 72 additional aliases,
including asparaginase formulations and doxorubicin. Tests exercise every
recognized name, known source wrappers, word boundaries, mixed-case names,
incidental mentions, and separate orders. Dexamethasone and other steroids
retain their existing defaults. Supportive medicines are not classified through
a broad chemotherapy context rule.

Automatic orders appear once under Hematology > Chemotherapy in text, HTML,
individual PDFs and Print All. Explicit group and category choices still win.
The old schema-34 catalog receives a virtual built-in without modifying the
saved definitions. Collision-safe names, category rules, encrypted reload, and
the original 250 slots plus the two later reserved built-ins are covered.

CHEMOTHERAPY_REFERENCE.md records the implemented roster and primary sources.
Grouping is presentation only and does not establish a treatment indication.

## Medication name cleanup

The shared name-only formatter hides leading And:, Or:, generated Alternative
order: labels, and recognized [START ON ...] annotations. Both regular
medication and infusion summaries use it. Held/discontinued labels, Followed by,
unknown bracketed context and custom handoff wording remain intact. A source
containing only annotations falls back to its original text instead of becoming
a blank entry.

Tests cover standalone and inline connectors, trailing table connectors, blank
dose columns, source identity, separate order counts, routes and frequencies,
HTML escaping, editor source names, future-order checks, date-specific hidden
rules, mapping keys, Last Admin selection, recorded rates and encrypted reload.
Rendering does not modify the source record or substitute a display name into
scheduling or rate calculations.

## Supplied SmartPhrase

The latest supplied SmartPhrase contains 35 medication orders. All 35 import
with unique identities and zero import errors. An independent source-column
check matched all source medication names, doses, routes and frequencies,
allowing the parser's intentional connector prefix.

The source has one And prefix, one Or prefix and five START ON annotations.
All requested prefixes are absent from its displayed medication names. Text,
HTML, individual PDF and Print All render successfully. Both PDF paths produce
one page, and the complete imported sheet remains unchanged after rendering.

Only counts and pass/fail results were recorded. The supplied clinical text,
screenshots and generated output from that text are not included in this
package. All new committed fixtures and previews use synthetic data.

## Synthetic preview

The 15-order synthetic example covers five asparaginase formulations, a held
future doxorubicin order, dexamethasone, diphenhydramine alternatives, future
antibiotics, Followed by wording, G-CSF and supportive medicines. Every visible
order appears exactly once across the text, HTML, PDF and Print All paths.

The included PDF was rendered and visually inspected. It is one page, with
Chemotherapy in the Heme column, clean medication labels, retained held status
and no clipping or overlapping content. These are software display examples,
not a treatment regimen.

## Verification runs

| Scope | Result |
| --- | --- |
| Chemotherapy, dynamic categories, Epidural, expanded groups and respiratory/Heme infusions | 515 passed, plus 14 subtests |
| New chemotherapy cases, included in the preceding run | 159 passed |
| Medication labels, alternatives, tapers, infusions, PN and export behavior | 673 cases accounted for |
| Final focused cleanup rerun, including all new cleanup cases and corrected legacy assertions | 57 passed |
| New cleanup cases, included in the preceding runs | 41 passed |
| Synthetic chemotherapy and label-cleanup integration | 14 passed |
| MRSA, hypernatremia, line days, devices, daily start, login gate and PDF reset guard | 336 passed |

The medication/export sweep initially passed 667 cases. Six older assertions
still required the display labels that this release intentionally removes.
Those expected strings were corrected, and all six cases passed in the final
57-case focused rerun. Their source-name, dose, frequency and status checks were
retained. No production code changed after that sweep, and no failure remains.

Runs overlap, so these counts are not added into a claimed unique-test total.
The only warning was an existing AnyIO/pytest plugin deprecation warning.
Callback and page tests use the repository's simulated Streamlit environment,
not a live browser deployment.

Python syntax validation passed for all 61 application modules. The dependency
requirements and schema-defining model module are byte-for-byte unchanged from
6.62. Daily cleanup transactions, its review/Continue behavior, same-day reset
protection and the shared PDF download guard remain covered.

## Archive and package

The stored schema remains 34. No new dependency, encryption key or conversion
is required. The existing daily-start marker from 6.62 is retained. Original
medication fields remain available for editing and later imports.

The ZIP passes CRC validation and its complete SHA256 manifest matches every
bundled file. Generated caches, compiled bytecode, credentials and supplied
clinical attachments are excluded. The live Streamlit deployment and shared
patient archive were not accessed or changed.
