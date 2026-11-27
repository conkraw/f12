# PICU Handoff 6.118

## Generate a Word document

Open Utilities in the sidebar and unlock it with the shared Admin username and existing Admin password. Admin and Utilities use the same credentials. The username defaults to `admin` when no `admin_username` is configured under `[app]` in deployment Secrets. Choose a patient handoff, select Progress note or Attending attestation, and click Generate note. The Word document is ready to download with the applicable suggested plan references already included. Review and edit the downloaded document in Word.

There is no required confirmation step for each suggested diagnosis. The utility uses documented diagnoses, current respiratory support, active medications and their mapped therapeutic categories, viral results, nutrition support, and supported laboratory findings to populate the plan on the first generation.

Both exports use the original uploaded Word templates. Existing styles, tables, fonts, colors, headers, footers, and margins are preserved. Added content flows through the document naturally, so a longer note can use additional pages. Existing Epic links, SmartLists, and assessment placeholders remain available for completion. The two medication placeholders in Hematology and Infectious Diseases are removed from the generated progress note, including when those medication cells are empty.

The progress note selects a full neurologic section from the seven supplied templates, with neuro medications inside its Medications cell. Respiratory and Cardiovascular medication lists remain directly beneath their SmartList references. The age-appropriate FEN/GI section appears immediately before Hematology, with its medications inside the supplied table's Medications cell. Hematology and Infectious Diseases use their existing medication blocks. The extra medication review captions are omitted. The expanded contents of the two remaining system SmartLists are not present in the source Word document. After expansion in Epic, move relevant medication lines into their intended placeholders as needed.

Each main system keeps the simple Drips, Scheduled, and PRN lists. Therapeutic category names such as Bowel Regimen, GI prophylaxis, and Antiepileptic help identify suggested plans internally and do not become medication subheadings in the Word document or plain-text note. Recorded doses and rates are copied without new dose, weight, fluid, nutrition, or PRN-count calculations. A missing drip rate is marked for review. Held or stopped orders carry their status instead of a stale rate and do not supply active-medication plan suggestions.

The attending attestation keeps its original wording, examination SmartLists, assessment, and clinical-indication reference. Its plan uses the same automatic suggestions, but the document contains no medication lists.

Only Generate note and Update note with selected plans build the document. Opening Utilities, changing plan selections, saving phrase settings, and downloading do not regenerate it. Prepared Word and plain-text downloads are reused until you generate or update the note. The plain-text preview is read-only. Make document edits in the downloaded Word file.

## Automatic neurologic section

The utility uses current handoff findings to choose one of the supplied neurologic templates. It replaces the general Neurologic SmartList reference with the selected full table between Objective and Respiratory. The selected phrase name and a short reason appear in Utilities after generation.

When several templates apply, the more specific section takes priority in this order:

| Current handoff finding | Selected section |
| --- | --- |
| Documented traumatic brain injury | ACKNTBI |
| Current ICP monitoring or EVD | ACKNICPMONITORING |
| Documented status epilepticus | ACKNSTATUSEPI |
| Recorded cerebral oximetry or current cardiac postoperative context | ACKNCTPATIENT |
| Current invasive ventilation or intubation | ACKNINTUBATED |
| Documented extubation, or nonintubated support with sedation or withdrawal monitoring | ACKNEXTUBATED |
| No more specific matching finding | ACKNNONE |

Neuro medications appear once in the selected table's Medications cell, separated only into Drips, Scheduled, and PRN. The medication placeholder is removed even when the list is empty. Recorded doses and rates are copied without calculations. The original table formatting and examination, monitoring, imaging, and laboratory references are preserved.

Historical, negated, uncertain, removed, excluded, or failed-import data do not supply a more specific current neurologic section. Antiepileptic therapy alone does not select status epilepticus. A CT scan alone does not select the cerebral-oximetry template. Prior ventilator modes and a CPAP trial alone do not establish current intubation. An absent ETT does not by itself establish extubation.

The selector reads the handoff each time a generation button is pressed. Changes to the source handoff clear the previous prepared note. Editing the optional plan selections does not change which neurologic template the handoff supports. The attending attestation retains its own examination layout and does not receive these tables or medication lists.

The TBI and ICP device-site examination uses the confirmed reference `{ICPMONITORSITE:45483}`. The status-epilepticus template retains `{ACKNIMAGES:45359}` under both EEG and imaging, as supplied.

## Age-appropriate FEN/GI section

The progress note uses the full formatted section supplied in the corresponding attachment:

| Documented current age | Supplied section | Distinguishing anthropometric field |
| --- | --- | --- |
| Less than 2 years | ACKFENGILESSTHAN2YEARS | Head circumference |
| At least 2 years, including exactly 2 years or 24 months | ACKFENGIGREATERTHAN2YEARS | Body mass index |

The selected table replaces the general FEN/GI SmartList placeholder. Its original Epic links, SmartLists, labels, and formatting remain in place. FEN/GI medications fill the table's Medications cell using Drips, Scheduled, and PRN groups. The medication placeholder is removed even when the list is empty. The separate urine-output and assessment placeholders remain available for completion.

Selection uses the current patient age documented in the handoff. An explicitly labeled current age in the demographics text can support older handoffs. Historical BMI or head-circumference measurement ages are not used to choose the section. Missing, malformed, conflicting, or boundary-ambiguous age keeps the general FEN/GI placeholder and medication list, with a message to verify the current age and regenerate. The utility does not guess an age or birth date.

