from recovery_helpers import assert_retained
"""Synthetic source-pattern tests. These do not validate current bedside device use."""
from copy import deepcopy
from migration_helpers import strip_v6_fields
from io import BytesIO
import json
import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader
from noninvasive import parse_respiratory, format_noninvasive, validate_noninvasive, mode_kind
from models import (new_sheet, new_vault, apply_ventilation, validate_sheet,
                    save_sheet_in, upgrade_vault, fields_with_medications)
from importing import import_sections
from ventilation import parse_ventilation
from batching import available_handoffs
from exports import handoffs_pdf, handoffs_html
from security import seal_vault, open_vault, generate_key
from test_callbacks import app, open_room

BILEVEL = 'Invasive Ventilation:\nVent Mode: Bilevel Non Invasive Ventilation\nFiO2 (%): 30 %'
CPAP = 'Invasive Ventilation:\nVent Mode: Continuous Positive Airway Pressure - Non Invasive Ventilation\nFiO2 (%): 60 %\nPEEP (cm H2O): 8 cm H2O'
HFNC = 'Non-invasive Ventilation:\nO2 Delivery Method: High flow nasal cannula\nFiO2 (%): 30 %\nO2 Flow Rate (L/min): 20 L/min'
PRESSURES = '\nTotal Inspiratory Pressure (cm H2O): 12 cmH20\nExpiratory Positive Airway Pressure (EPAP) (cmH20): 6 cmH20'
MASK = 'Non-invasive Ventilation:\nO2 Delivery Method: CPAP/Bi-PAP mask\nFiO2 (%): 60 %\nExpiratory Positive Airway Pressure (EPAP) (cmH20): 8 cmH20'
INVASIVE = 'Invasive Ventilation:\nVent Mode: Volume Targeted Pressure Control - PS\nFiO2 (%): 35 %\nResp Rate (Set): 16'


def wrapped(c=None, d=None):
    return ('cccccccc\n' + c + '\ncccccccc\n' if c is not None else '') + ('dddddddd\n' + d + '\ndddddddd' if d is not None else '')


def devices(result):
    assert not result.error
    return [item['device'] for item in result.devices]


def import_support(c=None, d=None, sheet=None):
    result = import_sections(sheet or new_sheet('P4102'), wrapped(c,d), new_vault()['settings'])
    assert not result.errors
    return result.sheet


def test_example_bilevel_and_hfnc():
    result = parse_respiratory(BILEVEL, HFNC + PRESSURES)
    assert devices(result) == ['BiPAP', 'HFNC']
    assert result.devices[0]['values'] == {'IPAP':'12 cmH20','EPAP':'6 cmH20','FiO2':'30 %'}
    assert result.devices[1]['values'] == {'Flow':'20 L/min','FiO2':'30 %'}
    assert not any(item['flow_inferred'] for item in result.devices)
    assert result.invasive is None


def test_example_stale_bilevel_hfnc_only():
    result = parse_respiratory(BILEVEL.replace('30 %','40 %'), HFNC.replace('30 %','40 %').replace('20 L/min','(S) 5 L/min'))
    assert devices(result) == ['HFNC']
    assert result.devices[0]['values'] == {'Flow':'5 L/min','FiO2':'40 %'}
    assert '(S)' not in format_noninvasive(result.devices)


def test_example_cpap_mask_with_flow_adds_labeled_hfnc():
    result = parse_respiratory(CPAP, MASK + '\nO2 Flow Rate (L/min): 20 L/min')
    assert devices(result) == ['CPAP','HFNC']
    assert result.devices[0]['values'] == {'EPAP':'8 cmH20','FiO2':'60 %'}
    assert result.devices[1]['flow_inferred']
    assert 'HFNC (flow-based)' in format_noninvasive(result.devices)
    assert any('source labels' in note for note in result.issues)


@pytest.mark.parametrize('mode', ['Bilevel Non Invasive Ventilation','BiPAP','Bi-PAP','BI-LEVEL NIV'])
def test_bilevel_name_variants(mode):
    result=parse_respiratory(BILEVEL.replace('Bilevel Non Invasive Ventilation',mode),HFNC+PRESSURES)
    assert devices(result)==['BiPAP','HFNC']


