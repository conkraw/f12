# Version 6.41: Measurement notes and observed PIP

Built directly from the delivered Version 6.40 package. Retains the compact
landscape handoff, 8-point starting text, automatic fitting, PDF-only download
controls, difficult-airway section, and all medication categories. There is no
manual font-size picker or Labs/Imaging print column.

## Measurement import fix

The height parser previously accepted one feet/inches parenthetical, but not a
second chart-transfer note. That rejected the I / NUTRITION section even when
measured weight and dosing weight were valid. The import-review message meant
that this section was not refreshed and any previous measurements were retained.

The parser now accepts a recorded primary height with its matching imperial
equivalent and recognized Epic/Cerner migration or recharting notes, for example:

    Height: 120 cm (3' 11.24") (Imported from Cerner and recharted in Epic)

The handoff displays Height: 120 cm. The charting comment does not print. A note
can also follow a height without an imperial equivalent. Repeated Height/Length
headings and split heading/value lines remain supported.

This is not a blanket removal of parentheses. Conflicting heights, unbalanced
parentheses, unknown notes, and notes that invalidate a measurement still produce
an in-app warning. The primary and imperial values must agree within the existing
rounding tolerance. Height is never derived from BMI or weight.

A successful I reimport replaces the old measurements and clears only its own
import warning. Other warnings remain. The existing dosing-weight-based intake
and output calculations become available after that warning clears.

## Observed PIP on the handoff

Observed PIP was already parsed and stored, but omitted from the mode-specific
printed summary. It now prints whenever the invasive ventilation record contains
it, including PRVC, VC, PC, PS-CPAP and Home Vent summaries.

    Mode: PRVC-IMV
    Set RR: 16
    Set TV: 160 mL
    Observed PIP: Avg: 22.4 Min: 18.2 Max: 28 cm H2O
    Set PEEP: 6 cm H2O
    Inspiratory Time: 0.8 sec
    Pressure Support: 8 cm H2O

A scalar displays as Observed PIP: 22.5 cm H2O. Supplied statistics are retained,
not calculated. Blank or No data recorded entries do not produce a placeholder.
Set PIP and Observed PIP remain separate. The app does not add PEEP, substitute
one for the other, or infer a measurement from the ventilator mode.

The change applies to the on-screen handoff, PDF and Print all. Stored observed
PIP values display without re-pasting. The existing TV source-selection rules,
mode abbreviations and noninvasive-device detection are unchanged.

## Installation and refresh

Extract PICU641.zip and open PICU_Handoff_v6_41_Measurements_PIP. Upload that
folder's contents into the existing application code repository, replacing
matching files. Keep app.py at the root. Restart the deployment and refresh the
browser. The sidebar should read:

    Version 6.41 | Measurement notes and observed PIP

Keep the current Secrets, both passwords, encryption key, medication mappings,
BMI reference data and shared storage. Do not rerun setup generators. No new
Python dependencies, secret fields or saved-archive schema changes are required.

For the rejected measurements, re-paste the complete paired I section or full
SmartPhrase, click Create / update handoff, check the displayed values, then Save
handoff. Installation alone cannot recover values from a rejected import.

For respiratory data already stored, open Preview / print or regenerate Print all.
Re-paste complete C and D sections only when refreshing the source settings.

## Scope and testing

Production changes are limited to anthropometrics.py, the formatting function in
ventilation.py, the version caption in app.py, and the technical-report version
constant in error_store.py. No source patient records or private settings are
bundled. The preview and new regression-test fixtures use synthetic records.
See TEST_REPORT.md for the actual test results and limitations.
