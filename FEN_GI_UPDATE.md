# PICU Handoff 6.15: Intake/output and FEN/GI medication groups

This is a complete ZIP update to Version 6.14. No repository was changed directly.

## Update the existing app

Save open work, extract PICU615.zip, and open PICU_Handoff_v6_15_FEN_GI.
Replace the application files in your code repository with all the contents of
this folder. Keep app.py at the root and include fluid_balance.py and fen_gi.py.
No dependencies have changed. Restart your existing Streamlit deployment.

Keep Streamlit Secrets, your password, encryption key, GitHub token, private data
repository and saved medication mappings. Do not run create_secrets.py or the
secrets notebook again. The next save writes schema 15. Do not downgrade the
application after that save without restoring a compatible earlier archive.

Sidebar: Version 6.15 | Intake/output and FEN/GI medication groups

## S-section totals

Paste the complete SmartPhrase or only a complete paired S block. The S block
may begin with Intake/Output Summary rather than an extra heading. Click Create /
update handoff. Its recorded Intake, Output and Net print at the very top of FEN/GI.
Only S is imported for fluid totals. H is not used as a fallback and is not added
to S, even if both sections contain the same totals.

Zero, signed net values, decimal precision and supplied units are kept. Net is
not recalculated. A missing value displays --, not zero. The source period,
summary time and last-filed time are retained in the editor. Conflicting totals
or an unreadable nonempty S block stop the proposed import without replacing
the previous handoff. Nothing is silently dropped to make a malformed paste fit.

An omitted S keeps the old totals. An included empty S clears them. Re-pasting S
replaces only its snapshot and does not touch separate notes, medications, labs,
CBC columns, blood gases, cultures, vitals or R orders.

Edit the totals under Edit handoff > FEN / GI. The optional Show intake/output
totals control hides that snapshot from the output without deleting its values.
Room-change autosave, encrypted storage, single-sheet printing and Print all
include the edited snapshot. As before, paste text must first be imported with
Create / update handoff. Unsubmitted paste text is not an imported draft.

## Medication groups

The user-requested automatic name rules are:

- GI prophylaxis: famotidine, omeprazole, pantoprazole.
- Bowel Regimen: docusate, lactulose, polyethylene glycol, glycerin suppositories,
  and sennosides.

These are display groups chosen by the user, not inferred treatment indications.
They recognize the generic name at the start of a formulation after known held,
start-date and sequence annotations. They do not guess unlisted brand-only names,
match drug-name substrings, or classify topical glycerin as a suppository.

Matching visible entries appear automatically in FEN/GI, without requiring a new
system mapping. Existing stored system mappings and source medication fields are
retained. Each order appears once. Different doses and schedules remain separate.
Hidden and excluded entries stay omitted. Held/start/sequence labels, prescribed
doses, routes, frequencies, recorded rates and custom wording remain intact.
The existing output-only removal of (Dosing Weight) still applies.

The printed order is Intake/Output/Net, a separator, GI prophylaxis, a separator,
Bowel Regimen, separate FEN/GI notes, and remaining FEN/GI medications. Empty groups
are omitted. Group headings are bold in PDF and HTML.

The Medications tab has a FEN/GI display choice for these entries. Automatic uses
the listed defaults. GI prophylaxis or Bowel Regimen explicitly chooses a group.
No GI grouping returns the order to its saved system assignment. Selecting a
different system also disables automatic GI grouping for that formulation,
route and frequency. The choice is remembered separately from system mapping
and hiding rules. Saved overrides are editable in Admin > FEN/GI display choices,
including without an open handoff. Returning an override to Automatic removes it.

Previously saved medication rows adopt this grouping when viewed or exported.
They do not need to be re-pasted. New S totals do need a paste/import. Separate
manually typed notes are not rewritten or deduplicated.

## Practice and limits

examples/synthetic_fen_gi.txt is a practice paste with no patient record.
examples/fen_gi_preview.pdf shows a one-page synthetic handoff. No sample-loading
buttons have been reintroduced to the screen. The compact print layout still
uses continuation pages when needed rather than clipping content.

Storage/access/privacy protections and limits are unchanged. Use an approved
hosting and storage arrangement. Exports are unencrypted. The original paste
enters server memory and is not certified de-identified. Refer to the existing
security documentation and institutional policies.

See TEST_REPORT.md for checks actually executed and deployment limitations.
