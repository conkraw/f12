# Compact nutrition display

Version 6.71 updates the presentation introduced in 6.70.

## Printed format

```text
Diet: Peds Regular
Tube feed:
GT: Synthetic Formula (24 kcal/oz) @ 30 mL/hr (20 hr/day) | 480 kcal/day | 60 mL/kg/day
```

This synthetic example uses a dosing weight of 10 kg. A 24-hour feed omits the
hour annotation. The Tube feed heading appears once even when several distinct
tubes are listed. Oral feed records use Diet, alongside other oral diet orders.

Instructions and additives are stored for source review but do not print.
The display omits the multiplication equation, mL/day total and separate
Using dosing weight line.

## Calculations

For an active continuous order:

```text
daily mL = hourly mL times daily feeding hours
mL/kg/day = daily mL divided by dosing weight in kg
kcal/day = daily mL times kcal/mL
kcal/day = daily mL times kcal/oz divided by 30
kcal/day = daily mL times kcal/L divided by 1000
```

Blank duration defaults to 24 hours. Explicit conflicting or invalid duration
blocks that default. A provided duration other than 24 is printed, including
20 hours. Dosing weight accepts kg or g. Measured weight is never substituted.
Daily kcal and mL/kg are rounded to one decimal, with trailing zeros removed.
No calories are inferred from formula brand numbers, ketogenic ratios or
recipe ingredient amounts. The final feed density must be explicit. If no
density is present, the calorie total is omitted.

The 30 mL/oz nutrition convention is also used in the Children's Hospital of
Philadelphia patient instructions for preparing 24 kcal/oz infant formula:
https://chopib.staywellsolutionsonline.com/Bedside/22%2C38223
This reference supports the unit convention only. It does not supply any
patient-specific formula, recipe, density or feeding recommendation.

Held, future and bolus orders remain labelled and do not receive continuous
daily totals. A disagreement between the listed daily volume and rate times
hours withholds calculated totals for source review.

## Source reconciliation

A dietary order takes precedence over its matched current T-section record.
Matching first uses formula and compatible route, then a mutually unique
remaining compatible route. Formula differences are not interpreted as a
mixture or proof of equivalence. The displayed formula and calculation fields
stay together in the dietary order. A different recorded rate is not combined
with the dietary order's hours.

Unmatched distinct devices may appear as additional rows under the same
heading. Multiple ambiguous same-route devices are not silently collapsed.
Existing inclusion choices, current recorded_feed_ids, hidden-import guards
and PN medication deduplication continue to apply.

## Source and archive support

AB remains the detailed Dietary Orders section. X supports its existing diet
summary and detailed compact orders. T remains the recorded feeding source.
No SmartPhrase divider change or data migration is needed for this update.
Caloric-density fields support kcal/oz, kcal/mL and kcal/L. Original comments,
additives and source strings remain editable in the expanded source editor.
