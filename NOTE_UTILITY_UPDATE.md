# PICU Handoff 6.120

## New in this update

The note utility recognizes seven additional diagnosis references:

| Documented diagnosis or matching wording | Plan reference |
| --- | --- |
| Hypoplastic left heart syndrome or HLHS | `@ACKZHLHS@` |
| Chylothorax or chylous pleural effusion | `@ACKZCHYLOUSEFFUSION@` |
| Prematurity or a clearly documented preterm birth | `@ACKZPREMATURITY@` |
| Trisomy 13 or Patau syndrome | `@ACKZTRISOMY13@` |
| Trisomy 21 or Down syndrome | `@ACKZTRISOMY21@` |
| Trisomy 18 or Edwards syndrome | `@ACKZTRISOMY18@` |
| Metachromatic leukodystrophy | `@ACKZMETACHROMATICLEUKODYSTROPHY@` |

Repeated diagnosis descriptions produce one reference. The existing plan order and optional editing controls remain in place. The new baseline conditions can be recognized in the patient's own documented history. Documented prematurity includes relevant birth history. The patient's current age in weeks does not establish prematurity. Family history and prenatal screening alone do not supply these new plan references.

The lower Other labs list includes the latest available TSH, free T4, and cortisol from the supplied laboratory results. These tests use all supplied dates, including results before admission or outside the 24-hour window. The display preserves the recorded value, units when supplied, abnormal flag, and collection date. Equivalent component names are combined so CORT and CORTISOL do not produce duplicate cortisol entries. Free T4 remains distinct from total T4.

The display uses the last included measured result. A newer pending, canceled, or unusable entry does not displace that result. All original rows remain available in the lab editor. Future-dated results and failed current lab imports do not supply a displayed level. If the source contains no usable result for one of these tests, the utility leaves that test out.

## Generate a Word document

Open Utilities in the sidebar and unlock it with the shared Admin username and existing Admin password. Admin and Utilities use the same credentials. The username defaults to `admin` when no `admin_username` is configured under `[app]` in deployment Secrets. Choose a patient handoff, select Progress note or Attending attestation, and click Generate note. The Word document is ready to download with the applicable suggested plan references already included. Review and edit the downloaded document in Word.

There is no required confirmation step for each suggested diagnosis. The utility uses documented diagnoses, current respiratory support, active medications and their mapped therapeutic categories, viral results, nutrition support, and supported laboratory findings to populate the plan on the first generation.

Both exports use the original uploaded Word templates. Existing styles, tables, fonts, colors, headers, footers, and margins are preserved. Added content flows through the document naturally, so a longer note can use additional pages. Progress-note table headings stay with their following content when a page break is needed. Existing Epic links, SmartLists, and assessment placeholders remain available for completion. The two medication placeholders in Hematology and Infectious Diseases are removed from the generated progress note, including when those medication cells are empty.

The progress note selects full neurologic, respiratory, and cardiovascular sections from the supplied templates. Each system's medications appear inside its selected table's Medications cell. The age-appropriate FEN/GI section appears immediately before Hematology, with its medications inside the supplied table's Medications cell. Hematology and Infectious Diseases use their existing medication blocks. The extra medication review captions are omitted.

Each main system keeps the simple Drips, Scheduled, and PRN lists. Inside a Word table, each group starts with its bold label and first medication on the same line. Additional medications appear on their own lines, keeping long lists readable across pages. Therapeutic category names such as Bowel Regimen, GI prophylaxis, and Antiepileptic help identify suggested plans internally and do not become medication subheadings in the Word document or plain-text note. Recorded doses and rates are copied without new dose, weight, fluid, nutrition, or PRN-count calculations. A missing drip rate is marked for review. Held or stopped orders carry their status instead of a stale rate and do not supply active-medication plan suggestions.

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

## Automatic respiratory section

The progress note replaces the general Respiratory SmartList reference with the full supplied table that matches the current support. Utilities shows the selected phrase name and a short reason after generation.

| Current handoff support | Selected section |
| --- | --- |
| Invasive AVAPS | ACKRAVAPS |
| Invasive NAVA | ACKRNAVA |
| Current home-ventilator settings with a numeric Pmin | ACKRHOMEVENT |
| Pressure-control ventilation | ACKRPC |
| PRVC or another supported volume-targeted mode | ACKRPRVC |
| BiPAP | ACKRBPAP |
| High-flow nasal cannula | ACKRHFNC |
| Room air, low-flow nasal cannula, or no more specific matching support | ACKRNONE |

The selected current mode takes priority over old ventilator modes. An explicit current Ventilator Off setting, removed airway, failed import, unconfirmed mode history, or conflicting support does not silently select a retained invasive template. The AVAPS and NAVA source tables describe invasive ventilation, so noninvasive AVAPS or NAVA does not use those tables. Unsupported modes and unresolved current-support conflicts use the basic section with a short review message. A tracheostomy or ETT alone does not establish a ventilator mode.

Respiratory medications appear once in the selected Medications cell, separated only into Drips, Scheduled, and PRN. The medication placeholder is removed even when the cell is empty. The original examination, monitoring, ventilator, imaging, and laboratory references remain. The packaged AVAPS template corrects its missing opening at sign in the PS Min reference to `@FLOW24(3040000087)@`, keeping the identifier and formatting intact.

## Automatic cardiovascular section

The progress note replaces the general Cardiovascular SmartList reference with the full supplied table selected from current lines and support:

