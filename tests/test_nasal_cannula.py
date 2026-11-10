"""Synthetic regression cases for missing-mode pressure pairs and nasal cannula."""
from copy import deepcopy
from migration_helpers import strip_v6_fields
from io import BytesIO
import json
from pathlib import Path
import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader
from noninvasive import parse_respiratory, format_noninvasive, validate_noninvasive
from importing import import_sections
from models import (new_sheet, new_vault, save_sheet_in, upgrade_vault,
                    validate_sheet, fields_with_medications)
from medications import parse_medications, remap, upsert_rule
from batching import available_handoffs
from exports import handoffs_pdf, handoffs_html, handoff_text
from security import generate_key, seal_vault, open_vault
from test_callbacks import app, open_room

C = "Invasive Ventilation:\nVent Information\nManual resuscitator at bedside: Yes\nSettings\nFiO2 (%): 21 %"
D = "Non-invasive Ventilation:\nO2 Delivery Method: Nasal cannula, Other (Comment) (humidified)\nFiO2 (%): 21 %\nO2 Flow Rate (L/min): 3 L/min"
PRESSURES = "\nTotal Inspiratory Pressure (cm H2O): 10 cmH20\nExpiratory Positive Airway Pressure (EPAP) (cmH20): 5 cmH20"
EXPECTED = ("BiPAP (pressure-based) | IPAP: 10 cmH20 | EPAP: 5 cmH20 | FiO2: 21 %\n"
            "Nasal cannula | Flow: 3 L/min | FiO2: 21 %")


def wrapped(c=C, d=D+PRESSURES):
    return ("cccccccc\n"+c+"\ncccccccc\n" if c is not None else "") + ("dddddddd\n"+d+"\ndddddddd" if d is not None else "")


def imported(c=C, d=D+PRESSURES, sheet=None):
    result=import_sections(sheet or new_sheet('P4102'), wrapped(c,d), new_vault()['settings'])
    assert not result.errors
    return result.sheet


def kinds(c=C, d=D+PRESSURES):
    result=parse_respiratory(c,d)
    assert not result.error
    return [row['device'] for row in result.devices]


def test_missing_mode_pressure_pair_and_humidified_nc_exact_output():
    result=parse_respiratory(C,D+PRESSURES)
    assert not result.error and result.invasive is None
    assert format_noninvasive(result.devices)==EXPECTED
    assert result.devices[0]['pressure_inferred']
    assert not result.devices[1]['pressure_inferred']
    assert not any(d['flow_inferred'] for d in result.devices)
    assert any('carried-forward' in s for s in result.issues)


@pytest.mark.parametrize('mode_line',['','\nVent Mode:','\nVent Mode: --','\nVent Mode: N/A','\nVent Mode: not documented'])
def test_absent_and_placeholder_mode_are_not_import_errors(mode_line):
    assert kinds(C+mode_line)==['BiPAP','Nasal cannula']


@pytest.mark.parametrize('label',['Nasal cannula','Nasal cannula, Other (Comment) (humidified)',
                                  'Low flow nasal cannula','Low-flow nasal cannula',
                                  'LFNC','NC','nasal cannula (heated/humidified)'])
def test_standard_cannula_label_variants(label):
    d=D.replace('Nasal cannula, Other (Comment) (humidified)',label)
    assert kinds(C,d)==['Nasal cannula']


@pytest.mark.parametrize('rate',['0.5 L/min','3 L/min','20 L/min','(S) 3 L/min'])
def test_nc_is_not_relabelled_as_hfnc_by_rate(rate):
    result=parse_respiratory(C,D.replace('3 L/min',rate))
    assert [x['device'] for x in result.devices]==['Nasal cannula']
    assert result.devices[0]['values']['Flow']==rate.removeprefix('(S) ')


@pytest.mark.parametrize('label',['High flow nasal cannula','High-flow nasal cannula','HFNC','HHFNC'])
def test_explicit_hfnc_at_low_numerical_flow_stays_hfnc(label):
    d=D.replace('Nasal cannula, Other (Comment) (humidified)',label)
    assert kinds(C,d+PRESSURES)==['BiPAP','HFNC']


def test_named_bilevel_and_nc_is_not_pressure_inferred():
    result=parse_respiratory(C+'\nVent Mode: Bilevel Non Invasive Ventilation',D+PRESSURES)
    assert kinds(C+'\nVent Mode: Bilevel Non Invasive Ventilation')==['BiPAP','Nasal cannula']
    assert not result.devices[0]['pressure_inferred']
    assert 'pressure-based' not in format_noninvasive(result.devices)


def test_cpap_and_nc():
    c=C+'\nVent Mode: CPAP\nPEEP (cm H2O): 5 cm H2O'
    result=parse_respiratory(c,D+'\nEPAP: 5 cmH20')
    assert [x['device'] for x in result.devices]==['CPAP','Nasal cannula']


@pytest.mark.parametrize('partial',['','\nIPAP: 10 cmH20','\nEPAP: 5 cmH20',
                                    '\nIPAP: N/A\nEPAP: 5 cmH20','\nIPAP: 10 cmH20\nEPAP: --',
                                    '\nIPAP: 0 cmH20\nEPAP: 5 cmH20'])
