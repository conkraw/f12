# Dated neurologic scores in 6.81

The K, Y and L sections now recognize dated EPIC score values with an optional staff attribution. The source timestamp establishes order. The handoff shows only the score and its date in MM/DD/YY format.

## Source examples

These examples are synthetic. The fictional attribution in the first column is discarded during import.

| Source | Result |
| --- | --- |
| SBS -1 (11/15/26 0630 : Example Recorder, RN) | SBS: -1 (11/15/26), when invasive mode qualifies |
| Target Arousal Level (SBS): SBS 0 (11/15/26 0900 : Example Recorder, DO) | SBS target: 0 (11/15/26), when invasive mode qualifies |
| CAPD: Cornell Assessment of Pediatric Delirium Score: 6 (11/15/26 0800 : Example Recorder, RN) | CAPD: 6 (11/15/26) |
| WAT-1 total score (0-12): 2 (11/16/26 0640 : Example Recorder, RN) | WAT-1: 2 (11/16/26) |

## Selecting the latest score

Each scale is selected independently. Multiple dated entries are compared by recording date and, where supplied, time. The largest or smallest numerical score is never used as a substitute for chronology. Reversing the source row order does not change the result.

When entries conflict at the latest timestamp, or an undated entry prevents a reliable comparison, the affected import fails with a static review message. Dates and times must be valid. No staff attribution or pasted source content enters that message.

Dated values do not expire merely because they are older than 24 hours. An EPIC label such as SBS Last 24 Hours does not cause an older explicitly dated score to lose its source date. Existing undated data keeps legacy support without an invented date.

## SBS condition and target labels

All SBS output requires a recognized invasive ventilator mode in the current respiratory snapshot. Noninvasive modes and an explicit off value do not qualify. Oxygen delivery and a removed ETT record do not supply this evidence. A failed C/D import suppresses SBS until the respiratory record is corrected.

The existing respiratory parser treats a pressure-support mode accompanied by nasal cannula, high-flow or mask delivery as noninvasive. The SBS condition follows that same decision, including older saved records with this combination.

CAPD and WAT-1 have no ventilation condition.

An explicitly labeled target remains SBS target. Adding an observed SBS preserves the latest prior target separately, so a target cannot silently become a measured score.

## Edits, saves and output

New CAPD and WAT score rows retain only a canonical score and date. SBS retains a validated source timestamp where needed for ordering. Staff attribution is discarded before score persistence. Legacy saved WAT values remain loadable and are sanitized for output. Unrecognized old prose is omitted from the score display.

Editor callbacks and pending edits captured during a room switch use the same normalization. A valid correction clears the affected score import warning. Invalid edits do not replace the current draft or saved room. Inclusion flags remain editable.

Text, HTML and PDF use the same score display. Print all refreshes the affected room when a score, date or respiratory condition changes. Existing encrypted storage, complete-room replacement and archive schema 34 remain in place.

## Retained medication update

The 6.80 changes remain included. Qualifying nebulized sodium chloride 3% goes to Respiratory / Airway Clearance for both 3 mL and 4 mL. Other sodium chloride products keep their applicable placement.

Sedative PRNs and intermittent chlorothiazide or furosemide retain the source dose and the per-kg annotation when supported by an unambiguous dose and usable weight. See MEDICATION_UPDATE_680.md for those calculation boundaries.
