# PICU Handoff 6.113

## Generate a Word document

Open Utilities in the sidebar and unlock it with the existing separate Admin password. Choose a patient handoff, select Progress note or Attending attestation, and click Generate note. The Word document is ready to download with the applicable suggested plan references already included. Review and edit the downloaded document in Word.

There is no required confirmation step for each suggested diagnosis. The utility uses documented diagnoses, current respiratory support, active medications and their mapped therapeutic categories, viral results, nutrition support, and supported laboratory findings to populate the plan on the first generation.

Both exports use the original uploaded Word templates. Existing styles, tables, fonts, colors, headers, footers, and margins are preserved. Added content flows through the document naturally, so a longer note can use additional pages. Existing Epic links, SmartLists, wording, and placeholders remain available for completion.

The progress note includes medication review lists beneath the Neurologic, Respiratory, Cardiovascular, and FEN/GI SmartList references. Hematology and Infectious Diseases use their existing medication blocks. The expanded contents of the four system SmartLists are not present in the source Word document. After expansion in Epic, move relevant medication lines into the intended placeholders and remove review text you do not need.

Each main system keeps the simple Drips, Scheduled, and PRN lists. Therapeutic category names such as Bowel Regimen, GI prophylaxis, and Antiepileptic help identify suggested plans internally and do not become medication subheadings in the Word document or plain-text note. Recorded doses and rates are copied without new dose, weight, fluid, nutrition, or PRN-count calculations. A missing drip rate is marked for review. Held or stopped orders carry their status instead of a stale rate and do not supply active-medication plan suggestions.

The attending attestation keeps its original wording, examination SmartLists, assessment, and clinical-indication reference. Its plan uses the same automatic suggestions, but the document contains no medication lists.

Only Generate note and Update note with selected plans build the document. Opening Utilities, changing plan selections, saving phrase settings, and downloading do not regenerate it. Prepared Word and plain-text downloads are reused until you generate or update the note. The plain-text preview is read-only. Make document edits in the downloaded Word file.

## Automatic plan references

Plan references are arranged in this order: Neurologic, Respiratory, Cardiovascular, FEN/GI, Hematology, then Infectious Diseases. The plan contains only the diagnosis references. It does not add system names or therapeutic subcategory headings. This order is the same in the preview, progress-note Word download, attending-attestation Word download, and optional manual plan selections.

When more than one supported virus is present, the viral references are adjacent within the infectious-disease portion of the plan. Each virus keeps its own exact SmartPhrase. Repeated evidence for the same diagnosis still produces only one reference.

The following handoff information can now place the matching reference in the plan immediately:

| Handoff information | Suggested plan reference |
| --- | --- |
| Current invasive or noninvasive respiratory support | The corresponding acute hypoxemic respiratory failure phrase |
| Sedative therapy with an identifiable support route | The corresponding restlessness and agitation phrase |
| Active antibiotic therapy or a mapped antibiotic category | Sepsis |
| Constipation medication or a mapped bowel regimen category | Constipation |
| Pantoprazole or a mapped gastric prophylaxis category | At risk for gastric ulcers |
| Antiepileptic medication or its mapped category | At risk for seizures |
| Melatonin or the mapped Insomnia category | `@ACKZINSOMNIA@` |
| Bethanechol or the mapped Airway Tone Modulator category | `@ACKZTRACHEOBRONCHOMALACIA@` |
| A medication mapped to Antiarrhythmics | `@ACZKARRHYTHMIA@` |
| A supported positive respiratory viral result | The matching viral diagnosis phrase |
| NPO, active feeding orders, recorded feeds, or parenteral nutrition | At risk for malnutrition |
| Supported current laboratory abnormalities | Matching phrases such as anemia, thrombocytopenia, coagulopathy, hypokalemia, and other electrolyte abnormalities |

These are suggested plan references for your review in Word. Uncertain positive diagnosis wording can also supply a reference. Explicit negative or historical diagnoses are not automatically included. Laboratory matching uses recorded source results, abnormal flags, and the app's existing supported thresholds. Newer normal or unusable results suppress older abnormalities. It does not calculate new laboratory values. Viral matching uses the latest supported result for each component, so a newer negative result does not retain an older positive result.

Recognized positive viral results include adenovirus, rhinovirus or the combined rhinovirus/enterovirus target, influenza, parainfluenza, RSV, and explicitly identified COVID-19 or SARS-CoV-2. A positive target without a matching supplied phrase produces a message. For example, no phrase name was supplied for human metapneumovirus. Known source assay names retain their identity when their display labels are edited.