| Current handoff finding | Selected section |
| --- | --- |
| ECLS | ACKCVARTCVLECLS |
| Pacemaker or pacing wires present, including documented Off or Standby | ACKCVARTCVLPACEMAKER |
| Arterial line and central venous line | ACKCVARTCVL |
| Arterial line | ACKCVART |
| Central venous line, including a PICC | ACKCVCVL |
| No more specific matching finding | ACKCVNONE |

Current ECLS takes priority. If the patient also has a pacemaker, the two supplied Pacemaker rows are included within the ECLS table, before Medications. This produces one cardiovascular section with both support blocks and one medication list. The ECLS and pacemaker templates retain their supplied arterial and central-line monitoring rows.

The selector uses current included devices and monitoring, valid pacemaker and ECLS data, and explicit current handoff documentation. Source-labeled arterial pressure or CVP can support a line section when the device inventory is absent. Cuff blood pressure, a generic MAP, medications, or an old cannula entry alone do not establish the corresponding current support. Hidden, excluded, failed-import, removed, negated, historical, and planned support is not treated as current.

Cardiovascular medications fill the selected Medications cell once, separated only into Drips, Scheduled, and PRN. The medication placeholder is removed even when the cell is empty. The original examination, monitoring, imaging, and laboratory references and table formatting are preserved.

Both selectors read the handoff only when Generate note or Update note with selected plans is pressed. Source changes clear the previous prepared note and downloads. The attending attestation retains its own examination layout and does not receive these full tables or medication lists.

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

These are suggested plan references for your review in Word. Uncertain positive diagnosis wording can also supply a reference. Explicit negative diagnoses and historical acute conditions are not automatically included. The newly added baseline diagnoses can use the patient's own documented history, as described above. Laboratory matching for note diagnoses uses recorded source results, abnormal flags, and the app's existing supported thresholds. Newer normal or unusable results suppress older abnormalities. It does not calculate new laboratory values. Viral matching uses the latest supported result for each component, so a newer negative result does not retain an older positive result.

Recognized positive viral results include adenovirus, rhinovirus or the combined rhinovirus/enterovirus target, influenza, parainfluenza, RSV, and explicitly identified COVID-19 or SARS-CoV-2. A positive target without a matching supplied phrase produces a message. For example, no phrase name was supplied for human metapneumovirus. Known source assay names retain their identity when their display labels are edited.

Saved specific subcategories take precedence over broader parent categories and generic medication-name rules. A custom subcategory can match any of the existing diagnosis labels or exact phrase names. Category labels remain internal. An active feeding order can supply the malnutrition-risk reference even when its rate is unknown, without calculating intake.

The antiarrhythmic defaults include amiodarone, procainamide, esmolol, sotalol, digoxin, ivabradine, and qualifying intravenous lidocaine. The supplied spelling ivardabine is also recognized. An additional drug mapped to the Antiarrhythmics category supplies the same reference. Local lidocaine preparations do not automatically supply an arrhythmia reference. The corrected phrase is `ACKZARRHYTHMIA`. Older saved arrhythmia names or category labels with the previous typo still resolve to this corrected output.

The requested milrinone rule adds the heart-failure reference in the cardiovascular portion of the plan, including when milrinone has another saved category. Other inotropes do not receive that reference from this rule. Held, stopped, excluded, and future orders do not supply active-medication suggestions.

Hypoalbuminemia appears in the FEN/GI portion of the plan. Albumin matching uses the recorded low flag or an existing saved low-result limit with matching units. It accepts ALB and ALBUMIN source names and respects the latest recorded result. A newer normal or unusable result suppresses an older low result. No new numeric threshold is added.

The Word document is available without opening the plan controls. To change the included references in the app, open Edit included plans (optional). Use Included suggested plans to remove or restore a suggestion, or Add another plan to choose a catalog entry. Click Update note with selected plans to prepare the revised document. Your explicit selections replace the automatic defaults for that update. The reason for each suggestion remains available under Sources for suggested plans.

The catalog contains 96 entries using the complete supplied names, including the seven diagnoses added in this update. For example, pantoprazole can produce:

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

## Install from version 6.109 through 6.119

Use the complete update package. Upload these twenty Python files together beside the existing app.py, replacing matching files:

- app.py
- admin_access.py
- models.py
- error_store.py
- categories.py
- fen_gi.py
- medication_groups.py
- labs.py
- lab_windows.py
- note_generator.py
- note_fengi.py
- note_neuro.py
- note_respiratory.py
- note_cardiovascular.py
- note_medications.py
- note_medication_rules.py
- note_findings.py
- note_settings.py
- note_utility.py
- note_word.py

Also upload the templates folder with all twenty-five files, keeping these paths:

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
- templates/resp_pc.docx
- templates/resp_prvc.docx
- templates/resp_avaps.docx
- templates/resp_bpap.docx
- templates/resp_hfnc.docx
- templates/resp_none.docx
- templates/resp_nava.docx
- templates/resp_home_vent.docx
- templates/cv_art.docx
- templates/cv_art_cvl.docx
- templates/cv_art_cvl_ecls.docx
- templates/cv_art_cvl_pacemaker.docx
- templates/cv_cvl.docx
- templates/cv_none.docx

The package also includes `ADMIN_SETUP.txt` and an updated `secrets.example.toml` for reference. Keep your current Secrets values, especially the existing Admin password hash and encryption key. Do not replace them with the example file. There is no dependency change. Restart the app and confirm version 6.120 in the sidebar, then use the shared username and existing Admin password for Admin or Utilities. Generate a new note to apply the additional diagnosis references. Existing saved lab rows use the updated display rules when the handoff is reopened or exported.
