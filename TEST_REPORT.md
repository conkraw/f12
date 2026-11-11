# PICU Handoff 6.62 verification

Base: PICU661.zip. This update adds the patient-list choice after sign-in and
removes the special difficult-airway carry-forward workflow.

## Daily list and login behavior

The first authenticated screen offers Start new patient list and Continue saved
handoffs. Opening that screen, rendering a review, and choosing Continue do not
write or delete saved records. The first option requires an explicit review
confirmation before any shared change.

The review uses last saved times in America/New_York. Earlier dates and today's
inclusive 05:00:00 through 08:30:00 saves are selected. Other times today,
missing/invalid timestamps and future timestamps are kept. Tests cover exact
boundaries, UTC/Eastern date differences and daylight-saving transitions.

A confirmed reset atomically writes the selected removals, an actual confirmation
timestamp and a new generation. A shared daily marker makes a later start on
that Eastern date a no-op. The marker is added only on the first confirmed start.

## Transaction and concurrency checks

The review is bound to its source archive and SHA. Local changes, a different
Eastern date, a concurrent write or a failed save prevent confirmation. The
removal selection stays fixed if time advances while the review remains open.
A failure requires a fresh review, with no automatic destructive retry.

A lost save acknowledgement is tested: reload finds the marker from the successful
remote write and does not delete again. Continue and already-started paths perform
no storage write. Expired authentication cannot start a reset.

Selective reload preserves pending editor values and original conflict bases only
for the same saved handoff identity. Removed records, changed identities and
unbased unsaved drafts cannot restore a previous list. Full-reset behavior remains
covered. PDF workers check shared generation before and after rendering without
accessing Streamlit session state. Reset, expiry, cancellation and failed verification
prevent release of a new PDF. Ordinary saves with the same generation remain allowed.

## Airway behavior

SmartPhrase updates now apply without a Keep/Delete/Cancel airway prompt. Current
manual editor values still participate in normal updates. Full reset and selected
daily deletion remove airway details with the complete handoff. No retained-airway
placeholder is created. The ordinary editor, alert, escaping and encryption remain.

## Verification runs

| Scope | Result |
| --- | --- |
| Daily date logic, archive validation and save status | 146 passed |
| Login gate, review UI and reset transactions | 23 passed |
| Lazy download generation checks | 21 passed |
| Airway update, reset, ordinary airway and print behavior | 221 passed |
| Existing callbacks, workflow, printing, UI and save status | 307 passed |

The runs overlap in existing reset, print and save-status coverage. No combined
unique-test count is claimed. The only warning was an existing anyio/pytest plugin
deprecation warning. No test failed. Callback and page tests use a simulated
Streamlit environment, not a live browser deployment.

All application modules pass Python syntax validation. Existing clinical parsing,
medication placement, MRSA selection, sodium rules, line-day calculation and TMax
formatting modules are unchanged from 6.61.

## Archive and package

Existing schema 34 archives load unchanged. A validated optional nonclinical
patient_list_started_at setting is written on the first daily start. Encryption,
patient-sheet fields and dependencies remain unchanged. All unselected handoffs
and other shared settings are preserved by daily cleanup.

The ZIP passes CRC validation and its complete SHA256 manifest matches every
bundled file. Generated caches, compiled bytecode, credentials and clinical
attachments are excluded. Test fixtures are synthetic. The live Streamlit
deployment and shared patient archive were not accessed or changed.
