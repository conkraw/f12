# PICU Handoff 6.70

## Nutrition in FEN/GI

The new AB dietary section accepts the detailed Dietary Orders table and the
compact Diet Orders list. Use paired alternating abab... dividers, as shown in
SMARTPHRASE_TEMPLATE.txt. Keep each patient's orders in a separate paste.

Oral intake, tube feeds and PN can appear together. Oral Regular, Clear Liquid,
NPO and NPO exceptions remain separate from tube-feed orders. An NJ medication
exception or a breast-milk label request does not create a tube feed. Oral-swab
instructions remain attached to their documented order.

Tube feeds show the documented method, formula, rate and hours per day. The
calculation is rate in mL/hr multiplied by the recorded hours per day, then
divided by the documented dosing weight in kg. A synthetic example is:

```text
Oral: Peds Regular
Tube feeds (ordered, GT): Synthetic Formula 1.0 (24 kcal/oz)
@ 30 mL/hr x 20 hr/day = 600 mL/day (60 mL/kg/day)
Using dosing weight: 10 kg
```

These are ordered volumes. Feeding advancement, mixture instructions, breaks,
fortifiers and caloric density remain visible. A 20-hour order is not treated
as 24 hours. No dosing weight means no mL/kg/day value. Missing duration is not
filled in, and measured weight is not substituted for dosing weight.

A documented NJ route prints as NJ. Generic post-pyloric orders stay generic
unless the same paste supplies one matching explicit NJ or ND feeding record.
A later dietary update cannot borrow a tube route from an older feeding record.

## PN appears once

A matching PN medication supplies the medication entry, and its dietary copy is
omitted. A deliberately hidden or ignored matching medication is not restored
through the diet section. A PN order available only in diet is shown there.
Distinct PN formulations and lipid products remain separate.

## Edit and print

Open FEN/GI, then Edit diet / review source to edit the imported nutrition
fields, feeding hours, fortification, instructions, order status and inclusion.
The same values appear in the preview, individual handoff and Print All.
An unreadable dietary update retains the previous snapshot for review while
hiding its structured nutrition and recorded-feed output.

## Install

Replace the complete application file set in each app-code repository. Include
the new nutrition_display.py module. Keep app.py at its deployed location.
Restart and confirm:

```text
Version 6.70 | Oral, tube feeds and TPN
```

Keep the existing Streamlit Secrets and each app's encrypted data repository.
No dependency or key change is required. Re-paste the SmartPhrase with the new
AB dietary section to populate the detailed feeding fields.

The complete package includes the earlier QTc, NIRS, Ignore and AVAPS updates.
The latest QTc troubleshooting example already parsed correctly in 6.69 and
continues to do so. This release adds nutrition support.

See NUTRITION_ORDERS_UPDATE.md, TEST_REPORT.md and ARCHIVE_COMPATIBILITY.txt.
The examples folder contains synthetic input and PDF/HTML/text previews. The
supplied clinical source examples are not included in the package. This ZIP
has not been deployed to the live apps.
