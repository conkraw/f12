# PICU Handoff 6.90

This update builds on 6.89 and displays the latest reported ventilator mode first, followed by the other distinct modes recorded in the new All Vent Modes section.

## Install

Extract PICU690.zip. Copy the files inside PICU_Handoff_v6_90_Vent_Mode_History into your existing app repository, beside app.py, and replace matching files.

If your app already runs 6.89, these four application files are the required update:

- app.py
- ventilation.py
- noninvasive.py
- error_store.py

The complete package includes the earlier medication, code-status, nutrition, login, ECLS, AED-level and lysis-lab changes.

Keep your existing Streamlit Secrets and encryption key. Restart Streamlit and confirm that the sidebar reads:

    Version 6.90 | Latest ventilator mode and settings

Re-paste the complete current SmartPhrase, including All Vent Modes in the paired C section. Older saved handoffs do not contain this history, so it cannot be recovered without a new paste.

This package is ready to install. It has not been deployed to your live application.

## Mode ordering

The app compares the dates and times on every Vent Mode entry in All Vent Modes. Source order does not determine the latest mode.

The first block is labeled Latest reported mode. Other reported modes appear below it, ordered by their most recent recorded occurrence. The same mode is printed once even when many hourly entries or equivalent abbreviations appear.

PRVC-IMV, PRVC-PS, NAVA, PS-CPAP and pressure-control modes remain distinct. The existing shorthand for Epic source mode names is preserved.

When missing, invalid, tied or unrecognized mode entries prevent a reliable latest-mode determination, the output shows that uncertainty.

## Settings belong to their matching mode

| Mode or source | Settings used |
| --- | --- |
| Mode matching the initial C-block mode | The main settings for that mode |
| NAVA | NAVA Ventilator Settings |
| PS-CPAP | CPAP Trial Settings |
| AVAPS | Its dedicated AVAPS settings |
| Other explicitly labeled mode settings | The matching mode settings section |

A populated template heading does not establish that a mode was used. Supplemental modes must be present in All Vent Modes.

A change to a different latest mode uses settings explicitly assigned to that mode. It does not relabel the initial mode's settings. FiO2, PEEP, set volumes and other settings are kept within their source sections.

NAVA retains the existing Edi, observed pressure, tidal-volume and respiratory-rate ranges. PS-CPAP includes the reported weaning tidal-volume range and tolerance when supplied.

A recorded mode without matching settings remains visible with a settings-not-available note. Blank fields and No data recorded are omitted. A missing conventional Set TV is not replaced with an AVAPS target value.

Non-invasive support retains its existing separate display rules.

## What the timestamps mean

All Vent Modes timestamps establish when each mode was recorded. The supplied mode-specific settings blocks do not have their own timestamps.

The handoff therefore labels the first mode as the latest reported mode and identifies the other settings as reported values without setting timestamps. It does not claim to reconstruct a complete historical settings snapshot at each mode time.

Only the mode name and parsed mode time are retained from history entries. Charting-author suffixes and the raw mode history are not saved.

## Review and editing

The existing primary ventilator editor remains available. Review other recorded vent modes lets you hide or edit each additional mode's supplied settings.

Changing the primary mode to another mode already listed promotes that mode's matching settings and retains the former primary separately. Changing to a new mode clears the previous mode's settings. Manual mode changes remove the imported latest-time claim.

A new complete SmartPhrase replaces the selected room's prior mode history and associated editor state. Other rooms follow the existing replacement rules.

## Compatibility and verification

Existing schema-34 archives remain readable. There are no new application dependencies or configuration requirements. Install the updated application files together because older app versions do not understand the new history metadata.

TEST_REPORT.md records the executed checks. The synthetic preview in examples/vent_mode_history_preview.pdf shows the NAVA and PS-CPAP layouts. Uploaded patient examples are not included in the package.

The previous release notes are retained in the V689 files.
