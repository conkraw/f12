# Current Shift implementation

## Source and separation

The existing S-block intake/output parser and all existing 24-hour display
functions are byte-identical to 6.72. H now supplies a separate optional
current_shift snapshot. H's 24-hour volumes are not used to replace S or to
recalculate any existing total. The H summary's timestamp is read only to anchor
the new shift interval. S and H source cutoffs may differ and stay independent.

The optional snapshot stores only an ISO source timestamp, the current-shift
weight in kg, and numeric volumes for urine, drains, chest_tube and other.
No pasted clinical text, patient identifiers, intake, net or gross output is
stored by this feature. Like the rest of the sheet, the snapshot is saved only
inside the encrypted archive.

## Display and calculation

Current Shift appears after existing I/O and before Diet / Tube feed / TPN.
The same formatter serves the screen, text export, HTML, individual PDF and
Print All PDF. The label uses compact lowercase am/pm, for example:

Current Shift (11pm - 6:30am)

Urine becomes UOP. Drains, Chest Tube and Other retain their labels. Every
shown category is calculated independently in mL/kg/hr and rounded to two
decimals using ROUND_HALF_UP. A positive rate below 0.01 displays <0.01 rather
than being rounded to zero. Missing categories are omitted. Other never becomes
urine. Other unrequested output categories are not merged into Other.

Rate = output mL / current-shift weight kg / elapsed shift hours.

Weight comes only from the current-shift Weight line. Explicit grams are
converted to kg. A missing or invalid weight is not replaced by another weight.
The source summary's date and time must be available in the same H block.
Last data filed, S's time, a previous snapshot and print time are not fallbacks.

The three shift starts are 7am, 3pm and 11pm. Overnight intervals cross the
calendar date correctly. US Eastern daylight-saving transitions use actual
elapsed time. Repeated or nonexistent local source times cannot safely identify
one instant and therefore produce no rate. Exact shift-start cutoffs also
produce no rate because elapsed time is zero.

## Import behavior

A valid new H replaces the previous current-shift snapshot. H without a
current-shift section clears the previous shift. A partial paste without H
retains the prior snapshot and its source cutoff. Duplicate patient blocks keep
the existing document-level rejection behavior.

Invalid H boundaries, repeated current-shift snapshots, repeated supported
output labels, multiple weights, conflicting summary timestamps, unreadable
volumes or incomplete brackets reject only the shift import and clear the old
shift snapshot. Acknowledging the warning cannot restore those old rates.

Known independent output values can remain available when another category is
explicitly missing. A missing timestamp or weight withholds all rates. Missing
values are not converted to zero. No volume is inferred from the Out aggregate.

## Review and deployment

The new current-shift panel is read-only. It shows the source timestamp and
weight for review. Refresh by re-pasting the source. The original intake/output
editor is unchanged. No new include checkbox or configuration setting was added.

Update all app-code repositories sharing the encrypted archive before using the
new snapshot. Older builds do not recognize the optional new field. No live
repository was modified while preparing this release.