@pytest.mark.parametrize('mode', ['CPAP','Continuous Positive Airway Pressure - Non Invasive Ventilation','Continuous Positive Airway Pressure'])
def test_cpap_mode_variants(mode):
    assert mode_kind(mode)=='CPAP'
    assert devices(parse_respiratory('Invasive Ventilation:\nVent Mode: '+mode,MASK))==['CPAP']


def test_bipap_only_with_mask_and_no_flow():
    d='Non-invasive Ventilation:\nO2 Delivery Method: CPAP/Bi-PAP mask\nFiO2 (%): 30 %'+PRESSURES
    assert devices(parse_respiratory(BILEVEL,d))==['BiPAP']


def test_bipap_mask_and_flow_convention():
    d=HFNC.replace('High flow nasal cannula','CPAP/Bi-PAP mask')+PRESSURES
    result=parse_respiratory(BILEVEL,d)
    assert devices(result)==['BiPAP','HFNC']
    assert result.devices[1]['flow_inferred']


def test_cpap_only_without_flow():
    assert devices(parse_respiratory(CPAP,MASK))==['CPAP']


def test_cpap_and_explicit_hfnc():
    result=parse_respiratory(CPAP,MASK.replace('CPAP/Bi-PAP mask','High flow nasal cannula')+'\nO2 Flow Rate (L/min): 20 L/min')
    assert devices(result)==['CPAP','HFNC']
    assert not result.devices[1]['flow_inferred']


def test_hfnc_only_with_no_c_block():
    assert devices(parse_respiratory(None,HFNC))==['HFNC']


def test_empty_c_and_hfnc_d():
    assert devices(parse_respiratory('Invasive Ventilation:',HFNC))==['HFNC']


@pytest.mark.parametrize('pressure', ['', '\nTotal Inspiratory Pressure (cm H2O): 12 cmH20', '\nExpiratory Positive Airway Pressure (EPAP) (cmH20): 6 cmH20'])
def test_bilevel_needs_both_pressures(pressure):
    assert devices(parse_respiratory(BILEVEL,HFNC+pressure))==['HFNC']


@pytest.mark.parametrize('placeholder', ['', 'N/A', '--', 'not documented'])
def test_blank_or_missing_pressure_is_not_bipap(placeholder):
    d=HFNC+PRESSURES.replace('12 cmH20',placeholder)
    assert devices(parse_respiratory(BILEVEL,d))==['HFNC']


def test_cpap_peep_fallback_without_d_pressure():
    result=parse_respiratory(CPAP,None)
    assert devices(result)==['CPAP']
    assert result.devices[0]['values']['EPAP']=='8 cm H2O'


def test_cpap_without_pressure_not_reported():
    assert devices(parse_respiratory('Invasive Ventilation:\nVent Mode: CPAP',HFNC))==['HFNC']


def test_cpap_conflicting_pressures_rejects_whole_import():
    result=parse_respiratory(CPAP.replace('8 cm H2O','10 cm H2O'),MASK)
    assert result.error and 'differs' in result.error
    out=import_sections(new_sheet('P4102'),wrapped(CPAP.replace('8 cm H2O','10 cm H2O'),MASK),new_vault()['settings'])
    assert_retained(out, new_sheet("P4102"), "cd")


def test_two_fio2_values_stay_device_specific():
    result=parse_respiratory(BILEVEL.replace('30 %','50 %'),HFNC+PRESSURES)
    assert result.devices[0]['values']['FiO2']=='50 %'
    assert result.devices[1]['values']['FiO2']=='30 %'


def test_bilevel_fio2_fallback_is_disclosed():
    result=parse_respiratory(BILEVEL.replace('\nFiO2 (%): 30 %',''),HFNC+PRESSURES)
    assert result.devices[0]['values']['FiO2']=='30 %'
    assert any('uses D-block FiO2' in text for text in result.issues)


def test_hfnc_does_not_borrow_fio2_from_c():
    result=parse_respiratory(BILEVEL,HFNC.replace('\nFiO2 (%): 30 %',''))
    assert 'FiO2' not in result.devices[0]['values']


