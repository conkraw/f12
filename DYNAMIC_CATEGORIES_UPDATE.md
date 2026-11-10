# Version 6.42: Respiratory and editable medication categories

Built from delivered Version 6.41. No medication dose, route, frequency, infusion
rate, laboratory selection window, or clinical source value is changed.

## Default Respiratory groups

| Group | Default medications |
| --- | --- |
| Airway/Cerebral Steroids | Systemic dexamethasone |
| Beta-Agonist | Albuterol |
| Anticholinergic | Ipratropium |
| Methylxanthine | Aminophylline |
| Corticosteroid | Systemic methylprednisolone, prednisone, prednisolone |
| Airway Tone Modulator | Bethanechol |
| Inhaled Corticosteroids | Inhaled/nebulized budesonide, fluticasone, mometasone |
| Pulmonary Hypertension | Sildenafil |

Antisialorrhea Agents remains available. The labels reflect the requested local
handoff organization, not inferred indications or new treatment advice. Topical,
ophthalmic and otic steroid products do not acquire systemic steroid groups.
Oral, nasal and skin formulations do not automatically enter Inhaled
Corticosteroids. Combination products remain intact. Assign them to one chosen
category rather than splitting an order into its ingredients.

The latest eligible theophylline result appears directly below the first visible
aminophylline order, once per patient. Its existing 24-hour selection, date, units
when supplied, and flags are retained. It is no longer repeated above the drugs.
Without a visible aminophylline order, the result remains in the standalone
Respiratory location. A missing/old result does not create an empty placeholder.

## Create categories without changing code

Open Admin and enter the separate Admin password. Under Medication categories and
subcategories, choose Add a category or subcategory, enter its name, select its
system, and save. Choose a parent to create a subcategory. A subcategory inherits
the parent's system. Only two levels are supported: category and subcategory.

Existing built-in categories can be renamed, moved and reordered. For example,
create Respiratory / Bronchodilators, then edit the existing Beta-Agonist and
Anticholinergic categories to give them that parent. Their automatic medication
rules follow them. No extra medication rules are needed for that restructuring.

Display order is 0 to 999, lower first. Equal values are alphabetical. The default
Neurologic sedation/PRN/paralytic order is retained. Empty headings do not print.
Built-in categories cannot be deleted. Before deleting a custom category, move
its assigned rules and its subcategories. Renaming a category keeps its stable ID.

## Map a medication once

In Handoff / Medications, Category for order replaces the separate system,
FEN/GI group and medication-group pickers. Select one full destination, such as:

    Respiratory / Bronchodilators / Beta-Agonist

A category without a subcategory is also valid. Each order prints once. Selecting
a different destination replaces its previous placement. Scheduled and PRN
orders remain separate orders, as do different doses or taper steps. Hiding a
medication still takes precedence, so a new category never restores a hidden row.

An inline selection is saved immediately for that exact formulation, route and
frequency and is visible in Admin. Automatic / existing mappings removes that
specific override and restores applicable shared rules and defaults.

For broader rules, open Admin / Assign medications to categories. Use a generic
prefix (for example, albuterol) or an exact product name. Route and frequency
filters are optional. Select one destination and save. A new target replaces the
same matching rule's old target. Exact names take priority over prefixes. Among
prefix matches, the longest wins, then the more specific route/frequency filters.

Category assignments take priority over older routing/grouping settings. Those
older settings remain available in Existing mapping and display settings. A
manual override already saved there is retained unless a new category assignment
supersedes it. Unassigned medications still use the existing automatic groups or
Other Medications. Continuous orders retain their existing infusion emphasis
inside their category and are not repeated in a general infusion block.

## Persistence and printing

Category definitions and mapping rules use the existing encrypted shared
settings. No new service, token, password or encryption key is needed. Source
medication fields and saved handoff timestamps are not modified by category
editing. Open drafts and print packets use the current category definitions.
Other users must reload the saved archive to see changes from another session.
Failed/conflicting writes leave the previous settings and drafts unchanged.

The archive schema advances from 26 to 27. Previous handoffs upgrade automatically
without changing previous fields. Do not downgrade after saving category data.

## Install

Upload all contents of PICU_Handoff_v6_42_Dynamic_Categories into the existing
application code directory, replacing matching files. Keep app.py at the root.
The new runtime modules are categories.py and category_ui.py. Restart and refresh.
Keep all existing private Secrets, passwords, encryption key, shared archive and
public BMI reference data. Do not run the setup generators. No new dependencies.
No re-paste is needed for medications and results already stored.

Expected sidebar:

    Version 6.42 | Respiratory and editable medication categories

## Implementation references

The interface uses the existing Streamlit selectbox, session-state and form APIs:
https://docs.streamlit.io/develop/api-reference/widgets/st.selectbox
https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state
https://docs.streamlit.io/develop/concepts/architecture/forms

These documentation references describe the UI APIs, not clinical validation.
