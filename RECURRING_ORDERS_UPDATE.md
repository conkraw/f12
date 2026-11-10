# Version 6.14: Labs/Imaging recurring orders

## What changes

The former LABS column is labeled LABS/IMAGING in PDF/HTML and Labs/Imaging in the editor. Its saved internal key remains Labs so existing notes and medication destination rules are retained.

R is a separate import. It does not rework G lab results, Q CBC tables or P blood gases. Re-paste a complete R section, or the full separated SmartPhrase, then use Create / update handoff. Omitted sections are unchanged. An included empty R section, or a valid R section without matching recurring tests, clears the previous automatic order list. Re-pasting replaces, rather than appends to, the order snapshot.

## Selected tests

The filter includes chest X-rays, CBC and CBC with differential, basic metabolic panel, PT/INR, PTT/aPTT, fibrinogen or a named coagulation profile, magnesium, phosphorus, blood gases (including the named CG8/CG4/EG7 source panels), and lactic acid/lactate. The recorded test name is retained in the editor.

CMP is not relabeled as BMP and is excluded from this requested BMP-only filter. ECGs, cultures, type-and-screen, blood products, standalone potassium, triglycerides, nursing orders, and other unrequested items are excluded. Selecting a lab result for the bottom results area remains independent of this order filter.

## Repeating schedules

An order must have an explicit Timing field with a supported recurring interval. Examples are Recurring (Morning draw), Recurring (Daily), Recurring (Daily imaging), and Recurring (Every 1 hour). Hour intervals are printed as Q1H, Q6H, Q12H and so on. Recognized named daily/weekly schedules are retained.

Epic also writes Recurring around one-time orders. Once, PROCEDURE ONCE, STAT, Blood - Once and PRN do not qualify. Continuous, Until discontinued and Per protocol without a usable repeating interval do not provide a draw schedule and are not guessed. Unsupported schedules on otherwise selected test types produce a notice.

Only the order name, Timing, Number of Occurrences, inclusion flag and source position are stored for this feature. Reasons, provider details and other order instructions are not added to the handoff.

## Duplicate handling

Matching test and normalized schedule: retain the highest explicitly stated occurrence count. Do not sum counts. Equal counts keep source order. Case and explicit aliases such as PTT/APTT are normalized. Different intervals, gas specimens, panels and chest views remain separate. CBC with differential is not silently merged with a plain CBC.

All recognized scheduled candidates remain in the Labs/Imaging editor, including lower-count duplicates. The selected winner is marked shown. Others are marked duplicate not shown or excluded. You can edit a test, schedule or count, or exclude a candidate. Selection is recalculated from the remaining included candidates.

A missing count is displayed as occurrences not listed, never invented. A known count takes priority over a duplicate whose count is not supplied. The source count is not a computed number of draws remaining and does not establish whether an order is still active. This is a snapshot of the pasted encounter-order list, not a live connection to Epic.

## Saving and export

Existing room-change autosave saves the new order snapshot as part of the handoff. Manual Labs notes remain after a separator. PDF, HTML, text and Print all use the same duplicate selection. Orders-only rooms are included in Print all. Existing CBC trees, latest-gas selection, infusion formatting and result placement are unchanged.

Schema 14 adds recurring_orders. Schema 13 and earlier archives migrate with their original fields, keys, notes and mappings preserved. Keep existing Secrets and encryption key. After a new schema is saved, do not revert to earlier application files without a deliberate compatibility plan.

## Testing

See TEST_REPORT.md for executed tests and limitations. Bundled examples are synthetic. The three supplied source examples were tested separately and are not included in this package. No direct GitHub changes were made.
