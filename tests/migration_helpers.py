def strip_v6_fields(vault):
    vault['settings'].pop('medication_visibility', None)
    for sheet in vault['rooms'].values():
        sheet.pop('sbs_vent_mode', None)
        sheet.pop("feeds", None);sheet.pop("devices", None);sheet.pop("neuro_devices", None);sheet.pop("pacemaker", None);sheet.pop("diet", None);sheet.pop("import_warnings", None);sheet.pop("intake_output", None);sheet.pop("recurring_orders", None);sheet.pop("cbc", None);sheet.pop('blood_gas', None);sheet.pop('neuro_vitals', None)
        sheet.pop('nutrition', None)
        sheet.pop('cultures', None)
        sheet.pop('dosing_weight', None)
        sheet.pop("feeds", None);sheet.pop("devices", None);sheet.pop("neuro_devices", None);sheet.pop("pacemaker", None);sheet.pop("diet", None);sheet.pop("import_warnings", None);sheet.pop("intake_output", None);sheet.pop("recurring_orders", None);sheet.pop("cbc", None);sheet.pop('blood_gas', None);sheet.pop('viral_panel', None);sheet.pop('admission_date', None)
        sheet.pop('labs', None)
        sheet.pop('vitals', None)
        for row in sheet.get('medications', []):
            row.pop('hidden', None)
    return vault