The attending attestation retains its original structure and does not acquire a FEN/GI table or medication lists. Editing patient age clears the previous prepared note. Generate a new note to apply the updated age.

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
| A medication mapped to Antiarrhythmics | `@ACKZARRHYTHMIA@` |
| Active milrinone therapy | `@ACKZHEARTFAILURE@` |
| Documented hypoalbuminemia, a matching category, or a supported low albumin result | `@ACKZHYPOALBUMINEMIA@` |
| A supported positive respiratory viral result | The matching viral diagnosis phrase |
| NPO, active feeding orders, recorded feeds, or parenteral nutrition | At risk for malnutrition |
| Supported current laboratory abnormalities | Matching phrases such as anemia, thrombocytopenia, coagulopathy, hypokalemia, and other electrolyte abnormalities |

These are suggested plan references for your review in Word. Uncertain positive diagnosis wording can also supply a reference. Explicit negative or historical diagnoses are not automatically included. Laboratory matching uses recorded source results, abnormal flags, and the app's existing supported thresholds. Newer normal or unusable results suppress older abnormalities. It does not calculate new laboratory values. Viral matching uses the latest supported result for each component, so a newer negative result does not retain an older positive result.

Recognized positive viral results include adenovirus, rhinovirus or the combined rhinovirus/enterovirus target, influenza, parainfluenza, RSV, and explicitly identified COVID-19 or SARS-CoV-2. A positive target without a matching supplied phrase produces a message. For example, no phrase name was supplied for human metapneumovirus. Known source assay names retain their identity when their display labels are edited.

Saved specific subcategories take precedence over broader parent categories and generic medication-name rules. A custom subcategory can match any of the existing diagnosis labels or exact phrase names. Category labels remain internal. An active feeding order can supply the malnutrition-risk reference even when its rate is unknown, without calculating intake.

The antiarrhythmic defaults include amiodarone, procainamide, esmolol, sotalol, digoxin, ivabradine, and qualifying intravenous lidocaine. The supplied spelling ivardabine is also recognized. An additional drug mapped to the Antiarrhythmics category supplies the same reference. Local lidocaine preparations do not automatically supply an arrhythmia reference. The corrected phrase is `ACKZARRHYTHMIA`. Older saved arrhythmia names or category labels with the previous typo still resolve to this corrected output.

The requested milrinone rule adds the heart-failure reference in the cardiovascular portion of the plan, including when milrinone has another saved category. Other inotropes do not receive that reference from this rule. Held, stopped, excluded, and future orders do not supply active-medication suggestions.

Hypoalbuminemia appears in the FEN/GI portion of the plan. Albumin matching uses the recorded low flag or an existing saved low-result limit with matching units. It accepts ALB and ALBUMIN source names and respects the latest recorded result. A newer normal or unusable result suppresses an older low result. No new numeric threshold is added.

The Word document is available without opening the plan controls. To change the included references in the app, open Edit included plans (optional). Use Included suggested plans to remove or restore a suggestion, or Add another plan to choose a catalog entry. Click Update note with selected plans to prepare the revised document. Your explicit selections replace the automatic defaults for that update. The reason for each suggestion remains available under Sources for suggested plans.

The catalog contains 89 entries using the complete supplied names, including `ACKZARRHYTHMIA` and `ACKZHYPOALBUMINEMIA`. For example, pantoprazole can produce:

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

Admin and Utilities share one username/password login and one timed unlock. The existing `admin_password_hash` is used by both workspaces. To choose a different shared username, add `admin_username = "your_username"` under the existing `[app]` section in deployment Secrets. No password or encryption-key replacement is needed. Changing the configured username or either password hash revokes the previous unlock and prepared note downloads on the next authorization check.

The draft and prepared downloads stay in the current administrator session and do not overwrite the handoff. Changing the patient, document type, or source handoff clears the old draft. Locking Admin, leaving the protected workspaces, logging out, returning Home, or resetting the patient list clears the draft and revokes its prepared downloads. Protected actions recheck Admin access, including after Word rendering. Expired or revoked downloads are rejected.

## Install from version 6.109 through 6.117

Use the complete update package. Upload these sixteen Python files together beside the existing app.py, replacing matching files:

- app.py
- admin_access.py
- models.py
- error_store.py
- categories.py
- fen_gi.py
- medication_groups.py
- note_generator.py
- note_fengi.py
- note_neuro.py
- note_medications.py
- note_medication_rules.py
- note_findings.py
- note_settings.py
- note_utility.py
- note_word.py

Also upload the templates folder with all eleven files, keeping these paths:

- templates/picu_progress_note.docx
- templates/attending_attestation.docx
- templates/fengi_under_2.docx
- templates/fengi_age_2_plus.docx
- templates/neuro_ct_patient.docx
- templates/neuro_none.docx
- templates/neuro_icp_monitoring.docx
- templates/neuro_intubated.docx
- templates/neuro_tbi.docx
- templates/neuro_status_epilepticus.docx
- templates/neuro_extubated.docx

The package also includes `ADMIN_SETUP.txt` and an updated `secrets.example.toml` for reference. Keep your current Secrets values, especially the existing Admin password hash and encryption key. Do not replace them with the example file. There is no dependency change. Restart the app and confirm version 6.118 in the sidebar, then use the shared username and existing Admin password for Admin or Utilities. Generate a new note to apply the corrected ICP monitor site examination reference.