def test_missing_mode_needs_complete_usable_pressure_pair(partial):
    assert kinds(C,D+partial)==['Nasal cannula']


def test_missing_mode_epap_zero_is_preserved_not_treated_as_blank():
    r=parse_respiratory(C,D+PRESSURES.replace('5 cmH20','0 cmH20'))
    assert r.devices[0]['values']['EPAP']=='0 cmH20'


@pytest.mark.parametrize('on',['No','Off','false'])
def test_explicit_off_overrides_pressure_fallback(on):
    assert kinds(C+'\nVentilator On: '+on)==['Nasal cannula']


@pytest.mark.parametrize('airway',['Endotracheal tube','ETT','Tracheostomy','Trach'])
def test_no_pressure_fallback_from_invasive_airway_label(airway):
    d=D.replace('Nasal cannula, Other (Comment) (humidified)',airway)
    assert kinds(C,d+PRESSURES)==[]


def test_explicit_unknown_mode_is_not_replaced_by_inferred_bipap():
    assert kinds(C+'\nVent Mode: Unrecognized example mode')==['Nasal cannula']


def test_invasive_mode_wins_without_mixing_nasal_cannula():
    r=parse_respiratory(C+'\nVent Mode: Volume Targeted Pressure Control - PS',D+PRESSURES)
    assert r.invasive is not None and not r.devices


def test_fio2_21_does_not_turn_nc_into_room_air():
    s=imported(d=D)
    text=fields_with_medications(s)['Respiratory']
    assert 'Nasal cannula | Flow: 3 L/min | FiO2: 21 %' in text
    assert 'Room air' not in text


def test_missing_mode_pressure_entry_prefers_same_source_d_fio2():
    r=parse_respiratory(C.replace('21 %','60 %'),D+PRESSURES)
    assert all(x['values']['FiO2']=='21 %' for x in r.devices)


def test_nc_does_not_borrow_fio2_or_flow_from_c_or_old_snapshot():
    old=imported()
    d=D.replace('\nFiO2 (%): 21 %','').replace('\nO2 Flow Rate (L/min): 3 L/min','')
    s=imported(c=C+'\nO2 Flow Rate (L/min): 15 L/min',d=d,sheet=old)
    assert s['noninvasive'][0]['device']=='Nasal cannula'
    assert s['noninvasive'][0]['values']=={}


def test_zero_nc_flow_is_not_displayed_as_positive_support():
    assert kinds(C,D.replace('3 L/min','0 L/min')+PRESSURES)==['BiPAP']


def test_nc_only_reimport_removes_previous_bipap():
    old=imported()
    old['fields']['Respiratory']='Synthetic manual note'
    new=imported(d=D,sheet=old)
    assert [x['device'] for x in new['noninvasive']]==['Nasal cannula']
    assert new['fields']['Respiratory']=='Synthetic manual note'


def test_d_only_pair_keeps_values_but_does_not_borrow_named_mode():
    old=imported(c=C+'\nVent Mode: BiPAP')
    new=imported(c=None,sheet=old)
    assert new['noninvasive'][0]['pressure_inferred']
    assert new['noninvasive'][0]['values']==old['noninvasive'][0]['values']


def test_full_abcd_does_not_fail_when_c_mode_is_absent():
    text=('aaaaaaaa\nDiagnoses:\n1. Synthetic test diagnosis\naaaaaaaa\n'
          'bbbbbbbb\nMedications:\n'
          'Medication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin\n'
          '• albuterol nebulizer\t2.5 mg\tNebulization\tq4h\tTest provider\t \t \n'
          'bbbbbbbb\n'+wrapped())
    r=import_sections(new_sheet('P4102'),text,new_vault()['settings'])
    assert not r.errors
    assert len(r.sheet['medications'])==1
    assert r.sheet['fields']['Diagnoses']=='Synthetic test diagnosis'
    assert len(r.sheet['noninvasive'])==2


def test_support_precedes_notes_and_meds_and_single_separator():
    s=imported()
    s['fields']['Respiratory']='Keep this synthetic note'
    rows=parse_medications('Medications:\n• albuterol\t2.5 mg\tNebulization\tq4h').rows
    s['medications']=remap(rows,upsert_rule([],'albuterol','Respiratory'))
    result=fields_with_medications(s)['Respiratory']
    assert result.startswith('Vent Settings\n'+EXPECTED+'\n-----\nBeta-Agonist\nalbuterol')
    assert result.endswith('-----\nKeep this synthetic note')
    assert result.count('-----')==2


def legacy_four():
    s=imported(c=C+'\nVent Mode: BiPAP',d=D.replace('Nasal cannula, Other (Comment) (humidified)','High flow nasal cannula')+PRESSURES)
    s['fields']['Respiratory']='Keep old synthetic note'
    v=save_sheet_in(new_vault(),s)
    v['schema']=4;v.pop("reset_generation", None);v["settings"].pop("medication_groups", None);v["settings"].pop("medication_gi_groups", None);v['settings'].pop('medication_infusions', None)
    strip_v6_fields(v)
    v['settings']['medication_mappings']=upsert_rule([],'albuterol','Respiratory')
    for d in v['rooms']['P4102']['noninvasive']:
        del d['pressure_inferred']
    return v


