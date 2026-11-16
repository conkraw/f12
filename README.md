# PICU Handoff 6.81

This release displays the latest documented SBS, CAPD and WAT-1 score with its recorded date. Staff names and recording times are omitted from the handoff. SBS displays only when the current respiratory record contains a recognized invasive ventilator mode.

Built from PICU680.zip. The 3% saline mapping, weight-based medication display, faster Print all and complete-room SmartPhrase replacement are retained.

This package has not been deployed to the live application.

## Install

Extract PICU681.zip. Replace matching code files at your existing app repository root, beside the current app.py. Do not add another folder level.

From 6.80, install all eight runtime files in UPDATE_FILES.txt together. score_dates.py is new. Restart Streamlit after uploading the files.

For an older installed version, use the complete application code set, including pdf_cache.py and requirements.txt. Keep your existing Streamlit Secrets, encryption key, encrypted archives and saved settings. No new dependency or archive migration is required from 6.80.

Confirm the sidebar reads:

    Version 6.81 | Dated neurologic scores

## Score display

Examples below are synthetic.

| Source field | Handoff output | Condition |
| --- | --- | --- |
| Observed SBS | SBS: -1 (11/15/26) | Recognized invasive ventilator mode |
| Explicit SBS target | SBS target: -1 (11/15/26) | Recognized invasive ventilator mode |
| CAPD | CAPD: 6 (11/15/26) | Independent of ventilation |
| WAT-1 | WAT-1: 2 (11/16/26) | Independent of ventilation |

The full source timestamp selects the latest entry. Only the date appears in text, HTML and PDF output. Older dated scores remain visible with their actual date. The upload date and report date are never substituted for the score's recording date.

An explicit SBS target retains its target label. SBS is hidden for nasal cannula, high-flow nasal cannula, noninvasive ventilator modes, an explicit ventilator-off record or failed respiratory import. A removed ETT record does not enable SBS.

CAPD keeps its existing high-score display flag and CAPD: None behavior when no included score is available. Blank WAT fields remain omitted. Existing undated values remain usable, but no date is invented.

## Editing and saved handoffs

You can paste the EPIC score together with its dated attribution into the CAPD or WAT value field. A valid edit retains only the score and date. SBS also accepts a recording date without a time. A supplied time is used for source ordering.

If conflicting entries do not establish which score is latest, the affected section needs review. No score is selected by its numerical value or position in the paste. Other sections continue to import independently.

## Verification and preview

DATED_SCORES_681.md describes parsing, source dates and the SBS condition.
TEST_REPORT.md records the completed checks and their limits.
examples/dated_scores_681_preview.pdf contains two synthetic handoffs.
validation/build_dated_scores_681_preview.py rebuilds that preview.

MEDICATION_UPDATE_680.md and TEST_REPORT_680.md retain the medication release details. TEST_REPORT_679.md and FASTER_PRINT_ALL.md retain the prior printing release details.
