# PICU Handoff 6.82

This release fixes the performance regression introduced by dated neurologic scores in 6.81. It retains the latest dated SBS, CAPD and WAT-1 display, the SBS invasive-ventilation condition and the medication changes from 6.80.

Install this package directly over 6.80. The complete application code is included.

This package has not been deployed to the live application.

## What changed

Ordinary score dates now use a direct, calendar-validated parser. They no longer walk through multiple date formats during each validation, preview or cached PDF check. Unusual formats accepted by older archives retain their existing support.

Opening or leaving an unchanged older handoff no longer rewrites its WAT value merely to remove attribution from the displayed text. That prevents an unnecessary shared-storage save and PDF preparation during navigation. Actual edits still save, normalize the score and clear the affected import warning when valid.

The performance fix uses no global cache of patient text. Score validation, source-date ordering, metadata removal, room isolation and PDF freshness checks remain enabled.

## Install

Extract PICU682.zip. Replace matching code files at your existing app repository root, beside the current app.py. Do not add another folder level.

From 6.80, install all eight files in UPDATE_FILES.txt together. score_dates.py is new to 6.80. From 6.81, the changed runtime files are app.py, sbs.py and score_dates.py. Restart Streamlit after replacing the files.

Keep your existing Streamlit Secrets, encryption key, encrypted archives and saved settings. No new dependency or archive migration is required.

Confirm the sidebar reads:

    Version 6.82 | Faster dated scores

## Score behavior retained

The latest documented SBS, CAPD and WAT-1 score appears with its recorded date only. A supplied time determines ordering but does not print. Staff names are omitted. Older dated scores remain visible with their source date.

SBS requires a recognized invasive ventilator mode. An explicit target retains the SBS target label. CAPD and WAT-1 do not depend on respiratory support. The latest source date is never replaced with the upload date or report date.

DATED_SCORES_681.md describes the score behavior and accepted source examples.
MEDICATION_UPDATE_680.md describes the retained saline mapping and dose calculations.

## Verification

PERFORMANCE_682.md describes the measured regression and correction.
PERFORMANCE_682.json records reproducible local benchmark results and limits.
TEST_REPORT.md records the completed regression checks.

examples/dated_scores_681_preview.pdf shows the retained score formatting.
The prior test reports and medication preview remain included.
