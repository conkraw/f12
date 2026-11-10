# Version 6.23: automatic print fit and clear all handoffs

## Install

Extract PICU623.zip. Upload the contents of PICU_Handoff_v6_23_Print_Reset to the existing code repository. Keep app.py at the root. Include handoff_reset.py and all updated Python files. Restart the deployment and refresh the browser.

Keep your existing app password, separate Admin password, encryption key, GitHub token and private data repository. Do not rerun either password or key generator. No new dependencies are required. Installing this update does not clear any handoffs.

The clinical archive upgrades from schema 17 to 18. Every existing room, clinical field and setting is preserved. The new reset_generation value starts empty and changes only when Clear all is used. The next successful archive write uses schema 18, so do not downgrade the application after saving.

## Automatic PDF fit

Open Preview / print in a room, or Print all. The default PDF page target is Auto-fit to 1 page. Auto-fit to at most 2 pages is also available for a longer handoff or a less compressed layout.

Already-fitting handoffs retain the previous layout. For overflowing handoffs, the app tests the existing bounded font reduction, then tighter line spacing and padding, then bounded column-width reallocation. Column order and all clinical content are preserved. Body text is never reduced below 6.5 points. The CBC/BMP drawing code and all result selection rules are unchanged.

The page-count table uses the actual PDF renderer and shows each room's page count, selected font size and whether spacing or column widths changed. The chosen layout is used by the PDF download as well. A one-page target is a goal, not a hard crop. If the full content cannot fit at the font limit, it continues onto additional pages and a warning explains that. A two-page target likewise never discards content to enforce two pages.

Each patient's handoff starts on a fresh landscape Letter page. Automatic fitting applies to PDF exports. The on-screen HTML panel and downloaded HTML can paginate differently. Open the PDF for the exact print layout. Actual print settings should use landscape Letter without adding browser headers or footers.

No text is abbreviated, summarized, or removed by this feature. Notes, medication doses, infusion emphasis, laboratory dates, import-review warnings and timestamps remain included.

## Clear all handoffs with one button

As of 6.51, open Handoff, expand Delete all handoff data, and click Delete all handoff data. Any signed-in user can clear the current shared census without an Admin password. There is no second confirmation dialog.

This removes all handoffs in the shared current archive and all open drafts in the current session. All custom rooms are deleted from the room selector. The preset P-prefixed rooms remain available as empty rooms.

Medication mappings, hidden-medication rules, infusion and medication group choices, diagnosis routing, app/Admin passwords, encryption settings, the published user guide, SmartPhrase and technical error journal are not reset.

The new empty archive is committed before local drafts or widgets are cleared. A rejected or unconfirmed write keeps the local drafts and displays an error. If the connection ended after GitHub accepted a write, reload the archive to establish what was saved before retrying.

This is a shared reset, not only a reset of the current browser. Tell teammates to use Reload saved archive after it. Existing stale save attempts are rejected by the archive version check. On reload, a changed reset_generation clears old local drafts, including unsaved custom rooms, to prevent them from being saved back. Other browsers are not forcibly refreshed and previously downloaded files cannot be revoked.

The current session's prepared download callbacks are revoked on reset and logout. Technical error reports remain available for review. Earlier encrypted Git history, platform backups, browser copies and downloaded PDFs are not erased. There is no new in-app bulk undo. Do not use this button until you are ready to clear the current handoffs.

## Test first

Use a synthetic handoff to check the page-count table and PDF. Test the reset in session-only mode or a separate test data repository before using it on the shared clinical archive. See TEST_REPORT.md for executed checks and limitations.
