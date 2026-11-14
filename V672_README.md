# PICU Handoff 6.72

## Compact nutrition in FEN/GI

Oral intake is labelled Diet. Tube feeding appears under one Tube feed heading.
Each feed shows its documented route, formula and rate, followed by kcal/day
when an explicit caloric density is available. kcal/kg/day and mL/kg/day use
the documented dosing weight. A synthetic example is:

```text
Diet: Peds Regular
Tube feed:
GT: Synthetic Formula (24 kcal/oz) @ 30 mL/hr (20 hr/day) | 480 kcal/day (48 kcal/kg/day) | 60 mL/kg/day
```

Missing formula or rate is omitted without an UNK placeholder or a dangling @.
A known formula can appear without a rate, and a known rate without a formula.
An entry with neither is omitted, along with its empty Tube feed heading.

For continuous feeding, a blank duration uses 24 hours. A supplied 24-hour
schedule is also used without printing it. Other documented durations are
printed and used in the calculation. An invalid or conflicting duration does
not receive the default. Bolus, held and future orders do not get continuous
daily totals.

Instructions, additives, the daily-volume equation and the dosing-weight basis
line are omitted from the handoff. The original fields remain in Edit diet /
review source. Existing saved nutrition records use the compact display after
installing this version.

## One feeding entry

The dietary order supplies the formula, rate, duration and caloric density.
A matching current T-section record does not produce another entry. Exact
formula matches are paired first. An otherwise unique compatible tube can
also match when its recorded formula label differs. The recorded formula and
rate do not replace the dietary order. Separate and ambiguous devices remain
separate rows within the same Tube feed section.

A generic post-pyloric route can become NJ or ND only when the same import has
one unambiguous explicit device. Older saved T rows cannot refine a new order.
A T-only feeding record still displays compactly, using its own documented
hourly rate and the 24-hour default. Intake volume is never converted to rate.

## Calories and weight

Ordered daily volume equals hourly rate times feeding hours. Daily calories
use an explicit kcal/oz, kcal/mL or kcal/L density. The kcal/oz calculation uses
30 mL per ounce. No calorie value is inferred from a product name, recipe or
brand number. Missing density omits kcal/day and kcal/kg/day. Missing dosing
weight omits kcal/kg/day and mL/kg/day. kcal/kg/day divides the unrounded daily
calorie total by dosing weight and rounds the final result to one decimal. Measured weight is not substituted for dosing weight.

Conflicting supplied totals or values require source review and withhold the
related calculated amounts. Calculations are display values, not measured
intake or stored source facts.

PN present in both diet and medications continues to appear once. Oral diet,
tube feeding and PN can coexist. Hidden or ignored PN choices remain effective.

## Install

Replace the complete application file set in each app-code repository. Include
nutrition_display.py, and keep app.py at its deployed location. Restart and
confirm Version 6.72 | kcal/kg/day and clean tube feeds.

Keep existing Streamlit Secrets and encrypted data repositories. No key or
dependency changes are needed. Existing detailed nutrition records display in
the new format without reimport. Re-paste current dietary orders when their
clinical contents have changed.

The earlier QTc, NIRS, Ignore and AVAPS updates remain included. This ZIP has
not been deployed to the live apps. See NUTRITION_ORDERS_UPDATE.md,
TEST_REPORT.md and ARCHIVE_COMPATIBILITY.txt. Packaged examples are synthetic.
