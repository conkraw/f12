# PICU Handoff 6.85 verification

## Results

All 718 distinct executed checks passed.

| Check group | Passed | Coverage |
| --- | ---: | --- |
| Focused regression suite | 609 | Anti-Xa, lab routing, CV time windows, existing drug levels, ECLS, room replacement, security, UI, login, PDF exports and cache behavior |
| AED selection tests | 87 | Assay recognition, latest result selection, strict 24-hour handling, date uncertainty, flags and unchanged source rows |
| AED integration and export tests | 22 | G imports, Neuro and Labs placement, single and batch exports, room separation, archive round trips and cache expiration |

A final combined run of the 87 AED selection tests and 22 integration tests passed all 109 checks. This repeats those checks and is not added to the 718 total.

The supplied complete SmartPhrase imported with no skipped sections. Its requested G-section drug levels and flags were recognized, and the date-only prior-day results used the dated Labs fallback at the reviewed morning cutoff. The source text was processed locally and is excluded from this package.

## AED selection and placement

Tests cover PHENOBARB and PHENYTOIN, supported Phenobarbital and total Phenytoin aliases, and separation of free Phenytoin. They verify that the latest valid measured result is selected before applying the time window, independently for each drug.

Recent results appear in Neuro through the exact 24-hour boundary. Older or date-only results whose age cannot be established within that window appear in lower Labs with Last checked and the original date. A mixed case puts one drug in Neuro and the other in Labs. Earlier history is not duplicated.

Coverage includes missing results, disabled rows, invalid values, status text, future dates, date-only uncertainty, daylight saving time boundaries, stale saved timestamps and recognized label variants. Values, abnormal flags, supplied units and raw rows remain unchanged. No collection time or unit is invented.

## Import, storage and replacement

Real G-section import tests cover dated and timed source rows. New complete room imports without G do not retain prior drug levels. Failed G-section imports suppress automatic AED output from retained rows. Batch checks keep separate rooms' results independent.

Encrypted archive round trips retain the original lab rows without a new AED field. Schema 34 remains in use. Existing ECLS import, calculations, missing data handling and room replacement checks passed.

## ECLS and export coverage

ECLS now has six logical lines, including its heading. Mode, blood flow, RPM, sweep and FiO₂ each have a separate setting line without pipe separators. The existing CV order remains vitals, cardiac labs, ECLS, then notes and medications. Indexed flow still uses dosing weight, and CI still uses the chart-reported BSA.

Plain text, HTML preview, batch HTML, single PDF and batch PDF checks cover AED placement and one selected result per drug. They verify preserved dates and flags, lower Labs labels, bold AED Drug Levels: headings in HTML and PDF, and the existing clinical font size. ECLS export checks cover the separate setting lines and placement.

The display uses the current Eastern clock. A result at the exact 24-hour boundary appears in Neuro. One second later, it moves to Labs. The PDF content signature changes so an earlier cached PDF is not reused after that change.

## Visual PDF review

A two-page synthetic batch PDF was generated, rendered to PNG with Poppler, and visually inspected at the existing handoff size.

The first page contains recent AED levels in Neuro and the separate ECLS settings lines in CV. The second page contains older AED results in a compact lower Labs card with independent Last checked dates. The headings are bold and the drug results remain readable. Long blood flow and date lines wrap within their columns. No clipping or overlap was seen.

These visual examples contain synthetic data only. The handoff font size and column widths were not enlarged for the review.

## Login and scope

The centered password screen is unchanged from version 6.84. Its existing Streamlit AppTest checks passed within the 609-check regression suite. No new browser visual review was performed for this update.

Checks ran locally with the installed runtime dependencies. Dependencies and configuration requirements are unchanged. Existing deprecation warnings did not affect the checks. No live deployment, production password or production archive was used.
