# v6.68 change details

## ECG

The SmartPhrase parser now recognizes paired Z dividers. ecg.py extracts only
the named Bazett measurement and its ECG date. The newest usable dated result
is selected without consulting the current date, laboratory windows or admission.
Two conflicting results with unresolved chronology trigger section review.

The optional ecg snapshot stores value and date strings. models.py places it
in Cardiac through the shared automatic-vitals path, so text, HTML, individual
PDF and Print All receive the same value. clinical_style.py makes the flagged
QTc label and value red. problem_review.py adds Long QTc for values greater
than 450 and uses the existing review, confirmation and dismissal controls.

## NIRS

nirs.py reads explicit cerebral percentage values, minimum/maximum summaries
and a separate latest value. vitals.py routes them to Neurologic and combines
compatible readings for display. Existing stored rows are not mutated by
rendering. The source average is not used to calculate either endpoint.

## Ignore

medications.py recognizes override-pull annotations before normal medication
routing. The Ignore destination is available through the existing placement
picker. All medication output paths use the shared visibility guard, including
old saved override rows that predate this update.

An exact category choice or exact Restore choice can include the entry. A
validated optional Boolean records deliberate restoration on saved medication
rows. Ordinary orders for the same drug keep their own names and mappings.
The Restore callback also handles an explicit Ignore assignment made through
the older Admin medication mapping controls and saves the choice atomically.

## Scope

No Epic connection, source SmartLink definition, live deployment, encryption
key, archive path or patient identity field was added. The source template is
illustrative and contains placeholders rather than populated patient data.