def test_units_and_rates_not_recalculated():
    result=parse_respiratory(BILEVEL.replace('30 %','0.3'),HFNC.replace('20 L/min','(S) 5 L/min')+PRESSURES)
    assert result.devices[0]['values']['FiO2']=='0.3'
    assert result.devices[1]['values']['Flow']=='5 L/min'


def test_explicit_hfnc_missing_flow_still_visible_without_invented_value():
    result=parse_respiratory(None,HFNC.replace('\nO2 Flow Rate (L/min): 20 L/min',''))
    assert devices(result)==['HFNC']
    assert 'Flow' not in result.devices[0]['values']
    assert any('flow is missing' in text for text in result.issues)


def test_zero_flow_does_not_add_active_hfnc():
    assert devices(parse_respiratory(None,HFNC.replace('20 L/min','0 L/min')))==[]


@pytest.mark.parametrize('delivery', ['Simple face mask','Room air','Endotracheal tube'])
def test_other_delivery_not_relabelled_hfnc_by_flow(delivery):
    result=parse_respiratory(None,HFNC.replace('High flow nasal cannula',delivery))
    assert devices(result)==[]


def test_bipap_pressures_without_c_mode_are_visibly_pressure_based():
    result=parse_respiratory(None,HFNC+PRESSURES)
    assert devices(result)==['BiPAP','HFNC']
    assert result.devices[0]['pressure_inferred']
    assert 'BiPAP (pressure-based)' in format_noninvasive(result.devices)


def test_ventilator_off_prevents_pressure_device():
    result=parse_respiratory(BILEVEL+'\nVentilator On: No',HFNC+PRESSURES)
    assert devices(result)==['HFNC']


def test_invasive_mode_keeps_exact_old_fields_no_niv_mix():
    result=parse_respiratory(INVASIVE,HFNC+PRESSURES)
    assert result.invasive==parse_ventilation(INVASIVE).data and not result.devices


def test_same_repeated_field_allowed_conflicting_repeated_field_error():
    assert not parse_respiratory(BILEVEL,HFNC+PRESSURES+'\nFiO2 (%): 30 %').error
    assert parse_respiratory(BILEVEL,HFNC+PRESSURES+'\nFiO2 (%): 90 %').error


def test_bad_c_or_d_dividers_blocks_all_changes():
    for text in ('cccccccc\n'+BILEVEL+'\ncccccccc\ndddddddd\n'+HFNC,
                 'cccccccc\n'+BILEVEL+'\ndddddddd\n'+HFNC+'\ndddddddd'):
        result=import_sections(new_sheet('P4102'),text,new_vault()['settings'])
        assert_retained(result, new_sheet("P4102"), "cd")


def test_niv_reimport_clears_stale_bipap_and_keeps_notes():
    s=import_support(BILEVEL,HFNC+PRESSURES)
    s['fields']['Respiratory']='Keep manual note'
    s=import_support(BILEVEL,HFNC,s)
    assert [d['device'] for d in s['noninvasive']]==['HFNC']
    assert s['fields']['Respiratory']=='Keep manual note'
    assert 'BiPAP' not in fields_with_medications(s)['Respiratory']


def test_only_d_is_new_pressure_based_snapshot_not_old_c_mode():
    s=import_support(BILEVEL,HFNC+PRESSURES)
    s=import_support(None,HFNC+PRESSURES,s)
    assert [d['device'] for d in s['noninvasive']]==['BiPAP','HFNC']
    assert s['noninvasive'][0]['pressure_inferred']


def test_empty_respiratory_pair_clears_only_automatic_support():
    s=import_support(BILEVEL,HFNC+PRESSURES)
    s['fields']['Respiratory']='Keep note'
    s=import_support('Invasive Ventilation:','Non-invasive Ventilation:',s)
    assert not s['noninvasive'] and s['ventilation'] is None
    assert fields_with_medications(s)['Respiratory']=='Keep note'


def test_a_only_preserves_support_snapshot():
    s=import_support(BILEVEL,HFNC+PRESSURES)
    out=import_sections(s,'aaaaaaaa\nDiagnoses:\n1. Synthetic diagnosis\naaaaaaaa',new_vault()['settings'])
    assert out.sheet['noninvasive']==s['noninvasive']


