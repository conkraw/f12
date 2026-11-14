# Dietary orders and feeding calculations

## Recognized source

The app accepts the new alternating AB divider pair around Dietary Orders.
It also recognizes detailed dietary content in X. When both X and AB are
pasted together, AB supplies the dietary snapshot. A malformed AB block does
not silently fall back to a different X summary. Duplicate AB sections still
trigger the existing multiple-patient rejection.

Detailed order headers, Question/Answer rows and repeated compact summaries
are matched within their source order. Repeated copies produce one entry.
Conflicting fields remain available in the retained source, are omitted from
calculation, and have a review notice. Order start dates do not silently cancel
another listed order. Explicit held/future labels remain visible.

## Separate routes of nutrition

| Source order | Display |
| --- | --- |
| Regular, Clear Liquid or another oral diet | Oral line |
| NPO with or without exceptions | Oral NPO line preserving the exception |
| Tube feeding with a documented route | Ordered tube-feed entry with the route |
| PN in both diet and medications | One matching medication entry |
| PN only in diet | Dietary PN entry |
| None or label printing only | No invented nutrition entry |

Oral feeding and tube feeding may coexist, including with PN. An NPO exception
for NJ medications is not evidence of enteral feeding. Breast-milk print labels
and oral-swab comments do not establish an oral diet.

GT, NJ, NG, OG, ND, GJ and the other existing supported method labels are used
when explicit. Nasoenteric (post-pyloric) stays Post-pyloric unless a matching
formula and one explicit NJ/ND feeding record appear in the same import.
Retained records from an earlier import do not establish the new order's route.

## Daily tube-feed amount

```text
mL/day = ordered rate in mL/hr x ordered feeding hours per day
mL/kg/day = calculated mL/day / documented dosing weight in kg
```

Dosing weight follows the app's existing I/O convention. Positive kg and g
values are supported. Measured weight is not substituted. A failed weight
import also prevents a new normalized calculation using retained weight.

Only active continuous orders with an explicit hourly rate and valid daily
hours are calculated. Bolus, held and future orders retain their supplied
schedule without being converted into a continuous daily total. Hours do not
default to 24. Intake volumes are never interpreted as hourly rates.

A supplied total that disagrees with rate times hours is shown beside the
calculated daily volume for review. The mL/kg/day figure is withheld until
that disagreement is resolved. No value is derived by dividing a listed total
by an assumed duration. Calculated mL/kg/day is rounded to one decimal place,
with unnecessary trailing zeroes removed.

Formula, caloric density, additives and full feeding instructions are retained.
A ramp-up plan remains visible beside the ordered total, so that total is not
presented as volume already delivered.

## Recorded feeding data

Detailed dietary orders are the source of the ordered formula, rate and hours.
Matching feeding records are not repeated. A different recorded rate remains
labelled Recorded rate and is not multiplied by a different order's hours.
If the ordered formula is missing, a matching known recorded formula remains
explicitly labelled Recorded formula.

Current feeding-row identifiers link the records supplied with the dietary
update. A new AB-only None or NPO import does not bring an older feeding record
back into output. A later explicit T update can add newly supplied records.
When an explicit dietary tube order is present, an unmatched formula-only tube
record without a rate is not presented as an additional feeding route. The
record remains available for editing. Legacy T-only behavior is preserved.

A failed detailed dietary update retains its source records but hides the
structured dietary and recorded-feed output until review or successful import.
Medication-based PN remains governed by its own medication source and choices.

## PN deduplication

Matching uses product/order identity, preserving formulation and schedule
qualifiers. A generic PN label matches only an unambiguous compatible product.
Different 2-in-1/3-in-1 products, cyclic/continuous orders, PPN/PN qualifiers,
age-specific products and distinct lipid brands remain separate.

Hidden and Ignore medication choices also suppress a matching dietary copy.
This does not erase the source order. Existing manual category choices remain
in effect. Explicitly named IV PN orders use the existing TPN medication group.

## Editing and compatibility

FEN/GI's dietary editor exposes the new fields and inclusion controls. Pending
changes are captured before save, room changes and printing. The existing
schema remains 34. Older snapshots open without migration. Records with the
new structured diet fields require version 6.70 or later after saving.

Install the complete application file set, including nutrition_display.py.
No new dependency, encryption key, repository path or Secrets field is needed.
