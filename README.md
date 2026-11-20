# PICU Handoff 6.89

This update builds on 6.88 and adds the requested medication categories, code status in demographics, and one latest PN order plus one latest intravenous lipid order in the handoff.

## Install

Extract PICU689.zip. Copy all files from PICU_Handoff_v6_89_Medications_Code_Status into the root of your existing app repository, beside app.py. Replace matching application files and include the new code_status.py and pn_orders.py modules. Upload the files themselves without adding another folder level.

Keep your existing Streamlit Secrets and encryption key. Restart Streamlit, then confirm the sidebar reads:

    Version 6.89 | Medication categories and code status

UPDATE_FILES.txt lists the application files changed since 6.88. The complete package includes all prior modules, including the recent login, ECLS, AED-level and lysis-lab updates.

This package is ready to install. It has not been deployed to your live application.

## Medication categories

| Medication | Handoff section | Subcategory |
| --- | --- | --- |
| Ocular lubricant, Artificial Tears ointment, Refresh PF drops | Neurology | Eye Care/Lubricants |
| Amantadine | Neurology | Neurorecovery/Neurostimulant |
| Enteral The Very Finest Fish Oil | Neurology | Neurorecovery Supplement |
| Pyridoxine | Neurology | Antiepileptic Adjunct |
| Systemic naproxen, ibuprofen and related NSAIDs | Neurology | NSAIDS |
| Ferrous sulfate | Hematology | Iron Deficiency Anemia |
| Hydroxyurea | Hematology | Sickle Cell Anemia |

These requested placements apply to new imports and existing saved medication rows, including rows with older category assignments. The app continues to honor hidden, excluded and Ignore selections. Category changes do not add a diagnosis to the Problems section.

Enteral fish oil remains separate from SMOFlipid and other intravenous lipid preparations. IV PN and lipids appear under FEN/GI, in TPN. Aspirin keeps its existing antiplatelet grouping. Acetaminophen remains under Fever Control.

## Code status

The app reads the paired AE section and displays the exact documented value in demographics. Both of these source layouts are supported:

    aeaeaeaeaeaeaeae
    Code Status: Full Code
    aeaeaeaeaeaeaeae

    aeaeaeaeaeaeaeae
    Code Status:
    No Order
    aeaeaeaeaeaeaeae

No Order remains No Order. A missing value does not become Full Code. The imported status can be edited in Labs / Vitals under Demographics / Weight.

A complete replacement paste without AE clears the previous room's code status. Malformed or conflicting AE content clears the old status and produces an import-review message. A manually verified status can be entered in the editor.

Re-paste the current SmartPhrase to populate code status in an older saved handoff, because older versions did not retain AE.

## Latest PN and lipid orders

The handoff shows at most one selected PN order and one selected intravenous lipid order. All original medication rows remain in the editor and encrypted archive.

Selection uses labelled order dates or scheduled starts when available. When usable order timing is absent, it uses later source occurrence. Last Admin and Last Rate do not determine order recency. A new pending bag can be selected even when its administration and infusion-rate fields are blank.

The app preserves the selected order's own dose, route, frequency and recorded rate. It does not copy an older bag's rate into a newer order. A lipid linked by And may use its paired PN's explicit scheduling information for selection.

Dietary and medication copies are reconciled so PN is not repeated across sections. Hiding the selected newest order does not restore an older one. Date-only and timed entries on the same day do not establish a newer bag solely because one entry contains a time. Explicitly discontinued nutrition orders are not selected. Held status remains visible on a selected held order.

The supplied medication table does not contain an order-time column. Its newer unadministered PN/lipid pair therefore uses the source-order fallback. A future source with an ambiguous sequence cannot establish an actual ordering time from Last Admin.

## Compatibility and verification

The archive schema remains 34. Existing archives without the optional code-status field remain readable. No new application dependencies, credentials or configuration settings are required.

TEST_REPORT.md describes the executed regression and export checks. Synthetic PDF output was visually inspected. The six uploaded examples were checked locally and are not included in this package.

One supplied example has an AD block containing only cerebral rSO2. The existing ECLS importer continues to flag that block because it contains no supported circuit settings. Its medication, nutrition and code-status sections import independently.

Prior release documentation is retained as V688 files. The older numbered notes describe their original releases.
