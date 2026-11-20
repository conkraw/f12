# PICU Handoff 6.87 verification

## Results

All 630 executed checks passed.

| Check group | Passed | Coverage |
| --- | ---: | --- |
| Existing regression checks | 516 | Anti-Xa, Heme infusions, DVT grouping, lab routing, lactate trends, AED selection and exports, ECLS exports, PDF cache and UI smoke checks |
| Lysis Labs selection checks | 97 | Supported assays, latest two results, time windows, source ordering, single results, flags, units and unchanged source rows |
| Lysis Labs integration checks | 17 | G imports, Heme-only placement, text and HTML, single and batch PDFs, cache aging, failed imports and room replacement |

The supplied complete SmartPhrase imported without errors. Its only available lysis assay was correctly displayed as a single HGBFREE result with its less-than symbol and source date. No missing LDH or uric acid value was invented. The supplied patient paste was processed in memory and is excluded from the package.

## Selection and placement

The checks confirm that each supported assay uses the latest two eligible measurements rather than the earliest and latest when there are more than two. The displayed arrow runs from older to newer. A single result has no arrow. Missing or unusable assays have no placeholder line, and an empty group has no heading.

The time window and date-only overlap convention match lactate. Tests cover the exact 24-hour boundary, future and malformed dates, same-day source ordering, zero values, explicit status messages, excluded rows and failed G imports. Source values, units and flags remain unchanged. CBC HGB, lactate, urine uric acid and LDH isoenzymes are kept separate.

All export formats show the block once in Hematology before existing body content. Recognized lysis assays are not duplicated in lower Labs or CV. Cached PDFs are rebuilt when the current time changes result eligibility. A new complete paste without G removes prior lysis results for that room, with other rooms preserved.

## Visual review

A two-page synthetic PDF was rendered to PNG with Poppler and visually inspected. The first page shows a single HGBFREE result. The second shows separate HGBFREE, LDH and uric acid trend lines. The bold heading, labels, flags and dates are readable in the Heme column. Long lines wrap within the existing column at the existing font size. No clipping or overlap was seen.

## Scope

The package retains the centered login and the previous ECLS and AED formatting. No dependencies or archive schema changes were needed. Existing pytest and pypdf deprecation warnings did not affect the checks. Verification used synthetic fixtures and local imports, without a live deployment or production credentials.
