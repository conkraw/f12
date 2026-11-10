# Version 6.49: annotated ventilator modes and cleaner opening screen

## Cause and correction

The original 6.48 invasive-ventilation parser used the literal mode string for
matching. A leading (S) made an otherwise supported mode unrecognized. The
non-invasive field reader already ignored this prefix, so the two parser paths
were inconsistent. This was reproduced before editing.

The mode lookup and control-family classification now normalize a leading (S),
including case/spacing variants and repeated markers. Known C-section wrappers
are still recognized when the marker precedes a nested label. The same helper is
used by the C/D field reader, numeric display, missing-value detection and
repeated-field comparison. A repeated field differing only by this annotation
is not a conflict. A different mode or numeric value is still a conflict.

Original final field values remain stored for review. No numeric value is
recalculated, no observed value substitutes for a set value, and meaningful
comments such as (safety vt) and (PC above PEEP) remain intact. Other annotations
are not removed indiscriminately. Unsupported modes remain unsupported.

The existing C/D precedence remains: a supported invasive mode uses C settings
without adding the D-block mask/pressure/flow values to that ventilator. The
in-app notice about potentially alternating support remains. This update does
not determine which device is currently in use from source headings alone.

## Opening screen

The SmartPhrase source/sample expander is removed from Handoff. Short workflow
instructions, the real publication timestamp and refresh control remain. The
stored source and Admin editor are not deleted or changed.

## Blank feeding template

The supplied paste also contained an empty Back Up Feed Intake label. The prior
code treated that label as an unsuccessful active feeding import. Empty backup
intake/rate labels now count as empty template fields. A paired empty T section
clears its automatic feeding snapshot as other empty sections do. Omitting T
still preserves previous data. Unknown nonempty feeding text still warns.

## Updating

Replace application code, restart, and re-paste complete C/D sections or the full
SmartPhrase. There are no dependency, key, password or schema changes. Existing
6.48 archived data remain compatible. Do not run the secret generators again.

This release was tested locally. No live deployment or shared patient archive
was accessed or modified.
