# PICU Handoff 6.108

## Head circumference percentiles

The patient column now adds the WHO head-circumference-for-age percentile after the measurement and its date, for example `Head circumference: 43.52 cm [11/24/26] [56th %tile]`. The existing display limit remains under age 2. The local WHO daily reference uses explicit growth-chart sex and age at the measurement.

An optional `HC Age: 183 days` line can be placed in A, I or N, or entered in Labs / Vitals. `Head Circumference Age:` and `Age at HC measurement:` also work. This age belongs to the HC measurement and does not replace general Age or BMI Age. A clinician-selected corrected age can be entered here when appropriate. Prematurity is not inferred from diagnoses.

When HC Age is blank, a dated HC can use the documented current Age. The app records the date on which Age was pasted or changed, then subtracts the elapsed days to the HC measurement. It keeps that age date fixed when other fields are edited or the handoff is printed. A percentile based on a rounded current age has a `~` marker, such as `[~56th %tile]`. WHO's standard conversion of 30.4375 days per month is used for ages expressed in months.

Older saved handoffs without that age date need a fresh paste or explicit HC Age. An undated HC also needs HC Age. Missing or contradictory age/sex information leaves the measurement intact without adding an unsupported percentile. Extreme percentiles display as `[<1st %tile]` or `[>99th %tile]`. The editor explains unavailable calculations and flags HC values beyond 5 standard deviations for measurement review. It does not add a microcephaly or macrocephaly diagnosis.

## Estimated ideal body weight

For ages 2 through 19, the patient column displays estimated IBW when the recorded BMI is at or above the age- and sex-specific CDC 95th percentile. A fixed kilogram threshold is not used. Height, growth-chart sex and a sufficiently precise BMI measurement age must be available. The same BMI Age field and monthly reference bin used by the existing BMI feature are used here.

Estimated IBW in kilograms equals the CDC median BMI for age and sex multiplied by the recorded height in meters squared. For a male at 180 months with height 160 cm and an eligible BMI, the display is `Estimated IBW: 50.8 kg (BMI 50th %tile)`. The result is a reference estimate. Pediatric IBW methods are not interchangeable, and this value does not automatically select a medication, fluid, nutrition or ventilator dosing weight. The editor asks the clinician to verify that height and BMI refer to the same measurement episode.

The calculation uses the recorded BMI to establish eligibility. It does not reconstruct BMI or height from weight. A broad height-entry guard of 45 to 250 cm catches likely unit errors. That guard is not an age-specific growth-chart range. No pediatric IBW result is generated below age 2 or at age 20 and above.

## Latest ventilator mode from the Epic flow table

The All Vent Modes flow table is now the primary source for the current mode. The importer compares complete dates and times across every table block, including when Epic splits the six entries into multiple blocks. Blank cells keep their column positions and do not become mode entries.

When the newest mode is PS - CPAP, the handoff uses the dedicated CPAP Trial Settings for pressure support, PEEP, FiO2, and available weaning tidal volumes and tolerance. When a newer conventional mode follows the trial, its matching settings remain the main ventilator block and the most recent dated PS - CPAP trial is included below it as CPAP Trial Data. Other earlier table modes remain unchecked by default in the history editor. The older individual SmartLink history format keeps its existing behavior.

NAVA, AVAPS, and non-invasive modes continue through their existing settings rules. An empty or absent table uses the original Vent Mode field. The table can also supply the mode when that original SmartLink has been removed. An unrecognized newest table mode retains its name without borrowing settings from an older mode.

The timestamp belongs to the mode entry. Numerical settings still come from the matching settings section in the same paste, because the table does not timestamp those individual settings. No new settings are calculated.


## Paralytic PRN counts from the AF table

The handoff counts only vecuronium and rocuronium automatically. Paste the complete SmartPhrase as usual, including the dated volume table between the alternating af dividers. No PRN review form or confirmation step is needed.

Each positive dated Volume (mL) cell contributes one count. The parser combines repeated date-header blocks and preserves blank columns so each volume keeps its correct timestamp. Exact duplicate entries are included once. Blank and zero-volume cells do not contribute. Earlier dated FLOWDATETIME output and explicitly administered PRN entries remain supported. The presence of a paralytic infusion does not suppress the count.

Analgesic and sedative entries are ignored, including malformed entries in those columns beside valid paralytic records. The imported AF records contain only the two supported paralytics. Existing medication orders continue to be displayed through their normal mappings.

