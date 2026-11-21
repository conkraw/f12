# PICU Handoff 6.91 verification

## Final regression result

302 tests passed across nine selected modules and the current-version assertion from a tenth module. There were no failures, errors or skipped tests in the final combined run.

The selection covers the loaded-parser check, mode-history parsing and integration, application callbacks, UI rendering, room replacement, saving before printing, print workflows and technical error reports.

Twelve new checks in tests/test_respiratory_update_check.py verify the incomplete-update condition and its handling.

## Exact error reproduction

Both newly uploaded SmartPhrases were checked through the full import_replacement workflow.

The delivered 6.90 package imports respiratory support successfully in both. Its respiratory files were compared with the working source and match byte-for-byte.

The older 6.89 parser reproduces the exact reported error in both examples. Its source selector passes timestamped mode-history lines to the current-setting reader, which rejects them as repeated Vent Mode fields.

This is evidence of a likely older or mixed running module. The remote deployment was not inspected and no claim is made that its file state has been confirmed.

## Runtime check

The new check uses a small fixed synthetic example and the same loaded import function as the user's replacement workflow.

It verifies the newest mode, parsed timestamp, two separate historical modes, deduplication and mode-specific settings. An old unscoped selector fails this check.

The check runs after authentication and before archive loading. It also runs after the existing import guards and before replacing a handoff. Failure preserves the pasted text and existing records, with no archive read or write from the check itself.

Tests also verify that internal exceptions do not expose source text and that the ready label appears only when the check passes.

## Provided sources

All five uploaded SmartPhrases were processed through the complete replacement-import workflow with the final code. Each produced ventilation data without a respiratory import warning.

The two new examples remain PRVC first, followed by their recorded NAVA, PRVC-PS or PS-CPAP entries as applicable. Blank current FiO2 is not replaced with an unrelated historical NAVA value.

The Current Shift warning is appropriate for both new sources because the required current-shift output breakdown is absent. That calculation logic was not changed.

One source also contains an AD section with no supported ECLS settings. Its existing ECLS alert is independent of respiratory import.

Uploaded source text and patient-derived output are not included in this package.

## Scope

Only app.py and error_store.py changed as runtime files after 6.90. The known-working ventilation.py and noninvasive.py are included in the four-file installation instructions to resolve an incomplete earlier update.

The archive schema remains 34. No application dependencies or credentials changed.

Independent review found no blocking issue in the readiness probe or its placement before patient replacement. Existing dependency deprecation warnings did not affect test results.

No live Streamlit deployment or production archive write was performed.