def test_invasive_to_niv_and_back_clears_obsolete_devices():
    s=import_support(INVASIVE)
    s=import_support(None,HFNC,s)
    assert s['ventilation'] is None and s['noninvasive'][0]['device']=='HFNC'
    s=import_support(INVASIVE,None,s)
    assert s['ventilation'] is not None and not s['noninvasive']


def test_order_before_notes_and_separator_once():
    s=import_support(BILEVEL,HFNC+PRESSURES)
    s['fields']['Respiratory']='Manual note'
    text=fields_with_medications(s)['Respiratory']
    assert text.index('BiPAP')<text.index('HFNC')<text.index('-----')<text.index('Manual note')
    assert text.count('-----')==1


def test_schema_three_migration_preserves_invasive_notes_mappings_and_ids():
    s=apply_ventilation(new_sheet('P4102'),parse_ventilation(INVASIVE).data)
    s['fields']['Respiratory']='Old note'
    vault=save_sheet_in(new_vault(),s)
    vault['schema']=3;vault.pop("reset_generation", None);vault["settings"].pop("medication_groups", None);vault["settings"].pop("medication_gi_groups", None);vault['settings'].pop('medication_infusions', None)
    strip_v6_fields(vault)
    vault['rooms']['P4102'].pop('noninvasive')
    migrated=upgrade_vault(vault)
    assert migrated['schema']==34 and vault['schema']==3
    assert migrated['rooms']['P4102']['noninvasive']==[]
    assert migrated['rooms']['P4102']['ventilation']==s['ventilation']
    assert migrated['rooms']['P4102']['id']==s['id']
    assert migrated['settings']==dict(vault['settings'], medication_visibility=[], medication_infusions=[], medication_gi_groups=[], medication_groups=[])
    assert migrated['rooms']['P4102']['fields']==s['fields']


def test_encrypted_niv_roundtrip_and_schema3_ciphertext_upgrade():
    key=generate_key()
    vault=save_sheet_in(new_vault(),import_support(BILEVEL,HFNC+PRESSURES))
    token=seal_vault(vault,key)
    assert b'BiPAP' not in token and b'IPAP' not in token
    assert open_vault(token,key)==vault
    vault['schema']=3;vault.pop("reset_generation", None);vault["settings"].pop("medication_groups", None);vault["settings"].pop("medication_gi_groups", None);vault['settings'].pop('medication_infusions', None)
    strip_v6_fields(vault)
    vault['rooms']['P4102'].pop('noninvasive')
    oldtoken=Fernet(key.encode()).encrypt(json.dumps(vault).encode())
    assert open_vault(oldtoken,key)['schema']==34


def test_niv_only_rooms_print_all_and_both_exports():
    s=import_support(BILEVEL,HFNC+PRESSURES)
    second=import_support(CPAP,MASK+'\nO2 Flow Rate (L/min): 20 L/min',new_sheet('P4104'))
    selected=available_handoffs(new_vault(),{'P4102':s,'P4104':second})
    assert list(selected)==['P4102','P4104']
    pdf=PdfReader(BytesIO(handoffs_pdf(list(selected.values()))))
    assert len(pdf.pages)==2
    text='\n'.join(p.extract_text() for p in pdf.pages)
    assert 'BiPAP' in text and 'CPAP' in text and 'HFNC (flow-based)' in text
    assert all(float(p.mediabox.width)>float(p.mediabox.height) for p in pdf.pages)
    html=handoffs_html(list(selected.values()))
    assert 'BiPAP' in html and 'HFNC (flow-based)' in html


def test_bad_structure_rejected_no_extra_raw_source_storage():
    s=import_support(BILEVEL,HFNC+PRESSURES)
    s['noninvasive'][0]['raw_source']='should-not-be-saved'
    with pytest.raises(ValueError): validate_sheet(s)


def test_validation_rejects_duplicate_device_and_wrong_inference_flag():
    row=parse_respiratory(None,HFNC).devices[0]
    with pytest.raises(ValueError): validate_noninvasive([row,row])
    row=deepcopy(parse_respiratory(BILEVEL,HFNC+PRESSURES).devices[0])
    row['flow_inferred']=True
    with pytest.raises(ValueError): validate_noninvasive([row])


