# Version 6.36: choose the handoff font size

## Use it

Open Handoff > Preview / print, or Print all. Type the size you prefer into
Handoff font size (pt), from 6.5 to 14.0 points. The arrows change it by 0.1 pt.
The initial value is the previous 7.2 pt base size. Try 8, 9 or 10 for larger text.
No Admin password is required to change your own print size.

The setting changes body text, medication doses, notes, horizontal lab summaries,
and CBC/BMP result values. Supporting labels and dates scale proportionally.
Compact column headings and page-identification/footer text keep their fixed size.
Wider laboratory cards are used when necessary. Overlong result text falls back
to a wrapping labelled summary rather than losing values.

Allow smaller text to fit the page target is OFF by default. With it off, the PDF
keeps your selected size. It can tighten spacing and adjust column widths, but
will use extra pages rather than shrinking text or discarding content.

Turn that option on to let the app reduce text from your chosen size down to
6.5 pt to try the selected one-page or two-page goal. The page target is a goal,
not a limit. Long handoffs still continue onto additional pages when needed.
The per-room report shows the actual PDF page count, output font size and whether
auto-fit reduced the text. Each patient begins on a new page in Print all.

The HTML preview and HTML download use the requested size. Auto-fitting and the
checked page count apply to the PDF. Browser printing may paginate differently.
Use the downloaded PDF at Actual size / 100% for the selected physical point size.

Your choices follow you between rooms and Print all during the current session.
They are not written to the shared GitHub archive and do not alter another team
member's preferences. They reset after sign-out, session expiry, or a new session.
The existing saved handoffs, medication mappings and save times are untouched.

## Install

Extract PICU636.zip and upload the contents of PICU_Handoff_v6_36_Font_Size into
your existing application code repository, replacing matching files. Keep app.py
at the root. Include the new print_options.py. Restart and refresh the app.
The sidebar reads: Version 6.36 | Adjustable handoff font size

Keep your existing Secrets, both passwords, encryption key, GitHub token,
medication mappings, private data repository and CDC BMI reference data. Do not
rerun setup generators. No new dependencies or archive-format changes are needed.
No re-pasting is needed. The formatting applies to previously saved handoffs.

The supplied font_size_preview.pdf is synthetic, not a patient record. Its body
and laboratory values are 9 pt, with one page and no automatic font reduction.
The same synthetic sheet at 10 pt requires two pages. Individual results vary
with the amount of text and the selected settings.

See TEST_REPORT.md for validation details and limitations.