The count window starts at 07:00 Eastern on the calendar day before printing and ends at the time the handoff is prepared or printed. Both endpoints are included. For a handoff printed on November 22 at 12:30, counting starts on November 21 at 07:00 and includes available entries through November 22 at 12:30. The window continues past 07:00 on the printing day and is not a rolling 24-hour interval. Future entries are excluded until their administration time arrives.

The number appears after PRN on the first visible Neurologic PRN order for that medication. Counts below six display as `PRN × 5`, for example. Six or more display as `PRN ≥6`, reflecting the table's six-entry limit. The count adds no administration dates or times. A valid AF block with no qualifying entries gives zero for the ordered paralytic. A missing or unreadable AF block does not invent a count.

PDF generation, combined PDFs, PDF caching, and HTML printing use the same counting rules. HTML refreshes at printing, on focus, when visible, and every minute. It uses the timestamped entries contained in that export. New source records become available after a new paste.

## CPAP trial display

A reported Pressure Support - Continuous Positive Airway Pressure mode, including PS-CPAP, displays CPAP Trial Data. A valid dated trial in the flow table remains visible after the patient returns to a conventional mode. Repeated trial entries appear once, using the latest recorded trial time. A CPAP settings template alone does not establish that a trial occurred, and an untimed prior flow-table entry is not automatically included. The CPAP block omits the duplicate respiratory rate. Existing history controls can hide an included trial.

## Update from 6.107

Apply the files listed in UPDATE_FILES.txt together, including data/who_hcfa_lms.csv. Confirm Version 6.108 in the sidebar, then re-paste the complete SmartPhrase to attach the current-age reference date and refresh measurements. If Streamlit has not picked up the updated files, reboot the app once.

For an earlier version, use the complete repository's application files. Keep the current Streamlit Secrets and encryption key. Dependencies and archive schema 34 are unchanged. Existing eight-drug PRN records remain readable, but only the two paralytics receive automatic counts. Legacy review signatures do not gate the count.

## Verification

Version 6.108 verification is recorded in VALIDATION_GROWTH_6108.txt. Tests use synthetic data and cover official reference values, boundary conditions, parsing, replacement, saved records, editor callbacks, single-patient output, print-all and PDF cache invalidation.

## Earlier 6.107 verification

Version 6.107 verification is recorded in VALIDATION_CPAP_6107.txt. The attached source was checked locally with current PRVC-IMV settings at 20:00 and a separately displayed PS-CPAP trial at 11:30. Tests cover imports, current-mode selection, dedicated trial settings, duplicate trials, user hiding, replacement, saved records and exports. Patient source data is not included in the update package.

## Earlier 6.103 verification

801 focused tests passed on the merged 6.103 code. Coverage includes horizontal flow tables, the older mode-history format, CPAP selection, NAVA, AVAPS, NIV, missing-table fallback, native Streamlit import and save, PDF caching, and batch exports. The new coverage adds 32 table cases and one native end-to-end test. The run took 15.35 seconds and reported 103 existing anyio and pypdf deprecation warnings.

The supplied example selected the conventional mode at 11:40. Making PS - CPAP the newest entry selected its dedicated trial settings. A separate synthetic example combined the mode table with the AF table and retained the expected paralytic displays of `PRN × 5` at 10:30 and `PRN ≥6` at 12:02 while displaying CPAP correctly.

The 6.102 medications.py, prn_counts.py, and prn_html.py files remain identical to the current baseline. No supplied patient examples are committed. These are local runtime and automated checks. Live Streamlit deployment was not verified. See TEST_REPORT.md for details.

## Previous release verification

467 focused tests passed across parsing, HTML print refresh, integration, native Streamlit import and save, medication formatting, and the error journal. Coverage includes repeated header blocks, empty cells, exact duplicates, both paralytics, exclusion of other medications, previous-day 07:00 cutoffs, the six-entry cap, PDF caching, and existing archive compatibility.

The supplied complete SmartPhrase also imported its AF table successfully. It produced three qualifying entries at 06:59, five at 10:30, and the capped six display at 12:02 on the printing day. Its generated PDF used `PRN >=6`, the PDF font-compatible form of `PRN ≥6`.

Test fixtures use synthetic data. No supplied patient source is included in the repository. See V6102_README.md for the previous release's behavior and the earlier versioned notes for previous changes.
