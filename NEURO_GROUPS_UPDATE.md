# Version 6.40: Neurologic groups and compact trends

Built directly from the delivered 6.39 ZIP. Keeps the compact landscape layout,
automatic page fitting, PDF-only downloads, difficult-airway section, and all
other 6.39 features. There is no manual font-size picker.

## TV

The observed tidal-volume summary uses `Observed TV` instead of TVi or TVe.
The original inspiratory, expiratory or generic observed source field and value
remain stored and editable. Source selection is unchanged. Set TV remains Set TV.

## Compact lactate trend

The cardiovascular summary uses the earliest and latest eligible lactates within
the existing rolling 24-hour window:

```
Lactate 1.0 -> 1.1 [11/8/2026]
```

The bracket contains the latest selected result's date. A single eligible result
prints `Lactate 1.1 [11/8/2026]`. More than two results still display only the two
endpoints. The text wraps naturally to the available column width.

Time-based ordering and date-only source-order handling are unchanged. A
previous-day result without a collection time can overlap the cutoff, as before.
There is no new timing message on the handoff. Supplied flags and units remain
attached to each result, without conversion. Result codes do not print. Full
source values, dates and supplied times remain in Labs / Vitals. Older results
are filtered from the summary, not deleted.

## New neurologic medication groups

| Group | Automatic medication names |
|---|---|
| Airway/Cerebral Steroids | Systemic dexamethasone |
| Insomnia | Melatonin, trazodone |
| Antispasmodic | Baclofen |
| Neuromodulation | Gabapentin, pregabalin |

Local eye, ear and topical dexamethasone preparations do not receive the automatic
steroid group. The headings are display categories chosen for this workflow, not
inferred medication indications. Original doses, routes, frequencies, start/held
labels and administration-rate fields remain unchanged.

The automatic steroid category defaults to Neurologic. A deliberate Medication
group or system override can change the placement. Existing explicit overrides
and hidden/excluded medication choices are retained.

## Neurologic sequence

Recorded neurologic observations (SBS/RASS, WAT, and any ICP/CPP/EVD information)
remain first. The medication blocks then appear as:

```
Infusions
PRN
Paralytic Infusions
Paralytic PRN
Airway/Cerebral Steroids
Antiepileptic
Antispasmodic
Fever Control
Insomnia
Neuromodulation
```

The first blocks keep bedside sedation and paralytic information together.
The remaining named categories are sorted alphabetically by heading.
Only nonempty blocks print. Notes and other uncategorized neurologic medications
follow. Medicines within the neurologic blocks are sorted by the leading medication
name. The same medicine's orders and taper steps keep their relative source
order, including when Epic embeds a different dose in the product name.

Continuous IV rocuronium, cisatracurium and vecuronium appear under Paralytic
Infusions. Their PRN orders stay in Paralytic PRN. One-time boluses are not
classified as continuous infusions. Sedative infusion display retains the
existing system mappings and Last Admin emphasis. Antiepileptic infusions remain
inside Antiepileptic, with their infusion emphasis, instead of printing twice.

## Editing and installation

The new choices are available in Medications > Medication group and in the
existing Admin medication subgroup controls. Choices are remembered through the
existing settings. Setting a group explicitly overrides its automatic default.
The No special grouping choice permits the ordinary system mapping to apply.

Extract PICU640.zip and open PICU_Handoff_v6_40_Neuro_Groups. Upload that folder's
contents into the existing application code repository, replacing matching
files. Keep app.py at the root. Restart the app and refresh the browser.

Keep current Secrets, both passwords, the encryption key, medication mappings,
BMI reference data and the existing data repository. Do not rerun generators.
There are no new dependencies, secret fields or archive-schema changes.

Look for `Version 6.40 | Neurologic groups and compact trends`.

No re-pasting is needed for existing stored values or medication orders. An
explicit old override can still suppress a new automatic group. Change its
Medication group to Automatic or the desired category to use the new placement.
New subgroup choices are not understood by older releases. Do not downgrade
after saving them without restoring a compatible backup.

## Validation

See TEST_REPORT.md for the checks actually performed. The app was not deployed
to or tested against the user's live storage. Changes are delivered as this ZIP.
