# Version 6.35: weight and height import fix

## What caused the Weight warning

The I section includes measured weight, dosing weight, Z-score, BMI, height,
and BSA. In v6.34, a height with a parenthetical feet/inches equivalent was
rejected by the height validator. That failed the I-section import even though
the weight entries themselves were readable.

The app retains previous values when this happens. Retained does not mean
updated or verified. With no previous value, the field remains empty. Other
successfully imported sections still update. Per-kilogram fluid calculations
remain suppressed while the I section has an import warning.

## Fix

Epic height values such as `120 cm (3' 11.24")` now import as `120 cm`.
Both `Height:` and `Length:` headings work, including repeated or split headings.
The primary recorded value is kept, without calculating height from BMI or weight.
Recognized feet/inches equivalents may use straight quotes, typographic quotes,
prime symbols, or spelled-out units. Equivalent heights must agree within the
rounding precision of the stated measurements. Unknown annotations and conflicting
values are not silently removed or accepted.

The review label now says `Weight / measurements` so a failed height or BSA
import is not misleadingly described as just a weight problem. Genuine errors
still preserve previous values and show the warning. No warning is automatically
acknowledged or hidden. A successful I reimport clears only the I warning.

## Install and refresh

Save open work. Extract PICU635.zip. Upload the contents of
PICU_Handoff_v6_35_Weight_Import into the existing application code repository,
replacing matching files. Keep app.py at the root. Restart and refresh the app.
Look for `Version 6.35 | Weight and height import fix` in the sidebar.

Re-paste the complete paired I section or full SmartPhrase for the affected room.
Click Create / update handoff, check the weight, dosing weight and height against
Epic, then Save handoff. Installing the fix cannot recover previously rejected
values unless you re-paste them. No SmartPhrase wording change is required.

Keep the existing Secrets, both passwords, encryption key, mappings, private
storage and public CDC BMI reference file. Do not rerun the setup generators.
No dependency or saved-archive schema changes are required.

Until installed, shorten a copied height line to just its verified metric value,
for example `Height: 120 cm`, and reimport the complete I section. This workaround
is for the pasted copy and does not require editing the patient's Epic chart.
