# PICU Handoff 6.74

## Bowel movement status and missing I/O totals

Built from the supplied PICU673.zip. This release includes both requested changes.
No live deployment or repository has been changed.

## Install

Extract this ZIP. Copy the application files into the existing app-code repository,
replacing matching files. Upload both new modules, bowel_movements.py and
io_sources.py, along with every changed file listed in UPDATE_FILES.txt.
Do not change Streamlit Secrets, encryption keys, passwords, or separate encrypted
patient-data and mapping repositories. No dependency update is required.

Restart the deployment and confirm the sidebar says:
Version 6.74 | BM status + I/O fix

Re-paste each current SmartPhrase to populate the new BM field and recover totals
that an earlier import omitted. Raw pasted source is not stored, so previously
missing totals cannot be reconstructed from the archive alone.

Update all deployments sharing the same encrypted archive before using the new
BM field. An older build cannot validate that new optional field.

## I/O source fix

Version 6.73 imported the 24-hour summary only from S. In the supplied examples,
the explicit 24-hour summary is in H while S is empty. That combination caused
S to clear the 24-hour display even though H contained the totals.

This release selects one source independently of the current-shift parser:

1. A valid populated S block keeps its existing priority and behavior.
2. If S is absent or validly empty, the app reads an explicitly labeled 24-hour
   summary from H, stopping before current-shift or completed-shift details.
3. An empty S no longer clears a usable H 24-hour summary.
4. A malformed S is reported rather than silently replaced with another source.
   Malformed H boundaries are reported when H would be the only totals source.
5. Missing values stay missing. No shift totals are added, no net is calculated,
   and no source timestamps are changed. A standalone empty S still clears its
   prior display when no H 24-hour summary is supplied.

The existing fluid_balance.py and current_shift.py are byte-for-byte unchanged
from 6.73. Their calculations, display labels and time-window formatting remain
unchanged. Current Shift still uses the source timestamp and current-shift weight.

A current-shift parsing error does not suppress a separately valid 24-hour summary.
A totals parsing error does not suppress a separately valid current-shift result.

## Plain BM status under Bowel Regimen

The dedicated alternating AC block is read separately from all other sections.
A positive Stool Amount such as Small, Medium, Moderate or Large, or a positive
Diaper Weight Mixed Urine/Stool (g) or Diaper Weight with Stool (g), establishes Yes.
Only one line is printed, beneath the Bowel Regimen medications or empty group:

Last BM (24 hours): Yes

A valid empty AC block, zero amount, or absent positive signal in recognized
fields displays:

Last BM (24 hours): No

The entire BM line is regular text, not bold. Stool type, amount, weight, date,
and time are not printed or stored in the BM snapshot. Only the documented
Yes/No boolean is saved. No generic I/O Other value, urine-only diaper, medication,
or breast-milk/BM feeding text is used to infer a bowel movement.

No means no recognized positive BM signal was documented in the AC source, not
proof that no bowel movement occurred. The AC SmartLink must itself be limited
to the past 24 hours. These undated source values cannot independently verify
that time window or establish an exact date/time of the last BM.

Unreadable or malformed AC data generates an import-review warning and clears
the prior BM status rather than inventing No or retaining a stale Yes. Older
archives without AC data do not acquire a fabricated status. A fresh H or S
snapshot without AC clears a prior BM claim. Re-paste a complete current source,
including a valid empty AC block when no stool data is documented.

## Validation

1,261 selected regression and compatibility tests passed in completed runs.
The latest inline H/AC snippet and six mounted full SmartPhrase examples were
also exercised locally. Their 24-hour totals now import, with current-shift
output remaining separate. The uploaded clinical sources are not packaged.

Synthetic text, HTML, individual PDF, and Print All output were checked. The
one-room PDF was rasterized and visually inspected. The three-room PDF produces
three pages. BM text was also checked programmatically for non-bold PDF font.

UI checks use widget stubs rather than a live browser or hosted deployment.
See TEST_REPORT.md for the completed test commands and limitations.