def test_support_callback_import_edit_remove_save(app):
    open_room(app)
    ss=app.st.session_state
    ss['paste']=wrapped(BILEVEL,HFNC+PRESSURES)
    app.create_handoff()
    assert ss['paste']==''
    s=ss['drafts']['P4102']
    assert len(s['noninvasive'])==2
    ss['niv_test']='14 cmH20'
    app.noninvasive_change('P4102','BiPAP','IPAP','niv_test')
    assert ss['drafts']['P4102']['noninvasive'][0]['values']['IPAP']=='14 cmH20'
    ss['niv_test']=''
    app.noninvasive_change('P4102','BiPAP','IPAP','niv_test')
    assert ss['niv_test']=='14 cmH20'
    app.remove_support_device('P4102','HFNC')
    assert len(ss['drafts']['P4102']['noninvasive'])==1
    app.save_room(None)
    assert len(ss['vault']['rooms']['P4102']['noninvasive'])==1
    app.start_new_patient()
    assert not ss['drafts']['P4102']['noninvasive']


def test_support_changes_cannot_leak_between_rooms(app):
    open_room(app)
    ss=app.st.session_state
    ss['paste']=wrapped(BILEVEL,HFNC+PRESSURES)
    app.create_handoff()
    saved=deepcopy(ss['drafts']['P4102'])
    open_room(app,'P4104')
    ss['niv_test']='18 cmH20'
    app.noninvasive_change('P4102','BiPAP','IPAP','niv_test')
    app.remove_support_device('P4102','HFNC')
    saved['updated_at']=ss['drafts']['P4102']['updated_at']  # Room switch now autosaves.
    assert ss['drafts']['P4102']==saved
    assert ss['vault']['rooms']['P4102']==saved
    assert not ss['drafts']['P4104']['noninvasive']


def test_session_schema3_migration_preserves_unsaved_support_notes(app):
    open_room(app)
    ss=app.st.session_state
    app.save_room(None)
    ss['drafts']['P4102']['fields']['Respiratory']='Unsaved note'
    ss['vault']['schema']=3;ss['vault'].pop("reset_generation", None);ss['vault']["settings"].pop("medication_groups", None);ss['vault']["settings"].pop("medication_gi_groups", None);ss['vault']['settings'].pop('medication_infusions', None)
    ss['vault']['settings'].pop('medication_visibility', None)
    for obj in (ss['vault']['rooms']['P4102'],ss['drafts']['P4102'],ss['base_sheets']['P4102']):
        obj.pop("feeds", None);obj.pop("devices", None);obj.pop("neuro_devices", None);obj.pop("pacemaker", None);obj.pop("diet", None);obj.pop("import_warnings", None);obj.pop("intake_output", None);obj.pop("recurring_orders", None);obj.pop("cbc", None);obj.pop('blood_gas', None)
        obj.pop('noninvasive')
        obj.pop('neuro_vitals', None)
        obj.pop('nutrition', None)
        obj.pop('cultures', None)
        obj.pop('dosing_weight', None)
        obj.pop('viral_panel', None);obj.pop('admission_date', None)
        obj.pop('labs', None)
        obj.pop('vitals', None)
        for row in obj.get('medications', []): row.pop('hidden', None)
    app.upgrade_existing_session()
    assert ss['vault']['schema']==34
    assert ss['drafts']['P4102']['fields']['Respiratory']=='Unsaved note'
    assert ss['drafts']['P4102']['noninvasive']==[]


def test_render_niv_editor_with_downloads(app,monkeypatch):
    from test_ui_smoke import equip
    open_room(app)
    app.st.session_state['paste']=wrapped(CPAP,MASK+'\nO2 Flow Rate (L/min): 20 L/min')
    app.create_handoff()
    downloads=equip(app,monkeypatch)
    app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)
    assert any(key.startswith('niv_') for key in app.st.session_state)


def test_load_respiratory_example_does_not_save_it(app):
    open_room(app)
    app.load_niv_sample()
    app.create_handoff()
    assert len(app.st.session_state['drafts']['P4102']['noninvasive'])==2
    assert not app.st.session_state['vault']['rooms']
