# Nutrition display tweaks in 6.72

Version 6.72 adds kcal/kg/day and removes unknown feeding placeholders.

## Example

```text
Diet: Peds Regular
Tube feed:
GT: Synthetic Formula (24 kcal/oz) @ 30 mL/hr (20 hr/day) | 480 kcal/day (48 kcal/kg/day) | 60 mL/kg/day
```

This synthetic example uses a dosing weight of 10 kg. Formula, route, rate and
non-24-hour duration remain together. kcal/kg/day appears beside kcal/day.

## Weight-normalized calories

Daily calories still use the documented hourly rate, feeding hours and explicit
final caloric density. kcal/kg/day is the unrounded daily calorie total divided
by dosing weight in kg, then rounded to one decimal with trailing zeros removed.
Daily calories and weight-normalized calories are rounded independently.

The same dosing-weight rule applies to kcal/kg/day and mL/kg/day. A measured
weight is never substituted. Missing, zero or invalid dosing weight omits both
normalized values. A failed weight import also prevents using retained DCW.
Daily kcal can remain visible when density and rate are known but DCW is absent.

All 6.71 duration, listed-volume, held/future/bolus and explicit-density guards
remain. A missing continuous duration uses 24 hours. An unreadable or conflicting
supplied duration does not default, including after acknowledgment or recall.

## Missing fields

A missing or UNK formula is omitted while its known rate remains visible. A
missing rate is omitted while its known formula remains. The @ separator only
appears when both are present. A rate-only entry may retain its own explicit
density and valid calculated totals. An entry with neither formula nor rate
does not print. An empty Tube feed heading does not print.

The stored source remains editable, so a later correction can restore the
missing field. This applies to detailed dietary orders and recorded T-only
feeds. The Print All eligibility check uses the compact display, preventing an
otherwise empty record from being selected solely for an unknown feed row.

## Prior compact behavior

Tube feeds appear in one place. Dietary orders remain authoritative over their
uniquely matched recorded counterparts. Distinct devices remain separate.
Instructions, additives, the daily-volume equation and the dosing-weight basis
line do not print. Oral intake is labelled Diet. PN deduplication is unchanged.

The explicit-density unit convention and calculation details are documented
in V671_NUTRITION_ORDERS_UPDATE.md. This version changes neither that convention
nor how caloric density is parsed.
