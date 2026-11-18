# PICU Handoff 6.83

This release adds dedicated invasive NAVA settings to the Respiratory section. It is based on PICU680.zip, the 6.80 baseline, and retains its existing medication, import, and printing behavior.

## Install

Extract PICU683.zip. At the root of your existing app repository, replace these files together:

    app.py
    ventilation.py
    noninvasive.py

Keep them beside your current app.py, without another folder level. Restart Streamlit and confirm the sidebar reads:

    Version 6.83 | Invasive NAVA settings

No new dependency or configuration change is needed from 6.80. Keep your existing Streamlit Secrets, encryption key, encrypted archives, and saved mappings.

This package is ready to install. It has not been deployed to the live application.

## NAVA behavior

When Vent Mode is Neurally Adjusted Ventilatory Assist or NAVA, the app reads the NAVA Ventilator Settings subsection. Its values supply the Respiratory section in the existing Vent Settings layout.

The NAVA subsection supplies NAVA level, PEEP, FiO2, Edi peak, Edi min, observed PIP, observed tidal volume, observed respiratory rate, and apnea time. An existing NAVA subsection is authoritative even when a field or the entire subsection is blank. Generic ventilator values and noninvasive settings do not fill those blanks.

Edi peak, Edi min, observed PIP, observed tidal volume, and observed respiratory rate display the recorded Min and Max as a range. Single values remain single values. Partial statistics remain explicitly labeled. Original source strings remain in the saved record. No average, missing range endpoint, or reporting window is calculated.

Tidal volume remains in mL, matching the supplied source and the app's existing ventilator formatting.

For the supplied respiratory example, the output is:

    Mode: NAVA
    NAVA Level: 3 cm H2O/µV
    Set PEEP: 5 cm H2O
    FiO2: 21 %
    Edi Peak: 3.1–13.6 µV
    Edi Min: 0.1–3 µV
    Observed PIP: 21–31 cm H2O
    Observed TV: 22–57 mL
    Observed RR: 24–45 breaths/min
    Apnea Time: 10 seconds

The general section's FiO2 of 25%, observed tidal volume of 23–47 mL, and set rate of 16 do not replace these NAVA values. Set tidal volume, set rate, pressure support, and inspiratory time are omitted from the NAVA display.

Other modes ignore the dedicated NAVA subsection. NIV-NAVA retains its existing noninvasive behavior. Conflicting repeated values within the selected subsection still block that respiratory import. Explicit Ventilator On control fields continue to apply to the existing SBS display rule.

The current SmartPhrase example needs no changes. Paste it again after installing to populate the new fields. Old saved NAVA records without the new subsection can only show the fields they already contain.

## Verification

TEST_REPORT.md documents the focused respiratory, import, encryption, export, and printing checks. New tests use a respiratory-only fixture without patient names or MRNs. No real patient paste is included in this package.

ARCHIVE_COMPATIBILITY.txt describes compatibility with saved handoffs.
