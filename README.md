# PICU Handoff 6.79

Print all now reuses current, already-rendered patient PDFs instead of repeating
all clinical layout and page fitting on every download.

After import/save, each room's PDF is prepared once. Single-patient printing and
Print all share a private in-memory cache. Changed or missing patient PDFs are
rebuilt automatically. Print times, saved times and page numbering stay current.
The complete-room replacement rules from 6.78 are preserved.

This package has not been deployed to the live application.

## Install

Extract PICU679.zip. Replace the matching application-code files at your
existing app repository root, not inside an extra nested directory.

From version 6.78, the required update is:

    app.py
    exports.py
    census_guard.py
    pdf_cache.py
    requirements.txt

Upload all five together. pdf_cache.py is new. requirements.txt adds pypdf for
in-memory PDF assembly. Reboot/redeploy to install it. For an older version,
replace the complete application code set from this package.

Keep your existing Streamlit Secrets, encryption key, encrypted patient archive,
medication mappings and separate data repositories. Do not replace your secrets
with the example files. No archive migration is needed.

Confirm the sidebar reads:

    Version 6.79 | Faster Print all

## What to expect

PDF preparation moves to import/save for the affected room. Unchanged Print all
requests then reuse those pages. Missing or time-sensitive changed displays are
regenerated. After a new login or app restart, the first print may still require
initial generation because PDF bytes are not persisted in shared storage.

The app still saves edits before Print all and checks the current shared records
before and after assembly. Network checks, browser downloads and the printer are
not bypassed. Room order, landscape layout and overflow pages are retained.

Test with fictional patients before clinical use. Confirm a manual edit appears,
a same-room SmartPhrase replacement removes the old patient's information, and
a reset removes the previous list. Compare one-patient and Print all output.

## Documentation

FASTER_PRINT_ALL.md explains the code path, cache safety and limitations.
TEST_REPORT.md documents synthetic tests and environment limitations.
PRINT_PERFORMANCE_679.json contains measured local timings.
REPLACE_NEVER_MERGE_678.md preserves the prior room-replacement release notes.
UPDATE_FILES.txt lists required files.

Use only within your institution's approved workflow. Confirm the current
patient and source information in Epic. Downloaded PDFs are unencrypted.
