# Version 6.16: import recovery and shared technical error review

## What was fixed

The old divider detector classified any alphabetic word of at least eight letters
made entirely from a through s as a malformed divider. Ordinary order comments
such as Peripheral matched. Only near-divider strings dominated by a repeated
letter are flagged now. Actual paired dividers and missing/duplicate-boundary
protection are retained.

A CBC cell may contain two numeric values separated by a literal pipe. The app
cannot tell which method belongs to either result just from that pipe. It no
longer chooses a minimum, maximum, first value, or a result from another time.
The original cell is retained as an excluded row. The CBC tree leaves that
component unavailable and a persistent review warning identifies the omission.
Other valid cells and rows are imported. In Labs / Vitals, replace the excluded
cell with a verified single result before selecting Include. Unknown nonnumeric
cells are omitted rather than saved as clinical numeric results.

A CBC row with the wrong number of dated columns is omitted as a whole. Conflicts
within the same cell are excluded instead of allowing the first alias to win.
Ambiguous date/time headers still reject the Q section. The separate P blood-gas
parser and its specimen/time selection rules are not changed.

## Partial import contract

The Create / update handoff action now imports each unambiguous section
independently. A bad section does not cancel unrelated successful sections.
C and D remain a single respiratory-support group, because their fields depend
on each other. Medication parsing remains atomic within B: a failed order does
not produce a silently incomplete new medication list. G and P still reject
ambiguous tables within their own sections.

- A failed section keeps its prior values in the editor and receives a durable
  not-updated flag. The banner explicitly says to verify retained values.
- A failed R section is special: its prior automatic order list is kept for
  review but hidden from all handoff outputs until explicitly reviewed or
  replaced by a successful R import. Separate Labs notes remain unchanged.
- Safe partial Q results receive a durable incomplete-CBC warning.
- Unsubmitted text is not treated as an imported handoff.
- Omitted sections are unchanged, including any outstanding review flags.
- A successful reimport clears the flag for that section only.
- Repeated complete sections can mean more than one patient was pasted. The
  entire proposed import is rejected in that case rather than combining them.
- An empty paste, oversized paste, or paste with no usable boundaries is not
  imported. This is not a promise that every possible malformed input can be
  interpreted.

Warnings appear above the columns in PDF/HTML, in plain-text output, and on each
continuation page. They are saved with the room so another signed-in user can
see that content needs review. Review skipped or incomplete imports expands the
individual warnings. Its acknowledgement buttons do not edit clinical values.
For R, Use retained orders after checking Epic deliberately restores the prior
order display. For partial CBCs, acknowledging omissions leaves excluded cells
excluded. Acknowledging the handoff is separate from resolving the technical
error report.

## Shared Import errors workspace

Import errors and recoveries automatically create one technical report per
import attempt in the existing private data repository:

    encrypted-data/import-errors/YYYY-MM/<UTC-event-time>-<random-id>.enc

This is a separate journal, not a new plaintext log and not a GitHub issue.
It reuses the existing encryption key and GitHub configuration. Nothing needs
to be added to deployment Secrets. Application code is still delivered as a ZIP.

The report allows only app version, event ID, event/updated UTC timestamps,
open/resolved status, section identifier, allowlisted issue code, numeric row and
column positions, standard CBC component identifier, and the action taken.
It does not accept a room, patient name, MRN, source text, clinical value, staff
name, exception body or stack trace. A raw multi-value CBC cell can remain in
that patient's encrypted handoff for review but is NOT copied to this journal.

Open Import errors, choose a month, and Refresh shared errors. The page loads
up to the newest 100 records from that monthly directory and explicitly states
when the result is partial. It reports unreadable records instead of claiming
that an incomplete list is complete. Reports can be marked resolved or reopened,
and exported as a technical JSON report. This report contains no source records.

Every import report uses a unique create-only path. Retrying the same event is
idempotent. A review-state change uses GitHub's expected file SHA and refuses a
conflicting edit. Separate reports do not overwrite another teammate's reports
or the handoff archive. Error uploads still depend on connectivity and repository
permissions. If saving fails, the handoff is retained, an unsaved-log warning is
shown, and Retry saving errors resends the same queued event. Queued events exist
only in that session until saved. A reload, logout or server restart may lose an
unsaved queue, so do not treat the queue as durable storage.

This is a shared technical log under the current app sign-in, not individual
staff authentication or an audit trail identifying which clinician made a
change. Existing handoff-save conflict protection is retained. Separate users
should not assume simultaneous edits to a room will merge automatically. Marking
an error resolved does not erase repository history or change any patient sheet.

## Upgrade

Replace every application file with this complete package. Keep app.py at the
repository root. New modules are import_review.py and error_store.py. Keep the
existing password, encryption key, token, private data repository and medication
mappings. Do not run the secrets generator. No dependencies changed.

Schema 16 adds import_warnings to each sheet. Earlier supported archives migrate
without discarding clinical fields, intake/output, medication grouping rules, or
other settings. After a schema-16 save, do not downgrade individual app files.
For a rollback, restore both a compatible code version and its matching archive.

Institution-approved hosting, storage and access controls are still required.
This change does not certify a deployment for clinical use. Downloaded handoffs
are not encrypted. The app still processes pasted content in server memory.

## Technical references

- GitHub Contents API: https://docs.github.com/en/rest/repos/contents
- Streamlit session-state callbacks: https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state
- Fernet authenticated encryption: https://cryptography.io/en/latest/fernet/