Saved specific subcategories take precedence over broader parent categories and generic medication-name rules. A custom subcategory can match any of the existing diagnosis labels or exact phrase names. Category labels remain internal. An active feeding order can supply the malnutrition-risk reference even when its rate is unknown, without calculating intake.

The antiarrhythmic defaults include amiodarone, procainamide, esmolol, sotalol, digoxin, ivabradine, and qualifying intravenous lidocaine. The supplied spelling ivardabine is also recognized. An additional drug mapped to the Antiarrhythmics category supplies the same reference. Local lidocaine preparations do not automatically supply an arrhythmia reference. `ACZKARRHYTHMIA` retains the exact spelling supplied by the user.

The Word document is available without opening the plan controls. To change the included references in the app, open Edit included plans (optional). Use Included suggested plans to remove or restore a suggestion, or Add another plan to choose a catalog entry. Click Update note with selected plans to prepare the revised document. Your explicit selections replace the automatic defaults for that update. The reason for each suggestion remains available under Sources for suggested plans.

The catalog contains 88 entries using the complete supplied names, including the new `ACZKARRHYTHMIA` name. For example, pantoprazole can produce:

```text
PLAN
@ACKZATRISKFORGASTRICULCERS@
```

Both respiratory phrase names are confirmed defaults:

```text
@ACKZACUTEHYPOXEMICRESPIRATORYFAILUREINVASIVE@
@ACKZACUTEHYPOXEMICRESPIRATORYFAILURENONINVASIVE@
```

Current respiratory support determines the matching route and can include its plan reference without a separate confirmation. Historical modes do not add a second respiratory plan. Conflicting current airway information does not automatically include both competing plans.

Epic phrase settings allows a custom invasive phrase name and a choice of output format. Save phrase settings retains those choices in the existing encrypted settings.

## Handoff medication placement

These requested placements apply to new imports and saved handoffs with older assignments:

| Medication | Handoff system | Handoff subcategory | Note reference |
| --- | --- | --- | --- |
| Enteral calcium carbonate | FEN/GI | Hypocalcemia | `@ACKZHYPOCALCEMIA@` |
| Enteral sodium chloride | FEN/GI | Hyponatremia | `@ACKZHYPONATREMIA@` |
| Zinc acetate | FEN/GI | Zinc Deficiency | No new phrase supplied |

The calcium carbonate and sodium chloride rules require an enteral route or an explicitly enteral product. Nebulized saline and intravenous fluids keep their separate rules. Zinc acetate also qualifies when the route is unspecified, while explicitly nonenteral products are excluded. Ignore and hidden or excluded orders remain respected. These placement rules leave saved rule definitions and recorded medication amounts unchanged.

Hypocalcemia and Hyponatremia supply their existing note references. Zinc Deficiency appears as a handoff subcategory, but the note does not invent an Epic phrase name for it. The note continues to omit subcategory headings from medication review lists.

## Epic reference format

The requested template format is the default. Dot phrases are available as a separate setting, for example `.ACKZATRISKFORGASTRICULCERS`.

Epic training distinguishes SmartLinks from personal SmartPhrases. SmartLinks appear between at signs in templates. The documented interactive SmartPhrase workflow uses a period followed by the name and an expansion action such as Spacebar. Confirm that the exported custom references expand in the local Epic installation. The utility creates documents and does not connect to Epic.

Sources:

- [Methodist physician settings guide](https://www.methodistmd.org/files/epic/user-settings-lab/mlh-provider-user-settings-guides/pdfs/Inpatient%20and%20Outpatient%20Physician%20User%20Settings%20Guide.pdf), pages 4 through 7.
- [University of Iowa SmartTools guide](https://epicsupport.sites.uiowa.edu/epic-resources/smarttools).

## Draft controls

The draft and prepared downloads stay in the current administrator session and do not overwrite the handoff. Changing the patient, document type, or source handoff clears the old draft. Locking Admin, leaving the protected workspaces, logging out, returning Home, or resetting the patient list clears the draft and revokes its prepared downloads. Protected actions recheck Admin access, including after Word rendering. Expired or revoked downloads are rejected.

## Install from version 6.109 through 6.112

Use the complete update package. Upload these fourteen Python files together beside the existing app.py, replacing matching files:

- app.py
- admin_access.py
- models.py
- error_store.py
- categories.py
- fen_gi.py
- medication_groups.py
- note_generator.py
- note_medications.py
- note_medication_rules.py
- note_findings.py
- note_settings.py
- note_utility.py
- note_word.py

Also upload the templates folder with both files, keeping these paths:

- templates/picu_progress_note.docx
- templates/attending_attestation.docx

There is no dependency change. Keep the existing Streamlit Secrets and encryption key. Restart the app and confirm version 6.113 in the sidebar.
