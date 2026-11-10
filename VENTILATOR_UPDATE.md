Historical 6.38 release note. In 6.40, the handoff uses Observed TV for the stored inspiratory or expiratory value. See NEURO_GROUPS_UPDATE.md.

# Version 6.38: mode-specific ventilator summaries

Built directly on PICU637.zip, which retains the Version 6.35 printing approach.
No Version 6.36 font-size picker was added. The compact seven-column layout,
SmartPhrase publication time, hidden printed diagnostics, difficult-airway tab,
medication rules, and laboratory selection rules are retained.

## C-section import and display

Both the original Epic fields and the new wrapped fields are accepted, including
`Mode: Vent Mode: ...`, `Set PIP: PIP Set (cm H2O): ...`, and reported Avg/Min/Max.
The source mode and separate source values are saved and editable. Display
abbreviations do not rewrite the original mode or patient-specific values.

- PC-IMV / PC-CMV: set RR, set PIP, observed volume when available, set PEEP,
  inspiratory time, pressure support, and C-section FiO2.
- PRVC / PRVC-IMV / PRVC-PS and VC modes: set RR, set TV, set PEEP, inspiratory
  time, pressure support, and C-section FiO2. Observed PIP/TV remain in the editor
  but do not crowd the volume-targeted summary.
- A numeric Pmin selects `Device: Home Vent` by the app owner's requested display
  rule. The mode is shortened to PC, PRVC, or VC where appropriate. Pmin/Pmax and
  Tmin/Tmax print when available. A blank home-vent template does not activate it.
- Volume-targeted pressure control uses PRVC as the owner's local handoff
  shorthand, not a claim that every manufacturer's mode is identical.
- Long mode names and supplied abbreviated labels are mapped in
  ventilator_modes.py. HFOV, HFJV, APRV, AVAPS, NAVA, VSV, PPS and ASV names are
  recognized, but undisclosed specialized parameters are not invented.
- Named AVAPS NIV and NAVA NIV remain NIV labels, not BiPAP. Existing BiPAP,
  CPAP, HFNC and nasal cannula rules remain available for old and wrapped C data.

## Distinctions preserved

`Vt Insp ml` prints as Observed TVi. An explicitly expiratory field such as
`Vt Exp ml` prints as Observed TVe. `Vt (observed, mL)` alone prints as Observed TV
because the label does not identify the phase. An average/range is printed only
when supplied, never fabricated from a single observation. An explicit expiratory
measurement is preferred when both inspiratory and expiratory values are present.

Set PIP is copied from the set field, never substituted from observed PIP or
calculated by adding PEEP. Source pressure qualifications, such as 'PC above
PEEP', remain attached. Source units are not converted. Typography such as
'cm H20' is normalized to 'cm H2O'.

An explicit C-block FiO2 set value is preferred for the compact ventilator line.
C-block FiO2 is used when no set value is present. D/E FiO2 values are not silently
substituted into the C-block ventilator settings. Missing settings and
'No data recorded' placeholders are omitted rather than carried forward.

## Editing, import and installation

Edit handoff > Respiratory > Edit ventilator values includes the new fields.
Changing Pmin or the source mode updates the derived display. Saves, room-change
autosave, Preview/print, PDF, HTML, text and Print all use the same summary.

Re-paste the full SmartPhrase or complete paired C and D sections, then choose
Create / update handoff and Save handoff. The respiratory import replaces the
C/D snapshot together. It never fills missing new values from a previous paste.
Omitting both C and D preserves the saved respiratory snapshot. Genuine conflicting
fields still show an in-app import error without blocking unrelated sections.

Extract PICU638.zip. Upload the contents of PICU_Handoff_v6_38_Ventilator to the
existing application code repository, replacing matching files. Keep app.py at
the root. Include the new ventilator_modes.py. Restart and refresh.

Keep existing Secrets, both passwords, the encryption key, mappings, private
data repository and CDC reference data. Do not rerun the generators. No new
Python dependencies. Existing 6.37 archives open with their fields unchanged.
The archive schema remains 26, with additional permitted ventilation-value keys.
Do not downgrade after saving new ventilator fields, because older validators
will not recognize them. Installing this update does not modify the published
SmartPhrase source in Admin or make changes inside Epic.

## Validation scope

Automated tests check deterministic extraction and display, not clinical accuracy
at the bedside. Existing diagnoses and problem rules are not changed. The live
Streamlit deployment and private GitHub connection were not accessed.
