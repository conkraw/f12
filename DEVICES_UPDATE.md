# Devices and EVD update: Version 6.26

## Update the existing app

Extract PICU626.zip. Open PICU_Handoff_v6_26_Devices and copy its contents to your existing application code repository, replacing matching files. Keep app.py at the root. Include the new devices.py module. Restart the deployment and refresh each user's browser.

Keep the existing app password, Admin password, encryption key, token, private repository, published guide and medication rules. Do not run the setup generators again. No new dependencies are required. This update does not clear handoffs.

Schema 20 adds independent devices and neuro_devices snapshots. Existing schemas 1-19 migrate without replacing previous fields, settings, reset generation or save timestamps. After saving with this version, do not downgrade. The schema change is necessary to persist the new structured entries.

## U: device inventory at the bottom

Paste the complete U section, or the full SmartPhrase. Select Create / update handoff, review the device inventory, and save. The detected inventory appears in a full-width Devices band below Goals / Follow-up. Existing manually entered Airway, Last Intubation, Access and Drains / Tubes notes remain separate and are never overwritten. The unused manual footer row is omitted only when there is a detected device inventory and every manual footer field is blank.

The compact groups are Airway, Vascular access, Tubes / drains and, when needed, Other devices. Device labels determine the group, not Epic's surrounding heading. Thus an NJ tube listed under Endotracheal Tube remains an NJ tube, not an ETT.

PICC, CVC, peripheral and arterial lines retain documented dates, lumen/size descriptors and site details. Dates are displayed as documented device dates, not calculated insertion times or line ages. Urinary catheters, tracheostomies, feeding tubes and chest/surgical drains retain their relevant descriptions. Routine Site Assessment prose is omitted. A blank field does not establish that a device is absent.

## Removed entries and airway history

All [REMOVED] non-ETT rows are discarded, including removed vascular lines, feeding tubes, urinary catheters, drains, ICP devices and tracheostomies.

ETT rows are the only exception. Each retained ETT shows Last Airway Size and Last Secure Site, using the recorded size and secured depth/location. Missing values show UNK. No lip, oral or nasal site is inferred from a depth in cm.

Removed ETTs explicitly display ETT history (removed). Current and removed ETTs remain distinct. If multiple different ETT records are supplied, they are not assigned invented chronology. Repeated identical device descriptions can combine their properties, but conflicting values are not silently selected. An uncertain detail shows UNK and a review warning.

## V: EVD status in Neurologic

A ventricular drainage catheter or explicit EVD/ventriculostomy device in V prints its recorded Drain Status beside the other neurologic observations, before notes and medications. Example: EVD: Clamped.

An empty status is UNK, not assumed clamped. A device listed only under the generic Intracranial Pressure/Ventriculostomy category is not automatically an EVD. An explicitly described non-draining ICP monitor remains in the bottom device summary. Removed non-ETT devices are excluded here too.

## Editing, saving and partial imports

Use Edit handoff > Devices / airway and EVD to edit descriptions, dates, airway size, secured values and status. Uncheck Include on handoff to omit an entry without losing the editable row. The removal status and detected device category are not changed by editing a description.

Room-change autosave, Save handoff, Save all, reload, new-patient blanking and shared reset include these snapshots. PDF, HTML, text and Print all use the same inventory and EVD display.

U and V update independently. Omitting a section keeps its previous snapshot. Including an empty section clears that snapshot. A failed U or V import does not cancel other valid sections. Its old automatic devices are retained for review but hidden from output until successfully reimported or explicitly accepted after checking Epic. Existing technical error reports use patient-free codes and row positions, not source text.

## Scope and limits

These are documented device snapshots, not proof of current bedside placement. The app does not infer devices from medications, respiratory support, culture specimen names or other sections. It does not infer an anatomical secure site or insertion time. Review the output against Epic and the bedside inventory.

The existing lab, CBC, gas, vital, feed and medication parsers are unchanged. Existing automatic PDF fitting includes the device band. Long inventories continue rather than being clipped. The live Streamlit host and private storage connection were not tested here.
