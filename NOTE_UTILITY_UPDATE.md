# PICU Handoff 6.111

## Generate a Word document

Open Utilities in the sidebar and unlock it with the existing separate Admin password. Choose a patient handoff, select Progress note or Attending attestation, and click Generate note. Download the Word document to review and edit it.

Both exports use the original uploaded Word templates. Existing styles, tables, fonts, colors, headers, footers, and margins are preserved. Added content flows through the document naturally, so a longer note can use additional pages. Existing Epic links, SmartLists, wording, and placeholders remain available for completion.

The progress note includes medication review lists beneath the Neurologic, Respiratory, Cardiovascular, and FEN/GI SmartList references. Hematology and Infectious Diseases use their existing medication blocks. The expanded contents of the four system SmartLists are not present in the source Word document. After expansion in Epic, move relevant medication lines into the intended placeholders and remove review text you do not need.

Each main system has simple Drips, Scheduled, and PRN lists where relevant. Therapeutic medication subgroups are flattened. Recorded doses and rates are copied without new dose, weight, fluid, nutrition, or PRN-count calculations. A missing drip rate is marked for review. Held or stopped orders carry their status instead of a stale rate.

The attending attestation keeps its original attestation wording, examination SmartLists, assessment, and clinical-indication reference. It includes only the selected plan phrases under PLAN. It contains no medication lists. Medications can still inform the suggested plans shown for review in the utility.

Only Generate note and Update note with selected plans build the document. Opening Utilities, changing plan selections, saving phrase settings, and downloading do not regenerate it. Prepared Word and plain-text downloads are reused until you generate or update the note. The plain-text preview is read-only. Make document edits in the downloaded Word file.

## Review the plan

The utility matches documented diagnoses and offers possible medication or respiratory-support indications for review. Documented diagnosis wording can preselect a plan. Medication-only possibilities remain unselected except the requested pantoprazole gastric-ulcer-risk default. Uncertain, historical, and negated wording is handled conservatively. No new diagnoses are calculated from laboratory values. Review every selected plan before using the note.

Use Include these suggested plans to remove or select a suggestion. Add another plan offers the remaining catalog entries. Click Update note with selected plans to apply those choices. The reason for each suggestion is available in the review expander.

The catalog contains 85 entries using complete ACKZ names. For example, pantoprazole can produce:

```text
PLAN
@ACKZATRISKFORGASTRICULCERS@
```

Both respiratory phrase names are confirmed defaults:

```text
@ACKZACUTEHYPOXEMICRESPIRATORYFAILUREINVASIVE@
@ACKZACUTEHYPOXEMICRESPIRATORYFAILURENONINVASIVE@
```

When acute hypoxemic respiratory failure is documented, current respiratory support determines the matching route. Historical modes do not add a second respiratory plan. Support alone produces an unselected review candidate and does not establish acute hypoxemia. Conflicting current support requires review before either phrase is selected.

Epic phrase settings allows a custom invasive phrase name and a choice of output format. Save phrase settings retains those choices in the existing encrypted settings.

## Epic reference format

The requested template format is the default. Dot phrases are available as a separate setting, for example `.ACKZATRISKFORGASTRICULCERS`.

Epic training distinguishes SmartLinks from personal SmartPhrases. SmartLinks appear between at signs in templates. The documented interactive SmartPhrase workflow uses a period followed by the name and an expansion action such as Spacebar. Confirm that the exported custom references expand in the local Epic installation. The utility creates documents and does not connect to Epic.

Sources:

- [Methodist physician settings guide](https://www.methodistmd.org/files/epic/user-settings-lab/mlh-provider-user-settings-guides/pdfs/Inpatient%20and%20Outpatient%20Physician%20User%20Settings%20Guide.pdf), pages 4 through 7.
- [University of Iowa SmartTools guide](https://epicsupport.sites.uiowa.edu/epic-resources/smarttools).

## Draft controls

The draft and prepared downloads stay in the current administrator session and do not overwrite the handoff. Changing the patient, document type, or source handoff clears the old draft. Locking Admin, leaving the protected workspaces, logging out, returning Home, or resetting the patient list clears the draft and revokes its prepared downloads. Protected actions recheck Admin access. Expired or revoked downloads are rejected.

## Install from version 6.109 or 6.110

Use the complete update package. Upload these nine Python files together beside the existing app.py, replacing matching files:

- app.py
- admin_access.py
- models.py
- error_store.py
- note_generator.py
- note_medications.py
- note_settings.py
- note_utility.py
- note_word.py

Also upload the templates folder with both files, keeping these paths:

- templates/picu_progress_note.docx
- templates/attending_attestation.docx

There is no dependency change. Keep the existing Streamlit Secrets and encryption key. Restart the app and confirm version 6.111 in the sidebar.
