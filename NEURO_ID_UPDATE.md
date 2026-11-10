# Version 6.45 update

## ICP and CPP

The exact M example supplied in the request was already accepted by the
original 6.44 package in local testing. The live failure could not be reproduced.
This release verifies its full import-to-print path and extends parsing for
wrapped Avg/Min/Max values and full-width colon characters.

    ICP Range: ICP Mean (mmHg) Avg: 9.6 mmHg Min: 1 mmHg Max: 22 mmHg
    Last ICP: ICP Mean (mmHg): 11 mmHg
    CPP Range: CPP Avg: 69.5 mmHg Min: 31 mmHg Max: 97 mmHg
    Last CPP: CPP: 52 mmHg

Prints:

    ICP: 1-22 [11 mm Hg]
    CPP: 31-97 [52 mm Hg]

The average never becomes a last reading. Missing values, zero, decimals,
older single-value formats, and separate labels/values are supported. Conflicts
or invalid values generate an in-app import warning, not an invented result.
A successful new M import clears an earlier M warning. Empty M clears its
readings, while omitted M preserves them. No import errors print on the sheet.

## SBS in the last 24 hours

K accepts explicit observed SBS scores with recording dates and times, including
labeled single readings, vertical Date/Time/SBS tables, and Lab/Units matrices.
Only the latest qualifying reading prints as SBS: value, above CAPD and WAT-1.
Zero is a measured score. Older values, future readings, excluded entries,
missing timestamps, and ambiguous local daylight-saving times do not print.
The window is evaluated at preview or printing time using Eastern time.

The supplied K examples contain Target Arousal Level or no entry, rather than
a timestamped observed score. Those targets are retained in the editor but are
not presented as a measured SBS within 24 hours. Untimed measured values are
retained for review. No admission date, lab date, intake/output time, or upload
time is borrowed to establish when SBS was recorded.

Example supported input, with the actual source date/time substituted:

    kkkkkkkkkkkkkkkkkkkkkkkk
    SBS observations:
    11/09/2026 08:00 SBS: -2
    11/09/2026 10:00 SBS: -1
    kkkkkkkkkkkkkkkkkkkkkkkk

Edit or add a reading under Labs / Vitals, Neurologic observations, then
Observed SBS / recording time. An empty K clears measured readings and targets.
Omitted K preserves them, but old readings expire from the output as time passes.
A failed K import does not block other valid sections and suppresses retained
K data from printing until corrected.

## Medication destinations

New automatic destinations:

- FEN / GI, TPN: Pediatric 2-in-1 PN and SMOFlipid IV orders.
- Hematology, Antiplatelet Therapy: aspirin and cangrelor.
- Infectious Disease, Antibiotics: recognized systemic antibacterial orders.

The PN product is recognized independently of the spelling of Continuous.
Each source order has one destination. Separate PN orders are not merged,
and a blank rate never inherits another bag's rate. TPN and cangrelor retain
infusion emphasis and the established Last Admin/pump-rate display.

Heparin and enoxaparin keep their existing DVT rules. Aspirin and cangrelor
no longer trigger the automatic DVT group. Explicit saved category or group
overrides remain in effect. Change such an order's category selector once to
Antiplatelet Therapy, or choose Automatic to use the new default.

Antibacterial defaults include the supplied cefepime, ceftriaxone, cefazolin,
ampicillin-sulbactam, amoxicillin, vancomycin, meropenem, piperacillin-tazobactam,
azithromycin, and sulfamethoxazole-trimethoprim patterns, among other named
systemic antibacterials. Eye, ear, topical, and irrigation preparations are
not automatically assigned. Antifungals are not relabeled as antibiotics.
Erythromycin retains the earlier requested Prokinetic Agents default.

Use the existing Admin category editor to rename, move, nest, or map additional
medications. Hidden and excluded orders remain hidden. Shared category edits
are received by other sessions when the saved archive is reloaded.

## Infectious Disease results

VANCOTROUGH is read from G and displayed once under Drug Levels as
Vancomycin trough, followed by its supplied value, units, flags, and date.
The latest numeric result from all supplied dates is used, without a new age
cutoff. No unit is guessed and no level or dose interpretation is generated.
An older result keeps its actual older date. Missing or canceled results do not
create a Drug Levels heading. A failed G section suppresses retained automatic
ID results until reviewed or successfully imported.

The Cultures heading is bold. Positive organisms remain bold and no-growth
results remain NGTD, with dates and specimen sites intact. An empty culture
snapshot displays Cultures: None. Hidden/excluded culture rows or a failed
F import do not falsely become None. Culture selection limits are unchanged.

## Installation

Replace the files in the application code folder with this package's contents.
Keep app.py at the root and include sbs.py. Preserve private Secrets and the
existing encryption key. Restart and refresh. No new dependencies are needed.
Archive schema 29 upgrades to 30, adding missing new built-in categories
without overwriting prior definitions or rules. Avoid downgrading after save.

No live deployment, private repository, clinical archive, or credentials were
accessed. Tests and previews use local simulations and synthetic data.
