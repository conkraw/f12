# Version 6.50: cleaner Handoff header

Removes the SmartPhrase publication date/time and the publication refresh button
from Handoff, including the session-only, not-published and unavailable-date
variants. The short instructions remain above room selection.

No patient data, mapping, category, stored guide or publication timestamp is
deleted. The protected Admin editor retains publication metadata and publishing
controls. Existing automatic guide loading remains in place. Related success
and load-error messages no longer refer users to the removed Handoff button.

No clinical parsing, saved-archive schema, security, autosave or printed layout
changes are included. No additional dependency or re-pasting is needed.
