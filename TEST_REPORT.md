# PICU Handoff 6.102 verification

467 focused automated checks passed. Tests use synthetic records. The final code is based on version 6.101 and follows the newly requested window through printing.

## Reporting and source behavior

The AF parser reads horizontal dated volume tables, including repeated headers and empty cells. Each positive volume contributes one record. Existing dated FLOWDATETIME inputs remain supported. Only vecuronium and rocuronium are counted.

The window begins at 07:00 Eastern on the calendar day before printing. Both endpoints are inclusive. Today's doses after 07:00 enter the count when they are at or before the printing clock. At midnight, the start date advances. Date filtering occurs before the six-entry cap.

Counts below six use `PRN × N`. Six or more use `PRN ≥6`. PDF output uses the equivalent `PRN >=6` for compatibility with its existing font. No count review or infusion check is required.

## Verification groups

| Group | Passed |
| --- | ---: |
| Core parsing, counts, boundary and calendar cases | 122 |
| HTML script and markup | 45 |
| Import, text/HTML/PDF integration and native Streamlit flow | 53 |
| Medication formatting and encrypted error journal regressions | 247 |
| Total | 467 |

Coverage includes repeated and blank table cells, exact duplicates, malformed dates, separate paralytics, ignored sedatives and analgesics, print-time inclusion, five-to-six transitions, midnight, daylight saving transitions, year and leap-day boundaries, fractional timestamps, Python/JavaScript agreement, PDF cache refresh, archive compatibility, and complete room replacement.

The supplied full SmartPhrase also imported AF successfully. It produced three entries at 06:59, five at 10:30, and the capped six display at 12:02 on the printing day. A PDF generated from that input contained `PRN >=6`. No supplied patient text or output was written to the repository.

Existing anyio and pypdf deprecation warnings were reported. Dependencies and archive schema 34 remain unchanged. Live deployment status is separate from these local runtime and automated checks.