def test_schema4_upgrade_preserves_existing_notes_rules_values_ids():
    old=legacy_four()
    original=deepcopy(old)
    v=upgrade_vault(old)
    assert old==original
    assert v['schema']==34
    assert v['settings']==dict(old['settings'], medication_visibility=[], medication_infusions=[], medication_gi_groups=[], medication_groups=[])
    old_sheet=old['rooms']['P4102']
    new_sheet_=v['rooms']['P4102']
    assert new_sheet_['id']==old_sheet['id']
    assert new_sheet_['fields']==old_sheet['fields']
    assert new_sheet_['updated_at']==old_sheet['updated_at']
    for before,after in zip(old_sheet['noninvasive'],new_sheet_['noninvasive']):
        assert after==dict(before,pressure_inferred=False)


def test_old_schema4_encrypted_archive_migrates_with_same_key():
    key=generate_key()
    token=Fernet(key.encode()).encrypt(json.dumps(legacy_four()).encode())
    v=open_vault(token,key)
    assert v['schema']==34
    s=imported(sheet=v['rooms']['P4102'])
    v=save_sheet_in(v,s)
    encoded=seal_vault(v,key)
    assert b'Nasal cannula' not in encoded and b'pressure_inferred' not in encoded
    assert open_vault(encoded,key)==v


def test_malformed_schema4_entry_is_not_discarded_silently():
    v=legacy_four()
    v['rooms']['P4102']['noninvasive'][0]['raw_source']='Not allowed'
    with pytest.raises(ValueError):
        upgrade_vault(v)


@pytest.mark.parametrize('device',['Nasal cannula','HFNC','CPAP'])
def test_pressure_inference_flag_is_only_allowed_on_bipap(device):
    row={'device':device,'values':{'EPAP':'5 cmH20'} if device=='CPAP' else {'Flow':'3 L/min'},
         'flow_inferred':False,'pressure_inferred':True}
    with pytest.raises(ValueError):
        validate_noninvasive([row])


def test_pdf_and_html_print_all_keep_pressure_provenance_and_nc():
    first=imported()
    second=imported(d=D,sheet=new_sheet('P4104'))
    selected=available_handoffs(new_vault(),{'P4102':first,'P4104':second})
    pdf=PdfReader(BytesIO(handoffs_pdf(list(selected.values()))))
    assert len(pdf.pages)==2
    assert all(float(p.mediabox.width)>float(p.mediabox.height) for p in pdf.pages)
    text=' '.join(p.extract_text() for p in pdf.pages)
    assert 'pressure-based' in text and 'Nasal cannula' in text and '3 L/min' in text
    html=handoffs_html(list(selected.values()))
    assert 'BiPAP (pressure-based)' in html and 'Nasal cannula' in html
    assert EXPECTED in handoff_text(first)


def test_nc_editor_and_remove_do_not_touch_pressure_entry(app):
    open_room(app)
    ss=app.st.session_state
    ss['paste']=wrapped()
    app.create_handoff()
    ss['nc_value']='2 L/min'
    app.noninvasive_change('P4102','Nasal cannula','Flow','nc_value')
    assert ss['drafts']['P4102']['noninvasive'][1]['values']['Flow']=='2 L/min'
    app.remove_support_device('P4102','Nasal cannula')
    assert len(ss['drafts']['P4102']['noninvasive'])==1
    assert ss['drafts']['P4102']['noninvasive'][0]['pressure_inferred']
    app.save_room(None)
    assert ss['vault']['schema']==34


def test_bipap_remove_keeps_nc(app):
    open_room(app)
    ss=app.st.session_state
    ss['paste']=wrapped()
    app.create_handoff()
    app.remove_support_device('P4102','BiPAP')
    assert [x['device'] for x in ss['drafts']['P4102']['noninvasive']]==['Nasal cannula']


def test_session_schema4_migration_preserves_unsaved_edits(app):
    open_room(app)
    ss=app.st.session_state
    ss['vault']=legacy_four()
    ss['drafts']={'P4102':deepcopy(ss['vault']['rooms']['P4102'])}
    ss['base_sheets']={'P4102':deepcopy(ss['vault']['rooms']['P4102'])}
    ss['drafts']['P4102']['fields']['Respiratory']='Unsaved synthetic note'
    app.upgrade_existing_session()
    assert ss['vault']['schema']==34
    assert ss['drafts']['P4102']['fields']['Respiratory']=='Unsaved synthetic note'
    assert 'pressure_inferred' in ss['base_sheets']['P4102']['noninvasive'][0]


def test_nc_page_render_and_sample_callback(app,monkeypatch):
    from test_ui_smoke import equip
    open_room(app)
    app.load_niv_sample()
    app.create_handoff()
    ss=app.st.session_state
    assert [x['device'] for x in ss['drafts']['P4102']['noninvasive']]==['BiPAP','Nasal cannula']
    downloads=equip(app,monkeypatch)
    app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)
    assert not ss['vault']['rooms']
