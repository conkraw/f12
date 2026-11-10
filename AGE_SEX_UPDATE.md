# Version 6.32: age and sex below Room

Save open work. Extract PICU632.zip and upload the contents of
PICU_Handoff_v6_32_Age_Sex to the existing application code repository.
Replace matching files and keep app.py at the root. Restart and refresh.
Keep all current Streamlit Secrets, both passwords, the encryption key,
GitHub token, medication mappings, private data repository, and public BMI
reference data unchanged. Do not run setup generators. No new dependencies
or archive schema changes are needed.

The exact Epic line Age: 6 y.o. Sex: female is accepted in A, I, or N.
It prints as:

    Room: P4201
    Age: 6 y.o.
    Sex: Female

Admission and Diagnoses follow below. Explicit Age/Sex metadata is removed
from A before diagnoses are assembled, including a combined suffix appended
to a diagnosis. Clinical wording and codes are preserved.

After installing, re-paste the affected complete SmartPhrase or the complete
A section and click Create / update handoff, then Save handoff. This updates
the previously imported raw text as well as the structured demographics.
Installing alone does not rewrite old diagnosis text or guess missing age.
The same-line format works in I / NUTRITION and N / admission as well.

Supported Epic age abbreviations include y.o., m.o., w.o., and d.o.
A whole-year age remains a whole-year age for the BMI rules. Do not assume an
exact month for a BMI percentile. The prior under-two/unknown-age BMI display
restriction remains. No patient identifiers or date of birth are added.

Malformed or conflicting age/sex values do not overwrite the affected source
section. Other valid sections still import under the existing recovery rules.

Sidebar: Version 6.32 | Age and sex below Room

See TEST_REPORT.md for what was tested.
